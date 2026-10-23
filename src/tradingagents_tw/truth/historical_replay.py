"""One verified historical path for both boards, including persisted configuration."""
from dataclasses import dataclass
from datetime import date
import math
from typing import Literal, Mapping

from pydantic import Field, model_validator

from tradingagents_tw.contracts import (
    Evidence, EvidenceAssessment, EvidenceStatus, GateStatus, PriceBar, PriceBasis,
    PriceSeries, StrictModel, TrendAssessment, TruthSnapshot,
)
from tradingagents_tw.providers.base import ProviderAdapter, ProviderRequest
from tradingagents_tw.providers.registry import Market, REGISTRY_VERSION, HISTORICAL_SOURCES, require_historical_source
from tradingagents_tw.state.price_inputs import derive_trend_inputs, evaluate_trend_from_prices
from tradingagents_tw.state.trend import TrendInputs
from .calendar import TradingCalendar, PostMarketPolicy
from .corporate_actions import apply_back_adjustments
from .factors import DerivedFactor, derive_adjustment_factor, validate_action_coverage
from .identity import derive_config_hash
from .ingestion import promote_validated_evidence
from .point_in_time import assert_point_in_time
from .provider_boundary import validate_provider_output
from .snapshot import build_truth_snapshot
from .signed_historical import verify_signed_historical_coverage
from .store import TruthSnapshotStore, verify_snapshot_integrity


class HistoricalReplayConfig(StrictModel):
    engine_version: Literal["historical-truth-trend-v1"] = "historical-truth-trend-v1"
    archive_mode: Literal["SYNTHETIC_FIXTURE_ONLY", "SIGNED_PIT_V1"] = "SYNTHETIC_FIXTURE_ONLY"
    registry_version: Literal["taiwan-market-sources-v1"] = REGISTRY_VERSION
    factor_version: Literal["official-reference-factor-v1"] = "official-reference-factor-v1"
    market: Market
    calendar: TradingCalendar
    cutoff_policy: PostMarketPolicy = Field(default_factory=PostMarketPolicy)
    start_date: date
    minimum_bars: int = Field(default=60, ge=60, strict=True)
    # External deterministic State input, persisted rather than taken from today's defaults.
    rs_20d: float = Field(allow_inf_nan=False)
    confirmation_window: int = Field(default=2, ge=1, strict=True)

    @model_validator(mode="after")
    def same_market(self):
        if self.market is not self.calendar.market:
            raise ValueError("replay calendar/market mismatch")
        return self


@dataclass(frozen=True)
class HistoricalReplay:
    truth_hash: str
    config_hash: str
    adjusted: PriceSeries
    factors: tuple[DerivedFactor, ...]
    inputs: TrendInputs
    trend: TrendAssessment


def _raw_prices(evidence: tuple[Evidence, ...], *, symbol: str, end: date, cutoff,
                config: HistoricalReplayConfig) -> tuple[PriceSeries, dict[date, Evidence]]:
    calendar = config.calendar
    config.cutoff_policy.require_finalized(calendar, end, cutoff)
    by_date, bars = {}, []
    for item in evidence:
        if item.evidence_type != "OHLCV":
            continue
        p = item.payload
        if (item.status is not EvidenceStatus.VERIFIED or item.schema_version != "1.0"
                or item.symbol != symbol or item.source != HISTORICAL_SOURCES[config.market].source
                or p.get("market") != config.market.value or p.get("price_basis") != "RAW"):
            raise ValueError("unverified, mixed-board or non-RAW historical OHLCV")
        assert_point_in_time(item, cutoff)
        day = date.fromisoformat(p["trade_date"])
        if day in by_date or not config.start_date <= day <= end:
            raise ValueError("duplicate or out-of-window historical bar")
        if item.observed_at < config.cutoff_policy.ready_at(day):
            raise ValueError("historical bar was observed before finalization")
        values = {k: p[k] for k in ("open", "high", "low", "close", "volume")}
        if any(isinstance(v, bool) or not math.isfinite(v) for v in values.values()):
            raise ValueError("historical OHLCV must be finite numeric values")
        bar = PriceBar(symbol=symbol, trade_date=day, price_basis=PriceBasis.RAW, **values)
        by_date[day] = item
        bars.append(bar)
    expected = calendar.sessions(config.start_date, end, cutoff=cutoff)
    if tuple(sorted(by_date)) != expected:
        raise ValueError("historical sessions incomplete; require an official amendment or suspension evidence")
    if len(bars) < config.minimum_bars:
        raise ValueError("insufficient historical bars for State bootstrap")
    return PriceSeries(symbol=symbol, price_basis=PriceBasis.RAW,
                       bars=tuple(sorted(bars, key=lambda b: b.trade_date))), by_date


def _verify_coverage_boundary(
    coverage: Evidence, announcements: tuple[Evidence, ...], *,
    config: HistoricalReplayConfig, symbol: str, end: date, cutoff,
    trusted_public_keys: Mapping[str, str] | None,
) -> None:
    if config.archive_mode == "SIGNED_PIT_V1":
        verify_signed_historical_coverage(
            coverage, announcements, market=config.market, symbol=symbol,
            start=config.start_date, end=end, cutoff=cutoff,
            trusted_public_keys=trusted_public_keys or {},
        )
    else:
        # Backward-compatible synthetic fixtures. This path does NOT certify live PIT.
        validate_action_coverage(
            coverage, announcements, market=config.market, symbol=symbol,
            start=config.start_date, end=end, cutoff=cutoff,
        )


def evaluate_historical_snapshot(
    snapshot: TruthSnapshot, config: HistoricalReplayConfig, *,
    trusted_public_keys: Mapping[str, str] | None = None,
) -> HistoricalReplay:
    verify_snapshot_integrity(snapshot)
    if snapshot.config_hash != derive_config_hash(config.model_dump(mode="json")):
        raise ValueError("historical replay config hash mismatch")
    if snapshot.assessment.decision_gate is not GateStatus.PASS:
        raise ValueError("historical State requires a PASS Truth gate")
    if any(e.evidence_type not in ("OHLCV", "CORPORATE_ACTION", "CORPORATE_ACTION_COVERAGE") for e in snapshot.evidence):
        raise ValueError("unsupported historical evidence type")
    raw, prices = _raw_prices(snapshot.evidence, symbol=snapshot.symbol, end=snapshot.trade_date,
                              cutoff=snapshot.analysis_cutoff, config=config)
    announcements = tuple(e for e in snapshot.evidence if e.evidence_type == "CORPORATE_ACTION")
    coverages = tuple(e for e in snapshot.evidence if e.evidence_type == "CORPORATE_ACTION_COVERAGE")
    if len(coverages) != 1:
        raise ValueError("exactly one historical corporate action coverage manifest is required")
    _verify_coverage_boundary(
        coverages[0], announcements, config=config, symbol=snapshot.symbol,
        end=snapshot.trade_date, cutoff=snapshot.analysis_cutoff,
        trusted_public_keys=trusted_public_keys,
    )
    factors = []
    for announcement in sorted(announcements, key=lambda e: (e.payload["event_date"], e.evidence_id)):
        event = date.fromisoformat(announcement.payload["event_date"])
        preceding = config.calendar.previous_session(event, cutoff=snapshot.analysis_cutoff)
        if preceding not in prices:
            raise ValueError("missing point-in-time pre-event close")
        factors.append(derive_adjustment_factor(
            announcement, prices[preceding], calendar=config.calendar,
            cutoff=snapshot.analysis_cutoff, as_of=snapshot.trade_date,
        ))
    adjusted = apply_back_adjustments(raw, tuple(f.action for f in factors),
                                      as_of=snapshot.trade_date, adjustment_version=config.factor_version)
    return HistoricalReplay(
        truth_hash=snapshot.content_hash, config_hash=snapshot.config_hash,
        adjusted=adjusted, factors=tuple(factors), inputs=derive_trend_inputs(adjusted, rs_20d=config.rs_20d),
        trend=evaluate_trend_from_prices(adjusted, rs_20d=config.rs_20d,
                                         confirmation_window=config.confirmation_window),
    )


def ingest_historical(*, provider: ProviderAdapter, request: ProviderRequest,
                      config: HistoricalReplayConfig, announcements: tuple[Evidence, ...],
                      coverage: Evidence, snapshot_id: str, store: TruthSnapshotStore,
                      trusted_public_keys: Mapping[str, str] | None = None) -> TruthSnapshot:
    require_historical_source(config.market, provider.metadata)
    if request.start_date != config.start_date or request.evidence_types != ("OHLCV",):
        raise ValueError("historical request/config window mismatch")
    config.cutoff_policy.require_finalized(config.calendar, request.end_date, request.analysis_cutoff)
    # Fail before any network access when the required action archive is absent/incomplete.
    _verify_coverage_boundary(
        coverage, announcements, config=config, symbol=request.symbol,
        end=request.end_date, cutoff=request.analysis_cutoff,
        trusted_public_keys=trusted_public_keys,
    )
    raw = provider.fetch(request)
    validated = validate_provider_output(metadata=provider.metadata, request=request, evidence=raw)
    verified = promote_validated_evidence(validated)
    config_payload = config.model_dump(mode="json")
    snapshot = build_truth_snapshot(
        snapshot_id=snapshot_id, symbol=request.symbol, trade_date=request.end_date,
        analysis_cutoff=request.analysis_cutoff, evidence=verified + announcements + (coverage,),
        assessment=EvidenceAssessment(coverage=100, freshness="PASS", provenance="PASS", decision_gate=GateStatus.PASS),
        config=config_payload,
    )
    evaluate_historical_snapshot(
        snapshot, config, trusted_public_keys=trusted_public_keys,
    )  # No invalid PASS snapshot is persisted.
    store.put(snapshot, config=config_payload)
    return snapshot


def replay_historical(
    *, store: TruthSnapshotStore, snapshot_id: str,
    trusted_public_keys: Mapping[str, str] | None = None,
    require_live_pit: bool = False,
) -> HistoricalReplay:
    snapshot = store.replay(snapshot_id)
    config = HistoricalReplayConfig.model_validate(store.replay_config(snapshot.config_hash))
    if require_live_pit and config.archive_mode != "SIGNED_PIT_V1":
        raise ValueError("synthetic replay cannot certify real historical PIT")
    return evaluate_historical_snapshot(
        snapshot, config, trusted_public_keys=trusted_public_keys,
    )
