from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from tradingagents_tw.contracts import DirectionalScore, ScoreComponent


@dataclass(frozen=True)
class ScoreConfig:
    version: str
    raw_min: float
    raw_max: float
    weights: tuple[tuple[str, float], ...]

    def weight_for(self, component: str) -> float:
        for key, weight in self.weights:
            if key == component:
                return weight
        raise KeyError(component)


V0_1_SCORE_CONFIG = ScoreConfig(
    version="score-v0.1",
    raw_min=-1.0,
    raw_max=1.0,
    weights=(
        ("TREND", 0.30),
        ("VOLUME_PRICE", 0.20),
        ("RELATIVE_STRENGTH", 0.15),
        ("FLOW", 0.15),
        ("FUNDAMENTAL", 0.10),
        ("EVENT", 0.10),
    ),
)


def normalize_raw_value(raw_value: float, *, config: ScoreConfig = V0_1_SCORE_CONFIG) -> float:
    if not config.raw_min < config.raw_max:
        raise ValueError("invalid normalization range")
    if raw_value < config.raw_min or raw_value > config.raw_max:
        raise ValueError("raw score must stay within the frozen normalization range")
    return ((raw_value - config.raw_min) / (config.raw_max - config.raw_min)) * 100.0


def build_score_components(
    raw_values: Mapping[str, float],
    *,
    config: ScoreConfig = V0_1_SCORE_CONFIG,
    rule_version: str = "component-normalization-v0.1",
) -> tuple[ScoreComponent, ...]:
    expected = tuple(name for name, _ in config.weights)
    if set(raw_values) != set(expected):
        missing = sorted(set(expected) - set(raw_values))
        extra = sorted(set(raw_values) - set(expected))
        raise ValueError(f"component set mismatch: missing={missing}, extra={extra}")

    components: list[ScoreComponent] = []
    for name, weight in config.weights:
        raw = float(raw_values[name])
        normalized = normalize_raw_value(raw, config=config)
        components.append(
            ScoreComponent(
                component=name,  # type: ignore[arg-type]
                raw_value=raw,
                normalized_value=normalized,
                weight=weight,
                contribution=normalized * weight,
                rule_version=rule_version,
            )
        )
    return tuple(components)


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
