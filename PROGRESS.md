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
- Validation ledger: branch CI SHA c1d6bc460d83c21d400de3e9d544b2ed7ea293bc failed 2/148 only on wrong-key expected error string (Python 3.11; 3.12 cancelled). Root cause: wrong but well-formed pinned key correctly fails signature verification, not key-presence check. Failure count 1; corrected exact negative assertion; next new SHA gets one branch gate. Do not rerun successful PR #11 gates.
- Next: verify branch CI once; if green open PR -> PR CI -> merge -> main CI. Then provision real independent attestor/archive capture before claiming live PIT; proceed with DailyReport and mobile-first Web on separately gated work.

## 2026-10-24 — Atomic batch D: DailyReport binding + read-only dashboard projection
- Base main: `656c17458562758cd7c6f26d5e56110254112555` (PR #12 merged, 148/148 Python 3.11/3.12).
- Branch: `codex/v0.1-dailyreport-projection`.
- Added fail-closed TruthSnapshot/StateSnapshot identity and config binding for DailyReport, with explicit supplied confidence (no LLM inference or recomputation).
- Added versioned read-only DashboardProjection and deterministic JSON output. Green/yellow/red reflect **evidence readiness only**, never buy/sell direction.
- Five-day score slope is separate from five-day change; unavailable five-day change, thesis and "most likely wrong" stay null/not assessed. Report alone cannot certify live historical PIT.
- Synthetic fixtures verify lineage rejection, tampering, cutoff, gate semantics, missing fields and deterministic serialization.
- Verification checkpoint: pending first Branch CI for the new SHA. Do not rerun PR #12 gates. Failure counter for this new point starts at 0.
- Next: PR gate → merge → main gate if branch green. Then Mobile-First Web UI reading projection JSON only. Issue #9 remains OPEN pending independent real-world PIT attestor and complete capture evidence.
- First Branch CI `9afc4dbfe37d20f7341d28b66b71b6ca50c30eb8`, run 39992470187: 157 PASS / 2 FAIL on Python 3.11 (3.12 cancelled). One fixture-expectation root cause: tampered Truth raises the existing `SnapshotIntegrityError`, and a changed gate without a rebuilt hash is rightly rejected at integrity verification before gate validation. Tests now expect the integrity exception and rebuild a valid BLOCKED snapshot to exercise the non-PASS branch. No production checks relaxed. Failure count 1; next SHA gets one Branch CI.


## 2026-10-24 — Issue #14 atomic batch E: Mobile-First Web read-only client
- Base main: `be25e54b82fcd0604087dc5bc5db3d9de7b1ae6e` (PR #13 merged; its successful gates are reused without rerun).
- Branch: `codex/v0.1-mobile-web`.
- Added static accessible mobile-first `web/index.html`, strict `dashboard.mjs` consumer and deterministic Node 22 smoke tests. No mock projection or generated scores are bundled; missing/invalid JSON leaves the page blocked. A local file-picker allows explicit v1 JSON import with format validation, not cryptographic authentication.
- Browser displays upstream Directional Score, Trend, Confidence, Decision Gate, evidence-readiness traffic lights, 5-day score slope, explicitly unavailable 5-day change/thesis/most-likely-wrong, limitations and source IDs. The browser never recomputes market state.
- Addressed two P1 Codex findings from merged PR #13: reject unknown DailyReport schema versions; unresolved conflicts cannot be presented as PASS/DEGRADED. Added Python regression tests.
- CI adds a Node 22 UI gate beside Python 3.11/3.12; branch gate pending. Do not rerun the already-green PR #13 gates.
- Remaining: Branch CI once on final SHA, then PR CI → merge → main CI. Deploy the `web/` static output to an authorized HTTPS URL and verify real reachability. No genuine signed PIT archive or production attestor is provisioned (Issue #9 OPEN).
- Retry ledger: new web batch failure count 0; do not retry unchanged SHA/gate.

## 2026-10-24 — Issue #14 atomic batch F: alternative GitHub Pages delivery gate
- Verified prior main CI for merge SHA `1bde2379a11d82ef6c48b8336471709cc81bef24`: run https://github.com/tn289723-spec/TradingAgents/actions/runs/40001137731 has `conclusion=success` (2026-10-23 18:10 UTC). This reuses the existing run; no CI rerun.
- Main had no open PRs; Issue #9 and #14 remain open. Existing Cloudflare Pages creation previously required interactive authorization; do not retry the same unauthorized write.
- Branch: `codex/v0.1-pages-delivery`. Add a GitHub Pages Actions deployment path as an independent alternative, with Node 22 validation and an explicit allowlist of static HTML/JS only; no `projection.json` or synthetic fixtures are published.
- GitHub Pages site may require one-time repository Settings → Pages → Source: GitHub Actions enablement. Deployment URL and HTTP reachability must be verified before closing #14; do not infer live hosting from a workflow file.
- No changes to Truth/State, PIT attestation, market calculations or production data. Issue #9 remains open for independently captured complete historical PIT evidence.
- New branch CI → PR CI → main CI and Pages deployment are distinct gates. No unchanged SHA rechecks; failed deployment caused by missing Pages enablement is an external configuration blocker, not a reason to rerun equivalent CI.

## 2026-10-24 — Issue #9 atomic batch G: prospective official feed receipt (unattested)
- Base main: `b77e085b9997269c2e05948906127c292b9ad824` (PR #16 and its main CI already PASS; no rerun).
- Branch: `codex/v0.1-prospective-feed-capture`.
- Added a bounded, raw-byte-preserving, SHA-256-verified, exclusive-create receipt for the official TWSE rolling corporate-action feed. A direct CLI captures at actual retrieval time; no historical publication timestamp is invented.
- Captures preserve the full source response, including empty arrays, but **never claim COMPLETE/no-action historical PIT coverage**. Retrieval failures create no success receipt. There is no production independent attestor, no live history backfill, no TPEX action source and no scheduler in this batch.
- Offline tests exercise byte identity, immutable collision/tamper, empty observations, invalid feed, clock and fetch failure.
- Next: one Branch CI for the final SHA, PR CI, merge and main CI. Then operational capture scheduling and independently auditable coverage attestations, with missing polling intervals fail-closed. Issue #9 remains OPEN.
- Retry ledger: this new point starts at 0 failures; existing green SHA/gates must not be rerun.


## 2026-10-24 — Issue #9 atomic batch H: scheduled prospective poll audit (pending gates)
- Base main: `64cbed332092303b88bd2916c33894f48535232c` (PR #17 merged, 3 CI gates green; no reruns).
- Branch: `codex/v0.1-pit-capture-operator`; separate `pit-capture` append-only evidence branch created from this base for GitHub Actions to store receipts without mutating main.
- Added hash-linked single-writer poll journal, success/error receipts, deterministic missed-poll or previous-error indicators, no exception text/secret persistence, and fail-closed corruption detection.
- Added daily GitHub Actions scheduled operator at 19:17 Asia/Taipei; GitHub schedule is best-effort and missing runs cannot be considered covered. Audit receipts persist to isolated `pit-capture` branch; failed captures are committed as errors before the workflow reports failure.
- Raw feed receipts remain untrusted prospective observations. Even consecutive successful polls do **not** prove announcement publication/revision completeness, independent attestation or historical PIT. No live data is bundled with the Web.
- New point validation: one Branch CI on final SHA, then PR CI -> merge -> main CI. Verify first actual scheduled/manual poll separately only if authorized; GitHub Actions write permission and schedule execution are operational prerequisites.
- Issue #14 Pages/Cloudflare permissions unchanged: no equivalent failed deployment retry. Issue #9 remains open until independently operated attestor and complete trustworthy coverage are available.

## 2026-10-24 — Issue #9 atomic batch I: read-only prospective poll health audit (pending gates)
- Base main: `98b94d7b3ffb35c3627865b01acaf340c364d779` (PR #18 merged; existing Branch/PR/main CI PASS; do not rerun).
- Adds deterministic read-only `--audit-only` to the prospective capture operator. It verifies the complete local hash-linked journal and referenced raw receipts, detects skipped polls even without a next scheduled run, and preserves earlier gap/error visibility after later successes.
- Status `NO_BASELINE`, `STALE`, `GAP_OR_FAILURE`, or `RECENT_UNATTESTED` always includes `coverage=UNATTESTED`; audit cannot establish independent publication/revision completeness.
- Tests cover missing baseline, stale clock, recovered but historically gapped chain, corrupt/missing raw receipt, invalid clocks and failure receipts.
- Next: one Branch CI on this new commit; if green, PR CI -> merge -> main CI. Observe first actual scheduled TWSE capture only when it occurs; do not trigger unauthorized/manual duplicate capture. Issue #14 deployment blockers unchanged.


## 2026-10-24 — Issue #9 atomic batch J: preserve first failed scheduled poll (pending gates)
- Base main: `191a647ddaeca200d959b77d2347d9ddcf2d5270` (PR #19 main CI 40030466128 PASS; not rerun).
- Identified a real workflow pathspec failure: on the very first unsuccessful TWSE fetch, `poll-records/` has an ERROR receipt but `feed-observations/` contains no files; `git add -- data/pit/feed-observations data/pit/poll-records` aborts and can prevent the error receipt from reaching `pit-capture`.
- Changed staging to `git add -A -- data/pit`; synthetic regression initializes a fresh Git repository, simulates a first failed poll, and asserts only the error receipt is staged, not unrelated files.
- This fixes *audit persistence only*. No successful real poll, independent attestor, historical PIT coverage, Pages deployment, or production projection is claimed.
- Gate plan: one Branch CI on implementation SHA -> PR CI -> merge -> main CI; observe the first real 19:17 Asia/Taipei scheduled poll separately after it actually occurs. Do not retry blocked Pages/Cloudflare writes without changed permissions.
- Retry count for this newly identified failure point: 0 before implementation; no prior SHA/gate reruns.
