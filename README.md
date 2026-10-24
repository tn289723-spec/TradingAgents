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

## Prospective capture and health

- `.github/workflows/pit-capture.yml`: scheduled daily **19:17 Asia/Taipei** (`17 11 * * *` UTC), best-effort; stores real SUCCESS/ERROR receipts on isolated `pit-capture` branch. Verify actual run, branch SHA and receipts before claiming operational success. Empty official `[]` is **not** no-action proof.
- `.github/workflows/pit-health.yml`: daily **09:00 Asia/Taipei** (`0 1 * * *` UTC), read-only; verifies journal chain, referenced raw receipts, freshness and historical gaps/errors. `RECENT_UNATTESTED` means operational freshness only. A skipped workflow is not evidence.

Read-only audit of an existing evidence checkout:

```sh
python -m tradingagents_tw.truth.capture_operator --archive-root /path/to/pit-capture/data/pit --audit-only
```

The audit exits nonzero unless `RECENT_UNATTESTED`. Never fabricate/backdate receipts or publish provider credentials.

## Mobile Web release

Without same-origin, independently authorized `projection.json`, the static client intentionally displays **BLOCKED / no data**. Its manual file picker schema-checks JSON but always displays imported claims as **BLOCKED / unverified source**; it does **not** authenticate the signer or historical PIT. Only publish exact validated upstream `render_dashboard_projection_json(report)` bytes after Truth/State/PIT release gates pass. See `web/README.md` for deployment restrictions.

**GitHub Pages:** the repository Pages source was enabled and [deploy run 40060667366](https://github.com/tn289723-spec/TradingAgents/actions/runs/40060667366) **SUCCESS** for main `9dba5de6ae8d2deabb126fcabbbae3a7758ec2c2`. Its environment URL is `https://tn289723-spec.github.io/TradingAgents/`. **Independent external HTTPS reachability has not yet been verified** due to network/DNS limits in the checking environment; do not claim a fully operational market dashboard. No unchanged-SHA deployment rerun is needed.

**Cloudflare alternative:** authorized Pages project, no build command, output directory `web`. Prior Pages creation required interactive authorization; a Workers alternative returned 403 for missing script-write permission. Do not retry unchanged permissions or modify other Workers.

## Completion gate

[Issue #9](https://github.com/tn289723-spec/TradingAgents/issues/9) remains **OPEN** pending verified live dual-source capture, independent genuine historical PIT publication/revision coverage and a trusted production projection. [Issue #14](https://github.com/tn289723-spec/TradingAgents/issues/14) is **CLOSED** after successful GitHub Pages deployment; independent external HTTPS reachability and live data readiness are still unverified and must not be inferred from that closure. Green CI and successful static deployment do not establish live PIT readiness.
