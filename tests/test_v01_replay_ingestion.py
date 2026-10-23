from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradingagents_tw.contracts import (
    Evidence,
    EvidenceStatus,
    GateStatus,
    PriceBar,
    PriceBasis,
    PriceSeries,
)
from tradingagents_tw.providers import (
    ProviderMetadata,
    ProviderRequest,
    TPEXDailyCloseAdapter,
    TPEX_DAILY_CLOSE_URL,
    TWSEExRightPreviewAdapter,
    TWSE_EXRIGHT_PREVIEW_URL,
)
from tradingagents_tw.state import derive_trend_inputs, evaluate_trend_from_prices
from tradingagents_tw.truth import (
    FileTruthSnapshotStore,
    IngestionViolation,
    SnapshotImmutableError,
    SnapshotIntegrityError,
    assess_evidence,
    ingest_post_market,
    replay_truth_snapshot,
)

UTC = timezone.utc


class FakeProvider:
    metadata = ProviderMetadata(
        provider_id="fake",
        source="FAKE_OFFICIAL",
        schema_version="1.0",
        evidence_types=("OHLCV",),
        source_priority=1,
        history_mode="LATEST_ONLY",
        endpoint="fixture://fake",
    )

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, request: ProviderRequest) -> tuple[Evidence, ...]:
        self.calls += 1
        return (
            Evidence(
                evidence_id="fake:3037:ohlcv",
                symbol=request.symbol,
                evidence_type="OHLCV",
                source=self.metadata.source,
                published_at=datetime(2026, 10, 23, 7, tzinfo=UTC),
                observed_at=datetime(2026, 10, 23, 7, tzinfo=UTC),
                content_hash="a" * 64,
                revision_id="r1",
                status=EvidenceStatus.RAW,
                payload={"close": 100, "price_basis": "RAW"},
            ),
        )


def _request(
    *,
    symbol: str = "3037",
    evidence_types: tuple[str, ...] = ("OHLCV",),
    start: date = date(2026, 10, 23),
    end: date = date(2026, 10, 23),
) -> ProviderRequest:
    return ProviderRequest(
        symbol=symbol,
        evidence_types=evidence_types,
        start_date=start,
        end_date=end,
        analysis_cutoff=datetime(2026, 10, 23, 16, tzinfo=UTC),
    )


def test_ingestion_persists_verified_snapshot_and_replay_never_refetches(tmp_path):
    provider = FakeProvider()
    store = FileTruthSnapshotStore(tmp_path)
    assessment = assess_evidence(
        coverage=100,
        freshness="PASS",
        provenance="PASS",
    )
    snapshot = ingest_post_market(
        provider=provider,
        request=_request(),
        assessment=assessment,
        snapshot_id="3037-2026-10-23",
        store=store,
        config={"truth_version": "v0.1"},
    )
    assert provider.calls == 1
    assert snapshot.evidence[0].status is EvidenceStatus.VERIFIED

    replayed = replay_truth_snapshot(
        store=store,
        snapshot_id="3037-2026-10-23",
    )
    assert provider.calls == 1
    assert replayed == snapshot
    assert store.replay_config(snapshot.config_hash) == {"truth_version": "v0.1"}


def test_snapshot_store_is_immutable_by_snapshot_id(tmp_path):
    provider = FakeProvider()
    store = FileTruthSnapshotStore(tmp_path)
    assessment = assess_evidence(coverage=100, freshness="PASS", provenance="PASS")
    first = ingest_post_market(
        provider=provider,
        request=_request(),
        assessment=assessment,
        snapshot_id="same-id",
        store=store,
        config={"version": 1},
    )
    store.put(first)

    with pytest.raises(SnapshotImmutableError, match="already points to different content"):
        ingest_post_market(
            provider=provider,
            request=_request(),
            assessment=assessment,
            snapshot_id="same-id",
            store=store,
            config={"version": 2},
        )


def test_snapshot_store_deduplicates_content_across_snapshot_ids(tmp_path):
    provider = FakeProvider()
    store = FileTruthSnapshotStore(tmp_path)
    assessment = assess_evidence(coverage=100, freshness="PASS", provenance="PASS")

    first = ingest_post_market(
        provider=provider,
        request=_request(),
        assessment=assessment,
        snapshot_id="alias-a",
        store=store,
        config={"version": 1},
    )
    second = ingest_post_market(
        provider=provider,
        request=_request(),
        assessment=assessment,
        snapshot_id="alias-b",
        store=store,
        config={"version": 1},
    )

    assert first.content_hash == second.content_hash
    assert len(list((tmp_path / "objects").glob("*.json"))) == 1
    assert replay_truth_snapshot(store=store, snapshot_id="alias-a").content_hash == first.content_hash
    assert replay_truth_snapshot(store=store, snapshot_id="alias-b").content_hash == first.content_hash


def test_snapshot_store_detects_object_tampering(tmp_path):
    provider = FakeProvider()
    store = FileTruthSnapshotStore(tmp_path)
    assessment = assess_evidence(coverage=100, freshness="PASS", provenance="PASS")
    snapshot = ingest_post_market(
        provider=provider,
        request=_request(),
        assessment=assessment,
        snapshot_id="tamper-test",
        store=store,
        config={"version": 1},
    )

    object_path = tmp_path / "objects" / f"{snapshot.content_hash}.json"
    payload = json.loads(object_path.read_text(encoding="utf-8"))
    payload["symbol"] = "9999"
    object_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError):
        replay_truth_snapshot(store=store, snapshot_id="tamper-test")


def test_empty_provider_output_cannot_create_pass_snapshot(tmp_path):
    class EmptyProvider(FakeProvider):
        def fetch(self, request: ProviderRequest):
            self.calls += 1
            return ()

    with pytest.raises(IngestionViolation, match="empty provider output"):
        ingest_post_market(
            provider=EmptyProvider(),
            request=_request(),
            assessment=assess_evidence(
                coverage=100,
                freshness="PASS",
                provenance="PASS",
            ),
            snapshot_id="empty",
            store=FileTruthSnapshotStore(tmp_path),
        )


def test_tpex_official_latest_adapter_parses_daily_close():
    rows = [
        {
            "Date": "1151023",
            "SecuritiesCompanyCode": "6488",
            "CompanyName": "環球晶",
            "Close": "435.50",
            "Change": "+4.50",
            "Open": "430.00",
            "High": "440.00",
            "Low": "428.00",
            "TradingShares": "12,345,000",
            "TransactionAmount": "5,350,000,000",
            "TransactionNumber": "15,000",
        }
    ]
    observed = datetime(2026, 10, 23, 7, tzinfo=UTC)
    adapter = TPEXDailyCloseAdapter(fetch_json=lambda: rows, clock=lambda: observed)
    evidence = adapter.fetch(_request(symbol="6488"))

    assert adapter.metadata.endpoint == TPEX_DAILY_CLOSE_URL
    assert adapter.metadata.history_mode == "LATEST_ONLY"
    assert len(evidence) == 1
    item = evidence[0]
    assert item.status is EvidenceStatus.RAW
    assert item.source == "TPEX_OPENAPI"
    assert item.payload["close"] == 435.5
    assert item.payload["volume"] == 12_345_000
    assert item.payload["transaction_count"] == 15_000


def test_twse_corporate_action_adapter_preserves_pending_values():
    rows = [
        {
            "Date": "1151027",
            "Code": "2330",
            "Name": "台積電",
            "Exdividend": "息",
            "StockDividendRatio": "",
            "CashDividend": "",
            "SubscriptionRatio": "0.00000000",
            "SubscriptionPricePerShare": "尚未公告",
        }
    ]
    observed = datetime(2026, 10, 23, 7, tzinfo=UTC)
    adapter = TWSEExRightPreviewAdapter(
        fetch_json=lambda: rows,
        clock=lambda: observed,
    )
    request = _request(
        symbol="2330",
        evidence_types=("CORPORATE_ACTION",),
        start=date(2026, 10, 23),
        end=date(2026, 11, 1),
    )
    evidence = adapter.fetch(request)

    assert adapter.metadata.endpoint == TWSE_EXRIGHT_PREVIEW_URL
    assert adapter.metadata.history_mode == "LATEST_ONLY"
    assert len(evidence) == 1
    item = evidence[0]
    assert item.status is EvidenceStatus.RAW
    assert item.effective_at is not None
    assert item.effective_at.date() == date(2026, 10, 27)
    assert item.payload["cash_dividend"] is None
    assert item.payload["subscription_price_per_share"] is None
    assert item.payload["adjustment_factor"] is None


def _adjusted_series() -> PriceSeries:
    start = date(2026, 8, 25)
    bars = tuple(
        PriceBar(
            symbol="3037",
            trade_date=start + timedelta(days=i),
            open=float(100 + i),
            high=float(101 + i),
            low=float(99 + i),
            close=float(100 + i),
            volume=1000,
            price_basis=PriceBasis.ADJUSTED,
            adjustment_method="FIXTURE_V1",
            adjustment_version="1",
        )
        for i in range(60)
    )
    return PriceSeries(
        symbol="3037",
        price_basis=PriceBasis.ADJUSTED,
        adjustment_method="FIXTURE_V1",
        adjustment_version="1",
        adjustment_as_of=bars[-1].trade_date,
        bars=bars,
    )


def test_adjusted_price_series_feeds_deterministic_trend_fixture():
    fixture_path = Path(__file__).with_name("fixtures") / "price_state_replay_v0_1.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    series = _adjusted_series()
    inputs = derive_trend_inputs(series, rs_20d=0.2)
    trend = evaluate_trend_from_prices(series, rs_20d=0.2)

    assert inputs.close == expected["close"]
    assert inputs.ma20 == expected["ma20"]
    assert inputs.ma60 == expected["ma60"]
    assert inputs.rs_20d == expected["rs_20d"]
    assert inputs.volume_ratio_20d == expected["volume_ratio_20d"]
    assert trend.state.value == expected["trend_state"]


def test_state_refuses_raw_price_series():
    raw = PriceSeries(
        symbol="3037",
        price_basis=PriceBasis.RAW,
        bars=tuple(
            PriceBar(
                symbol="3037",
                trade_date=date(2026, 1, 1) + timedelta(days=i),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
                price_basis=PriceBasis.RAW,
            )
            for i in range(60)
        ),
    )
    with pytest.raises(ValueError, match="require ADJUSTED"):
        derive_trend_inputs(raw, rs_20d=0.2)


def test_snapshot_store_detects_config_tampering(tmp_path):
    provider = FakeProvider()
    store = FileTruthSnapshotStore(tmp_path)
    snapshot = ingest_post_market(
        provider=provider,
        request=_request(),
        assessment=assess_evidence(
            coverage=100,
            freshness="PASS",
            provenance="PASS",
        ),
        snapshot_id="config-tamper",
        store=store,
        config={"version": 1, "cutoff_policy": "post-market"},
    )

    config_path = tmp_path / "configs" / f"{snapshot.config_hash}.json"
    config_path.write_text('{"version":2}', encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="config failed integrity"):
        replay_truth_snapshot(store=store, snapshot_id="config-tamper")
