from __future__ import annotations

from enum import Enum
from statistics import fmean

from pydantic import Field

from tradingagents_tw.contracts import PriceBasis, PriceSeries, StrictModel


class IndicatorKind(str, Enum):
    SMA = "SMA"
    RSI = "RSI"
    RETURN = "RETURN"
    VOLUME_RATIO = "VOLUME_RATIO"


class IndicatorSpec(StrictModel):
    kind: IndicatorKind
    window: int = Field(ge=2, le=250, strict=True)

    @property
    def key(self) -> str:
        return f"{self.kind.value}_{self.window}"


def calculate_indicators(
    series: PriceSeries, specs: tuple[IndicatorSpec, ...]
) -> dict[str, tuple[float | None, ...]]:
    """Calculate causal indicators; each index uses only bars through that date.

    `VOLUME_RATIO_N` compares today's volume with the mean of the prior N bars.
    `RETURN_N` is close-to-close return over N completed intervals. RSI uses
    simple N-period average gains/losses (not Wilder smoothing), fixed as v1.
    """
    if series.price_basis is not PriceBasis.RAW:
        raise ValueError("research indicators require point-in-time RAW prices")
    keys = [spec.key for spec in specs]
    if len(set(keys)) != len(keys):
        raise ValueError("indicator specifications must have unique keys")

    closes = [bar.close for bar in series.bars]
    volumes = [bar.volume for bar in series.bars]
    result: dict[str, tuple[float | None, ...]] = {}
    for spec in specs:
        values: list[float | None] = []
        n = spec.window
        for i in range(len(series.bars)):
            if spec.kind is IndicatorKind.SMA:
                values.append(fmean(closes[i - n + 1:i + 1]) if i + 1 >= n else None)
            elif spec.kind is IndicatorKind.RETURN:
                values.append(closes[i] / closes[i - n] - 1 if i >= n else None)
            elif spec.kind is IndicatorKind.VOLUME_RATIO:
                prior = volumes[i - n:i]
                baseline = fmean(prior) if len(prior) == n else 0
                values.append(volumes[i] / baseline if baseline > 0 else None)
            else:
                changes = [closes[j] - closes[j - 1] for j in range(i - n + 1, i + 1)] if i >= n else []
                if not changes:
                    values.append(None)
                    continue
                gains = fmean(max(change, 0.0) for change in changes)
                losses = fmean(max(-change, 0.0) for change in changes)
                values.append(50.0 if gains == 0 and losses == 0 else
                              100.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses))
        result[spec.key] = tuple(values)
    return result
