from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError
from tradingagents_tw.contracts import (
    ConfidenceBreakdown,
    CorporateAction,
    CorporateActionType,
    DailyReport,
    DirectionalScore,
    EvidenceAssessment,
    GateStatus,
    PeerMembership,
    ScoreComponent,
    TrendAssessment,
    TrendState,
)
from tradingagents_tw.reporting import render_daily_report

UTC = timezone.utc


def test_peer_membership_rejects_inverted_validity_window():
    with pytest.raises(ValidationError):
        PeerMembership(
            symbol="3037",
            peer_group_id="ABF",
            valid_from=date(2026, 10, 1),
            valid_until=date(2026, 9, 1),
            source="internal",
            confidence=90,
        )


def test_corporate_action_requires_possible_chronology():
    with pytest.raises(ValidationError):
        CorporateAction(
            action_id="a1",
            symbol="2330",
            action_type=CorporateActionType.DIVIDEND,
            event_date=date(2026, 10, 23),
            adjustment_method="vendor-factor",
            source="TWSE",
            published_at=datetime(2026, 10, 23, 9, tzinfo=UTC),
            observed_at=datetime(2026, 10, 23, 8, tzinfo=UTC),
        )


def test_markdown_is_projection_of_daily_report():
    comps = (
        ScoreComponent(component="TREND", raw_value=1, normalized_value=80, weight=1, contribution=80, rule_version="r1"),
    )
    report = DailyReport(
        analysis_run_id="run-1",
        snapshot_id="snap-1",
        symbol="3037",
        trade_date=date(2026, 10, 23),
        directional_score=DirectionalScore(score=80, components=comps, scoring_version="s1"),
        trend=TrendAssessment(state=TrendState.UPTREND, confirmation_progress=1, state_since=date(2026, 10, 20), rule_version="t1"),
        confidence=ConfidenceBreakdown(evidence_confidence=90, final_confidence=70),
        evidence=EvidenceAssessment(coverage=95, freshness="PASS", provenance="PASS", decision_gate=GateStatus.PASS),
        state_engine_version="state-v0.1",
        config_hash="cfg",
        generated_at=datetime(2026, 10, 23, 8, tzinfo=UTC),
    )
    md = render_daily_report(report)
    assert "3037" in md
    assert "80.0 / 100" in md
    assert "Decision Gate: PASS" in md
    assert "snap-1" in md
