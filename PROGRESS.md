# TradingAgents-TW v0.1 Progress

## Merged baselines
- Batch 1 core invariants: `b4ffebcfcc6c9200850a9b2d7f8824f4a0d193cf`
- Batch 2 Truth hardening: `d7837457b3f9ed579984ef30bae213b5eed831e2`

## Current checkpoint
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

## Next atomic tasks
1. Add a market/source registry so TWSE vs TPEx selection is deterministic and auditable.
2. Add official trading-calendar contract and post-market cutoff policy.
3. Add historical official OHLCV adapters needed to bootstrap 60-bar State without future leakage.
4. Add Corporate Action announcement → adjustment-factor derivation contract using point-in-time pre-event prices.
5. Build a full TruthSnapshot → adjusted PriceSeries → Trend replay golden scenario for one listed and one OTC fixture.

## Rule
Do not add Judgment/LLM, adaptive weighting, RL, execution, or UI expansion until the V0.1 Truth/State historical replay path is complete.
