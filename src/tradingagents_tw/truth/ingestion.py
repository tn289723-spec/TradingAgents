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
) -> TruthSnapshot:
    if request.start_date != request.end_date:
        raise IngestionViolation("V0.1 post-market ingestion requires one trade date")

    raw = provider.fetch(request)
    validated = validate_provider_output(
        metadata=provider.metadata,
        request=request,
        evidence=raw,
    )

    if not validated and assessment.decision_gate is GateStatus.PASS:
        raise IngestionViolation("empty provider output cannot produce a PASS snapshot")

    verified = promote_validated_evidence(validated)
    config_payload = dict(config or {})
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
