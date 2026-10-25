# ADR 0004: Institutional flow and margin evidence adapters

## Status

Accepted for research ingestion; data does not affect V0.1 State or production reporting.

## Decision

- Read TWSE T86 per-stock daily net flows and TPEx `tpex_3insti_daily_trading`.
- Normalize foreign (excluding foreign dealers), investment trust, dealer, and
  published total net flow as signed shares. Preserve component/total mismatch
  as evidence; never silently recompute the exchange's published total.
- Read TWSE MI_MARGN per-stock financing and short balances as lots, retaining
  both prior-day and current balances.
- Preserve exchange, source session date, observation availability, response
  SHA-256, and `RAW` status. Reject changed field schemas, malformed rows,
  date mismatches, and future observations relative to the analysis cutoff.
- Do not map TPEx margin data until its official OpenAPI field names and units
  have been confirmed. Do not infer availability timestamps from the event date.

## Consequences

Institutional flow is available for both boards; margin balances are currently
available only through the TWSE adapter. These adapters do not create a
historical PIT archive, verify raw observations, alter scoring weights, or
connect the factors to the Web projection. The exchange's published total may
not equal a naïve sum if categories differ; the discrepancy is retained.

## Sources

- TWSE T86 field names and per-stock report: <https://www.twse.com.tw/fund/T86?response=html>
- TPEx OpenAPI listing and institutional report: <https://www.tpex.org.tw/openapi/>
- TWSE MI_MARGN schema, per-stock units, and publication caveat: <https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=html>
