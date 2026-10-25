from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tradingagents_tw.providers import (
    ProviderRequest, TWSEInstitutionalAdapter, TPEXInstitutionalAdapter, TWSEMarginAdapter,
    TPEXMarginAdapter,
)
from tradingagents_tw.providers.institutional import TWSE_FIELDS, TPEX_FIELDS


TZ = ZoneInfo("Asia/Taipei")
AS_OF = date(2026, 10, 22)
NOW = datetime(2026, 10, 23, 20, tzinfo=TZ)


def request(symbol="2330", trade_date=AS_OF):
    return ProviderRequest(
        symbol=symbol,
        evidence_types=("INSTITUTIONAL_FLOW",),
        start_date=trade_date,
        end_date=trade_date,
        analysis_cutoff=NOW,
    )


def test_twse_t86_uses_named_fields_and_preserves_raw_shares():
    fields = ["證券代號", *TWSE_FIELDS.values()]
    payload = {"date": "20261022", "fields": fields,
               "data": [["2330", "1,000", "-200", "300", "1,100"]], "stat": "OK"}
    adapter = TWSEInstitutionalAdapter(
        fetch_data=lambda _date: payload, clock=lambda: NOW,
    )

    evidence, = adapter.fetch(request())

    assert evidence.source == "TWSE_T86"
    assert evidence.payload["unit"] == "SHARES"
    assert evidence.payload["foreign"] == 1000
    assert evidence.payload["trust"] == -200
    assert evidence.payload["dealer"] == 300
    assert evidence.payload["total_matches_components"] is True
    assert evidence.status.value == "RAW"


def test_tpex_institutional_latest_source_requires_exact_report_date():
    row = {
        "Date": "115/10/22", "SecuritiesCompanyCode": "2330",
        TPEX_FIELDS["foreign"]: "1000", TPEX_FIELDS["trust"]: "-200",
        TPEX_FIELDS["dealer"]: "300", TPEX_FIELDS["total"]: "1100",
    }
    adapter = TPEXInstitutionalAdapter(fetch_data=lambda: [row], clock=lambda: NOW)
    evidence, = adapter.fetch(request())
    assert evidence.payload["market"] == "TPEX"
    assert evidence.payload["trade_date"] == "2026-10-22"

    with pytest.raises(ValueError, match="does not match requested date"):
        adapter.fetch(request(trade_date=date(2026, 10, 21)))


def test_institutional_adapter_rejects_unknown_required_columns():
    payload = {"date": "20261022", "fields": ["證券代號", "foreign"],
               "data": [["2330", "0"]], "stat": "OK"}
    adapter = TWSEInstitutionalAdapter(fetch_data=lambda _date: payload, clock=lambda: NOW)
    with pytest.raises(ValueError, match="required fields"):
        adapter.fetch(request())


def test_twse_margin_adapter_selects_named_balance_columns_and_lots():
    fields = ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
              "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額",
              "次一營業日限額", "資券互抵", "註記"]
    payload = {"stat": "OK", "date": "20261022", "tables": [
        {"fields": fields, "data": [["2330", "台積電", "1", "2", "0", "100", "99",
                                       "1000", "0", "0", "0", "5", "5", "1000", "0", ""]]}
    ]}
    adapter = TWSEMarginAdapter(fetch_json=lambda _date: payload, clock=lambda: NOW)
    margin_request = request().model_copy(update={"evidence_types": ("MARGIN_BALANCE",)})
    evidence, = adapter.fetch(margin_request)
    assert evidence.source == "TWSE_MI_MARGN"
    assert evidence.payload["unit"] == "LOTS"
    assert evidence.payload["margin_previous_balance"] == 100
    assert evidence.payload["margin_balance"] == 99
    assert evidence.payload["short_balance"] == 5


def test_tpex_margin_adapter_normalizes_latest_snapshot_and_activity_in_lots():
    row = {
        "Date": "115/10/22", "SecuritiesCompanyCode": "6488",
        "MarginPurchaseYesterdayBalance": "1,000", "MarginPurchaseBuy": "10",
        "MarginPurchaseSell": "20", "MarginPurchaseCashRepayment": "3",
        "MarginPurchaseTodayBalance": "987", "MarginPurchaseLimit": "5,000",
        "ShortSaleYesterdayBalance": "100", "ShortSaleSell": "5", "ShortSaleBuy": "7",
        "ShortSaleCashRepayment": "2", "ShortSaleTodayBalance": "96",
        "ShortSaleLimit": "5,000", "OffsetLoanAndShort": "1",
    }
    adapter = TPEXMarginAdapter(fetch_json=lambda: [row], clock=lambda: NOW)
    margin_request = request("6488").model_copy(update={"evidence_types": ("MARGIN_BALANCE",)})

    evidence, = adapter.fetch(margin_request)

    assert evidence.source == "TPEX_MARGIN_BALANCE"
    assert evidence.payload["market"] == "TPEX"
    assert evidence.payload["unit"] == "LOTS"
    assert evidence.payload["margin_previous_balance"] == 1000
    assert evidence.payload["margin_balance"] == 987
    assert evidence.payload["short_balance"] == 96
    assert evidence.payload["offset_loan_and_short"] == 1
    assert adapter.metadata.history_mode == "LATEST_ONLY"


def test_tpex_margin_adapter_rejects_date_mismatch_and_unknown_schema():
    good = {
        "Date": "115/10/22", "SecuritiesCompanyCode": "6488",
        "MarginPurchaseYesterdayBalance": "1", "MarginPurchaseBuy": "0",
        "MarginPurchaseSell": "0", "MarginPurchaseCashRepayment": "0",
        "MarginPurchaseTodayBalance": "1", "MarginPurchaseLimit": "5",
        "ShortSaleYesterdayBalance": "0", "ShortSaleSell": "0", "ShortSaleBuy": "0",
        "ShortSaleCashRepayment": "0", "ShortSaleTodayBalance": "0",
        "ShortSaleLimit": "5", "OffsetLoanAndShort": "0",
    }
    margin_request = request("6488").model_copy(update={"evidence_types": ("MARGIN_BALANCE",)})
    adapter = TPEXMarginAdapter(fetch_json=lambda: [good], clock=lambda: NOW)
    with pytest.raises(ValueError, match="does not match requested date"):
        adapter.fetch(margin_request.model_copy(update={"start_date": date(2026, 10, 21), "end_date": date(2026, 10, 21)}))

    adapter = TPEXMarginAdapter(fetch_json=lambda: [{"Date": "115/10/22"}], clock=lambda: NOW)
    with pytest.raises(ValueError, match="required fields"):
        adapter.fetch(margin_request)
