from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from tradingagents_tw.contracts import TrendAssessment, TrendState


@dataclass(frozen=True)
class TrendInputs:
    close: float
    ma20: float
    ma60: float
    rs_20d: float
    volume_ratio_20d: float


def classify_trend(
    inputs: TrendInputs, *, as_of: date, rule_version: str = "trend-candidate-v0.1"
) -> TrendAssessment:
    """Deterministically classify the candidate state from current inputs only."""
    reasons: list[str] = []

    if inputs.close > inputs.ma20 > inputs.ma60 and inputs.rs_20d > 0:
        state = TrendState.STRONG_UPTREND if inputs.volume_ratio_20d >= 1.2 else TrendState.UPTREND
        reasons += ["CLOSE_GT_MA20_GT_MA60", "RS_POSITIVE"]
    elif inputs.close < inputs.ma20 < inputs.ma60 and inputs.rs_20d < 0:
        state = TrendState.STRONG_DOWNTREND if inputs.volume_ratio_20d >= 1.2 else TrendState.DOWNTREND
        reasons += ["CLOSE_LT_MA20_LT_MA60", "RS_NEGATIVE"]
    elif inputs.close < inputs.ma20 and inputs.ma20 > inputs.ma60:
        state = TrendState.PULLBACK_IN_UPTREND
        reasons.append("PRICE_BELOW_MA20_BUT_MA20_GT_MA60")
    else:
        state = TrendState.SIDEWAYS
        reasons.append("NO_DOMINANT_TREND")

    return TrendAssessment(
        state=state,
        candidate_state=None,
        confirmation_progress=1.0,
        state_since=as_of,
        rule_version=rule_version,
        reasons=tuple(reasons),
    )


def transition_trend(
    *,
    previous: TrendAssessment | None,
    candidate: TrendAssessment,
    as_of: date,
    confirmation_window: int = 2,
    rule_version: str = "trend-hysteresis-v0.1",
) -> TrendAssessment:
    """Apply deterministic hysteresis; a state change requires repeated confirmation."""
    if confirmation_window < 1:
        raise ValueError("confirmation_window must be >= 1")

    if previous is None:
        return TrendAssessment(
            state=candidate.state,
            candidate_state=None,
            confirmation_progress=1.0,
            state_since=as_of,
            rule_version=rule_version,
            reasons=candidate.reasons + ("INITIAL_STATE",),
        )

    if candidate.state == previous.state:
        return TrendAssessment(
            state=previous.state,
            candidate_state=None,
            confirmation_progress=1.0,
            state_since=previous.state_since,
            rule_version=rule_version,
            reasons=candidate.reasons + ("STATE_CONFIRMED",),
        )

    step = 1.0 / confirmation_window
    if previous.candidate_state == candidate.state:
        progress = min(1.0, previous.confirmation_progress + step)
    else:
        progress = step

    if progress >= 1.0:
        return TrendAssessment(
            state=candidate.state,
            candidate_state=None,
            confirmation_progress=1.0,
            state_since=as_of,
            rule_version=rule_version,
            reasons=candidate.reasons + ("STATE_TRANSITION_CONFIRMED",),
        )

    return TrendAssessment(
        state=previous.state,
        candidate_state=candidate.state,
        confirmation_progress=progress,
        state_since=previous.state_since,
        rule_version=rule_version,
        reasons=candidate.reasons + ("STATE_TRANSITION_PENDING",),
    )


def evaluate_trend(
    inputs: TrendInputs,
    *,
    as_of: date,
    previous: TrendAssessment | None = None,
    confirmation_window: int = 2,
    rule_version: str = "trend-hysteresis-v0.1",
) -> TrendAssessment:
    candidate = classify_trend(inputs, as_of=as_of)
    return transition_trend(
        previous=previous,
        candidate=candidate,
        as_of=as_of,
        confirmation_window=confirmation_window,
        rule_version=rule_version,
    )
