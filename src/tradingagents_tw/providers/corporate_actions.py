from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tradingagents_tw.contracts import Evidence, EvidenceStatus
from .base import ProviderMetadata, ProviderRequest


TWSE_TZ = ZoneInfo("Asia/Taipei")
TWSE_EXRIGHT_PREVIEW_URL = (
    "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
)


def _parse_date(value: Any) -> date:
    raw = str(value).strip().replace("/", "").replace("-", "")
    if len(raw) == 7:
        return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
    if len(raw) == 8:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    raise ValueError(f"unsupported corporate-action date format: {value}")


def _optional_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if text in {
        "",
        "-",
        "--",
        "---",
        "N/A",
        "null",
        "None",
        "尚未公告",
        "待公告",
        "待公告實際收益分配金額",
    }:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _default_fetch_json() -> list[dict[str, Any]]:
    request = Request(
        TWSE_EXRIGHT_PREVIEW_URL,
        headers={"User-Agent": "TradingAgents-TW/0.1"},
    )
    with urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("TWSE TWT48U_ALL response must be a JSON array")
    return data


class TWSEExRightPreviewAdapter:
    """Current rolling ex-right/ex-dividend announcement snapshot.

    This adapter records announcement evidence. It does not calculate an
    adjustment factor; the adjustment engine is a separate Truth capability.
    """

    metadata = ProviderMetadata(
        provider_id="twse-exright-preview",
        source="TWSE_OPENAPI",
        schema_version="1.0",
        evidence_types=("CORPORATE_ACTION",),
        source_priority=1,
        history_mode="LATEST_ONLY",
        endpoint=TWSE_EXRIGHT_PREVIEW_URL,
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
        if "CORPORATE_ACTION" not in request.evidence_types:
            raise ValueError("TWSE TWT48U_ALL only supplies CORPORATE_ACTION")

        observed_at = self._clock()
        if observed_at.utcoffset() is None:
            raise ValueError("provider clock must return timezone-aware datetime")
        if observed_at > request.analysis_cutoff:
            raise ValueError(
                "LATEST_ONLY provider cannot reconstruct evidence for a cutoff before observation"
            )

        result: list[Evidence] = []
        for row in self._fetch_json():
            if str(row.get("Code", "")).strip() != request.symbol:
                continue
            event_date = _parse_date(row.get("Date"))
            if not request.start_date <= event_date <= request.end_date:
                continue

            event_kind = str(row.get("Exdividend", "")).strip()
            raw_hash = hashlib.sha256(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            effective_at = datetime.combine(
                event_date,
                time(9, 0),
                tzinfo=TWSE_TZ,
            )
            payload = {
                "event_date": event_date.isoformat(),
                "name": str(row.get("Name", "")).strip(),
                "event_kind": event_kind,
                "stock_dividend_ratio": _optional_number(
                    row.get("StockDividendRatio")
                ),
                "cash_dividend": _optional_number(row.get("CashDividend")),
                "subscription_ratio": _optional_number(
                    row.get("SubscriptionRatio")
                ),
                "subscription_price_per_share": _optional_number(
                    row.get("SubscriptionPricePerShare")
                ),
                "adjustment_factor": None,
            }
            result.append(
                Evidence(
                    evidence_id=(
                        f"twse:{event_date.isoformat()}:{request.symbol}:"
                        f"corporate-action:{event_kind or 'UNKNOWN'}"
                    ),
                    symbol=request.symbol,
                    evidence_type="CORPORATE_ACTION",
                    source=self.metadata.source,
                    source_record_id=(
                        f"{event_date.isoformat()}:{request.symbol}:{event_kind}"
                    ),
                    event_time=effective_at,
                    published_at=observed_at,
                    observed_at=observed_at,
                    effective_at=effective_at,
                    content_hash=raw_hash,
                    revision_id=f"twse-twt48u:{raw_hash[:16]}",
                    status=EvidenceStatus.RAW,
                    payload=payload,
                )
            )
        return tuple(result)
