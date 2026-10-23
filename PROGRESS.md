# TradingAgents-TW v0.1 Progress

## Merged baselines
- Batch 1 core invariants: `b4ffebcfcc6c9200850a9b2d7f8824f4a0d193cf`
- Batch 2 Truth hardening: `d7837457b3f9ed579984ef30bae213b5eed831e2`

## Previous checkpoint
Branch: `codex/v0.1-replay-ingestion`
Issue: #5

### Completed in batch 3
- Immutable content-addressed TruthSnapshot persistence:
  - snapshot objects keyed by `content_hash`
  - snapshot IDs are immutable refs
  - refs use exclusive create to prevent concurrent last-writer-wins
  - same content can be de-duplicated across multiple snapshot IDs
  - persisted object tampering fails closed
- Deterministic configuration persistence:
  - config stored separately by `config_hash`
  - replay validates config hash
  - config tampering fails closed
  - replay no longer depends on today's defaults
- Post-market ingestion orchestration:
  - Provider → Provider Boundary → RAW Evidence
  - Truth owns RAW → VERIFIED promotion
  - VERIFIED Evidence → TruthSnapshot → immutable Store
  - empty provider result cannot produce a PASS snapshot
  - replay has no live-provider dependency
- Official TPEx OHLCV adapter:
  - endpoint: `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
  - explicitly `LATEST_ONLY`
  - raw OHLCV / shares / value / transaction count normalization
  - ROC/Gregorian date parsing
- Official TWSE Corporate Action announcement adapter:
  - endpoint: `https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL`
  - explicitly `LATEST_ONLY`
  - current rolling ex-right/ex-dividend announcement Evidence
  - pending values remain `None`, never silently converted to zero
  - announcement adapter does not invent adjustment factors
- Adjusted PriceSeries → deterministic State:
  - State rejects RAW prices
  - 60-bar adjusted basis required for current Trend inputs
  - MA20 / MA60 / 20D volume ratio derived deterministically
  - replay fixture locks expected input values and Trend state

### Verification
Latest implementation HEAD:
`8d76e94116ab68d683055f16ef4d2de85a0dc7fb`

GitHub Actions run #35:
- Python 3.11: PASS
- Python 3.12: PASS
- Compile: PASS
- Pytest: **53 / 53 PASS**
- Runtime: 0.30s on Python 3.11

### GPT review corrections in batch 3
1. Replay must persist actual deterministic config, not only its hash.
2. Snapshot IDs must remain immutable even under concurrent writers.
3. Replay must detect both Truth-object tampering and config tampering.
4. Official rolling/latest endpoints are not allowed to masquerade as historical replay.

## Current checkpoint — Issue #7 / historical replay
Branch: `codex/v0.1-historical-replay`
Base: `81cb2afb2c7efd0fdc52d2bd08eae73f7a6cd3d2`

### Batch 4 implementation
- Explicit immutable TWSE/TPEx source registry; historical routing rejects latest-only,
  wrong-board and unknown capabilities. Board choice is explicit and persisted.
- Official annual calendar parsers for TWSE JSON and TPEx HTML-in-JSON, including
  rowspans, stock-versus-bond schedules and settlement-only days. Unknown schema,
  year, closure classification, future observation and conflicting amendments block.
- Versioned 18:00 Asia/Taipei post-market policy. This is our ingestion cutoff,
  not a claim that exchanges guarantee publication at that time.
- Official monthly historical OHLCV adapters, bounded month traversal, exact symbol,
  month and schema checks. Retrieval timestamps are never backdated. TPEx lots and
  thousands of TWD retain their source precision after unit normalization.
- Complete calendar session coverage and >=60 bars required before a PASS snapshot.
  Missing sessions (including suspensions/emergency closures) block; no fill-forward.
- Verified point-in-time action archive coverage is mandatory, including explicit
  no-action manifests. Latest rolling announcements cannot prove historical coverage.
- Cash/stock/rights reference-factor contract uses the immediately preceding RAW
  session close and explicit nonzero ratio units. Pending terms, unsupported events,
  late revisions, duplicates and ambiguous same-day actions block.
- Persisted Truth + calendar + source/policy/factor/engine versions + State input
  configuration replay offline into adjusted PriceSeries and Trend for either board.
- Two full synthetic multi-month Golden Replay fixtures, with independent rational
  expected prices/MA values; captured official calendars and monthly response schemas
  separately validate parser compatibility. Synthetic prices/actions are NOT market data.
- Decimal adjustment precision is fixed so ambient process precision cannot change State.

### Verification / retry ledger
- Remote starting HEAD and open PR inventory checked once; no newer work existed.
- Existing baseline result reused: 53/53, Python 3.11 / 3.12; baseline not rerun.
- Full batch verification: pending first GitHub Branch CI (3.11 / 3.12).
- No local equivalent full-suite run; Branch CI is the implementation verification gate.
- Branch / PR / main gates each get one run per unchanged SHA, never manually rerun
  just for confidence. Max 3 attempts per failing point; save evidence and switch path
  after the third failure. Current implementation failure count: 0.
- Official TWSE legacy history URL timed out once; switched to the current official
  RWD endpoint and captured a valid response. No repeated legacy endpoint attempts.
- TPEx calendar discovery moved from a guessed URL to the action declared by its
  official page (`bulletin/tradingDate`); valid calendar response captured.

### Source contracts
- TWSE history: https://www.twse.com.tw/zh/trading/historical/stock-day.html
- TPEx history: https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html
- TWSE calendar: https://www.twse.com.tw/zh/trading/holiday.html
- TPEx calendar: https://www.tpex.org.tw/zh-tw/announce/market/holiday.html
- Reference factor: https://www.twse.com.tw/zh/announcement/ex-right/twt49u.html
- TPEx reference formula: https://www.tpex.org.tw/zh-tw/about/company/faq.html

### Operational boundary
Historical endpoints supply past trade dates, not original publication/revision
archives. Today's fetch cannot reconstruct yesterday's information cutoff. Replay
requires evidence captured by the target cutoff, official calendar amendments where
needed, and a verified historical action-coverage manifest. Acquisition of a complete
live action archive is not claimed by the contract or the synthetic goldens.

### Next gate
Run Branch CI once; fix only evidenced failures, then PR CI -> merge -> main CI.
Keep the Issue #7/PR checkpoint as the authoritative run/SHA ledger.

## Rule
Do not add Judgment/LLM, adaptive weighting, RL, execution, or UI expansion until the V0.1 Truth/State historical replay path is complete.
