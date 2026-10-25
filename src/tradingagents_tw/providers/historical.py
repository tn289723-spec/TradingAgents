"""Official monthly RAW OHLCV. Retrieval time is never backdated to trade time."""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tradingagents_tw.contracts import Evidence, EvidenceStatus, PriceBar, PriceBasis
from tradingagents_tw.truth.calendar import TAIPEI, PostMarketPolicy
from .base import ProviderRequest, ProviderUnavailable
from .registry import Market, HISTORICAL_SOURCES
from .twse import _parse_date

TWSE_FIELDS = ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"]
TPEX_FIELDS = ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤", "漲跌", "筆數"]


def _number(value, *, integer=False):
    if isinstance(value, bool):
        raise ValueError("boolean is not a market number")
    try:
        n = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("missing or malformed historical number") from exc
    if not n.is_finite() or (integer and n != n.to_integral_value()):
        raise ValueError("non-finite or fractional integer market number")
    result = int(n) if integer else float(n)
    if not integer and not math.isfinite(result):
        raise ValueError("historical number exceeds finite float range")
    return result


def _fetch_json(url: str) -> dict:
    with urlopen(Request(url, headers={"User-Agent": "TradingAgents-TW/0.1"}), timeout=15) as r:
        value = json.loads(r.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("historical response must be a JSON object")
    return value


class HistoricalOHLCVAdapter:
    def __init__(self, market: Market, *, fetch_json: Callable[[str], dict] | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.market = Market(market)
        self.metadata = HISTORICAL_SOURCES[self.market]
        self._fetch_json = fetch_json or _fetch_json
        self._clock = clock or (lambda: datetime.now(TAIPEI))

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        if request.evidence_types != ("OHLCV",) or not re.fullmatch(r"[0-9]{4}", request.symbol):
            raise ValueError("historical v1 supports explicit four-digit ordinary-equity OHLCV only")
        if request.analysis_cutoff < PostMarketPolicy().ready_at(request.end_date):
            raise ValueError("historical request extends beyond post-market cutoff")
        month = request.start_date.replace(day=1)
        end = request.end_date.replace(day=1)
        month_count = (end.year - month.year) * 12 + end.month - month.month + 1
        if month_count > 24:
            raise ValueError("historical request exceeds 24-month bounded fetch")
        result, seen = [], set()
        for _ in range(month_count):
            params = ({"date": month.strftime("%Y%m%d"), "stockNo": request.symbol, "response": "json"}
                      if self.market is Market.TWSE else
                      {"date": month.strftime("%Y/%m/%d"), "code": request.symbol, "response": "json"})
            url = self.metadata.endpoint + "?" + urlencode(params)
            payload = self._fetch_json(url)
            observed_at = self._clock()  # Recorded AFTER the response arrives.
            if observed_at.utcoffset() is None or observed_at > request.analysis_cutoff:
                raise ValueError("historical response was not available at analysis cutoff; use archived Truth")
            if not isinstance(payload, dict) or payload.get("stat", "").lower() != "ok":
                raise ProviderUnavailable("official historical response is unavailable")
            if payload.get("date") != month.strftime("%Y%m%d"):
                raise ValueError("historical response month mismatch")
            if self.market is Market.TWSE:
                if not re.search(rf"\s{re.escape(request.symbol)}\s", payload.get("title", "")):
                    raise ValueError("historical response symbol mismatch")
                fields, rows = payload.get("fields"), payload.get("data")
                if fields not in (TWSE_FIELDS, TWSE_FIELDS + ["註記"]):
                    raise ValueError("unsupported TWSE historical schema")
            else:
                if payload.get("code") != request.symbol or payload.get("flagField") != "張數":
                    raise ValueError("TPEx historical symbol/unit mismatch")
                tables = payload.get("tables", [])
                if len(tables) != 1 or tables[0].get("date") != month.strftime("%Y%m%d"):
                    raise ValueError("unsupported TPEx historical table")
                fields, rows = tables[0].get("fields"), tables[0].get("data")
                if fields != TPEX_FIELDS:
                    raise ValueError("unsupported TPEx historical schema")
            if not isinstance(rows, list) or not rows:
                raise ProviderUnavailable("empty historical month")
            for row in rows:
                if not isinstance(row, list) or len(row) != len(fields):
                    raise ValueError("malformed historical row")
                day = _parse_date(row[0])
                if (day.year, day.month) != (month.year, month.month) or day in seen:
                    raise ValueError("duplicate or wrong-month historical row")
                seen.add(day)
                if not request.start_date <= day <= request.end_date:
                    continue
                if observed_at < PostMarketPolicy().ready_at(day):
                    raise ValueError("historical row observed before post-market finalization")
                unit = 1 if self.market is Market.TWSE else 1000
                bar = PriceBar(
                    symbol=request.symbol, trade_date=day,
                    open=_number(row[3]), high=_number(row[4]), low=_number(row[5]),
                    close=_number(row[6]), volume=_number(row[1], integer=True) * unit,
                    price_basis=PriceBasis.RAW,
                )
                trade_value, transactions = _number(row[2], integer=True) * unit, _number(row[8], integer=True)
                if trade_value < 0 or transactions < 0:
                    raise ValueError("negative historical turnover/transactions")
                normalized = bar.model_dump(mode="json", exclude={"symbol", "adjustment_method", "adjustment_version"})
                normalized.update({
                    "market": self.market.value, "trade_value": trade_value, "transaction_count": transactions,
                    "volume_precision_shares": unit, "trade_value_precision_twd": unit,
                    "source_volume_unit": "SHARES" if unit == 1 else "LOTS_1000_SHARES",
                    "source_url": url,
                })
                raw_hash = hashlib.sha256(json.dumps(
                    {"url": url, "fields": fields, "row": row}, ensure_ascii=False,
                    sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                event = datetime.combine(day, time(13, 30), TAIPEI)
                result.append(Evidence(
                    evidence_id=f"{self.market.value.lower()}:history:{day}:{request.symbol}",
                    symbol=request.symbol, evidence_type="OHLCV", source=self.metadata.source,
                    source_record_id=f"{day}:{request.symbol}", event_time=event, effective_at=event,
                    published_at=observed_at, observed_at=observed_at, content_hash=raw_hash,
                    revision_id=f"{self.metadata.provider_id}:{raw_hash}",
                    status=EvidenceStatus.RAW, payload=normalized,
                ))
            month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        return tuple(sorted(result, key=lambda e: e.payload["trade_date"]))


class TWSEHistoricalAdapter(HistoricalOHLCVAdapter):
    def __init__(self, **kwargs):
        super().__init__(Market.TWSE, **kwargs)


class TPEXHistoricalAdapter(HistoricalOHLCVAdapter):
    def __init__(self, **kwargs):
        super().__init__(Market.TPEX, **kwargs)
