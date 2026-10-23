# TradingAgents-TW v0.1 Progress

## Current checkpoint
Branch: `codex/v0.1-core`
PR: #2

### Completed
- Strict Contracts: Evidence, EvidenceAssessment, TruthSnapshot, TrendAssessment, DirectionalScore, Confidence, CorporateAction, PeerMembership, DailyReport.
- Point-in-Time enforcement and immutable TruthSnapshot builder.
- Point-in-Time semantics corrected: availability is bounded by `published_at` / `observed_at`; a future `event_time` or `effective_at` is allowed when the market already knows the scheduled event.
- All information timestamps and analysis cutoffs are timezone-aware; naive timestamps fail closed.
- Critical Missing / unresolved conflict Decision Gate.
- Explicit `RAW` / `ADJUSTED` price-basis contracts.
- Price series fail closed on mixed basis, adjustment method/version, symbol or chronology errors.
- Corporate Action adjustment factors, when present, must be positive.
- Versioned deterministic Trend candidate classifier.
- Versioned Trend hysteresis transition engine; default transition confirmation window = 2 observations.
- Frozen Directional Score V0.1 configuration:
  - TREND 30%
  - VOLUME_PRICE 20%
  - RELATIVE_STRENGTH 15%
  - FLOW 15%
  - FUNDAMENTAL 10%
  - EVENT 10%
- V0.1 component signal contract: standardized signed signal [-1, +1] → normalized [0, 100]; source-native metrics remain outside ScoreComponent and must be traceable through State/Evidence.
- Explainable Directional Score recomputation.
- Canonical state replay serialization.
- Exact V0.1 golden replay fixture.
- Data Provider Adapter contract; adapters return Evidence only and Truth retains authority over point-in-time/conflict validation.
- DailyReport → Markdown pure projection.

## Verification
Latest implementation HEAD before this documentation checkpoint:
`a051bc873c3c58fbf30d87e5b0006c39950aa232`

GitHub Actions:
- Push CI: PASS
- Pull Request CI: PASS
- Python 3.11: PASS
- Python 3.12: PASS
- Compile: PASS
- Pytest: **24 / 24 PASS**
- Runtime: 0.13s on Python 3.11 job

Verified invariants include:
- No evidence published/observed after analysis cutoff.
- Known future scheduled events are not falsely classified as lookahead.
- Naive timestamps fail closed.
- Critical Missing cannot be averaged away by high coverage.
- Unresolved critical source conflict → BLOCKED.
- RAW / ADJUSTED prices cannot be silently mixed.
- Trend changes require deterministic hysteresis confirmation.
- Same State input → byte-stable canonical replay.
- Score component set and weights are explicit/versioned.
- Out-of-contract standardized component signal fails closed.
- Provider request windows and cutoffs are strict and typed.

## Next atomic tasks
1. Add provider-output boundary validation under Truth (source/symbol/type/cutoff).
2. Add Corporate Action adjustment application + raw/adjusted dual-series fixture.
3. Add Trend transition-table tests across all eight states.
4. Add TruthSnapshot content hash / config hash derivation contract.
5. Add first official Taiwan OHLCV provider adapter behind the Provider contract.

## Rule
Do not add Judgment/LLM, adaptive weighting, RL, automatic execution or UI expansion until V0.1 Truth/State invariants are complete.
