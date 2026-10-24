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


## 2026-10-24 — Issue #9 atomic batch K: scheduled prospective health gate (pending gates)
- Base main: `5e58b0b442013f71e29c785bfecfe5768b828534` (PR #20 merged; Branch/PR/main CI PASS; do not rerun).
- Branch: `codex/v0.1-pit-scheduled-health-gate`.
- Add separate daily 09:00 Asia/Taipei GitHub Actions health audit of `pit-capture` evidence using the existing deterministic `--audit-only` verifier. It checks the entire receipt chain and source bytes, catches a missed 19:17 poll after the previous healthy day exceeds the 30h freshness threshold, and retains earlier gap/failure status.
- Workflow has read-only repository permission, no evidence push, no bundled market projection, and a manual audit trigger. Missing baseline, stale data, corrupt receipts, or prior failures fail the job; `RECENT_UNATTESTED` is only operational freshness, **not independent historical PIT coverage**. GitHub schedule remains best-effort and may itself be skipped.
- Added static regression checks for cron, evidence branch, no write token, fail-closed audit invocation, and the 30h threshold relationship.
- Validation ledger: new batch K point starts at 0 failures. Run Branch CI once on its final SHA, then PR CI -> merge -> main CI; never rerun a successful SHA/gate.
- First real TWSE scheduled capture is still pending at 19:17 Asia/Taipei; do not manually fabricate a poll or claim `pit-capture` has live receipts. Independent attestor, real historical publication/revision completeness, TPEx prospective source, and Issue #14 deployment remain unresolved.

## 2026-10-24 — Issue #9 atomic batch L: strict read-only health audit (pending gates)
- Base main: `511820cb7ac8c874a4f778ae48fd1f1e4e8b3b6a` (PR #21 Branch/PR/main CI all PASS; no reruns).
- Identified audit-only filesystem side effect: constructing poll/feed archive readers created missing directories. This contradicted the health workflow's read-only contract and could mask a missing evidence path.
- The audit path now opens both journal and referenced feed receipts with `create=False`; capture/write paths retain their existing exclusive-create behavior. No changes to PIT coverage status, source semantics, score or scheduling.
- Added regression for absent archive root and ERROR-only journal with removed feed directory: audit must not create any directories, and must remain `NO_BASELINE` or `GAP_OR_FAILURE` respectively.
- Branch: `codex/v0.1-pit-audit-no-write`. Validation plan: one new-SHA Branch CI -> PR CI -> merge -> main CI; no unchanged SHA/gate reruns. Failure count for this point starts at 0.
- First real TWSE 19:17 Asia/Taipei scheduled poll and `pit-capture` push remain unverified; live PIT attestation and Web deployment remain blocked by their previously recorded external prerequisites.
- First Branch CI on `c111eb58b803a8fee9fd08222f1fc0723f9d14e3`: run https://github.com/tn289723-spec/TradingAgents/actions/runs/40048001150 — Python 3.12 185 PASS / 1 FAIL; Python 3.11 cancelled, Node 22 PASS. Failure count 1 for test fixture clock: the invalid-feed path consumes start, inner fetch-start, and failure-finish timestamps, but the new test supplied only two. Corrected fixture to supply the third tick; no production checks relaxed. Next new SHA gets one Branch CI, never rerun the failed SHA.
- Second Branch CI on `8a328842313140fb6ae836396e8688b3b9c91865`: run https://github.com/tn289723-spec/TradingAgents/actions/runs/40048093689 — Python 3.11 185 PASS / 1 FAIL, Python 3.12 cancelled, Node PASS. Same fixture-only point: inner feed fetch reads observed_at before validating the invalid body, requiring four clock ticks total. Failure count 2. Replaced brittle finite tick fixture with constant aware UTC clock; this is the third and final allowed Branch validation for this point. If still failing, stop and preserve WIP; do not rerun unchanged SHA.

## 2026-10-24 — Issue #9 atomic batch M: reject malformed TWSE feed rows (pending gates)
- Base main: `78ea521d6ad07a5925a96792755c672984a9da33` (PR #22 merged, existing Branch/PR/main gates green; no reruns).
- Branch: `codex/v0.1-pit-feed-schema-guard`.
- Defect: an upstream JSON error array such as `[{"error":"rate limited"}]` previously passed the generic array-of-objects check, producing a misleading SUCCESS receipt. Non-empty official feed rows must contain usable `Code` and `Date` fields; empty `[]` remains a captured but UNATTESTED observation.
- Add deterministic invalid-row regressions; do not weaken append-only, SHA-256, PIT or replay checks. Malformed live fetch must produce an ERROR poll, not a successful observation.
- Branch CI, PR CI, merge and main CI pending. New validation point starts at 0 failures; do not rerun prior SHA/gates. First real 19:17 Asia/Taipei capture has not occurred at this checkpoint.
- Independent production PIT attestor, historical publication/revision completeness, TPEx prospective action feed and Web deployment remain outstanding.

## 2026-10-24 — Issue #9 atomic batch N: official TWSE row/date integrity (pending gates)
- Base main: `95328da03642c2a7b518312ef8cc302556050225` (PR #23 and its Branch/PR/main CI already SUCCESS; no reruns).
- Branch: `codex/v0.1-pit-official-row-contract`.
- Verified current TWSE official TWT48U_ALL response includes Code, Date (ROC 7-digit), Name and Exdividend for every nonempty row, including alphanumeric securities codes. A partially populated error-shaped row could still pass the prior Code/Date-only guard; a syntactically present but impossible date could also produce a false SUCCESS.
- Enforce nonempty string identity/name/action type plus calendar-valid ROC/Gregorian event dates before issuing an immutable observation. Keep [] as UNATTESTED, preserve raw response bytes and SHA-256. Invalid upstream data becomes an ERROR poll, never successful PIT evidence.
- Add deterministic valid-row, missing-field, invalid-calendar and poll-error regressions. This is schema hardening only, NOT a real live capture, independent attestor or historical publication/revision completeness proof.
- Gate plan: one Branch CI on final SHA -> PR CI -> merge -> main CI. New point failure count 0. First actual scheduled capture remains due 2026-10-24 19:17 Asia/Taipei; observe it after the window without manual fabrication.
- Issue #14 Pages/Cloudflare permission blockers unchanged; no deployment retries. TPEx prospective feed and real PIT attestation remain open.

## 2026-10-24 — Issue #9/#14 atomic batch O: release-readiness README (pending gates)
- Base main `9dba5de6ae8d2deabb126fcabbbae3a7758ec2c2`. Operator enabled GitHub Pages and triggered a new main commit. Main CI run 40060667297 and Pages deployment run 40060667366 report SUCCESS; Pages job emitted `https://tn289723-spec.github.io/TradingAgents/`. Independent HTTP reachability was not confirmed (checker network/DNS unavailable). No equivalent Pages/CI gate rerun.
- Branch `codex/v0.1-release-readiness`: update stale bootstrap README with actual Truth/State, synthetic-vs-live PIT boundary, operational TWSE capture/health, commands, Web behavior, Pages evidence and exact unresolved release gates.
- No source code, market data, attestor, deployment workflow or production projection changed. First genuine 2026-10-24 19:17 Asia/Taipei capture remains pending.
- One Branch CI → PR CI → merge → main CI per new SHA; new documentation validation point failure count 0.
- Next: inspect actual scheduled capture and `pit-capture` SHA after 19:17; independently verify Pages HTTPS reachability when available. Keep Issues #9/#14 open until real evidence and trusted projection.


## 2026-10-24 — Issue #9 atomic batch P: attested production projection gate (pending gates)
- Base main: `ff83d725d88087037f59d9d4de731a9b63ff228d` (release-readiness PR #25 merged; existing CI gates are reused and not rerun).
- Branch: `codex/v0.1-attested-projection-gate`.
- Add a fail-closed publication boundary between signed historical replay and the Web projection. The gate must call `replay_historical(require_live_pit=True)` with pinned trusted public keys before a projection may carry `SIGNED_PIT_V1_ATTESTATION_VERIFIED`.
- Bind the supplied StateSnapshot to the verified historical replay Trend and existing Truth/config lineage before building DailyReport. Synthetic fixture mode, missing/wrong trust roots, tampered signed coverage, or State/Truth mismatch cannot produce an attested projection.
- Ordinary `project_daily_report` remains `NOT_ESTABLISHED_BY_REPORT`; no report may self-certify PIT.
- Web accepts exactly the two formal certification states and explains that signed attestation verification still relies on the independent attestor's completeness claim. Traffic lights remain evidence-readiness only, never buy/sell.
- This batch does not provision a production attestor, fabricate a projection, or claim historical completeness. First real TWSE scheduled capture remains due 19:17 Asia/Taipei; TPEx prospective action capture is still separate.
- Validation ledger: new batch P point starts at 0 failures. One Branch CI on final SHA -> PR CI -> merge -> main CI. No unchanged-SHA reruns.


## 2026-10-24 — Issue #9 atomic batch Q: TPEx prospective action capture (pending gates)
- Base main: `dd5dea31e90010a862b995af2574461b43db5d0e` (batch P merged; successful gates are reused, not rerun).
- Branch: `codex/v0.1-tpex-prospective-capture`.
- Add official TPEx OpenAPI prospective source `https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost` with exact raw-byte SHA-256 receipts. Non-empty rows must provide valid `ExRrightsExDividendDate`, `SecuritiesCompanyCode`, `CompanyName`, `ExRrightsExDividend` and the four official term fields; empty [] remains UNATTESTED.
- TPEx uses independent `tpex-feed-observations/` and `tpex-poll-records/` chains. It never shares TWSE cadence state, so one exchange cannot hide another exchange's missed poll or failure.
- Daily 19:17 Asia/Taipei workflow captures TWSE and TPEx independently, persists both sources' SUCCESS/ERROR receipts to the isolated `pit-capture` branch, then fails the workflow if either source failed.
- Daily read-only health workflow requires both TWSE and TPEx audit chains to be recent and internally valid. Neither green status is independent publication/revision completeness proof.
- This source contract is corroborated by the official TPEx ex-right/ex-dividend preview dataset and multiple public OpenAPI schema captures; no historical timestamps are backdated and no live response is bundled into source control.
- Validation ledger: new batch Q point starts at 0 failures. One Branch CI on the final SHA -> PR CI -> merge -> main CI. Do not rerun unchanged gates.


## 2026-10-24 — Issue #9 atomic batch R: dual-source first-poll persistence regression (pending gates)
- Base main: `dd7538cfd0f23f2d3b0a0d8cf80f5f9597a3685b` (PR #27 merged; Branch/PR/main CI PASS; no reruns).
- Branch: `codex/v0.1-dual-source-poll-persistence-test`.
- Added four deterministic dual-source first-run cases (TWSE/TPEx both SUCCESS, either source ERROR, both ERROR), checking each independent audit state, both immutable poll receipts, optional raw feed receipts, and Git's bounded `data/pit` staging without unrelated files.
- Assert the workflow persists audit receipts before surfacing an observation failure. This guards the first real 19:17 dual-source scheduled capture without changing live capture, source schema, evidence contracts or deployment.
- Tests are synthetic transport fixtures, NOT real PIT evidence or historical completeness proof. Independent production attestor and pre-capture historical publication/revision coverage remain unavailable.
- New validation point: 0 failures before first Branch CI. One Branch CI for final SHA → PR CI → merge → main CI; no unchanged-SHA or equivalent gate reruns.
- First actual scheduled dual-source capture remains due 2026-10-24 19:17 Asia/Taipei. Afterwards inspect the real workflow, pit-capture SHA and both chains exactly once.
