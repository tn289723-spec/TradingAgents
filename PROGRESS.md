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
- First Branch CI: `3d4cd420b59fba3b68782d7c5268b3b3b4f53679`,
  https://github.com/tn289723-spec/TradingAgents/actions/runs/39960645710
  Compile PASS; Python 3.12: 100 passed / 4 failed; 3.11 matrix cancelled after failure.
- Two root causes, each at failure count 1: (a) official TPEx HTML permits omitted
  `</td>` at row end; parser now implements HTML's implicit cell close without relaxing
  mandatory columns/dates; (b) exact-rational golden oracle skipped the pre-existing
  float factor/price serialization and fsum-then-divide boundaries. Golden expectations
  now independently model those boundaries using rational arithmetic, still require
  exact output equality, and additionally bound deviation from real arithmetic to 1 ULP.
- Fixed batch verification pending the next Branch CI, on a new commit only.
- No local equivalent full-suite run; Branch CI is the implementation verification gate.
- Branch / PR / main gates each get one run per unchanged SHA, never manually rerun
  just for confidence. Max 3 attempts per failing point; save evidence and switch path
  after the third failure. No unchanged-SHA reruns; both known failure counts remain 1.
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

## 2026-10-23 — Issue #9 atomic batch A: prospective PIT capture contract
- Main base: `398e326dd75b1e147c6986941d820b858a718367` (Issue #7 / PR #8 complete; 105/105 on both Python versions; previous gates not rerun).
- Branch: `codex/v0.1-pit-archive-contract`.
- Added versioned, hash-verified, append-only captured corporate-action records and explicit COMPLETE/PARTIAL/UNKNOWN coverage attestation.
- Independent trusted attestation callback is mandatory: no automatic trust of latest-only empty feed or self-declared historical completeness.
- Verifier checks window continuity, board/symbol, cutoff, exact record membership, linear revisions, late observations, conflicts, and immutable hashes.
- Offline tests use synthetic observations; they do NOT establish live historical PIT completeness.
- Next: verify this SHA once in Branch CI, then PR gate; integrate the trusted coverage source into historical ingestion only after independent attestation mechanism is established. Build DailyReport and mobile web after the Truth gate.
- Retry ledger: new archive contract point starts at 0 failures; previous Issue #7 failures remain recorded in Issue #7, no equivalent gate reruns.

## 2026-10-23 — Issue #9 atomic batch B: independently signed coverage proof
- Base main HEAD: `d44c4613731d351d7bf9ebcfa604a85a29049fd2` (PR #10 merged, Python 3.11/3.12 main CI green; no repeated gates).
- Branch: `codex/v0.1-pit-trusted-attestation`.
- Added pinned out-of-band Ed25519 attestor public-key verification, domain-separated signed manifest hash, and combined signature + existing PIT coverage/revision verifier.
- Missing key, invalid signature, tampered manifest, partial coverage, late record and incorrect board fail closed; synthetic offline tests only.
- This verifies **who signed** a COMPLETE claim; it does not independently establish that the signer actually captured every historical announcement. No production attestor/key is provisioned.
- Remaining Issue #9: wire signed archive evidence into historical ingestion and offline replay; keep legacy synthetic golden explicitly marked synthetic. Then DailyReport / mobile Web.
- Retry ledger: batch B new validation point failure count 0; previous branch/PR/main successful gates must not be rerun.

## 2026-10-24 — Issue #9 atomic batch C: signed PIT ingestion + persisted replay
- Base main: `ed164eeaabea3b3caffd2779d4babc01dae84050` (PR #11, both Python CI matrices green; no previous gate rerun).
- Branch: `codex/v0.1-pit-signed-replay`.
- Added explicit `archive_mode` in persisted historical replay config: `SYNTHETIC_FIXTURE_ONLY` (legacy golden compatibility; not live PIT proof) or `SIGNED_PIT_V1` (out-of-band Ed25519 trust root required).
- Signed coverage bundle carries immutable captured records, exact active announcement bindings, revision identity, independent signature and legacy factor coverage contract.
- Verify before provider fetch and again on offline replay; reject absent/rotated keys, tampering, missing records, late or incomplete coverage, mismatched announcement payload/revision and cross-board data.
- `replay_historical(require_live_pit=True)` rejects legacy synthetic snapshots; production callers must supply pinned trusted keys at runtime. Keys are never persisted in snapshot config.
- Added synthetic end-to-end tests for TWSE/TPEx and fail-closed adversarial cases. **No production attestor or genuine historical completeness is claimed.**
- Validation ledger: new batch C branch gate pending first CI; no retries yet. Do not rerun successful PR #11 gates.
- Next: verify branch CI once; if green open PR -> PR CI -> merge -> main CI. Then provision real independent attestor/archive capture before claiming live PIT; proceed with DailyReport and mobile-first Web on separately gated work.
