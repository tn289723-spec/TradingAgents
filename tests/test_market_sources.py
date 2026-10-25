import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tradingagents_tw.reporting.market_sources import build_market_sources_snapshot
from tradingagents_tw.providers.margin import TPEX_MARGIN_URL, TWSE_MARGIN_URL
from tradingagents_tw.providers.institutional import TWSE_T86_URL, TPEX_3INSTI_URL, TPEX_FIELDS, TWSE_FIELDS
from tradingagents_tw.providers.tdcc import TDCC_OWNERSHIP_URL
from tradingagents_tw.providers.twse import TWSE_STOCK_DAY_ALL_URL
from tradingagents_tw.providers.tpex import TPEX_DAILY_CLOSE_URL


TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 10, 23, 20, tzinfo=TZ)
TRADE_DATE = "20261022"


def fixture_sources():
    twse_quote = [{"Code": "2330", "Date": TRADE_DATE, "Name": "台積電",
                   "OpeningPrice": "100", "HighestPrice": "102", "LowestPrice": "99",
                   "ClosingPrice": "101", "TradeVolume": "100000", "TradeValue": "10000000",
                   "Transaction": "500", "Change": "1"}]
    tpex_quote = [{"Date": "115/10/22", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶",
                   "Open": "500", "High": "510", "Low": "490", "Close": "505",
                   "TradingShares": "100000", "TransactionAmount": "50000000",
                   "TransactionNumber": "800", "Change": "5"}]
    t86 = {"stat": "OK", "date": TRADE_DATE, "fields": ["證券代號", *TWSE_FIELDS.values()],
           "data": [["2330", "1000", "-200", "300", "1100"]]}
    tpex_flow = [{"Date": "115/10/22", "SecuritiesCompanyCode": "6488",
                  **{TPEX_FIELDS["foreign"]: "1000", TPEX_FIELDS["trust"]: "-200",
                     TPEX_FIELDS["dealer"]: "300", TPEX_FIELDS["total"]: "1100"}}]
    twse_margin = {"stat": "OK", "date": TRADE_DATE, "tables": [{
        "fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                   "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額",
                   "次一營業日限額", "資券互抵", "註記"],
        "data": [["2330", "台積電", "1", "2", "0", "100", "99", "1000",
                  "0", "0", "0", "5", "5", "1000", "0", ""]],
    }]}
    tpex_margin = [{"Date": "115/10/22", "SecuritiesCompanyCode": "6488",
                    "MarginPurchaseBalancePreviousDay": "100", "MarginPurchase": "1",
                    "MarginSales": "2", "CashRedemption": "0", "MarginPurchaseBalance": "99",
                    "MarginPurchaseBalanceBelongSecuritiesFinanceEnterprise": "0",
                    "MarginPurchaseUtilizationRate": "9.9", "MarginPurchaseQuota": "1000",
                    "ShortSaleBalancePreviousDay": "5", "ShortSale": "0", "ShortConvering": "0",
                    "StockRedemption": "0", "ShortSaleBalance": "5",
                    "ShortSaleBalanceBelongSecuritiesFinanceEnterprise": "0",
                    "ShortSaleUtilizationRate": "0.5", "ShortSaleQuota": "1000",
                    "Offsetting": "0", "Note": ""}]
    tdcc = ("資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
            "20261016,2330,1,12,3000,0.01\n20261016,2330,17,19,40000000,100.00\n")
    payloads = {
        TWSE_STOCK_DAY_ALL_URL: twse_quote,
        TPEX_DAILY_CLOSE_URL: tpex_quote,
        TWSE_T86_URL: t86,
        TPEX_3INSTI_URL: tpex_flow,
        TWSE_MARGIN_URL: twse_margin,
        TPEX_MARGIN_URL: tpex_margin,
        TDCC_OWNERSHIP_URL: tdcc,
        TWSE_T86_URL + "?date=20261022&selectType=ALLBUT0999&response=json": t86,
        TWSE_MARGIN_URL + "?date=20261022&selectType=ALL&response=json": twse_margin,
    }
    return {url: (value.encode("utf-8") if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode())
            for url, value in payloads.items()}


def test_official_source_snapshot_groups_raw_evidence_for_both_boards():
    bodies = fixture_sources()
    snapshot = build_market_sources_snapshot(fetch_bytes=lambda url: bodies[url], clock=lambda: NOW)

    assert snapshot["schema_version"] == "official-market-snapshot-v1"
    assert snapshot["data_status"] == "RAW_UNVERIFIED"
    assert snapshot["symbols"]["2330"]["sources"]["institutional_flow"]["payload"]["total"] == 1100
    assert snapshot["symbols"]["2330"]["sources"]["margin_balance"]["payload"]["unit"] == "LOTS"
    assert snapshot["symbols"]["2330"]["sources"]["ownership_distribution"]["payload"]["frequency"] == "WEEKLY"
    assert all(item["status"] == "RAW_UNVERIFIED" for item in snapshot["sources"])
    assert all("missing_count" in item for item in snapshot["sources"])
    assert len(snapshot["sources"]) == 7


def test_official_source_snapshot_fails_closed_on_invalid_source_payload():
    bodies = fixture_sources()
    bodies[TPEX_DAILY_CLOSE_URL] = json.dumps([{"SecuritiesCompanyCode": "6488"}]).encode()
    with pytest.raises(ValueError):
        build_market_sources_snapshot(fetch_bytes=lambda url: bodies[url], clock=lambda: NOW)


def test_snapshot_source_rows_are_bound_to_verified_adapter_evidence():
    bodies = fixture_sources()
    snapshot = build_market_sources_snapshot(fetch_bytes=lambda url: bodies[url], clock=lambda: NOW)
    quote = snapshot["symbols"]["2330"]["sources"]["ohlcv"]

    assert quote["status"] == "RAW"
    assert quote["source"] == "TWSE_OPENAPI"
    assert quote["payload"]["close"] == 101
    assert len(quote["content_sha256"]) == 64


def test_official_snapshot_observed_at_is_after_each_completed_download():
    """Slow downloads must not be represented as evidence available before retrieval."""
    bodies = fixture_sources()
    current = [NOW]

    def fetch(url):
        current[0] += timedelta(seconds=2)
        return bodies[url]

    snapshot = build_market_sources_snapshot(fetch_bytes=fetch, clock=lambda: current[0])
    assert len(snapshot["sources"]) == 7
    for index, source in enumerate(snapshot["sources"], start=1):
        assert source["observed_at"] == (NOW + timedelta(seconds=2 * index)).isoformat()
    assert snapshot["symbols"]["2330"]["sources"]["ohlcv"]["observed_at"] == (
        NOW + timedelta(seconds=2)
    ).isoformat()
    assert snapshot["symbols"]["2330"]["sources"]["ownership_distribution"]["observed_at"] == (
        NOW + timedelta(seconds=14)
    ).isoformat()
    assert snapshot["generated_at"] == (NOW + timedelta(seconds=14)).isoformat()
