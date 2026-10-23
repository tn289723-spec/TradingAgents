from __future__ import annotations

from tradingagents_tw.contracts import DirectionalScore, ScoreComponent


def calculate_directional_score(
    components: tuple[ScoreComponent, ...], *, scoring_version: str = "score-v0.1"
) -> DirectionalScore:
    total_weight = sum(c.weight for c in components)
    if not components or abs(total_weight - 1.0) > 1e-9:
        raise ValueError("component weights must sum to 1.0")

    expected = sum(c.normalized_value * c.weight for c in components)
    declared = sum(c.contribution for c in components)
    if abs(expected - declared) > 1e-6:
        raise ValueError("component contribution mismatch")

    return DirectionalScore(
        score=round(expected, 4),
        components=components,
        scoring_version=scoring_version,
    )
