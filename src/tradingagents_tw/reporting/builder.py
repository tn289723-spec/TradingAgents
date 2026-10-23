"""Bind independently verified Truth and deterministic State into a DailyReport.

This function does not score, infer confidence, or certify historical PIT.
Callers must complete the signed replay/trust-root gate separately.
"""
from __future__ import annotations

from datetime import datetime

from tradingagents_tw.contracts import (
    ConfidenceBreakdown, DailyReport, EvidenceStatus, GateStatus,
    StateSnapshot, TruthSnapshot,
)
from tradingagents_tw.truth.store import verify_snapshot_integrity


def build_daily_report(
    *, truth: TruthSnapshot, state: StateSnapshot,
    confidence: ConfidenceBreakdown, analysis_run_id: str, generated_at: datetime,
) -> DailyReport:
    """Pure binding with fail-closed lineage checks; no new market judgments."""
    verify_snapshot_integrity(truth)
    if not analysis_run_id.strip():
        raise ValueError("analysis_run_id is required")
    if generated_at.utcoffset() is None or generated_at < truth.analysis_cutoff:
        raise ValueError("report generation must follow the aware analysis cutoff")
    if truth.assessment.decision_gate is not GateStatus.PASS:
        raise ValueError("a non-PASS Truth gate cannot produce a scored DailyReport")
    if (not truth.evidence or truth.assessment.critical_missing
            or truth.assessment.unresolved_conflicts
            or any(item.status is not EvidenceStatus.VERIFIED for item in truth.evidence)):
        raise ValueError("scored DailyReport requires complete VERIFIED Truth evidence")
    if (state.snapshot_id != truth.snapshot_id or state.symbol != truth.symbol
            or state.trade_date != truth.trade_date
            or state.config_hash != truth.config_hash):
        raise ValueError("Truth/State identity or config lineage mismatch")
    if state.trend.state_since > state.trade_date:
        raise ValueError("Trend state cannot originate after report trade date")
    return DailyReport(
        analysis_run_id=analysis_run_id,
        snapshot_id=truth.snapshot_id,
        symbol=truth.symbol,
        trade_date=truth.trade_date,
        directional_score=state.directional_score,
        trend=state.trend,
        confidence=confidence,
        evidence=truth.assessment,
        state_engine_version=state.state_engine_version,
        config_hash=truth.config_hash,
        generated_at=generated_at,
    )
