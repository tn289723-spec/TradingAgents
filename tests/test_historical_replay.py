from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tradingagents_tw.contracts import Evidence, EvidenceStatus, GateStatus
from tradingagents_tw.providers.base import ProviderRequest
from tradingagents_tw.providers.historical import HistoricalOHLCVAdapter
from tradingagents_tw.providers.registry import Market, resolve_ohlcv_source, require_historical_source
from tradingagents_tw.truth.calendar import (
    TradingCalendar, SessionAmendment, PostMarketPolicy, parse_twse_calendar, parse_tpex_calendar,
)
from tradingagents_tw.truth.factors import derive_adjustment_factor, validate_action_coverage
from tradingagents_tw.truth.historical_replay import (
    HistoricalReplayConfig, ingest_historical, replay_historical, evaluate_historical_snapshot,
)
from tradingagents_tw.truth.snapshot import build_truth_snapshot
from tradingagents_tw.truth.store import FileTruthSnapshotStore

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def evidence(kind, source, symbol, payload, observed, identity):
    return Evidence(
        evidence_id=identity, symbol=symbol, evidence_type=kind, source=source,
        source_record_id=identity, published_at=observed, observed_at=observed,
        content_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        revision_id="fixture-v1", status=EvidenceStatus.VERIFIED, payload=payload,
    )


def setup_case(tmp_path, market=Market.TWSE):
    fixture = load(f"{market.value.lower()}_historical_golden_v1.json")
    calendars = load("official_calendars_2026.json")
    parse = parse_twse_calendar if market is Market.TWSE else parse_tpex_calendar
    calendar = parse(calendars[market.value.lower()], year=2026,
                     observed_at=datetime.fromisoformat(fixture["calendar_observed_at"]))
    observed = datetime.fromisoformat(fixture["observed_at"])
    calls = []

    def fetch(url):
        calls.append(url)
        month = parse_qs(urlparse(url).query)["date"][0].replace("/", "")
        return deepcopy(fixture["pages"][month])

    provider = HistoricalOHLCVAdapter(market, fetch_json=fetch, clock=lambda: observed)
    request = ProviderRequest(symbol=fixture["symbol"], evidence_types=("OHLCV",),
                              start_date=date.fromisoformat(fixture["start_date"]),
                              end_date=date.fromisoformat(fixture["end_date"]),
                              analysis_cutoff=datetime.fromisoformat(fixture["cutoff"]))
    config = HistoricalReplayConfig(market=market, calendar=calendar, start_date=request.start_date,
                                     rs_20d=fixture["rs_20d"])
    action = evidence("CORPORATE_ACTION", f"{market.value}_ARCHIVE", request.symbol, {
        "event_date": fixture["event_date"], "event_kind": "息", "cash_dividend": fixture["cash_dividend"],
        "stock_dividend_ratio": 0, "subscription_ratio": 0, "subscription_price_per_share": 0,
        "adjustment_factor": None,
    }, observed, f"{market.value}:synthetic-dividend")
    coverage = evidence("CORPORATE_ACTION_COVERAGE", f"{market.value}_ARCHIVE", request.symbol, {
        "version": "historical-action-coverage-v1", "market": market.value,
        "start_date": fixture["start_date"], "end_date": fixture["end_date"],
        "announcement_ids": [action.evidence_id],
    }, observed, f"{market.value}:synthetic-archive-manifest")
    return dict(provider=provider, request=request, config=config, announcements=(action,),
                coverage=coverage, snapshot_id=f"golden-{market.value}",
                store=FileTruthSnapshotStore(tmp_path)), fixture, calls


@pytest.mark.parametrize("market", list(Market))
def test_full_offline_golden(tmp_path, market):
    args, fixture, calls = setup_case(tmp_path, market)
    snapshot = ingest_historical(**args)
    assert len(calls) == 4
    args["provider"]._fetch_json = lambda _: pytest.fail("replay must never fetch live data")
    result = replay_historical(store=args["store"], snapshot_id=args["snapshot_id"])
    expected = fixture["expected"]
    assert snapshot.assessment.decision_gate is GateStatus.PASS
    assert len(result.adjusted.bars) == expected["bars"] >= 60
    assert result.factors[0].action.adjustment_factor == expected["factor"]
    assert result.factors[0].reference_price == expected["reference_price"]
    assert result.adjusted.bars[0].close == expected["first_adjusted_close"]
    assert asdict(result.inputs) == {
        "close": expected["last_close"], "ma20": expected["ma20"], "ma60": expected["ma60"],
        "rs_20d": fixture["rs_20d"], "volume_ratio_20d": expected["volume_ratio_20d"],
    }
    assert result.trend.state.value == expected["state"]
    assert result.trend.rule_version == "trend-hysteresis-v0.1"
    assert result.trend.state_since == args["request"].end_date
    assert result.factors[0].previous_close_id in {e.evidence_id for e in snapshot.evidence}
    # Reordering input and changing process decimal context must not change replay.
    reordered = build_truth_snapshot(
        snapshot_id="reordered", symbol=snapshot.symbol, trade_date=snapshot.trade_date,
        analysis_cutoff=snapshot.analysis_cutoff, evidence=tuple(reversed(snapshot.evidence)),
        assessment=snapshot.assessment, config=args["config"].model_dump(mode="json"),
    )
    with localcontext() as ctx:
        ctx.prec = 5
        assert evaluate_historical_snapshot(reordered, args["config"]) == result
    assert len(calls) == 4


@pytest.mark.parametrize("market", list(Market))
def test_registry_never_substitutes_latest_or_other_board(market):
    historical = resolve_ohlcv_source(market, history_mode="HISTORICAL")
    require_historical_source(market, historical)
    other = Market.TPEX if market is Market.TWSE else Market.TWSE
    for wrong in (resolve_ohlcv_source(market, history_mode="LATEST_ONLY"),
                  resolve_ohlcv_source(other, history_mode="HISTORICAL")):
        with pytest.raises(ValueError, match="registered"):
            require_historical_source(market, wrong)
    with pytest.raises(ValueError):
        resolve_ohlcv_source("UNKNOWN", history_mode="HISTORICAL")
    with pytest.raises(ValueError, match="unknown history"):
        resolve_ohlcv_source(market, history_mode="AUTO")


@pytest.mark.parametrize("market", list(Market))
def test_official_calendars_and_post_market_cutoff(tmp_path, market):
    args, _, _ = setup_case(tmp_path, market)
    calendar, cutoff = args["config"].calendar, args["request"].analysis_cutoff
    for day, expected in [(date(2026, 2, 11), True), (date(2026, 2, 12), False),
                          (date(2026, 2, 13), False), (date(2026, 2, 20), False),
                          (date(2026, 2, 23), True), (date(2026, 9, 28), False),
                          (date(2026, 4, 4), False), (date(2026, 1, 3), False)]:
        assert calendar.is_session(day, cutoff=cutoff) is expected
    policy, day = PostMarketPolicy(), date(2026, 4, 30)
    with pytest.raises(ValueError, match="cutoff"):
        policy.require_finalized(calendar, day, datetime.fromisoformat("2026-04-30T17:59:59+08:00"))
    policy.require_finalized(calendar, day, datetime.fromisoformat("2026-04-30T10:00:00+00:00"))
    with pytest.raises(ValueError, match="coverage"):
        calendar.is_session(date(2027, 1, 4), cutoff=cutoff)
    with pytest.raises(ValueError, match="timezone"):
        calendar.is_session(day, cutoff=datetime(2026, 4, 30, 18))
    with pytest.raises(ValueError, match="unavailable"):
        calendar.is_session(day, cutoff=datetime.fromisoformat("2025-12-31T18:00:00+08:00"))


def test_amendments_are_explicit_board_bound_and_point_in_time(tmp_path):
    args, _, _ = setup_case(tmp_path)
    calendar = args["config"].calendar
    amendment = SessionAmendment(trade_date=date(2026, 4, 29), is_open=False, reason="synthetic emergency closure",
                                  source_url="https://www.twse.com.tw/synthetic-test-not-a-real-notice",
                                  observed_at=datetime.fromisoformat("2026-04-29T08:00:00+08:00"))
    calendar = TradingCalendar.model_validate({**calendar.model_dump(), "amendments": (amendment,)})
    assert not calendar.is_session(amendment.trade_date, cutoff=args["request"].analysis_cutoff)
    with pytest.raises(ValueError, match="unavailable"):
        calendar.is_session(amendment.trade_date, cutoff=amendment.observed_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="official board"):
        TradingCalendar.model_validate({**calendar.model_dump(), "amendments": [
            {**amendment.model_dump(), "source_url": "https://example.com/closure"}]})


@pytest.mark.parametrize("market", list(Market))
def test_calendar_rejects_wrong_year_and_unknown_schema(tmp_path, market):
    payload = load("official_calendars_2026.json")[market.value.lower()]
    parse = parse_twse_calendar if market is Market.TWSE else parse_tpex_calendar
    observed = datetime.fromisoformat("2026-01-01T18:00:00+08:00")
    with pytest.raises(ValueError):
        parse(payload, year=2025, observed_at=observed)
    payload = deepcopy(payload)
    if market is Market.TWSE:
        payload["data"].append(["2026-04-28", "未知市場事件", ""])
    else:
        payload["data"]["html"] = payload["data"]["html"].replace("勞動節", "未知市場事件")
    with pytest.raises(ValueError, match="unrecognized"):
        parse(payload, year=2026, observed_at=observed)


@pytest.mark.parametrize("market,first_volume,first_close", [(Market.TWSE, 37544470, 2505), (Market.TPEX, 3850000, 1105)])
def test_captured_official_history_response_schema(market, first_volume, first_close):
    payload = load(f"{market.value.lower()}_historical_response_202607.json")["response"]
    observed = datetime.fromisoformat("2026-10-23T18:00:00+08:00")
    provider = HistoricalOHLCVAdapter(market, fetch_json=lambda _: payload, clock=lambda: observed)
    request = ProviderRequest(symbol="2330" if market is Market.TWSE else "6488", evidence_types=("OHLCV",),
                              start_date=date(2026, 7, 1), end_date=date(2026, 7, 31), analysis_cutoff=observed)
    result = provider.fetch(request)
    assert len(result) == 22
    assert result[0].payload["volume"] == first_volume
    assert result[0].payload["close"] == first_close
    assert result[0].published_at == observed
    assert result[0].status is EvidenceStatus.RAW
    assert result[0].payload["volume_precision_shares"] == (1 if market is Market.TWSE else 1000)


@pytest.mark.parametrize("bad", ["--", "NaN", "Infinity", "1e999", "0", "-1", True])
def test_missing_or_nonfinite_historical_price_fails(tmp_path, bad):
    args, fixture, _ = setup_case(tmp_path)
    fixture["pages"]["20260101"]["data"][0][3] = bad
    args["provider"]._fetch_json = lambda _: fixture["pages"]["20260101"]
    with pytest.raises(ValueError):
        args["provider"].fetch(args["request"])


@pytest.mark.parametrize("mutation", ["date", "symbol", "schema", "duplicate", "empty", "fractional-volume", "negative-value"])
def test_history_response_drift_is_rejected(tmp_path, mutation):
    args, fixture, _ = setup_case(tmp_path)
    page = fixture["pages"]["20260101"]
    if mutation == "date": page["date"] = "20250101"
    elif mutation == "symbol": page["title"] = "115年01月 2317 其他公司"
    elif mutation == "schema": page["fields"][1] = "成交張數"
    elif mutation == "duplicate": page["data"].append(page["data"][0])
    elif mutation == "empty": page["data"] = []
    elif mutation == "fractional-volume": page["data"][0][1] = "1.5"
    elif mutation == "negative-value": page["data"][0][2] = "-1"
    args["provider"]._fetch_json = lambda _: page
    with pytest.raises(ValueError):
        args["provider"].fetch(args["request"])


def test_historical_retrieval_cannot_backdate_publication(tmp_path):
    args, _, _ = setup_case(tmp_path)
    args["provider"]._clock = lambda: args["request"].analysis_cutoff + timedelta(seconds=1)
    with pytest.raises(ValueError, match="archived Truth"):
        ingest_historical(**args)
    assert not tuple(args["store"].refs.iterdir())


@pytest.mark.parametrize("kind", ["missing-session", "duplicate-session", "wrong-board", "raw-basis", "future-bar", "insufficient-bars"])
def test_bootstrap_blocks_incomplete_or_mixed_history(tmp_path, kind):
    args, _, _ = setup_case(tmp_path)
    rows = args["provider"].fetch(args["request"])
    if kind == "missing-session": rows = rows[1:]
    elif kind == "duplicate-session": rows += (rows[0],)
    elif kind == "insufficient-bars":
        start = date.fromisoformat(rows[-59].payload["trade_date"])
        rows = rows[-59:]
        args["request"] = args["request"].model_copy(update={"start_date": start})
        args["config"] = args["config"].model_copy(update={"start_date": start})
    else:
        payload = dict(rows[0].payload)
        if kind == "wrong-board": payload["market"] = "TPEX"
        if kind == "raw-basis": payload["price_basis"] = "ADJUSTED"
        if kind == "future-bar": payload["trade_date"] = "2026-05-04"
        rows = (rows[0].model_copy(update={"payload": payload}),) + rows[1:]
    args["provider"].fetch = lambda _: rows
    with pytest.raises(ValueError):
        ingest_historical(**args)
    assert not tuple(args["store"].refs.iterdir())


@pytest.mark.parametrize("mutation", ["missing-action", "extra-action", "latest-source", "short-coverage", "future-coverage", "revoked"])
def test_action_coverage_failures_block_before_fetch(tmp_path, mutation):
    args, _, calls = setup_case(tmp_path)
    coverage = args["coverage"]
    p = dict(coverage.payload)
    if mutation == "missing-action": args["announcements"] = ()
    elif mutation == "extra-action": p["announcement_ids"] += ["not-present"]
    elif mutation == "latest-source": coverage = coverage.model_copy(update={"source": "TWSE_OPENAPI"})
    elif mutation == "short-coverage": p["start_date"] = "2026-02-02"
    elif mutation == "future-coverage": coverage = coverage.model_copy(update={"observed_at": args["request"].analysis_cutoff + timedelta(seconds=1)})
    elif mutation == "revoked": coverage = coverage.model_copy(update={"status": EvidenceStatus.REVOKED})
    args["coverage"] = coverage.model_copy(update={"payload": p})
    with pytest.raises(ValueError):
        ingest_historical(**args)
    assert calls == []


def factor_case(tmp_path):
    args, fixture, _ = setup_case(tmp_path)
    previous = args["config"].calendar.previous_session(date.fromisoformat(fixture["event_date"]),
                                                        cutoff=args["request"].analysis_cutoff)
    raw = next(e for e in args["provider"].fetch(args["request"]) if e.payload["trade_date"] == str(previous))
    return args, args["announcements"][0], raw.model_copy(update={"status": EvidenceStatus.VERIFIED})


@pytest.mark.parametrize("mutation", ["pending", "negative", "nan", "unknown-event", "unitless-ratio", "future-close", "wrong-day", "adjusted", "wrong-symbol", "precomputed", "wrong-market"])
def test_factor_derivation_fails_closed(tmp_path, mutation):
    args, action, close = factor_case(tmp_path)
    p = dict(action.payload)
    if mutation == "pending": p["subscription_ratio"] = None
    elif mutation == "negative": p["cash_dividend"] = -1
    elif mutation == "nan": p["cash_dividend"] = "NaN"
    elif mutation == "unknown-event": p["event_kind"] = "減資"
    elif mutation == "unitless-ratio": p.update(event_kind="權息", stock_dividend_ratio=10)
    elif mutation == "future-close": close = close.model_copy(update={"observed_at": args["request"].analysis_cutoff + timedelta(seconds=1)})
    elif mutation == "wrong-day": close = close.model_copy(update={"payload": {**close.payload, "trade_date": "2026-01-02"}})
    elif mutation == "adjusted": close = close.model_copy(update={"payload": {**close.payload, "price_basis": "ADJUSTED"}})
    elif mutation == "wrong-symbol": close = close.model_copy(update={"symbol": "2317"})
    elif mutation == "precomputed": p["adjustment_factor"] = 0.99
    elif mutation == "wrong-market": close = close.model_copy(update={"source": "TPEX_HISTORY"})
    action = action.model_copy(update={"payload": p})
    with pytest.raises(ValueError):
        derive_adjustment_factor(action, close, calendar=args["config"].calendar,
                                 cutoff=args["request"].analysis_cutoff, as_of=args["request"].end_date)


def test_combined_cash_stock_and_rights_factor_with_explicit_units(tmp_path):
    args, action, close = factor_case(tmp_path)
    action = action.model_copy(update={"payload": {
        **action.payload, "event_kind": "權息", "cash_dividend": 4, "stock_dividend_ratio": 10,
        "subscription_ratio": 20, "subscription_price_per_share": 50, "ratio_unit": "PERCENT",
    }})
    result = derive_adjustment_factor(action, close, calendar=args["config"].calendar,
                                      cutoff=args["request"].analysis_cutoff, as_of=args["request"].end_date)
    assert result.action.adjustment_factor == float(Fraction(700, 871))
    assert result.previous_close_hash == close.content_hash
    assert result.action.action_type.value == "RIGHTS_ISSUE"


def test_replay_rejects_config_or_engine_drift(tmp_path):
    args, _, _ = setup_case(tmp_path)
    snapshot = ingest_historical(**args)
    with pytest.raises(ValueError, match="hash mismatch"):
        evaluate_historical_snapshot(snapshot, args["config"].model_copy(update={"rs_20d": -2}))
    with pytest.raises(ValueError):
        HistoricalReplayConfig.model_validate({**args["config"].model_dump(), "engine_version": "future-v2"})
