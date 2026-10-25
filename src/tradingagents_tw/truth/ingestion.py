from __future__ import annotations

from typing import Any, Mapping

from tradingagents_tw.contracts import (
    Evidence,
    EvidenceAssessment,
    EvidenceStatus,
    GateStatus,
    TruthSnapshot,
)
from tradingagents_tw.providers import ProviderAdapter, ProviderRequest
from tradingagents_tw.providers.base import ProviderUnavailable
from tradingagents_tw.providers.registry import HISTORICAL_SOURCES, LATEST_SOURCES, Market, official_latest_fallback_for

from .provider_boundary import validate_provider_output
from .snapshot import build_truth_snapshot
from .store import TruthSnapshotStore


class IngestionViolation(ValueError):
    pass


def promote_validated_evidence(
    evidence: tuple[Evidence, ...],
) -> tuple[Evidence, ...]:
    """Truth, not the provider, owns RAW -> VERIFIED promotion."""
    return tuple(
        item.model_copy(update={"status": EvidenceStatus.VERIFIED})
        for item in evidence
    )


def ingest_post_market(
    *,
    provider: ProviderAdapter,
    request: ProviderRequest,
    assessment: EvidenceAssessment,
    snapshot_id: str,
    store: TruthSnapshotStore,
    config: Mapping[str, Any] | None = None,
    fallback_provider: ProviderAdapter | None = None,
) -> TruthSnapshot:
    if request.start_date != request.end_date:
        raise IngestionViolation("V0.1 post-market ingestion requires one trade date")

    selected_provider = provider
    fallback_reason = None
    try:
        raw = provider.fetch(request)
        validated = validate_provider_output(metadata=provider.metadata, request=request, evidence=raw)
        if not validated:
            fallback_reason = "empty_primary"
    except (ProviderUnavailable, OSError, TimeoutError):
        fallback_reason = "primary_unavailable"
        validated = ()

    if fallback_reason is not None:
        try:
            market = {
                "TWSE_HISTORY": Market.TWSE,
                "TPEX_HISTORY": Market.TPEX,
            }[provider.metadata.source]
        except KeyError:
            market = None
        if market is not None:
            if provider.metadata != HISTORICAL_SOURCES[market]:
                raise IngestionViolation("official fallback requires registered same-board historical provider")
            backup = fallback_provider or official_latest_fallback_for(provider.metadata)
            if backup is not None:
                if backup.metadata != LATEST_SOURCES[market]:
                    raise IngestionViolation("fallback must be the registered same-board official latest source")
                if request.start_date != request.end_date:
                    raise IngestionViolation("latest-only fallback cannot fill historical date ranges")
                try:
                    backup_raw = backup.fetch(request)
                    validated = validate_provider_output(
                        metadata=backup.metadata, request=request, evidence=backup_raw
                    )
                except (ProviderUnavailable, OSError, TimeoutError) as exc:
                    raise IngestionViolation("primary and official fallback sources are unavailable") from exc
                selected_provider = backup

    if not validated and assessment.decision_gate is GateStatus.PASS:
        raise IngestionViolation("empty provider output cannot produce a PASS snapshot")

    verified = promote_validated_evidence(validated)
    config_payload = dict(config or {})
    if fallback_reason is not None and selected_provider is not provider:
        if "data_source_resolution" in config_payload:
            raise IngestionViolation("data_source_resolution is reserved for source fallback provenance")
        config_payload["data_source_resolution"] = {
            "mode": "OFFICIAL_SAME_BOARD_FALLBACK",
            "reason": fallback_reason,
            "attempted_provider_ids": [provider.metadata.provider_id, selected_provider.metadata.provider_id],
            "selected_provider_id": selected_provider.metadata.provider_id,
        }
    snapshot = build_truth_snapshot(
        snapshot_id=snapshot_id,
        symbol=request.symbol,
        trade_date=request.end_date,
        analysis_cutoff=request.analysis_cutoff,
        evidence=verified,
        assessment=assessment,
        config=config_payload,
    )
    store.put(snapshot, config=config_payload)
    return snapshot


def replay_truth_snapshot(
    *,
    store: TruthSnapshotStore,
    snapshot_id: str,
) -> TruthSnapshot:
    """Replay only persisted Truth. Live providers are deliberately absent."""
    return store.replay(snapshot_id)
