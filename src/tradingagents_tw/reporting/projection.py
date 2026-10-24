"""Read-only mobile dashboard contract: never infer market direction from colors."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from tradingagents_tw.contracts import DailyReport, GateStatus, StrictModel, TrendState


class DashboardProjection(StrictModel):
    projection_version: Literal["dashboard-projection-v1"] = "dashboard-projection-v1"
    analysis_run_id: str
    snapshot_id: str
    symbol: str
    trade_date: date
    generated_at: datetime
    directional_score: float = Field(ge=0, le=100, allow_inf_nan=False)
    trend_state: TrendState
    confidence: float = Field(ge=0, le=100, allow_inf_nan=False)
    decision_gate: GateStatus
    traffic_light: Literal["GREEN", "YELLOW", "RED"]
    traffic_light_meaning: Literal["EVIDENCE_READINESS_ONLY"] = "EVIDENCE_READINESS_ONLY"
    score_slope_5d: float | None = Field(default=None, allow_inf_nan=False)
    five_day_change: None = None
    most_likely_wrong: None = None
    thesis_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    historical_pit_certification: Literal["NOT_ESTABLISHED_BY_REPORT", "SIGNED_PIT_V1_ATTESTATION_VERIFIED"] = "NOT_ESTABLISHED_BY_REPORT"
    limitations: tuple[str, ...] = ()


_GATE_LIGHT = {
    GateStatus.PASS: "GREEN",
    GateStatus.DEGRADED: "YELLOW",
    GateStatus.BLOCKED: "RED",
}


def project_daily_report(report: DailyReport) -> DashboardProjection:
    """Project supplied fields only. Missing analyses remain explicit nulls."""
    if report.schema_version != "1.0":
        raise ValueError("unsupported DailyReport schema_version")
    if (report.evidence.unresolved_conflicts
            and report.evidence.decision_gate is not GateStatus.BLOCKED):
        raise ValueError("unresolved conflicts require BLOCKED evidence gate")
    if (report.evidence.decision_gate is GateStatus.PASS
            and report.evidence.critical_missing):
        raise ValueError("PASS gate contradicts critical missing evidence")
    limitations = tuple(dict.fromkeys(
        report.confidence.limitations + report.evidence.gate_reasons
        + report.evidence.critical_missing + report.evidence.unresolved_conflicts
    ))
    return DashboardProjection(
        analysis_run_id=report.analysis_run_id,
        snapshot_id=report.snapshot_id,
        symbol=report.symbol,
        trade_date=report.trade_date,
        generated_at=report.generated_at,
        directional_score=report.directional_score.score,
        trend_state=report.trend.state,
        confidence=report.confidence.final_confidence,
        decision_gate=report.evidence.decision_gate,
        traffic_light=_GATE_LIGHT[report.evidence.decision_gate],
        score_slope_5d=report.directional_score.slope_5d,
        limitations=limitations,
    )


def render_dashboard_projection_json(report: DailyReport) -> str:
    return json.dumps(
        project_daily_report(report).model_dump(mode="json"),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
