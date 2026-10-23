# TradingAgents-TW v0.1 Progress

## Baseline
First V0.1 core batch merged to `main`:
`b4ffebcfcc6c9200850a9b2d7f8824f4a0d193cf`

## Current checkpoint
Branch: `codex/v0.1-truth-state-2`
Issue: #3

### Completed in batch 2
- Truth-owned Provider Output Boundary:
  - provider capability check
  - source identity check
  - symbol check
  - evidence-type check
  - duplicate evidence-id check
  - provider output must enter Truth as RAW
  - Point-in-Time cutoff enforcement
- Corporate Action deterministic back-adjustment:
  - explicit `BACK_ADJUST_MULTIPLICATIVE_V1`
  - RAW input required
  - adjusted output carries `adjustment_as_of`
  - only actions with `event_date <= adjustment_as_of` affect prices
  - known future actions remain Evidence but do not alter current prices early
  - volume remains as reported
- Trend state-machine transition tests now cover all 8 TrendState values.
- TruthSnapshot deterministic identity:
  - SHA-256 `content_hash`
  - SHA-256 `config_hash`
  - Evidence order canonicalized
  - datetimes canonicalized to UTC before hashing
  - equivalent UTC / Asia-Taipei instants produce the same snapshot identity
- First official Taiwan market provider:
  - `TWSEStockDayAllAdapter`
  - official endpoint: `https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
  - capability explicitly marked `LATEST_ONLY`
  - provider emits RAW Evidence only
  - conservative `published_at = observed_at`
  - latest-only adapter refuses historical replay after the requested cutoff
  - ROC and Gregorian date parsing supported

### Verification
Latest implementation HEAD:
`e1000bb03287f326f415ee1fc02f360707907ac3`

GitHub Actions run #27:
- Python 3.11: PASS
- Python 3.12: PASS
- Compile: PASS
- Pytest: **43 / 43 PASS**
- Runtime: 0.23s on Python 3.11

### Important GPT review corrections
1. Future `effective_at` is not automatically lookahead when the event was already published/observed.
2. Known future Corporate Actions must not modify today's adjusted price series before their event date.
3. Snapshot identity must normalize equivalent timezone representations to one UTC canonical instant.

## Next atomic tasks
1. Add TruthSnapshot persistence/replay store contract.
2. Add post-market ingestion orchestration around Provider → Truth Boundary → Snapshot.
3. Add TPEx official OHLCV adapter behind the same Provider contract.
4. Add official Corporate Action source adapter behind Truth.
5. Feed adjusted PriceSeries into the deterministic State engine with replay fixtures.

## Rule
Do not add Judgment/LLM, adaptive weighting, RL, execution, or UI expansion until V0.1 Truth/State replay path is complete.
