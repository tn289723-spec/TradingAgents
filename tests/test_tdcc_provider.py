from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tradingagents_tw.providers import ProviderRequest, TDCCOwnershipAdapter

TZ = ZoneInfo("Asia/Taipei")
CSV = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n20261016,2330,1,12,3000,0.01\n20261016,2330,15,7,800000,2.00\n20261016,2330,17,19,40000000,100.00\n"


def request(snapshot=date(2026, 10, 16), cutoff=datetime(2026, 10, 23, 20, tzinfo=TZ)):
    return ProviderRequest(symbol="2330", evidence_types=("OWNERSHIP_DISTRIBUTION",),
                           start_date=snapshot, end_date=snapshot, analysis_cutoff=cutoff)


def test_tdcc_adapter_preserves_weekly_snapshot_and_raw_provenance():
    adapter = TDCCOwnershipAdapter(fetch_csv=lambda: CSV,
                                   clock=lambda: datetime(2026, 10, 23, 20, tzinfo=TZ))
    evidence, = adapter.fetch(request())
    assert evidence.source == "TDCC_OPENDATA"
    assert evidence.payload["frequency"] == "WEEKLY"
    assert evidence.payload["snapshot_date"] == "2026-10-16"
    assert [tier["tier"] for tier in evidence.payload["tiers"]] == [1, 15, 17]
    assert len(evidence.content_hash) == 64


def test_tdcc_adapter_fails_closed_on_schema_change():
    adapter = TDCCOwnershipAdapter(fetch_csv=lambda: "code,date\n2330,20261016\n",
                                   clock=lambda: datetime(2026, 10, 23, 20, tzinfo=TZ))
    with pytest.raises(ValueError, match="schema is unknown"):
        adapter.fetch(request())


def test_tdcc_latest_only_source_does_not_backfill_or_misdate():
    adapter = TDCCOwnershipAdapter(fetch_csv=lambda: CSV,
                                   clock=lambda: datetime(2026, 10, 23, 20, tzinfo=TZ))
    assert adapter.fetch(request(snapshot=date(2026, 10, 23))) == ()
    window = request().model_copy(update={"start_date": date(2026, 10, 9)})
    with pytest.raises(ValueError, match="single snapshot date"):
        adapter.fetch(window)
