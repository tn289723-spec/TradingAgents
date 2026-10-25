# ADR 0001: Official same-board post-market source fallback

- Status: Accepted
- Date: 2026-10-25

## Gap

Post-market ingestion currently depends on one historical endpoint. If it returns
no row for the requested session or is unavailable, a daily snapshot cannot be
created even when the exchange's official current-day all-market feed has the
same session's record.

## Decision

For a single-session post-market request only, try the registered historical
source first. If it is empty or unavailable, automatically try the registered
official latest-only feed for the same exchange. Keep the selected evidence's
actual source, observation time, content hash, and provider ID. Persist a
deterministic source-resolution record in the snapshot config.

The latest-only endpoint cannot be used for historical ranges. Unknown schemas,
malformed evidence, source conflicts, wrong-board sources, and invalid provider
output remain hard failures. This fallback does not authorize unregistered,
third-party, paid, or cross-board sources and does not bypass PIT or corporate
action gates.

## Acceptance

1. Empty/unavailable TWSE history can use only the registered TWSE daily feed.
2. Empty/unavailable TPEx history can use only the registered TPEx daily feed.
3. The selected provider and fallback reason are persisted and replay-stable.
4. Multi-session requests never use a latest-only feed.
5. Invalid data is rejected; no prices or missing sessions are synthesized.

## Consequences

This closes the single-day acquisition gap using an already registered official
source. It does not provide a second historical archive source, a production PIT
attestor, or a live Web projection. Historical requests with missing sessions
still fail closed.
