from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingagents_tw.contracts import (
    CorporateAction,
    CorporateActionType,
    Evidence,
    EvidenceStatus,
    PriceBar,
    PriceBasis,
    PriceSeries,
    TrendAssessment,
    TrendState,
)
from tradingagents_tw.providers import (
    ProviderMetadata,
    ProviderRequest,
    TWSEStockDayAllAdapter,
    TWSE_STOCK_DAY_ALL_URL,
)
from tradingagents_tw.state import transition_trend
from tradingagents_tw.truth import (
    BACK_ADJUSTMENT_METHOD,
    ProviderBoundaryViolation,
    apply_back_adjustments,
    assess_evidence,
    build_truth_snapshot,
    validate_provider_output,
)

UTC = timezone.utc


def _request(symbol: str = "2330") -> ProviderRequest:
    return ProviderRequest(
        symbol=symbol,
        evidence_types=("OHLCV",),
        start_date=date(2026, 10, 23),
        end_date=date(2026, 10, 23),
        analysis_cutoff=datetime(2026, 10, 23, 16, tzinfo=UTC),
    )


def _raw_evidence(
    *,
    source: str = "TWSE_OPENAPI",
    symbol: str = "2330",
    observed_hour: int = 7,
    status: EvidenceStatus = EvidenceStatus.RAW,
) -> Evidence:
    return Evidence(
        evidence_id="e1",
        symbol=symbol,
        evidence_type="OHLCV",
        source=source,
        published_at=datetime(2026, 10, 23, observed_hour, tzinfo=UTC),
        observed_at=datetime(2026, 10, 23, observed_hour, tzinfo=UTC),
        content_hash="a" * 64,
        revision_id="r1",
        status=status,
        payload={"close": 100},
    )


def test_provider_boundary_accepts_matching_raw_evidence():
    metadata = ProviderMetadata(
        provider_id="twse-test",
        source="TWSE_OPENAPI",
        schema_version="1.0",
        evidence_types=("OHLCV",),
        source_priority=1,
    )
    evidence = (_raw_evidence(),)
    assert validate_provider_output(metadata=metadata, request=_request(), evidence=evidence) == evidence


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (_raw_evidence(source="OTHER"), "source mismatch"),
        (_raw_evidence(symbol="2317"), "symbol mismatch"),
        (_raw_evidence(status=EvidenceStatus.VERIFIED), "must enter Truth as RAW"),
        (_raw_evidence(observed_hour=17), "after analysis cutoff"),
    ],
)
def test_provider_boundary_fails_closed(evidence: Evidence, message: str):
    metadata = ProviderMetadata(
        provider_id="twse-test",
        source="TWSE_OPENAPI",
        schema_version="1.0",
        evidence_types=("OHLCV",),
        source_priority=1,
    )
    with pytest.raises(ProviderBoundaryViolation, match=message):
        validate_provider_output(metadata=metadata, request=_request(), evidence=(evidence,))


def test_corporate_action_dual_series_fixture():
    fixture_path = Path(__file__).with_name("fixtures") / "corporate_action_split_v0_1.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    raw = PriceSeries(
        symbol=data["symbol"],
        price_basis=PriceBasis.RAW,
        bars=tuple(
            PriceBar(
                symbol=data["symbol"],
                trade_date=date.fromisoformat(item["trade_date"]),
                open=item["open"],
                high=item["high"],
                low=item["low"],
                close=item["close"],
                volume=item["volume"],
                price_basis=PriceBasis.RAW,
            )
            for item in data["bars"]
        ),
    )
    action_data = data["action"]
    action = CorporateAction(
        action_id=action_data["action_id"],
        symbol=data["symbol"],
        action_type=CorporateActionType(action_data["action_type"]),
        event_date=date.fromisoformat(action_data["event_date"]),
        adjustment_factor=action_data["adjustment_factor"],
        adjustment_method=BACK_ADJUSTMENT_METHOD,
        source="TWSE",
        published_at=datetime(2026, 10, 20, 8, tzinfo=UTC),
        observed_at=datetime(2026, 10, 20, 8, tzinfo=UTC),
    )

    adjusted = apply_back_adjustments(raw, (action,), as_of=date(2026, 10, 23))
    assert raw.price_basis is PriceBasis.RAW
    assert adjusted.price_basis is PriceBasis.ADJUSTED
    assert adjusted.adjustment_method == BACK_ADJUSTMENT_METHOD
    assert adjusted.adjustment_as_of == date(2026, 10, 23)

    for actual, expected in zip(adjusted.bars, data["expected"], strict=True):
        assert actual.trade_date == date.fromisoformat(expected["trade_date"])
        assert actual.open == expected["open"]
        assert actual.high == expected["high"]
        assert actual.low == expected["low"]
        assert actual.close == expected["close"]
        assert actual.volume == expected["volume"]


@pytest.mark.parametrize("target", list(TrendState))
def test_transition_engine_supports_all_eight_states(target: TrendState):
    prior_state = TrendState.UPTREND if target is not TrendState.UPTREND else TrendState.DOWNTREND
    previous = TrendAssessment(
        state=prior_state,
        candidate_state=None,
        confirmation_progress=1.0,
        state_since=date(2026, 10, 20),
        rule_version="trend-hysteresis-v0.1",
    )
    candidate = TrendAssessment(
        state=target,
        candidate_state=None,
        confirmation_progress=1.0,
        state_since=date(2026, 10, 23),
        rule_version="candidate-test",
        reasons=("TABLE_TEST",),
    )
    result = transition_trend(
        previous=previous,
        candidate=candidate,
        as_of=date(2026, 10, 23),
        confirmation_window=1,
    )
    assert result.state is target


def test_truth_snapshot_identity_is_order_independent_and_config_sensitive():
    assessment = assess_evidence(coverage=100, freshness="PASS", provenance="PASS")
    a = _raw_evidence()
    b = Evidence(
        evidence_id="e2",
        symbol="2330",
        evidence_type="MATERIAL_EVENT",
        source="MOPS",
        published_at=datetime(2026, 10, 23, 6, tzinfo=UTC),
        observed_at=datetime(2026, 10, 23, 6, tzinfo=UTC),
        content_hash="b" * 64,
        revision_id="r1",
        status=EvidenceStatus.RAW,
        payload={"event": "test"},
    )

    one = build_truth_snapshot(
        snapshot_id="s1",
        symbol="2330",
        trade_date=date(2026, 10, 23),
        analysis_cutoff=datetime(2026, 10, 23, 16, tzinfo=UTC),
        evidence=(a, b),
        assessment=assessment,
        config={"critical_sources": ["TWSE", "MOPS"], "version": 1},
    )
    two = build_truth_snapshot(
        snapshot_id="s2",
        symbol="2330",
        trade_date=date(2026, 10, 23),
        analysis_cutoff=datetime(2026, 10, 23, 16, tzinfo=UTC),
        evidence=(b, a),
        assessment=assessment,
        config={"version": 1, "critical_sources": ["TWSE", "MOPS"]},
    )
    changed = build_truth_snapshot(
        snapshot_id="s3",
        symbol="2330",
        trade_date=date(2026, 10, 23),
        analysis_cutoff=datetime(2026, 10, 23, 16, tzinfo=UTC),
        evidence=(a, b),
        assessment=assessment,
        config={"critical_sources": ["TWSE"], "version": 2},
    )

    assert one.content_hash == two.content_hash
    assert one.config_hash == two.config_hash
    assert one.evidence == two.evidence
    assert one.content_hash != changed.content_hash
    assert one.config_hash != changed.config_hash


def test_twse_official_latest_adapter_parses_stock_day_all():
    rows = [
        {
            "Date": "1151023",
            "Code": "2330",
            "Name": "台積電",
            "TradeVolume": "31,000,000",
            "TradeValue": "75,000,000,000",
            "OpeningPrice": "2400.00",
            "HighestPrice": "2440.00",
            "LowestPrice": "2390.00",
            "ClosingPrice": "2435.00",
            "Change": "+35.00",
            "Transaction": "65,000",
        }
    ]
    observed = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
    adapter = TWSEStockDayAllAdapter(fetch_json=lambda: rows, clock=lambda: observed)
    request = ProviderRequest(
        symbol="2330",
        evidence_types=("OHLCV",),
        start_date=date(2026, 10, 23),
        end_date=date(2026, 10, 23),
        analysis_cutoff=datetime(2026, 10, 23, 16, tzinfo=UTC),
    )

    evidence = adapter.fetch(request)
    assert adapter.metadata.endpoint == TWSE_STOCK_DAY_ALL_URL
    assert adapter.metadata.history_mode == "LATEST_ONLY"
    assert len(evidence) == 1
    item = evidence[0]
    assert item.status is EvidenceStatus.RAW
    assert item.source == "TWSE_OPENAPI"
    assert item.payload["close"] == 2435.0
    assert item.payload["volume"] == 31_000_000
    assert item.payload["price_basis"] == "RAW"
    assert validate_provider_output(
        metadata=adapter.metadata, request=request, evidence=evidence
    ) == evidence


def test_twse_latest_adapter_refuses_historical_replay_after_cutoff():
    adapter = TWSEStockDayAllAdapter(
        fetch_json=lambda: [],
        clock=lambda: datetime(2026, 10, 24, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="cannot reconstruct"):
        adapter.fetch(_request())


def test_known_future_corporate_action_does_not_adjust_before_effective_date():
    raw = PriceSeries(
        symbol="9999",
        price_basis=PriceBasis.RAW,
        bars=(
            PriceBar(
                symbol="9999",
                trade_date=date(2026, 10, 23),
                open=100,
                high=110,
                low=90,
                close=100,
                volume=1000,
                price_basis=PriceBasis.RAW,
            ),
        ),
    )
    future = CorporateAction(
        action_id="future-split",
        symbol="9999",
        action_type=CorporateActionType.SPLIT,
        event_date=date(2026, 10, 24),
        adjustment_factor=0.5,
        adjustment_method=BACK_ADJUSTMENT_METHOD,
        source="TWSE",
        published_at=datetime(2026, 10, 20, 8, tzinfo=UTC),
        observed_at=datetime(2026, 10, 20, 8, tzinfo=UTC),
    )
    adjusted = apply_back_adjustments(raw, (future,), as_of=date(2026, 10, 23))
    assert adjusted.bars[0].close == 100
    assert adjusted.adjustment_as_of == date(2026, 10, 23)


def test_truth_snapshot_hash_normalizes_equivalent_timezone_instants():
    assessment = assess_evidence(coverage=100, freshness="PASS", provenance="PASS")
    evidence = (_raw_evidence(),)
    utc_cutoff = datetime(2026, 10, 23, 16, tzinfo=UTC)
    taipei_cutoff = datetime(2026, 10, 24, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    utc_snapshot = build_truth_snapshot(
        snapshot_id="tz-utc",
        symbol="2330",
        trade_date=date(2026, 10, 23),
        analysis_cutoff=utc_cutoff,
        evidence=evidence,
        assessment=assessment,
        config={"version": 1},
    )
    taipei_snapshot = build_truth_snapshot(
        snapshot_id="tz-taipei",
        symbol="2330",
        trade_date=date(2026, 10, 23),
        analysis_cutoff=taipei_cutoff,
        evidence=evidence,
        assessment=assessment,
        config={"version": 1},
    )
    assert utc_snapshot.content_hash == taipei_snapshot.content_hash
    assert utc_snapshot.config_hash == taipei_snapshot.config_hash
