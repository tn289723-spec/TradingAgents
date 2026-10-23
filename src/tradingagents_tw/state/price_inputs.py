from __future__ import annotations

from statistics import fmean

from tradingagents_tw.contracts import PriceBasis, PriceSeries, TrendAssessment
from .trend import TrendInputs, evaluate_trend


def derive_trend_inputs(
    series: PriceSeries,
    *,
    rs_20d: float,
) -> TrendInputs:
    """Derive deterministic Trend inputs from an adjusted price basis."""
    if series.price_basis is not PriceBasis.ADJUSTED:
        raise ValueError("State trend inputs require ADJUSTED prices")
    if series.adjustment_as_of is None:
        raise ValueError("ADJUSTED price series must declare adjustment_as_of")
    if len(series.bars) < 60:
        raise ValueError("at least 60 adjusted bars are required")
    if series.bars[-1].trade_date > series.adjustment_as_of:
        raise ValueError("price series extends beyond adjustment_as_of")

    closes = [bar.close for bar in series.bars]
    volumes = [bar.volume for bar in series.bars]
    volume_mean_20 = fmean(volumes[-20:])
    if volume_mean_20 <= 0:
        raise ValueError("20-day mean volume must be positive")

    return TrendInputs(
        close=closes[-1],
        ma20=fmean(closes[-20:]),
        ma60=fmean(closes[-60:]),
        rs_20d=rs_20d,
        volume_ratio_20d=volumes[-1] / volume_mean_20,
    )


def evaluate_trend_from_prices(
    series: PriceSeries,
    *,
    rs_20d: float,
    previous: TrendAssessment | None = None,
    confirmation_window: int = 2,
) -> TrendAssessment:
    inputs = derive_trend_inputs(series, rs_20d=rs_20d)
    return evaluate_trend(
        inputs,
        as_of=series.bars[-1].trade_date,
        previous=previous,
        confirmation_window=confirmation_window,
    )
