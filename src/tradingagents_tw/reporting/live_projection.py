"""Fail-closed publication gate for an attested historical dashboard projection.

A DailyReport cannot self-certify PIT. This module requires a persisted SIGNED_PIT_V1
historical snapshot to replay successfully with pinned trusted public keys, then binds
that verified replay to the deterministic State before marking the projection.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Mapping, Literal

from tradingagents_tw.contracts import ConfidenceBreakdown, StateSnapshot
from tradingagents_tw.truth.historical_replay import replay_historical
from tradingagents_tw.state.score import (
    V0_1_SCORE_CONFIG, build_score_components, calculate_directional_score,
)
from tradingagents_tw.truth.store import TruthSnapshotStore

from .builder import build_daily_report
from .projection import DashboardProjection, project_daily_report


PIT_ATTESTATION_CERTIFICATION: Literal[
    "SIGNED_PIT_V1_ATTESTATION_VERIFIED"
] = "SIGNED_PIT_V1_ATTESTATION_VERIFIED"

_ATTESTATION_LIMITATION = (
    "SIGNED_PIT_V1 verifies a pinned attestor-bound completeness claim; "
    "the exchange is not the attestor. "
    "Score arithmetic is checked against frozen v0.1 weights; component inputs "
    "and confidence are not independently attested by this PIT gate."
)


def _require_frozen_score_consistency(state: StateSnapshot) -> None:
    """Reject forged arithmetic; do not infer that inputs have independent provenance."""
    score = state.directional_score
    if score.scoring_version != V0_1_SCORE_CONFIG.version:
        raise ValueError("attested projection requires frozen v0.1 scoring version")
    raw = {item.component: item.raw_value for item in score.components}
    if len(raw) != len(score.components):
        raise ValueError("duplicate State score component")
    expected_components = build_score_components(raw)
    if score.components != expected_components:
        raise ValueError("State score components diverge from frozen v0.1 rules")
    if score.score != calculate_directional_score(expected_components).score:
        raise ValueError("State directional score mismatch")


def build_attested_dashboard_projection(
    *,
    store: TruthSnapshotStore,
    snapshot_id: str,
    state: StateSnapshot,
    confidence: ConfidenceBreakdown,
    analysis_run_id: str,
    generated_at: datetime,
    trusted_public_keys: Mapping[str, str],
) -> DashboardProjection:
    """Build a projection only after the signed historical PIT gate passes.

    This does not create a trust root and does not convert a self-signed or synthetic
    archive into independent evidence. The trusted key mapping must be provisioned
    out-of-band by the production operator.
    """
    replay = replay_historical(
        store=store,
        snapshot_id=snapshot_id,
        trusted_public_keys=trusted_public_keys,
        require_live_pit=True,
    )
    truth = store.replay(snapshot_id)

    if replay.truth_hash != truth.content_hash or replay.config_hash != truth.config_hash:
        raise ValueError("verified historical replay identity mismatch")
    if state.trend != replay.trend:
        raise ValueError("State trend does not match verified historical replay")
    _require_frozen_score_consistency(state)

    report = build_daily_report(
        truth=truth,
        state=state,
        confidence=confidence,
        analysis_run_id=analysis_run_id,
        generated_at=generated_at,
    )
    projection = project_daily_report(report)
    limitations = tuple(dict.fromkeys(
        projection.limitations + (_ATTESTATION_LIMITATION,)
    ))
    return DashboardProjection.model_validate({
        **projection.model_dump(mode="json"),
        "historical_pit_certification": PIT_ATTESTATION_CERTIFICATION,
        "limitations": limitations,
    })


def render_attested_dashboard_projection_json(**kwargs) -> str:
    projection = build_attested_dashboard_projection(**kwargs)
    return json.dumps(
        projection.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
