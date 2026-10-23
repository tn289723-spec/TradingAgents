from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from tradingagents_tw.contracts import Evidence, EvidenceAssessment, TruthSnapshot
from .identity import canonical_evidence, derive_config_hash, derive_truth_content_hash
from .point_in_time import assert_point_in_time


def build_truth_snapshot(
    *,
    snapshot_id: str,
    symbol: str,
    trade_date: date,
    analysis_cutoff: datetime,
    evidence: tuple[Evidence, ...],
    assessment: EvidenceAssessment,
    config: Mapping[str, Any] | None = None,
) -> TruthSnapshot:
    ordered = canonical_evidence(evidence)
    for item in ordered:
        assert_point_in_time(item, analysis_cutoff)

    config_hash = derive_config_hash(config or {})
    content_hash = derive_truth_content_hash(
        symbol=symbol,
        trade_date=trade_date,
        analysis_cutoff=analysis_cutoff,
        evidence=ordered,
        assessment=assessment,
        config_hash=config_hash,
    )
    return TruthSnapshot(
        snapshot_id=snapshot_id,
        symbol=symbol,
        trade_date=trade_date,
        analysis_cutoff=analysis_cutoff,
        evidence=ordered,
        assessment=assessment,
        content_hash=content_hash,
        config_hash=config_hash,
    )
