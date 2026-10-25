# TradingAgents-TW v0.1

Taiwan-stock post-market decision-error-prevention system. **No automated trading, RL, adaptive weighting or LLM authority over Truth/State.**

## Implemented vs. certified

- **Truth:** immutable evidence/config snapshots, cutoff and conflict gates, official TWSE/TPEx monthly OHLCV and calendars, corporate-action adjustment and offline historical replay. Synthetic goldens prove deterministic logic, **not** genuine historical publication/revision completeness.
- **State:** deterministic adjusted-price Trend and Directional Score. The score is **not** a probability or a trade instruction.
- **Reporting:** bound DailyReport and read-only DashboardProjection v1. No production `projection.json` exists; a report does not certify live PIT.
- **Web:** mobile-first `web/index.html` reads only the upstream projection: score, trend, confidence, decision gate, evidence-readiness red/yellow/green, five-day score slope; five-day change, most-likely-wrong and Thesis remain explicitly unavailable. The browser never calculates core market judgments. Green is evidence readiness, **not** buy/sell.
- **Prospective TWSE/TPEx feeds:** independent immutable raw-byte/SHA-256 observations, separate append-only SUCCESS/ERROR poll journals and read-only health audits. Both sources are scheduled daily, but the first real scheduled capture and evidence-branch write remain unverified. These are `UNATTESTED` observations, **not** historical PIT coverage. Independent production attestation and complete historical action publication/revision evidence remain outstanding.

The historical `SIGNED_PIT_V1` mode requires a pinned independent Ed25519 public key and genuine captured-at-cutoff archive coverage. This repository ships **no production attestor/key or complete historical archive**. A signature, current latest-only feed, synthetic test or consecutive successful polls cannot establish historical completeness.

## Local validation

Requires Python 3.11+ and Node 22:

```sh
python -m pip install -e '.[dev]'
python -m pytest
node --test web/dashboard.test.mjs
python -m http.server 8080 --directory web
```

CI tests Python 3.11/3.12 and Node 22. See `AGENTS.md` and `PROGRESS.md` for contracts, retry ledger and release gates. Do not repeat equivalent CI for an unchanged SHA.

## Research screening and backtests

`tradingagents_tw.research` adds deterministic, parameterized SMA, RSI, return,
and volume-ratio indicators; threshold/comparison/crossover screening rules; and
a long-only backtest that fills close-generated signals at the next session's
open. Commission, sell tax, and slippage must be supplied explicitly. The API
accepts RAW OHLCV only and does not change the frozen V0.1 Directional Score.

```python
from tradingagents_tw.research import (
    BacktestStrategy, IndicatorKind, IndicatorSpec, ScreenRule,
    ScreenSpec, run_backtest, screen_universe,
)

indicators = (
    IndicatorSpec(kind=IndicatorKind.SMA, window=20),
    IndicatorSpec(kind=IndicatorKind.SMA, window=60),
    IndicatorSpec(kind=IndicatorKind.VOLUME_RATIO, window=20),
)
screen = ScreenSpec(
    indicators=indicators,
    rules=(
        ScreenRule(indicator="SMA_20", operator="crosses_above", compare_to="SMA_60"),
        ScreenRule(indicator="VOLUME_RATIO_20", operator=">=", threshold=1.5),
    ),
)
candidates = screen_universe(verified_raw_series, screen, as_of=session_date)

strategy = BacktestStrategy(
    indicators=indicators,
    entry_rules=screen.rules,
    exit_rules=(ScreenRule(indicator="SMA_20", operator="<", compare_to="SMA_60"),),
    commission_bps=broker_commission_bps,
    sell_tax_bps=applicable_sell_tax_bps,
    slippage_bps=estimated_slippage_bps,
)
report = run_backtest(verified_raw_series[0], strategy)
```

This is a research API, not a deployed Web feature. Historical input provenance
and point-in-time completeness must be established by the caller. The first
version does not model dividends/corporate-action cash flows or interim
mark-to-market drawdown; see ADR 0002.

For a supplied JSON dataset/spec, run `tradingagents-research screen --data universe.json --spec screen.json --as-of YYYY-MM-DD` or `tradingagents-research backtest --data 2330.json --strategy strategy.json`. Inputs must be verified RAW `PriceSeries`; the command does not download market data.

### Official weekly ownership distribution

`TDCCOwnershipAdapter` reads the official TDCC Open Data 1-5 CSV and emits
`OWNERSHIP_DISTRIBUTION` evidence with the source snapshot date and all reported
holding tiers. TDCC defines this as a weekly end-of-last-business-day snapshot;
it must not be carried forward as daily evidence. The endpoint serves the latest
file, so the adapter is `LATEST_ONLY` and cannot reconstruct past point-in-time
data. Archive each raw response for historical research. The adapter rejects
unknown CSV schemas and emits `RAW` evidence pending the existing verification
flow. `TWSEInstitutionalAdapter` and `TPEXInstitutionalAdapter` add per-stock
daily three-institution net flows in shares. `TWSEMarginAdapter` reads TWSE
per-stock margin and short balances in lots. `TPEXMarginAdapter` completes the
dual-board margin coverage from the official TPEx margin-balance endpoint,
including previous/current balances, daily activity, limits and offset amount.
These adapters retain source dates and response hashes, reject schema/date
mismatches, and emit `RAW` evidence. The reference stock-chips page is a
generated static snapshot; its ranks and weights are not treated as
authoritative evidence.

| Evidence | Official source coverage | History capability |
| --- | --- | --- |
| Daily OHLCV | TWSE + TPEx | Historical date queries |
| Three-institution flow | TWSE T86 + TPEx OpenAPI | TWSE historical; TPEx latest snapshot |
| Margin and short balance | TWSE MI_MARGN + TPEx OpenAPI | TWSE historical; TPEx latest snapshot (official TPEx web report supports dated history, not yet wired into this adapter) |
| Ownership distribution by holder tier | TDCC Open Data 1-5 | Latest weekly snapshot |

Latest-only providers cannot reconstruct old point-in-time values. Archive raw
receipts daily to build that history; the adapters alone do not populate or
verify the PIT archive. TPEx's official dated margin report provides history
from 2007-01, and an older archive for 2003-08 through 2006-12. See ADR 0004.

## Prospective capture and health

- `.github/workflows/pit-capture.yml`: scheduled daily **19:17 Asia/Taipei** (`17 11 * * *` UTC), best-effort; stores real SUCCESS/ERROR receipts on isolated `pit-capture` branch. Verify actual run, branch SHA and receipts before claiming operational success. Empty official `[]` is **not** no-action proof.
- `.github/workflows/pit-health.yml`: daily **09:00 Asia/Taipei** (`0 1 * * *` UTC), read-only; verifies journal chain, referenced raw receipts, freshness and historical gaps/errors. `RECENT_UNATTESTED` means operational freshness only. A skipped workflow is not evidence.

Read-only audit of an existing evidence checkout:

```sh
python -m tradingagents_tw.truth.capture_operator --archive-root /path/to/pit-capture/data/pit --audit-only
```

The audit exits nonzero unless `RECENT_UNATTESTED`. Never fabricate/backdate receipts or publish provider credentials.

## Official source data on the Web dashboard

The read-only market-data panel displays official TWSE/TPEx daily quotes,
three-institution flows and margin balances plus TDCC weekly ownership tiers.
The GitHub Pages workflow captures and publishes a same-origin normalized
`market-sources.json` snapshot on weekdays after market close. Every source is
labelled RAW / unverified with its observation time and response hash; stale
snapshots older than 72 hours are hidden. This feed does not calculate scores
or signals and remains separate from the verified PIT score projection. See
ADR 0005 and `web/README.md`.

## Mobile Web release

Without same-origin, independently authorized `projection.json`, the static client intentionally displays **BLOCKED / no data**. Its manual file picker schema-checks JSON but always displays imported claims as **BLOCKED / unverified source**; it does **not** authenticate the signer or historical PIT. Only publish exact validated upstream `render_dashboard_projection_json(report)` bytes after Truth/State/PIT release gates pass. See `web/README.md` for deployment restrictions.

**GitHub Pages:** the repository Pages source was enabled and [deploy run 40060667366](https://github.com/tn289723-spec/TradingAgents/actions/runs/40060667366) **SUCCESS** for main `9dba5de6ae8d2deabb126fcabbbae3a7758ec2c2`. Its environment URL is `https://tn289723-spec.github.io/TradingAgents/`. The dashboard includes a scheduled official-source snapshot panel; verify a successful current capture/deploy run and external HTTPS reachability before claiming live-data readiness.

**Cloudflare alternative:** authorized Pages project, no build command, output directory `web`. Prior Pages creation required interactive authorization; a Workers alternative returned 403 for missing script-write permission. Do not retry unchanged permissions or modify other Workers.

## Completion gate

[Issue #9](https://github.com/tn289723-spec/TradingAgents/issues/9) remains **OPEN** pending verified live dual-source capture, independent genuine historical PIT publication/revision coverage and a trusted production projection. [Issue #14](https://github.com/tn289723-spec/TradingAgents/issues/14) is **CLOSED** after successful GitHub Pages deployment; independent external HTTPS reachability and live data readiness are still unverified and must not be inferred from that closure. Green CI and successful static deployment do not establish live PIT readiness.
