from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Callable, Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tradingagents_tw.contracts import Evidence, EvidenceStatus
from .base import ProviderMetadata, ProviderRequest


TWSE_TZ = ZoneInfo("Asia/Taipei")
TWSE_STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def _parse_number(value: Any) -> float:
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "N/A", "null", "None"}:
        raise ValueError("TWSE numeric field is missing")
    return float(text)


def _parse_int(value: Any) -> int:
    return int(_parse_number(value))


def _parse_change(value: Any) -> tuple[float | None, str | None]:
    text = str(value).strip()
    try:
        return _parse_number(text), None
    except ValueError:
        if text in {"除息", "除權", "除權息", "除權除息"}:
            return None, text
        raise


def _parse_date(value: Any) -> date:
    raw = str(value).strip().replace("/", "").replace("-", "")
    if len(raw) == 7:
        year = int(raw[:3]) + 1911
        month = int(raw[3:5])
        day = int(raw[5:7])
    elif len(raw) == 8:
        year = int(raw[:4])
        month = int(raw[4:6])
        day = int(raw[6:8])
    else:
        raise ValueError(f"unsupported TWSE date format: {value}")
    return date(year, month, day)


def _default_fetch_json() -> list[dict[str, Any]]:
    request = Request(
        TWSE_STOCK_DAY_ALL_URL,
        headers={"User-Agent": "TradingAgents-TW/0.1"},
    )
    with urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("TWSE STOCK_DAY_ALL response must be a JSON array")
    return data


class TWSEStockDayAllAdapter:
    metadata = ProviderMetadata(
        provider_id="twse-stock-day-all",
        source="TWSE_OPENAPI",
        schema_version="1.0",
        evidence_types=("OHLCV",),
        source_priority=1,
        history_mode="LATEST_ONLY",
        endpoint=TWSE_STOCK_DAY_ALL_URL,
    )

    def __init__(
        self,
        *,
        fetch_json: Callable[[], list[dict[str, Any]]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetch_json = fetch_json or _default_fetch_json
        self._clock = clock or (lambda: datetime.now(TWSE_TZ))

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        if "OHLCV" not in request.evidence_types:
            raise ValueError("TWSE STOCK_DAY_ALL only supplies OHLCV")
        if request.start_date != request.end_date:
            raise ValueError("LATEST_ONLY provider requires a single trade date request")

        observed_at = self._clock()
        if observed_at.utcoffset() is None:
            raise ValueError("provider clock must return timezone-aware datetime")
        if observed_at > request.analysis_cutoff:
            raise ValueError(
                "LATEST_ONLY provider cannot reconstruct evidence for a cutoff before observation"
            )

        rows = self._fetch_json()
        row = next((item for item in rows if str(item.get("Code", "")).strip() == request.symbol), None)
        if row is None:
            return ()

        trade_date = _parse_date(row.get("Date"))
        if trade_date != request.start_date:
            raise ValueError(
                f"TWSE latest trade date {trade_date.isoformat()} does not match requested date"
            )

        event_time = datetime.combine(trade_date, time(13, 30), tzinfo=TWSE_TZ)
        change, change_note = _parse_change(row.get("Change"))
        normalized = {
            "trade_date": trade_date.isoformat(),
            "name": str(row.get("Name", "")).strip(),
            "open": _parse_number(row.get("OpeningPrice")),
            "high": _parse_number(row.get("HighestPrice")),
            "low": _parse_number(row.get("LowestPrice")),
            "close": _parse_number(row.get("ClosingPrice")),
            "volume": _parse_int(row.get("TradeVolume")),
            "trade_value": _parse_int(row.get("TradeValue")),
            "transaction_count": _parse_int(row.get("Transaction")),
            "change": change,
            "price_basis": "RAW",
        }
        if change_note is not None:
            normalized["change_note"] = change_note
        raw_hash = hashlib.sha256(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return (
            Evidence(
                evidence_id=f"twse:{trade_date.isoformat()}:{request.symbol}:ohlcv",
                symbol=request.symbol,
                evidence_type="OHLCV",
                source=self.metadata.source,
                source_record_id=f"{trade_date.isoformat()}:{request.symbol}",
                event_time=event_time,
                published_at=observed_at,
                observed_at=observed_at,
                effective_at=event_time,
                content_hash=raw_hash,
                revision_id=f"twse-stock-day-all:{raw_hash[:16]}",
                status=EvidenceStatus.RAW,
                payload=normalized,
            ),
        )
