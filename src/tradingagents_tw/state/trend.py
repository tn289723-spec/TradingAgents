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


def classify_trend(inputs: TrendInputs, *, as_of: date, rule_version: str = "trend-v0.1") -> TrendAssessment:
    """Small deterministic V0.1 baseline. Thresholds are explicit and versioned."""
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
