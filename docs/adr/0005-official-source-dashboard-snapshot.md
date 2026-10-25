# ADR 0005: Publish official RAW source snapshots to the static dashboard

## Status

Accepted for read-only market-data display. Does not satisfy the historical PIT release gate.

## Gap

The dashboard previously consumed only the independently gated `DashboardProjection` v1. Official price, institutional-flow, margin and weekly ownership adapters existed, but their output was not visible on the website.

## Decision

- On weekdays after market close, the Pages workflow fetches TWSE and TPEx daily quotes, institution flows and margin balances, plus TDCC's latest weekly ownership CSV.
- The existing provider adapters normalize per-symbol records. The workflow publishes a same-origin `market-sources.json` containing only normalized public data, provider IDs, observation times, response SHA-256 digests, dates, and availability status.
- Every record remains `RAW`; the whole snapshot is `RAW_UNVERIFIED`. The UI labels both states, displays source timestamps and hashes, and blocks snapshots older than 72 hours.
- The official-source panel is read-only. It does not alter Truth, State, the frozen V0.1 score, the separate `projection.json` gate, or create trading signals.
- Missing numeric quote values remain explicit per-symbol `MISSING` evidence; unknown schemas, dates, malformed values, or unrecognized exchange annotations fail the capture.

## Acceptance

1. Each official provider response is retrieved once per scheduled capture and normalized through the registered adapter.
2. UI source records are accepted only for the pinned official endpoints and exact snapshot schema.
3. Unknown/malformed data is rejected; no market calculations or score claims run in browser code.
4. Missing or stale snapshots show BLOCKED; available source evidence remains visibly unverified.
5. Tests cover both-board source capture, schemas, date/data provenance and UI validation.

## Limitations

- Snapshot availability depends on GitHub Actions and the exchanges' public endpoints; schedule execution is best effort.
- TPEx institutional and margin APIs and TDCC ownership serve latest snapshots; daily captures build prospective history only.
- This does not archive independently attested vintages or make historical point-in-time claims.
- The dashboard's score panel still requires the separate verified PIT projection.
