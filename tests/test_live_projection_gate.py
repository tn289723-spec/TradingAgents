"""Attested projection publication requires real signed-PIT semantics.

Fixtures are synthetic cryptographic tests only; they do not establish production
historical completeness or a production attestor.
"""
from datetime import timedelta

import pytest

from test_historical_replay import setup_case
from test_pit_historical_ingestion import TRUST, signed_case
from tradingagents_tw.contracts import (
    ConfidenceBreakdown,
    DirectionalScore,
    ScoreComponent,
    StateSnapshot,
    TrendState,
)
from tradingagents_tw.reporting import (
    PIT_ATTESTATION_CERTIFICATION,
    build_attested_dashboard_projection,
    render_attested_dashboard_projection_json,
)
from tradingagents_tw.truth.historical_replay import ingest_historical, replay_historical


def _state(snapshot, replay):
    score = DirectionalScore(
        score=50,
        components=(
            ScoreComponent(
                component="TREND",
                raw_value=0,
                normalized_value=50,
                weight=1,
                contribution=50,
                rule_version="publication-gate-test",
            ),
        ),
        scoring_version="score-v0.1",
    )
    return StateSnapshot(
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        trade_date=snapshot.trade_date,
        trend=replay.trend,
        directional_score=score,
        state_engine_version="state-v0.1",
        config_hash=snapshot.config_hash,
    )


def _confidence():
    return ConfidenceBreakdown(
        evidence_confidence=100,
        final_confidence=80,
    )


def test_signed_pit_gate_marks_attested_projection(tmp_path):
    args, _ = signed_case(tmp_path)
    args["trusted_public_keys"] = TRUST
    snapshot = ingest_historical(**args)
    replay = replay_historical(
        store=args["store"],
        snapshot_id=args["snapshot_id"],
        trusted_public_keys=TRUST,
        require_live_pit=True,
    )
    projection = build_attested_dashboard_projection(
        store=args["store"],
        snapshot_id=args["snapshot_id"],
        state=_state(snapshot, replay),
        confidence=_confidence(),
        analysis_run_id="attested-run",
        generated_at=snapshot.analysis_cutoff + timedelta(minutes=1),
        trusted_public_keys=TRUST,
    )
    assert projection.historical_pit_certification == PIT_ATTESTATION_CERTIFICATION
    assert projection.snapshot_id == snapshot.snapshot_id
    assert projection.trend_state == replay.trend.state
    assert "exchange is not the attestor" in " ".join(projection.limitations)
    rendered = render_attested_dashboard_projection_json(
        store=args["store"],
        snapshot_id=args["snapshot_id"],
        state=_state(snapshot, replay),
        confidence=_confidence(),
        analysis_run_id="attested-run",
        generated_at=snapshot.analysis_cutoff + timedelta(minutes=1),
        trusted_public_keys=TRUST,
    )
    assert PIT_ATTESTATION_CERTIFICATION in rendered


def test_synthetic_historical_replay_cannot_publish_attested_projection(tmp_path):
    args, _, _ = setup_case(tmp_path)
    snapshot = ingest_historical(**args)
    replay = replay_historical(store=args["store"], snapshot_id=args["snapshot_id"])
    with pytest.raises(ValueError, match="synthetic replay cannot certify real historical PIT"):
        build_attested_dashboard_projection(
            store=args["store"],
            snapshot_id=args["snapshot_id"],
            state=_state(snapshot, replay),
            confidence=_confidence(),
            analysis_run_id="synthetic-run",
            generated_at=snapshot.analysis_cutoff + timedelta(minutes=1),
            trusted_public_keys=TRUST,
        )


def test_wrong_trust_root_cannot_publish_attested_projection(tmp_path):
    args, _ = signed_case(tmp_path)
    args["trusted_public_keys"] = TRUST
    snapshot = ingest_historical(**args)
    replay = replay_historical(
        store=args["store"], snapshot_id=args["snapshot_id"],
        trusted_public_keys=TRUST, require_live_pit=True,
    )
    with pytest.raises(ValueError):
        build_attested_dashboard_projection(
            store=args["store"],
            snapshot_id=args["snapshot_id"],
            state=_state(snapshot, replay),
            confidence=_confidence(),
            analysis_run_id="wrong-key-run",
            generated_at=snapshot.analysis_cutoff + timedelta(minutes=1),
            trusted_public_keys={next(iter(TRUST)): "0" * 64},
        )


def test_state_must_match_verified_historical_trend(tmp_path):
    args, _ = signed_case(tmp_path)
    args["trusted_public_keys"] = TRUST
    snapshot = ingest_historical(**args)
    replay = replay_historical(
        store=args["store"], snapshot_id=args["snapshot_id"],
        trusted_public_keys=TRUST, require_live_pit=True,
    )
    state = _state(snapshot, replay)
    other = TrendState.SIDEWAYS if replay.trend.state is not TrendState.SIDEWAYS else TrendState.UPTREND
    state = state.model_copy(update={
        "trend": state.trend.model_copy(update={"state": other})
    })
    with pytest.raises(ValueError, match="State trend does not match"):
        build_attested_dashboard_projection(
            store=args["store"],
            snapshot_id=args["snapshot_id"],
            state=state,
            confidence=_confidence(),
            analysis_run_id="mismatch-run",
            generated_at=snapshot.analysis_cutoff + timedelta(minutes=1),
            trusted_public_keys=TRUST,
        )
