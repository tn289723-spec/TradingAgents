from __future__ import annotations

from tradingagents_tw.contracts import DailyReport


def render_daily_report(report: DailyReport) -> str:
    """Presentation is a pure projection of DailyReport; it adds no facts."""
    gate = report.evidence.decision_gate.value
    trend = report.trend.state.value
    return "\n".join(
        [
            f"# {report.symbol}｜{report.trade_date.isoformat()} 盤後",
            "",
            f"Directional Score: {report.directional_score.score:.1f} / 100",
            f"Trend State: {trend}",
            f"Confidence: {report.confidence.final_confidence:.1f} / 100",
            f"Decision Gate: {gate}",
            "",
            "## Evidence",
            f"Coverage: {report.evidence.coverage:.1f}%",
            f"Freshness: {report.evidence.freshness}",
            f"Provenance: {report.evidence.provenance}",
            f"Critical Missing: {', '.join(report.evidence.critical_missing) or 'NONE'}",
            "",
            f"analysis_run_id: {report.analysis_run_id}",
            f"snapshot_id: {report.snapshot_id}",
            f"state_engine_version: {report.state_engine_version}",
            f"config_hash: {report.config_hash}",
        ]
    )
