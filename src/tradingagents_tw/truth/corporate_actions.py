from __future__ import annotations

from datetime import date
from decimal import Decimal

from tradingagents_tw.contracts import CorporateAction, PriceBar, PriceBasis, PriceSeries


BACK_ADJUSTMENT_METHOD = "BACK_ADJUST_MULTIPLICATIVE_V1"


def _scaled(value: float, factor: Decimal) -> float:
    return float(Decimal(str(value)) * factor)


def apply_back_adjustments(
    raw_series: PriceSeries,
    actions: tuple[CorporateAction, ...],
    *,
    as_of: date,
    adjustment_version: str = "1",
) -> PriceSeries:
    """Back-adjust OHLC prices to an explicit basis date.

    Only actions with event_date <= as_of are effective for the adjusted price
    basis. A known future action remains valid Evidence but must not alter
    today's State before it becomes effective. Volume is preserved as reported.

    CorporateAction.adjustment_factor is the multiplier applied to prices
    strictly before the action event date.
    """
    if raw_series.price_basis is not PriceBasis.RAW:
        raise ValueError("corporate action adjustment requires RAW input prices")
    if any(bar.trade_date > as_of for bar in raw_series.bars):
        raise ValueError("price series contains bars after adjustment as_of")

    ordered_actions = tuple(sorted(actions, key=lambda action: (action.event_date, action.action_id)))
    for action in ordered_actions:
        if action.symbol != raw_series.symbol:
            raise ValueError("corporate action symbol does not match price series")

    effective_actions = tuple(action for action in ordered_actions if action.event_date <= as_of)
    for action in effective_actions:
        if action.adjustment_factor is None:
            raise ValueError("effective corporate action adjustment_factor is required")
        if action.adjustment_method != BACK_ADJUSTMENT_METHOD:
            raise ValueError("unsupported corporate action adjustment_method")

    adjusted: list[PriceBar] = []
    for bar in raw_series.bars:
        factor = Decimal("1")
        for action in effective_actions:
            if bar.trade_date < action.event_date:
                factor *= Decimal(str(action.adjustment_factor))

        adjusted.append(
            PriceBar(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                open=_scaled(bar.open, factor),
                high=_scaled(bar.high, factor),
                low=_scaled(bar.low, factor),
                close=_scaled(bar.close, factor),
                volume=bar.volume,
                price_basis=PriceBasis.ADJUSTED,
                adjustment_method=BACK_ADJUSTMENT_METHOD,
                adjustment_version=adjustment_version,
            )
        )

    return PriceSeries(
        symbol=raw_series.symbol,
        price_basis=PriceBasis.ADJUSTED,
        adjustment_method=BACK_ADJUSTMENT_METHOD,
        adjustment_version=adjustment_version,
        adjustment_as_of=as_of,
        bars=tuple(adjusted),
    )
