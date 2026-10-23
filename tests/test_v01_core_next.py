from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from tradingagents_tw.contracts import (
    PriceBar,
    PriceBasis,
    PriceSeries,
    StateSnapshot,
    TrendAssessment,
    TrendState,
)
from tradingagents_tw.providers import ProviderAdapter, ProviderMetadata, ProviderRequest
from tradingagents_tw.state import (
    V0_1_SCORE_CONFIG,
    TrendInputs,
    build_score_components,
    calculate_directional_score,
    canonical_state_json,
    evaluate_trend,
    normalize_raw_value,
)

UTC = timezone.utc


def raw_bar(day: int) -> PriceBar:
    return PriceBar(
        symbol="3037",
        trade_date=date(2026, 10, day),
        open=100,
        high=110,
        low=95,
        close=105,
        volume=1000,
        price_basis=PriceBasis.RAW,
    )


def adjusted_bar(day: int) -> PriceBar:
    return PriceBar(
        symbol="3037",
        trade_date=date(2026, 10, day),
        open=100,
        high=110,
        low=95,
        close=105,
        volume=1000,
        price_basis=PriceBasis.ADJUSTED,
        adjustment_method="TWSE_CA_V1",
        adjustment_version="1",
    )


def test_price_series_rejects_raw_adjusted_mix():
    with pytest.raises(ValidationError, match="cannot be mixed"):
        PriceSeries(
            symbol="3037",
            price_basis=PriceBasis.RAW,
            bars=(raw_bar(22), adjusted_bar(23)),
        )


def test_adjusted_price_requires_explicit_method():
    with pytest.raises(ValidationError, match="require adjustment_method"):
        PriceBar(
            symbol="3037",
            trade_date=date(2026, 10, 23),
            open=100,
            high=110,
            low=95,
            close=105,
            volume=1000,
            price_basis=PriceBasis.ADJUSTED,
        )


def test_hysteresis_requires_two_confirmations_for_state_change():
    up = evaluate_trend(
        TrendInputs(close=110, ma20=105, ma60=100, rs_20d=1, volume_ratio_20d=1.0),
        as_of=date(2026, 10, 21),
    )
    down_inputs = TrendInputs(close=90, ma20=95, ma60=100, rs_20d=-1, volume_ratio_20d=1.0)

    first = evaluate_trend(
        down_inputs,
        as_of=date(2026, 10, 22),
        previous=up,
        confirmation_window=2,
    )
    assert first.state == TrendState.UPTREND
    assert first.candidate_state == TrendState.DOWNTREND
    assert first.confirmation_progress == 0.5

    second = evaluate_trend(
        down_inputs,
        as_of=date(2026, 10, 23),
        previous=first,
        confirmation_window=2,
    )
    assert second.state == TrendState.DOWNTREND
    assert second.candidate_state is None
    assert second.confirmation_progress == 1.0
    assert second.state_since == date(2026, 10, 23)


def test_hysteresis_resets_when_candidate_changes():
    previous = TrendAssessment(
        state=TrendState.UPTREND,
        candidate_state=TrendState.DOWNTREND,
        confirmation_progress=0.5,
        state_since=date(2026, 10, 20),
        rule_version="trend-hysteresis-v0.1",
    )
    sideways = evaluate_trend(
        TrendInputs(close=100, ma20=100, ma60=100, rs_20d=0, volume_ratio_20d=1),
        as_of=date(2026, 10, 23),
        previous=previous,
        confirmation_window=2,
    )
    assert sideways.state == TrendState.UPTREND
    assert sideways.candidate_state == TrendState.SIDEWAYS
    assert sideways.confirmation_progress == 0.5


def test_v01_score_config_is_frozen_and_reproducible():
    assert V0_1_SCORE_CONFIG.weights == (
        ("TREND", 0.30),
        ("VOLUME_PRICE", 0.20),
        ("RELATIVE_STRENGTH", 0.15),
        ("FLOW", 0.15),
        ("FUNDAMENTAL", 0.10),
        ("EVENT", 0.10),
    )
    components = build_score_components(
        {
            "TREND": 0.6,
            "VOLUME_PRICE": 0.2,
            "RELATIVE_STRENGTH": 0.0,
            "FLOW": 0.4,
            "FUNDAMENTAL": -0.2,
            "EVENT": 0.0,
        }
    )
    assert calculate_directional_score(components).score == 63.0


def test_score_normalization_fails_closed_outside_contract():
    with pytest.raises(ValueError, match="frozen normalization range"):
        normalize_raw_value(1.01)


def test_provider_request_contract_and_protocol():
    class FakeProvider:
        metadata = ProviderMetadata(
            provider_id="twse",
            source="TWSE",
            schema_version="1.0",
            evidence_types=("OHLCV",),
            source_priority=1,
        )

        def fetch(self, request: ProviderRequest):
            return ()

    request = ProviderRequest(
        symbol="3037",
        evidence_types=("OHLCV",),
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 23),
        analysis_cutoff=datetime(2026, 10, 23, 8, tzinfo=UTC),
    )
    assert isinstance(FakeProvider(), ProviderAdapter)
    assert request.analysis_cutoff.tzinfo is not None


def test_provider_request_rejects_inverted_window():
    with pytest.raises(ValidationError, match="end_date cannot precede start_date"):
        ProviderRequest(
            symbol="3037",
            evidence_types=("OHLCV",),
            start_date=date(2026, 10, 23),
            end_date=date(2026, 10, 1),
            analysis_cutoff=datetime(2026, 10, 23, 8, tzinfo=UTC),
        )


def test_golden_state_replay_is_exact():
    trend = evaluate_trend(
        TrendInputs(close=110, ma20=105, ma60=100, rs_20d=2, volume_ratio_20d=1.1),
        as_of=date(2026, 10, 23),
    )
    components = build_score_components(
        {
            "TREND": 0.6,
            "VOLUME_PRICE": 0.2,
            "RELATIVE_STRENGTH": 0.0,
            "FLOW": 0.4,
            "FUNDAMENTAL": -0.2,
            "EVENT": 0.0,
        }
    )
    state = StateSnapshot(
        snapshot_id="golden-s1",
        symbol="3037",
        trade_date=date(2026, 10, 23),
        trend=trend,
        directional_score=calculate_directional_score(components),
        state_engine_version="state-v0.1",
        config_hash="cfg-v0.1",
    )
    fixture = Path(__file__).with_name("fixtures") / "golden_state_v0_1.json"
    assert canonical_state_json(state) == fixture.read_text(encoding="utf-8").strip()


def test_provider_request_rejects_naive_cutoff():
    with pytest.raises(ValidationError, match="timezone-aware"):
        ProviderRequest(
            symbol="3037",
            evidence_types=("OHLCV",),
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 23),
            analysis_cutoff=datetime(2026, 10, 23, 8),
        )
