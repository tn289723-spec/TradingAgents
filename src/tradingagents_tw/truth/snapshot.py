from __future__ import annotations

from datetime import date, datetime
from tradingagents_tw.contracts import Evidence, EvidenceAssessment, TruthSnapshot
from .point_in_time import assert_point_in_time


def build_truth_snapshot(
    *,
    snapshot_id: str,
    symbol: str,
    trade_date: date,
    analysis_cutoff: datetime,
    evidence: tuple[Evidence, ...],
    assessment: EvidenceAssessment,
) -> TruthSnapshot:
    for item in evidence:
        assert_point_in_time(item, analysis_cutoff)
    return TruthSnapshot(
        snapshot_id=snapshot_id,
        symbol=symbol,
        trade_date=trade_date,
        analysis_cutoff=analysis_cutoff,
        evidence=evidence,
        assessment=assessment,
    )
