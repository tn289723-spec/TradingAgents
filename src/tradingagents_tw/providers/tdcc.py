from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, time
from typing import Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tradingagents_tw.contracts import Evidence, EvidenceStatus
from .base import ProviderMetadata, ProviderRequest


TDCC_OWNERSHIP_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
TDCC_TZ = ZoneInfo("Asia/Taipei")


def _download_csv() -> str:
    request = Request(TDCC_OWNERSHIP_URL, headers={"User-Agent": "TradingAgents-TW/0.2"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8-sig")


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"TDCC ownership CSV missing required field: {key}")
    return str(value).strip()


class TDCCOwnershipAdapter:
    """Fetch the official latest weekly ownership-distribution snapshot.

    TDCC's public open-data endpoint serves the current weekly file. It cannot
    reconstruct prior point-in-time snapshots; callers must archive each raw
    response if historical research is required.
    """

    metadata = ProviderMetadata(
        provider_id="tdcc-weekly-ownership-distribution",
        source="TDCC_OPENDATA",
        schema_version="1.0",
        evidence_types=("OWNERSHIP_DISTRIBUTION",),
        source_priority=1,
        history_mode="LATEST_ONLY",
        endpoint=TDCC_OWNERSHIP_URL,
    )

    def __init__(
        self,
        *,
        fetch_csv: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetch_csv = fetch_csv or _download_csv
        self._clock = clock or (lambda: datetime.now(TDCC_TZ))

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        if "OWNERSHIP_DISTRIBUTION" not in request.evidence_types:
            raise ValueError("TDCC endpoint only supplies weekly ownership distribution")
        if request.start_date != request.end_date:
            raise ValueError("LATEST_ONLY provider requires a single snapshot date request")
        # The weekly endpoint has no trustworthy publication time. The response
        # is first provably available only after the download has completed.
        raw = self._fetch_csv()
        observed_at = self._clock()
        if observed_at.utcoffset() is None:
            raise ValueError("provider clock must return timezone-aware datetime")
        if observed_at > request.analysis_cutoff:
            raise ValueError("TDCC latest snapshot cannot reconstruct an earlier analysis cutoff")
        reader = csv.DictReader(io.StringIO(raw))
        expected = {"資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"}
        if reader.fieldnames is None or not expected.issubset(set(reader.fieldnames)):
            raise ValueError("TDCC ownership CSV schema is unknown or incomplete")

        rows = []
        for row in reader:
            if _required(row, "證券代號") != request.symbol:
                continue
            snapshot_date = date.fromisoformat(
                datetime.strptime(_required(row, "資料日期"), "%Y%m%d").date().isoformat()
            )
            if snapshot_date != request.start_date:
                continue
            tier = int(_required(row, "持股分級"))
            if tier not in range(1, 18):
                raise ValueError("TDCC ownership tier is outside the documented 1..17 range")
            holders = int(_required(row, "人數").replace(",", ""))
            shares = int(_required(row, "股數").replace(",", ""))
            ratio = float(_required(row, "占集保庫存數比例%").replace(",", "").replace("%", ""))
            if holders < 0 or shares < 0 or not 0 <= ratio <= 100:
                raise ValueError("TDCC ownership row has invalid numeric values")
            rows.append({"tier": tier, "holders": holders, "shares": shares, "custody_pct": ratio})
        if not rows:
            return ()
        rows.sort(key=lambda item: item["tier"])
        if len({item["tier"] for item in rows}) != len(rows):
            raise ValueError("TDCC ownership CSV contains duplicate tiers")
        snapshot_date = request.start_date
        content_hash = hashlib.sha256(raw.encode("utf-8-sig")).hexdigest()
        # The public file does not expose a reliable publication timestamp;
        # use observation as the earliest provable availability time.
        published_at = observed_at
        return (Evidence(
            evidence_id=f"tdcc:{snapshot_date.isoformat()}:{request.symbol}:ownership-distribution",
            symbol=request.symbol,
            evidence_type="OWNERSHIP_DISTRIBUTION",
            source=self.metadata.source,
            source_record_id=f"{snapshot_date.isoformat()}:{request.symbol}",
            event_time=datetime.combine(snapshot_date, time(13, 30), tzinfo=TDCC_TZ),
            published_at=published_at,
            observed_at=observed_at,
            effective_at=datetime.combine(snapshot_date, time(13, 30), tzinfo=TDCC_TZ),
            content_hash=content_hash,
            revision_id=f"tdcc-1-5:{content_hash[:16]}",
            status=EvidenceStatus.RAW,
            payload={"snapshot_date": snapshot_date.isoformat(), "frequency": "WEEKLY", "tiers": rows},
        ),)
