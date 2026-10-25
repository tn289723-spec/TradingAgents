# ADR 0003: TDCC weekly ownership distribution evidence

## Status

Accepted for research ingestion; not a release gate for the live dashboard.

## Context

The stock-chips reference page uses TDCC shareholding distribution to describe
large-holder changes. TDCC's own description says the data is compiled from
custody balances after close on the last business day of each week. The public
Open Data 1-5 endpoint serves the latest CSV, which is insufficient to
reconstruct earlier point-in-time snapshots by itself.

## Decision

- Add a separate `TDCCOwnershipAdapter` for the official Open Data 1-5 CSV.
- Preserve the reported snapshot date, tier, holder count, share count and
  custody percentage in `OWNERSHIP_DISTRIBUTION` evidence.
- Mark observations `RAW`, retain a SHA-256 digest, and reject unknown schemas,
  invalid values, duplicate tiers, and historical windows the endpoint cannot
  supply.
- Record the observation/publication availability separately from the weekly
  snapshot's event date. Do not forward-fill this weekly evidence as daily data.
- Require separately archived raw weekly files before historical PIT use.
- Do not import the reference site's ranks, weights or conclusions into the
  frozen State/Directional Score.

## Consequences

This provides a provenance-preserving adapter for one official source family.
It does not add TWSE/TPEx institutional-flow or margin feeds, validate the
provider's real-world availability schedule, or certify historical PIT
completeness. Those remain separate measurable gaps.

## Sources

- TDCC shareholding distribution description: <https://www.tdcc.com.tw/portal/zh/smWeb/qryStock>
- TDCC OpenAPI lists dataset 1-5, "集保戶股權分散表": <https://openapi.tdcc.com.tw/>
- Official Open Data 1-5 CSV: <https://opendata.tdcc.com.tw/getOD.ashx?id=1-5>
