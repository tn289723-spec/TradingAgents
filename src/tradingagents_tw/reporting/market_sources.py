"""Build a compact, same-origin snapshot of official source evidence for Pages.

The output contains provider-normalized RAW evidence only. It never calculates
State, scores, screening results, or trade recommendations.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
from http.client import IncompleteRead
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tradingagents_tw.providers import (
    ProviderRequest, TWSEInstitutionalAdapter, TPEXInstitutionalAdapter,
    TWSEMarginAdapter, TPEXMarginAdapter,
    TWSEStockDayAllAdapter, TPEXDailyCloseAdapter,
)
from tradingagents_tw.providers.margin import TPEX_MARGIN_URL, TWSE_MARGIN_URL
from tradingagents_tw.providers.institutional import TWSE_T86_URL, TPEX_3INSTI_URL
from tradingagents_tw.providers.tdcc import TDCC_OWNERSHIP_URL
from tradingagents_tw.providers.twse import TWSE_STOCK_DAY_ALL_URL, _parse_date as twse_date
from tradingagents_tw.providers.tpex import TPEX_DAILY_CLOSE_URL, _parse_date as tpex_date


TZ = ZoneInfo("Asia/Taipei")
SCHEMA = "official-market-snapshot-v1"


def _http_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "TradingAgents-TW/0.2"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                body = response.read()
                expected = response.headers.get("Content-Length")
                if expected is not None and len(body) != int(expected):
                    raise IncompleteRead(body, int(expected) - len(body))
                return body
        except HTTPError as exc:
            if exc.code not in {408, 425, 429} and exc.code < 500:
                raise
            error: Exception = exc
        except (IncompleteRead, URLError, TimeoutError, ConnectionError) as exc:
            error = exc
        if attempt == 2:
            raise error
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable retry state")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _source_info(key: str, label: str, url: str, observed_at: datetime,
                 body_hash: str, count: int, trade_date: str | None = None,
                 missing_count: int = 0) -> dict[str, Any]:
    return {
        "id": key, "label": label, "url": url, "status": "RAW_UNVERIFIED",
        "observed_at": observed_at.isoformat(), "content_sha256": body_hash,
        "record_count": count, "missing_count": missing_count, "trade_date": trade_date,
    }


def build_market_sources_snapshot(*, fetch_bytes: Callable[[str], bytes] = _http_bytes,
                                  clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Fetch official feeds once, normalize using the source adapters, and group by symbol."""
    now = clock or (lambda: datetime.now(TZ))
    symbols: dict[str, dict[str, Any]] = {}
    source_info: list[dict[str, Any]] = []

    def download_json(key: str, label: str, url: str, *, request_url: str | None = None):
        raw = fetch_bytes(request_url or url)
        observed = now()  # Evidence is observed only after retrieval completes.
        payload = json.loads(raw.decode("utf-8-sig"))
        if not payload or not isinstance(payload, (list, dict)):
            raise ValueError(f"{key} response must be a non-empty JSON array or object")
        return payload, observed, hashlib.sha256(raw).hexdigest()

    def put_evidence(symbol: str, market: str, field: str, evidence) -> None:
        if not evidence:
            return
        item = evidence[0]
        record = symbols.setdefault(symbol, {"market": market, "trade_date": None, "sources": {}})
        if record["market"] != market:
            raise ValueError("symbol appears in both official boards")
        record["trade_date"] = item.payload.get("trade_date", item.payload.get("snapshot_date"))
        record["sources"][field] = {
            "status": item.status.value,
            "source": item.source,
            "evidence_id": item.evidence_id,
            "observed_at": item.observed_at.isoformat(),
            "content_sha256": item.content_hash,
            "payload": item.payload,
        }

    # Quote feeds establish board membership and the session date for latest-only feeds.
    quote_specs = (
        ("twse_ohlcv", "上市每日收盤行情", TWSE_STOCK_DAY_ALL_URL, TWSEStockDayAllAdapter,
         twse_date, "TWSE"),
        ("tpex_ohlcv", "上櫃每日收盤行情", TPEX_DAILY_CLOSE_URL, TPEXDailyCloseAdapter,
         tpex_date, "TPEX"),
    )
    quote_context: dict[str, tuple[list[dict[str, Any]], datetime, str, Any]] = {}
    for key, label, url, adapter_type, parse_date, market in quote_specs:
        rows, observed, digest = download_json(key, label, url)
        if not isinstance(rows, list):
            raise ValueError(f"{key} response must be a JSON array")
        get_code = "Code" if market == "TWSE" else "SecuritiesCompanyCode"
        get_date = "Date"
        dates = {parse_date(row[get_date]) for row in rows if isinstance(row, dict) and get_date in row}
        if len(dates) != 1:
            raise ValueError(f"{key} response has unknown or mixed session dates")
        trade_date = dates.pop()
        fetch = lambda rows=rows: rows
        adapter = adapter_type(fetch_json=fetch, clock=lambda observed=observed: observed)
        cutoff = now() + timedelta(minutes=1)
        count = 0
        missing_count = 0
        numeric_fields = ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue", "Transaction") if market == "TWSE" else ("Open", "High", "Low", "Close", "TradingShares", "TransactionAmount", "TransactionNumber")
        for row in rows:
            if not isinstance(row, dict) or not str(row.get(get_code, "")).strip():
                raise ValueError(f"{key} row has no stock code")
            code = str(row[get_code]).strip()
            missing_values = {"", "--", "---", "-", "N/A", "null", "None"}
            change_value = str(row.get("Change", "")).strip()
            missing_quote_values = (any(str(row.get(field, "")).strip() in missing_values for field in numeric_fields)
                                    or change_value in missing_values)
            if missing_quote_values:
                record = symbols.setdefault(code, {"market": market, "trade_date": trade_date.isoformat(), "sources": {}})
                record["sources"]["ohlcv"] = {
                    "status": "MISSING", "source": "TWSE_OPENAPI" if market == "TWSE" else "TPEX_OPENAPI",
                    "evidence_id": None, "observed_at": observed.isoformat(),
                    "content_sha256": _canonical_hash(row),
                    "payload": {"reason": "官方行情列有缺漏欄位，保留缺漏狀態"},
                }
                missing_count += 1
                continue
            evidence = adapter.fetch(ProviderRequest(
                symbol=code, evidence_types=("OHLCV",), start_date=trade_date,
                end_date=trade_date, analysis_cutoff=cutoff,
            ))
            put_evidence(code, market, "ohlcv", evidence)
            count += bool(evidence)
        source_info.append(_source_info(key, label, url, observed, digest, count, trade_date.isoformat(), missing_count))
        quote_context[market] = (rows, observed, digest, trade_date)

    # Each provider fetches one bulk response; adapters normalize one symbol at a time.
    feed_specs = (
        ("twse_institutional", "上市三大法人", TWSE_T86_URL, "TWSE", "institutional_flow", "INSTITUTIONAL_FLOW", "T86"),
        ("tpex_institutional", "上櫃三大法人", TPEX_3INSTI_URL, "TPEX", "institutional_flow", "INSTITUTIONAL_FLOW", "TPEX_INST"),
        ("twse_margin", "上市融資融券", TWSE_MARGIN_URL, "TWSE", "margin_balance", "MARGIN_BALANCE", "TWSE_MARGIN"),
        ("tpex_margin", "上櫃融資融券", TPEX_MARGIN_URL, "TPEX", "margin_balance", "MARGIN_BALANCE", "TPEX_MARGIN"),
    )
    for key, label, url, market, field, evidence_type, kind in feed_specs:
        trade_date = quote_context[market][3]
        request_url = url
        if kind == "T86":
            request_url = f"{url}?" + urlencode({"date": trade_date.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"})
        elif kind == "TWSE_MARGIN":
            request_url = f"{url}?" + urlencode({"date": trade_date.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
        rows, observed, digest = download_json(key, label, url, request_url=request_url)
        cutoff = now() + timedelta(minutes=1)
        if kind == "T86":
            adapter = TWSEInstitutionalAdapter(fetch_data=lambda _date, p=rows: p,
                                               clock=lambda observed=observed: observed)
        elif kind == "TPEX_INST":
            adapter = TPEXInstitutionalAdapter(fetch_data=lambda p=rows: p, clock=lambda observed=observed: observed)
        elif kind == "TWSE_MARGIN":
            adapter = TWSEMarginAdapter(fetch_json=lambda _date, p=rows: p,
                                        clock=lambda observed=observed: observed)
        else:
            adapter = TPEXMarginAdapter(fetch_json=lambda p=rows: p, clock=lambda observed=observed: observed)
        count = 0
        for symbol, info in list(symbols.items()):
            if info["market"] != market:
                continue
            evidence = adapter.fetch(ProviderRequest(
                symbol=symbol, evidence_types=(evidence_type,), start_date=trade_date,
                end_date=trade_date, analysis_cutoff=cutoff,
            ))
            put_evidence(symbol, market, field, evidence)
            count += bool(evidence)
        source_info.append(_source_info(key, label, url, observed, digest, count, trade_date.isoformat()))

    # TDCC publishes one weekly CSV. Parse and group it once rather than re-reading
    # the entire file once per listed symbol.
    raw_tdcc = fetch_bytes(TDCC_OWNERSHIP_URL)
    observed = now()  # Do not backdate a potentially slow weekly feed download.
    text = raw_tdcc.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("TDCC ownership CSV schema is unknown")
    ownership_count = 0
    for row in reader:
        code = str(row.get("證券代號", "")).strip()
        if not code or code not in symbols:
            continue
        snapshot_date = datetime.strptime(str(row["資料日期"]).strip(), "%Y%m%d").date()
        tier = int(str(row["持股分級"]).strip())
        holders = int(str(row["人數"]).replace(",", "").strip())
        shares = int(str(row["股數"]).replace(",", "").strip())
        ratio = float(str(row["占集保庫存數比例% "] if "占集保庫存數比例% " in row else row["占集保庫存數比例%"]).replace(",", "").replace("%", "").strip())
        if tier not in range(1, 18) or holders < 0 or shares < 0 or not 0 <= ratio <= 100:
            raise ValueError("TDCC ownership row has invalid values")
        record = symbols[code]["sources"].setdefault("ownership_distribution", {
            "status": "RAW", "source": "TDCC_OPENDATA", "evidence_id": None,
            "observed_at": observed.isoformat(), "content_sha256": hashlib.sha256(raw_tdcc).hexdigest(),
            "payload": {"snapshot_date": snapshot_date.isoformat(), "frequency": "WEEKLY", "unit": "SHARES", "tiers": []},
        })
        if record["payload"]["snapshot_date"] != snapshot_date.isoformat():
            raise ValueError("TDCC response mixes snapshot dates")
        record["payload"]["tiers"].append({"tier": tier, "holders": holders, "shares": shares, "custody_pct": ratio})
        ownership_count += 1
    for code, info in symbols.items():
        evidence = info["sources"].get("ownership_distribution")
        if evidence:
            tiers = evidence["payload"]["tiers"]
            tiers.sort(key=lambda item: item["tier"])
            if len({tier["tier"] for tier in tiers}) != len(tiers):
                raise ValueError("TDCC ownership response contains duplicate tiers")
            evidence["evidence_id"] = f"tdcc:{evidence['payload']['snapshot_date']}:{code}:ownership-distribution"
            evidence["payload"]["unit"] = "SHARES"
    source_info.append(_source_info(
        "tdcc_ownership", "TDCC 每週持股分級", TDCC_OWNERSHIP_URL, observed,
        hashlib.sha256(raw_tdcc).hexdigest(), ownership_count,
    ))

    return {
        "schema_version": SCHEMA,
        "generated_at": now().isoformat(),
        "data_status": "RAW_UNVERIFIED",
        "sources": source_info,
        "symbols": symbols,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--output":
        raise SystemExit("usage: python -m tradingagents_tw.reporting.market_sources --output PATH")
    snapshot = build_market_sources_snapshot()
    output = Path(args[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    output.write_bytes(gzip.compress(serialized, mtime=0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
