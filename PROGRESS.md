# TradingAgents-TW v0.1 Progress

## Current checkpoint
Branch: `codex/v0.1-core`

### Completed
- Strict Contracts: Evidence, EvidenceAssessment, TruthSnapshot, TrendAssessment, DirectionalScore, Confidence, CorporateAction, PeerMembership, DailyReport.
- Point-in-Time enforcement and immutable TruthSnapshot builder.
- Critical Missing / unresolved conflict Decision Gate.
- Explicit `RAW` / `ADJUSTED` price-basis contracts.
- Price series fail closed on mixed basis, adjustment method/version, symbol or chronology errors.
- Versioned deterministic Trend candidate classifier.
- Versioned Trend hysteresis transition engine; default transition confirmation window = 2 observations.
- Frozen Directional Score V0.1 configuration:
  - TREND 30%
  - VOLUME_PRICE 20%
  - RELATIVE_STRENGTH 15%
  - FLOW 15%
  - FUNDAMENTAL 10%
  - EVENT 10%
- Component raw contract fixed to [-1, +1] → [0, 100]; values outside contract fail closed.
- Explainable Directional Score recomputation.
- Canonical state replay serialization.
- Exact V0.1 golden replay fixture.
- Data Provider Adapter contract; adapters return Evidence only and Truth retains authority over point-in-time/conflict validation.
- DailyReport → Markdown pure projection.

## Verification
GitHub Actions run #10 on latest implementation HEAD:
- Python 3.11: PASS
- Python 3.12: PASS
- Compile: PASS
- Pytest: **21 / 21 PASS**
- Runtime: 0.21s on Python 3.11 job

Verified invariants include:
- No future Evidence past analysis cutoff.
- Critical Missing cannot be averaged away by high coverage.
- Unresolved critical source conflict → BLOCKED.
- RAW / ADJUSTED prices cannot be silently mixed.
- Trend changes require deterministic hysteresis confirmation.
- Same State input → byte-stable canonical replay.
- Score component set and weights are explicit/versioned.
- Out-of-contract raw score fails closed.
- Provider request windows are strict and typed.

## Next atomic tasks
1. Add provider-output boundary validation under Truth (source/symbol/type/cutoff).
2. Add Corporate Action adjustment application + raw/adjusted dual-series fixture.
3. Add Trend transition table tests across all eight states.
4. Add TruthSnapshot content hash / config hash derivation contract.
5. Add first official Taiwan OHLCV provider adapter behind the Provider contract.

## Rule
Do not add Judgment/LLM, adaptive weighting, RL or automatic execution until V0.1 Truth/State invariants are complete.
