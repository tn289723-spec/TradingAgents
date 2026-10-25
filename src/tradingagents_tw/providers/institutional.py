from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tradingagents_tw.contracts import Evidence, EvidenceStatus
from .base import ProviderMetadata, ProviderRequest


TZ = ZoneInfo("Asia/Taipei")
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_3INSTI_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"

TWSE_FIELDS = {
    "foreign": "外陸資買賣超股數(不含外資自營商)",
    "trust": "投信買賣超股數",
    "dealer": "自營商買賣超股數",
    "total": "三大法人買賣超股數",
}
TPEX_FIELDS = {
    "foreign": "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
    "trust": "SecuritiesInvestmentTrustCompanies-Difference",
    "dealer": "Dealers-Difference",
    "total": "TotalDifference",
}


def _http_json(url: str) -> Any:
    req = Request(url, headers={"User-Agent": "TradingAgents-TW/0.2"})
    with urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(value: Any) -> int:
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "---", "N/A", "null", "None"}:
        raise ValueError("institutional numeric field is missing")
    number = float(text)
    if not number.is_integer():
        raise ValueError("institutional share count must be an integer")
    return int(number)


def _ad_date(value: Any) -> date:
    text = str(value).strip().replace("/", "").replace("-", "")
    if len(text) == 7:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    if len(text) == 8:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    raise ValueError("unknown institutional trade date format")


class _InstitutionalAdapter:
    market = ""
    fields: dict[str, str] = {}
    metadata: ProviderMetadata

    def __init__(self, *, fetch_data: Callable[..., Any] | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._fetch_data = fetch_data
        self._clock = clock or (lambda: datetime.now(TZ))

    def _fetch(self, trade_date: date) -> tuple[list[dict[str, Any]], date, Any]:
        raise NotImplementedError

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        if "INSTITUTIONAL_FLOW" not in request.evidence_types:
            raise ValueError("provider only supplies institutional flow")
        if request.start_date != request.end_date:
            raise ValueError("provider requires a single trade date request")
        observed = self._clock()
        if observed.utcoffset() is None:
            raise ValueError("provider clock must return timezone-aware datetime")
        if observed > request.analysis_cutoff:
            raise ValueError("provider cannot reconstruct evidence before its observation")
        rows, served_date, raw_response = self._fetch(request.start_date)
        if served_date != request.start_date:
            raise ValueError("institutional source date does not match requested date")
        row = next((r for r in rows if str(r.get("證券代號", r.get("SecuritiesCompanyCode", ""))).strip() == request.symbol), None)
        if row is None:
            return ()
        normalized = {key: _number(row[field]) for key, field in self.fields.items()}
        # Preserve component arithmetic; discrepancies are evidence, not repaired values.
        components_total = normalized["foreign"] + normalized["trust"] + normalized["dealer"]
        normalized.update({"trade_date": served_date.isoformat(), "market": self.market,
                           "unit": "SHARES", "components_total": components_total,
                           "total_matches_components": components_total == normalized["total"]})
        digest = hashlib.sha256(json.dumps(raw_response, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
        event = datetime.combine(served_date, time(13, 30), tzinfo=TZ)
        return (Evidence(
            evidence_id=f"{self.market.lower()}:{served_date.isoformat()}:{request.symbol}:institutional-flow",
            symbol=request.symbol, evidence_type="INSTITUTIONAL_FLOW", source=self.metadata.source,
            source_record_id=f"{served_date.isoformat()}:{request.symbol}", event_time=event,
            published_at=observed, observed_at=observed, effective_at=event,
            content_hash=digest, revision_id=f"{self.metadata.provider_id}:{digest[:16]}",
            status=EvidenceStatus.RAW, payload=normalized,
        ),)


class TWSEInstitutionalAdapter(_InstitutionalAdapter):
    market = "TWSE"
    fields = TWSE_FIELDS
    metadata = ProviderMetadata(
        provider_id="twse-t86-institutional-flow", source="TWSE_T86", schema_version="1.0",
        evidence_types=("INSTITUTIONAL_FLOW",), source_priority=1,
        history_mode="HISTORICAL", endpoint=TWSE_T86_URL,
    )

    def _fetch(self, trade_date: date):
        if self._fetch_data:
            payload = self._fetch_data(trade_date)
        else:
            url = f"{TWSE_T86_URL}?" + urlencode({"date": trade_date.strftime("%Y%m%d"),
                                                   "selectType": "ALLBUT0999", "response": "json"})
            payload = _http_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list) or not isinstance(payload.get("data"), list):
            raise ValueError("TWSE T86 response schema is unknown")
        fields, data = payload["fields"], payload["data"]
        if not set(("證券代號", *self.fields.values())).issubset(fields):
            raise ValueError("TWSE T86 required fields are missing or renamed")
        indexes = {name: fields.index(name) for name in ("證券代號", *self.fields.values())}
        rows = []
        for values in data:
            if not isinstance(values, list) or len(values) != len(fields):
                raise ValueError("TWSE T86 row shape does not match fields")
            rows.append({key: values[idx] for key, idx in indexes.items()})
        reported_date = payload.get("date") or trade_date.strftime("%Y%m%d")
        return rows, _ad_date(reported_date), payload


class TPEXInstitutionalAdapter(_InstitutionalAdapter):
    market = "TPEX"
    fields = TPEX_FIELDS
    metadata = ProviderMetadata(
        provider_id="tpex-3insti-institutional-flow", source="TPEX_OPENAPI", schema_version="1.0",
        evidence_types=("INSTITUTIONAL_FLOW",), source_priority=1,
        history_mode="LATEST_ONLY", endpoint=TPEX_3INSTI_URL,
    )

    def _fetch(self, trade_date: date):
        payload = self._fetch_data() if self._fetch_data else _http_json(TPEX_3INSTI_URL)
        if not isinstance(payload, list) or not payload:
            raise ValueError("TPEx institutional response is empty or unknown")
        rows = []
        for row in payload:
            if not isinstance(row, dict) or "Date" not in row:
                raise ValueError("TPEx institutional row schema is unknown")
            if not set(("SecuritiesCompanyCode", *self.fields.values())).issubset(row):
                raise ValueError("TPEx institutional required fields are missing or renamed")
            rows.append({"證券代號": row["SecuritiesCompanyCode"],
                         **{field: row[field] for field in self.fields.values()}})
        dates = {_ad_date(row["Date"]) for row in payload}
        if len(dates) != 1:
            raise ValueError("TPEx institutional response mixes trade dates")
        return rows, dates.pop(), payload
