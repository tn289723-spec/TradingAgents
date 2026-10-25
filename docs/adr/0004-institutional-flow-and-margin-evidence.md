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
- Read TPEx `tpex_mainboard_margin_balance` for prior/current financing and
  short balances, daily activity, limits, and offset amount as lots. The OpenAPI
  endpoint is latest-snapshot only; historical date queries remain a separate
  TPEx web-report capability and are not exposed by this adapter.
- Preserve exchange, source session date, observation availability, response
  SHA-256, and `RAW` status. Reject changed field schemas, malformed rows,
  date mismatches, and future observations relative to the analysis cutoff.
- Do not infer availability timestamps from the event date. Both exchange
  margin feeds carry observation-time availability; use archived raw captures
  to establish historical point-in-time availability.

## Consequences

Institutional flow and margin balances are now available for both boards.
TPEx margin OpenAPI and institutional feeds are latest-only; TWSE daily reports
support historical date requests. Official TPEx margin web reports permit date
queries back to ROC 96 January (2007-01), with older archived period queries
from ROC 92 August through ROC 95 December (2003-08–2006-12), but this adapter
does not call that historical interface. These adapters do not create a
historical PIT archive, verify raw observations, alter scoring weights, or
connect the factors to the Web projection. The exchange's published total may
not equal a naïve sum if categories differ; the discrepancy is retained.

## Sources

- TWSE T86 field names and per-stock report: <https://www.twse.com.tw/fund/T86?response=html>
- TPEx OpenAPI listing and institutional report: <https://www.tpex.org.tw/openapi/>
- TWSE MI_MARGN schema, per-stock units, and publication caveat: <https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=html>
- TPEx margin OpenAPI endpoint: <https://www.tpex.org.tw/openapi/>
- TPEx official margin page, fields, CSV downloads and historical date range: <https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/transactions.html>
