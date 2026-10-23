"""DailyReport lineage and UI projection must fail closed without invented facts."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from tradingagents_tw.contracts import (
    ConfidenceBreakdown, DirectionalScore, Evidence, EvidenceAssessment,
    EvidenceStatus, GateStatus, ScoreComponent, StateSnapshot,
    TrendAssessment, TrendState,
)
from tradingagents_tw.reporting import (
    build_daily_report, project_daily_report, render_dashboard_projection_json,
)
from tradingagents_tw.truth.snapshot import build_truth_snapshot

UTC = timezone.utc
DAY = date(2026, 10, 23)
CUTOFF = datetime(2026, 10, 23, 10, tzinfo=UTC)


def fixtures():
    assessment = EvidenceAssessment(
        coverage=100, freshness="PASS", provenance="PASS",
        decision_gate=GateStatus.PASS,
    )
    evidence = Evidence(
        evidence_id="verified-1", symbol="2330", evidence_type="OHLCV",
        source="test-fixture", published_at=CUTOFF - timedelta(hours=2),
        observed_at=CUTOFF - timedelta(hours=1), content_hash="a" * 64,
        revision_id="r1", status=EvidenceStatus.VERIFIED, payload={"fixture": True},
    )
    truth = build_truth_snapshot(
        snapshot_id="snap-1", symbol="2330", trade_date=DAY,
        analysis_cutoff=CUTOFF, evidence=(evidence,),
        assessment=assessment, config={"fixture": 1},
    )
    score = DirectionalScore(
        score=60, components=(
            ScoreComponent(component="TREND", raw_value=.2,
                           normalized_value=60, weight=1,
                           contribution=60, rule_version="test"),
        ), scoring_version="score-v0.1",
    )
    trend = TrendAssessment(
        state=TrendState.UPTREND, confirmation_progress=1,
        state_since=DAY, rule_version="trend-v0.1",
    )
    state = StateSnapshot(
        snapshot_id=truth.snapshot_id, symbol=truth.symbol, trade_date=truth.trade_date,
        trend=trend, directional_score=score, state_engine_version="state-v0.1",
        config_hash=truth.config_hash,
    )
    confidence = ConfidenceBreakdown(
        evidence_confidence=80, final_confidence=70,
        limitations=("Live PIT completeness is not certified",),
    )
    return truth, state, confidence


def report():
    truth, state, confidence = fixtures()
    return build_daily_report(
        truth=truth, state=state, confidence=confidence,
        analysis_run_id="run-1", generated_at=CUTOFF + timedelta(minutes=1),
    )


def test_daily_report_binds_existing_truth_state_without_rescoring():
    r = report()
    assert r.directional_score.score == 60
    assert r.trend.state is TrendState.UPTREND
    assert r.config_hash == fixtures()[0].config_hash


@pytest.mark.parametrize("field,value", [
    ("snapshot_id", "other"), ("symbol", "2317"),
    ("trade_date", date(2026, 10, 22)), ("config_hash", "different"),
])
def test_rejects_truth_state_lineage_mismatch(field, value):
    truth, state, confidence = fixtures()
    with pytest.raises(ValueError, match="lineage"):
        build_daily_report(
            truth=truth, state=state.model_copy(update={field: value}),
            confidence=confidence, analysis_run_id="run-1",
            generated_at=CUTOFF + timedelta(minutes=1),
        )


def test_rejects_tampered_truth_and_premature_report():
    truth, state, confidence = fixtures()
    with pytest.raises(ValueError):
        build_daily_report(
            truth=truth.model_copy(update={"content_hash": "f" * 64}),
            state=state, confidence=confidence, analysis_run_id="run-1",
            generated_at=CUTOFF + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="cutoff"):
        build_daily_report(
            truth=truth, state=state, confidence=confidence,
            analysis_run_id="run-1", generated_at=CUTOFF - timedelta(seconds=1),
        )


def test_rejects_nonpass_truth_before_scored_report():
    truth, state, confidence = fixtures()
    with pytest.raises(ValueError, match="non-PASS"):
        build_daily_report(
            truth=truth.model_copy(update={
                "assessment": truth.assessment.model_copy(
                    update={"decision_gate": GateStatus.BLOCKED}
                )
            }), state=state, confidence=confidence,
            analysis_run_id="run-1", generated_at=CUTOFF + timedelta(minutes=1),
        )


def test_projection_is_read_only_and_does_not_claim_pit_or_thesis():
    r = report()
    p = project_daily_report(r)
    assert p.traffic_light == "GREEN"
    assert p.traffic_light_meaning == "EVIDENCE_READINESS_ONLY"
    assert p.directional_score == 60
    assert p.confidence == 70
    assert p.five_day_change is None
    assert p.most_likely_wrong is None
    assert p.thesis_status == "NOT_ASSESSED"
    assert p.historical_pit_certification == "NOT_ESTABLISHED_BY_REPORT"
    assert "Live PIT completeness is not certified" in p.limitations
    assert json.loads(render_dashboard_projection_json(r)) == p.model_dump(mode="json")


@pytest.mark.parametrize("gate,light", [
    (GateStatus.DEGRADED, "YELLOW"), (GateStatus.BLOCKED, "RED"),
])
def test_traffic_lights_mean_evidence_gate_only(gate, light):
    r = report()
    modified = r.model_copy(update={
        "evidence": r.evidence.model_copy(update={"decision_gate": gate})
    })
    assert project_daily_report(modified).traffic_light == light


def test_contradictory_green_gate_fails_closed():
    r = report()
    modified = r.model_copy(update={
        "evidence": r.evidence.model_copy(update={"critical_missing": ("OHLCV",)})
    })
    with pytest.raises(ValueError, match="contradicts"):
        project_daily_report(modified)
