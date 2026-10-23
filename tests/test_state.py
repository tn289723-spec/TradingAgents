from datetime import date
import pytest
from tradingagents_tw.contracts import ScoreComponent, TrendState
from tradingagents_tw.state import TrendInputs, calculate_directional_score, classify_trend


def test_trend_is_deterministic():
    inputs = TrendInputs(close=110, ma20=105, ma60=100, rs_20d=3.2, volume_ratio_20d=1.3)
    a = classify_trend(inputs, as_of=date(2026, 10, 23))
    b = classify_trend(inputs, as_of=date(2026, 10, 23))
    assert a == b
    assert a.state == TrendState.STRONG_UPTREND


def test_score_is_explainable_and_recomputed():
    components = (
        ScoreComponent(component="TREND", raw_value=1, normalized_value=80, weight=.5, contribution=40, rule_version="r1"),
        ScoreComponent(component="VOLUME_PRICE", raw_value=1, normalized_value=60, weight=.5, contribution=30, rule_version="r1"),
    )
    score = calculate_directional_score(components)
    assert score.score == 70


def test_score_rejects_hidden_weight_error():
    components = (
        ScoreComponent(component="TREND", raw_value=1, normalized_value=80, weight=.7, contribution=56, rule_version="r1"),
    )
    with pytest.raises(ValueError):
        calculate_directional_score(components)
