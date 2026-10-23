from datetime import date, datetime, timezone
import pytest
from tradingagents_tw.contracts import (
    Evidence,
    EvidenceStatus,
    ScoreComponent,
    StateSnapshot,
)
from tradingagents_tw.state import TrendInputs, calculate_directional_score, canonical_state_json, classify_trend
from tradingagents_tw.truth import LookaheadViolation, assess_evidence, build_truth_snapshot

UTC = timezone.utc


def mk_evidence(hour: int) -> Evidence:
    return Evidence(
        evidence_id=f"e-{hour}",
        evidence_type="OHLCV",
        source="TWSE",
        published_at=datetime(2026, 10, 23, hour, tzinfo=UTC),
        observed_at=datetime(2026, 10, 23, hour, tzinfo=UTC),
        content_hash=f"h-{hour}",
        revision_id="r1",
        status=EvidenceStatus.VERIFIED,
        payload={"close": 100},
    )


def test_truth_snapshot_rejects_any_future_record():
    assessment = assess_evidence(coverage=100, freshness="PASS", provenance="PASS")
    with pytest.raises(LookaheadViolation):
        build_truth_snapshot(
            snapshot_id="s1",
            symbol="2330",
            trade_date=date(2026, 10, 23),
            analysis_cutoff=datetime(2026, 10, 23, 8, tzinfo=UTC),
            evidence=(mk_evidence(7), mk_evidence(9)),
            assessment=assessment,
        )


def test_same_inputs_produce_byte_stable_state_json():
    trend = classify_trend(
        TrendInputs(close=110, ma20=105, ma60=100, rs_20d=2, volume_ratio_20d=1.1),
        as_of=date(2026, 10, 23),
    )
    comp = ScoreComponent(
        component="TREND",
        raw_value=1,
        normalized_value=75,
        weight=1,
        contribution=75,
        rule_version="r1",
    )
    score = calculate_directional_score((comp,))
    a = StateSnapshot(snapshot_id="s", symbol="2330", trade_date=date(2026,10,23), trend=trend, directional_score=score, state_engine_version="e1", config_hash="cfg")
    b = StateSnapshot(snapshot_id="s", symbol="2330", trade_date=date(2026,10,23), trend=trend, directional_score=score, state_engine_version="e1", config_hash="cfg")
    assert canonical_state_json(a) == canonical_state_json(b)
