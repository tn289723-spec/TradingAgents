from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from tradingagents_tw.contracts import PriceBasis, PriceSeries, StrictModel
from .indicators import IndicatorSpec, calculate_indicators
from .screener import ScreenRule, rules_match


class BacktestStrategy(StrictModel):
    indicators: tuple[IndicatorSpec, ...]
    entry_rules: tuple[ScreenRule, ...]
    exit_rules: tuple[ScreenRule, ...]
    commission_bps: float = Field(ge=0, le=500, allow_inf_nan=False)
    sell_tax_bps: float = Field(ge=0, le=500, allow_inf_nan=False)
    slippage_bps: float = Field(ge=0, le=500, allow_inf_nan=False)
    version: Literal["next-session-long-v1"] = "next-session-long-v1"

    @model_validator(mode="after")
    def valid_rules(self):
        keys = {spec.key for spec in self.indicators}
        if len(keys) != len(self.indicators) or not self.entry_rules or not self.exit_rules:
            raise ValueError("strategy requires unique indicators and nonempty entry/exit rules")
        if any(rule.indicator not in keys or (rule.compare_to is not None and rule.compare_to not in keys)
               for rule in self.entry_rules + self.exit_rules):
            raise ValueError("strategy rules must reference declared indicators")
        return self


class BacktestTrade(StrictModel):
    entry_signal_date: date
    entry_date: date
    entry_price: float
    exit_signal_date: date
    exit_date: date
    exit_price: float
    gross_return: float
    net_return: float


class OpenPosition(StrictModel):
    entry_signal_date: date
    entry_date: date
    entry_price: float
    mark_date: date
    mark_price: float
    unrealized_net_return: float


class BacktestReport(StrictModel):
    symbol: str
    start_date: date
    end_date: date
    strategy_version: str
    trade_count: int = Field(ge=0)
    win_rate: float = Field(ge=0, le=1)
    total_return: float
    max_drawdown_closed_trades: float
    trades: tuple[BacktestTrade, ...]
    open_position: OpenPosition | None = None
    limitations: tuple[str, ...]


def _net_exit_return(entry_fill: float, exit_fill: float, strategy: BacktestStrategy) -> float:
    commission = strategy.commission_bps / 10_000
    sell_tax = strategy.sell_tax_bps / 10_000
    return (exit_fill * (1 - commission - sell_tax)) / (entry_fill * (1 + commission)) - 1


def run_backtest(series: PriceSeries, strategy: BacktestStrategy) -> BacktestReport:
    """Long-only, close-generated signals filled at the next session's open.

    The final close is only a mark for any still-open position; it is never used
    as a fill for a signal formed at that same close.
    """
    if series.price_basis is not PriceBasis.RAW:
        raise ValueError("backtests require point-in-time RAW prices")
    if len(series.bars) < 2:
        raise ValueError("backtest requires at least two sessions")
    vectors = calculate_indicators(series, strategy.indicators)
    position: dict | None = None
    trades: list[BacktestTrade] = []
    realized_returns: list[float] = []
    slip = strategy.slippage_bps / 10_000

    for i in range(len(series.bars) - 1):
        bar, next_bar = series.bars[i], series.bars[i + 1]
        values = {key: vector[i] for key, vector in vectors.items()}
        previous = {key: vector[i - 1] if i > 0 else None for key, vector in vectors.items()}
        if position is None:
            if rules_match(values, strategy.entry_rules, previous):
                fill = next_bar.open * (1 + slip)
                position = {"signal_date": bar.trade_date, "entry_date": next_bar.trade_date,
                            "entry_price": fill, "entry_open": next_bar.open}
        elif rules_match(values, strategy.exit_rules, previous):
            exit_fill = next_bar.open * (1 - slip)
            gross = next_bar.open / position["entry_open"] - 1
            net = _net_exit_return(position["entry_price"], exit_fill, strategy)
            trades.append(BacktestTrade(
                entry_signal_date=position["signal_date"], entry_date=position["entry_date"],
                entry_price=position["entry_price"], exit_signal_date=bar.trade_date,
                exit_date=next_bar.trade_date, exit_price=exit_fill,
                gross_return=gross, net_return=net,
            ))
            realized_returns.append(net)
            position = None

    open_position = None
    if position is not None:
        last = series.bars[-1]
        open_position = OpenPosition(
            entry_signal_date=position["signal_date"], entry_date=position["entry_date"],
            entry_price=position["entry_price"], mark_date=last.trade_date,
            mark_price=last.close,
            unrealized_net_return=_net_exit_return(position["entry_price"], last.close, strategy),
        )
    equity, peak, max_drawdown = 1.0, 1.0, 0.0
    for value in realized_returns:
        equity *= 1 + value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, 1 - equity / peak)
    total_equity = equity * (1 + open_position.unrealized_net_return) if open_position else equity
    return BacktestReport(
        symbol=series.symbol, start_date=series.bars[0].trade_date,
        end_date=series.bars[-1].trade_date, strategy_version=strategy.version,
        trade_count=len(trades), win_rate=(sum(t.net_return > 0 for t in trades) / len(trades) if trades else 0),
        total_return=total_equity - 1, max_drawdown_closed_trades=max_drawdown,
        trades=tuple(trades), open_position=open_position,
        limitations=(
            "Long-only; one open position per symbol; fills use the next session open.",
            "Performance uses RAW OHLCV and does not yet model dividends or corporate-action cash flows.",
            "Closed-trade drawdown excludes interim mark-to-market drawdown.",
            "Results are research simulations, not forward performance or investment advice.",
        ),
    )
