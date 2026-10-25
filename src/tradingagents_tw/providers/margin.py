from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, date
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tradingagents_tw.contracts import Evidence, EvidenceStatus
from .base import ProviderMetadata, ProviderRequest


TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_MARGIN_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
TZ = ZoneInfo("Asia/Taipei")


def _load(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "TradingAgents-TW/0.2"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _int(value: Any) -> int:
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "-", "---", "N/A", "null", "None"}:
        raise ValueError("TWSE margin balance field is missing")
    result = float(text)
    if not result.is_integer():
        raise ValueError("TWSE margin balance must be an integer number of lots")
    return int(result)


def _report_date(value: str, fallback: date) -> date:
    text = str(value).strip().replace("/", "").replace("-", "")
    if not text:
        return fallback
    if len(text) == 7:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    if len(text) == 8:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    raise ValueError("unknown TWSE margin report date format")


class TWSEMarginAdapter:
    """Historical per-stock TWSE margin/short balances; report values are lots."""

    metadata = ProviderMetadata(
        provider_id="twse-mi-margn-margin-balance", source="TWSE_MI_MARGN",
        schema_version="1.0", evidence_types=("MARGIN_BALANCE",), source_priority=1,
        history_mode="HISTORICAL", endpoint=TWSE_MARGIN_URL,
    )

    def __init__(self, *, fetch_json: Callable[[date], Any] | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._fetch_json = fetch_json or self._default_fetch
        self._clock = clock or (lambda: datetime.now(TZ))

    @staticmethod
    def _default_fetch(trade_date: date) -> Any:
        query = urlencode({"date": trade_date.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
        return _load(f"{TWSE_MARGIN_URL}?{query}")

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        if "MARGIN_BALANCE" not in request.evidence_types:
            raise ValueError("TWSE MI_MARGN only supplies margin balance")
        if request.start_date != request.end_date:
            raise ValueError("provider requires a single trade date request")
        observed = self._clock()
        if observed.utcoffset() is None:
            raise ValueError("provider clock must return timezone-aware datetime")
        if observed > request.analysis_cutoff:
            raise ValueError("provider cannot reconstruct evidence before its observation")
        payload = self._fetch_json(request.start_date)
        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            raise ValueError("TWSE MI_MARGN response is empty or unknown")
        report_date = _report_date(payload.get("date", ""), request.start_date)
        if report_date != request.start_date:
            raise ValueError("TWSE margin report date does not match requested date")
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise ValueError("TWSE MI_MARGN response has no tables")
        table = None
        for candidate in tables:
            if not isinstance(candidate, dict):
                continue
            fields, rows = candidate.get("fields"), candidate.get("data")
            if (isinstance(fields, list) and isinstance(rows, list) and rows
                    and len(fields) >= 16 and fields[0] in {"代號", "證券代號"}
                    and fields.count("前日餘額") >= 2 and fields.count("今日餘額") >= 2):
                table = candidate
                break
        if table is None:
            raise ValueError("TWSE MI_MARGN per-stock table schema is unknown")
        fields, rows = table["fields"], table["data"]
        finance_prev = fields.index("前日餘額")
        finance_today = fields.index("今日餘額")
        short_prev = fields.index("前日餘額", finance_prev + 1)
        short_today = fields.index("今日餘額", finance_today + 1)
        for row in rows:
            if not isinstance(row, list) or len(row) != len(fields):
                raise ValueError("TWSE MI_MARGN row shape does not match fields")
        row = next((r for r in rows if str(r[0]).strip() == request.symbol), None)
        if row is None:
            return ()
        normalized = {
            "trade_date": report_date.isoformat(), "market": "TWSE", "unit": "LOTS",
            "margin_previous_balance": _int(row[finance_prev]),
            "margin_balance": _int(row[finance_today]),
            "short_previous_balance": _int(row[short_prev]),
            "short_balance": _int(row[short_today]),
        }
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
        event = datetime.combine(report_date, time(13, 30), tzinfo=TZ)
        return (Evidence(
            evidence_id=f"twse:{report_date.isoformat()}:{request.symbol}:margin-balance",
            symbol=request.symbol, evidence_type="MARGIN_BALANCE", source=self.metadata.source,
            source_record_id=f"{report_date.isoformat()}:{request.symbol}", event_time=event,
            published_at=observed, observed_at=observed, effective_at=event,
            content_hash=digest, revision_id=f"twse-mi-margn:{digest[:16]}",
            status=EvidenceStatus.RAW, payload=normalized,
        ),)


class TPEXMarginAdapter:
    """Latest TPEx per-stock margin/short snapshot; balances and activity are lots."""

    metadata = ProviderMetadata(
        provider_id="tpex-openapi-margin-balance", source="TPEX_MARGIN_BALANCE",
        schema_version="1.0", evidence_types=("MARGIN_BALANCE",), source_priority=1,
        history_mode="LATEST_ONLY", endpoint=TPEX_MARGIN_URL,
    )

    _FIELDS = {
        "date": "Date",
        "symbol": "SecuritiesCompanyCode",
        "margin_previous_balance": "MarginPurchaseBalancePreviousDay",
        "margin_buy": "MarginPurchase",
        "margin_sell": "MarginSales",
        "margin_cash_repayment": "CashRedemption",
        "margin_balance": "MarginPurchaseBalance",
        "margin_finance_company_balance": "MarginPurchaseBalanceBelongSecuritiesFinanceEnterprise",
        "margin_limit": "MarginPurchaseQuota",
        "short_previous_balance": "ShortSaleBalancePreviousDay",
        "short_sell": "ShortSale",
        "short_buy": "ShortConvering",
        "short_cash_repayment": "StockRedemption",
        "short_balance": "ShortSaleBalance",
        "short_finance_company_balance": "ShortSaleBalanceBelongSecuritiesFinanceEnterprise",
        "short_limit": "ShortSaleQuota",
        "offset_loan_and_short": "Offsetting",
    }
    _RATES = {
        "margin_utilization_rate_pct": "MarginPurchaseUtilizationRate",
        "short_utilization_rate_pct": "ShortSaleUtilizationRate",
    }
    _NOTE = "Note"

    def __init__(self, *, fetch_json: Callable[[], Any] | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._fetch_json = fetch_json or (lambda: _load(TPEX_MARGIN_URL))
        self._clock = clock or (lambda: datetime.now(TZ))

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        if "MARGIN_BALANCE" not in request.evidence_types:
            raise ValueError("TPEx margin source only supplies margin balance")
        if request.start_date != request.end_date:
            raise ValueError("provider requires a single trade date request")
        observed = self._clock()
        if observed.utcoffset() is None:
            raise ValueError("provider clock must return timezone-aware datetime")
        if observed > request.analysis_cutoff:
            raise ValueError("provider cannot reconstruct evidence before its observation")
        rows = self._fetch_json()
        if not isinstance(rows, list) or not rows:
            raise ValueError("TPEx margin response is empty or unknown")
        for row in rows:
            if (not isinstance(row, dict)
                    or not set(self._FIELDS.values()).issubset(row)
                    or not set(self._RATES.values()).issubset(row)
                    or self._NOTE not in row):
                raise ValueError("TPEx margin required fields are missing or renamed")
        dates = {_report_date(row[self._FIELDS["date"]], request.start_date) for row in rows}
        if len(dates) != 1:
            raise ValueError("TPEx margin response mixes trade dates")
        report_date = dates.pop()
        if report_date != request.start_date:
            raise ValueError("TPEx margin report date does not match requested date")
        row = next((r for r in rows if str(r[self._FIELDS["symbol"]]).strip() == request.symbol), None)
        if row is None:
            return ()
        normalized = {
            key: _int(row[source]) for key, source in self._FIELDS.items()
            if key not in {"date", "symbol"}
        }
        for key, source in self._RATES.items():
            value = float(str(row[source]).strip().replace(",", ""))
            if not 0 <= value <= 100:
                raise ValueError("TPEx margin utilization rate is outside 0..100 percent")
            normalized[key] = value
        normalized["note"] = str(row[self._NOTE]).strip()
        normalized.update({"trade_date": report_date.isoformat(), "market": "TPEX", "unit": "LOTS"})
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode("utf-8")).hexdigest()
        event = datetime.combine(report_date, time(13, 30), tzinfo=TZ)
        return (Evidence(
            evidence_id=f"tpex:{report_date.isoformat()}:{request.symbol}:margin-balance",
            symbol=request.symbol, evidence_type="MARGIN_BALANCE", source=self.metadata.source,
            source_record_id=f"{report_date.isoformat()}:{request.symbol}", event_time=event,
            published_at=observed, observed_at=observed, effective_at=event,
            content_hash=digest, revision_id=f"tpex-margin:{digest[:16]}",
            status=EvidenceStatus.RAW, payload=normalized,
        ),)
