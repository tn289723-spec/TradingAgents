from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from tradingagents_tw.contracts import PriceBasis, PriceSeries, StrictModel
from .indicators import IndicatorSpec, calculate_indicators


class ScreenRule(StrictModel):
    indicator: str
    operator: Literal[">", ">=", "<", "<=", "==", "crosses_above", "crosses_below"]
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    compare_to: str | None = None

    @model_validator(mode="after")
    def has_one_comparison(self):
        if (self.threshold is None) == (self.compare_to is None):
            raise ValueError("rule requires exactly one of threshold or compare_to")
        if self.operator.startswith("crosses_") and self.compare_to is None:
            raise ValueError("cross rules require compare_to")
        if self.compare_to == self.indicator:
            raise ValueError("rule cannot compare an indicator with itself")
        return self


class ScreenSpec(StrictModel):
    indicators: tuple[IndicatorSpec, ...]
    rules: tuple[ScreenRule, ...]

    @model_validator(mode="after")
    def rules_are_resolvable(self):
        keys = {spec.key for spec in self.indicators}
        if not self.rules:
            raise ValueError("screen requires at least one rule")
        if len(keys) != len(self.indicators):
            raise ValueError("indicator keys must be unique")
        if any(rule.indicator not in keys or (rule.compare_to is not None and rule.compare_to not in keys)
               for rule in self.rules):
            raise ValueError("every screen rule must reference a declared indicator")
        return self


class ScreenMatch(StrictModel):
    symbol: str
    as_of: date
    indicator_values: dict[str, float]
    matched_rules: tuple[str, ...]


def rules_match(
    rule_values: dict[str, float | None], rules: tuple[ScreenRule, ...],
    previous_values: dict[str, float | None] | None = None,
) -> bool:
    for rule in rules:
        left = rule_values.get(rule.indicator)
        right = rule_values.get(rule.compare_to) if rule.compare_to is not None else rule.threshold
        if left is None or right is None:
            return False
        if rule.operator.startswith("crosses_"):
            if previous_values is None:
                return False
            prev_left = previous_values.get(rule.indicator)
            prev_right = previous_values.get(rule.compare_to)
            if prev_left is None or prev_right is None:
                return False
            passed = (prev_left <= prev_right and left > right) if rule.operator == "crosses_above" else (
                prev_left >= prev_right and left < right
            )
        else:
            target = rule.threshold if rule.compare_to is None else right
            passed = {
                ">": left > target,
                ">=": left >= target,
                "<": left < target,
                "<=": left <= target,
                "==": left == target,
            }[rule.operator]
        if not passed:
            return False
    return True


def screen_universe(
    series: tuple[PriceSeries, ...], spec: ScreenSpec, *, as_of: date
) -> tuple[ScreenMatch, ...]:
    """Return symbols matching every rule on exactly the requested session."""
    symbols = [item.symbol for item in series]
    if len(symbols) != len(set(symbols)):
        raise ValueError("screen universe contains duplicate symbols")
    matches = []
    for item in series:
        if item.price_basis is not PriceBasis.RAW:
            raise ValueError("screening requires point-in-time RAW prices")
        if item.bars[-1].trade_date != as_of:
            raise ValueError(f"{item.symbol} does not have data for requested session")
        vectors = calculate_indicators(item, spec.indicators)
        values = {key: vector[-1] for key, vector in vectors.items()}
        previous = {key: vector[-2] if len(vector) > 1 else None for key, vector in vectors.items()}
        if rules_match(values, spec.rules, previous):
            matches.append(ScreenMatch(
                symbol=item.symbol, as_of=as_of,
                indicator_values={key: value for key, value in values.items() if value is not None},
                matched_rules=tuple(
                    f"{rule.indicator}{rule.operator}{rule.compare_to if rule.compare_to is not None else rule.threshold}"
                    for rule in spec.rules
                ),
            ))
    return tuple(sorted(matches, key=lambda item: item.symbol))
