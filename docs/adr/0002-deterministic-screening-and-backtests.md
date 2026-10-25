# ADR 0002: Deterministic screening and next-session backtests

- Status: Accepted
- Date: 2026-10-25

## Gap

The project has deterministic Trend/Directional State inputs but no reusable
way to screen a symbol universe by user-selected technical conditions or test
those conditions against historical bars.

## Decision

Add a separate research module that accepts RAW point-in-time OHLCV, supports
parameterized SMA, RSI, close-to-close return and volume-ratio indicators, and
filters a universe using explicit threshold, indicator-comparison and crossing
rules. A strategy backtest is
long-only and has one position per symbol. Signals use completed closes and
execute at the next session open with configurable commission, sell tax and
slippage. Final-day signals are not filled at the same close.

The module does not modify frozen V0.1 weights, Truth, State, signed PIT gates,
or the read-only Web projection. It does not place trades. Indicators use only
data through their signal date. Backtest output remains a research simulation.

## Acceptance

1. Indicator windows and thresholds are configurable without arbitrary code execution.
2. Extending a series with future bars cannot change prior indicator values.
3. Screens require an exact requested session and reject stale/adjusted input.
4. Backtests use next-session opens and account for declared costs and slippage.
5. Missing warm-up history cannot silently pass a rule.

## Known limitations

The first version covers OHLCV technical rules only. Institutional flow,
margin data and weekly TDCC ownership data from the reference site are not yet
ingested. It does not model dividends or other corporate-action cash flows,
short selling, multi-symbol portfolio constraints, intraday execution, or
interim mark-to-market drawdown. The Web interface and TradingView integration
are separate follow-up work.
