from datetime import date, timedelta
import json

import pytest

from tradingagents_tw.contracts import PriceBar, PriceBasis, PriceSeries
from tradingagents_tw.research import (
    BacktestStrategy, IndicatorKind, IndicatorSpec, ScreenRule, ScreenSpec,
    calculate_indicators, run_backtest, screen_universe,
)
from tradingagents_tw.research.cli import main


def series(closes, opens=None, volumes=None, basis=PriceBasis.RAW):
    opens = opens or closes
    volumes = volumes or [100] * len(closes)
    start = date(2026, 1, 2)
    bars = tuple(
        PriceBar(
            symbol="2330", trade_date=start + timedelta(days=i),
            open=float(opens[i]), high=float(max(opens[i], closes[i]) + 1),
            low=float(min(opens[i], closes[i]) - 1), close=float(closes[i]),
            volume=float(volumes[i]), price_basis=basis,
            adjustment_method="fixture" if basis is PriceBasis.ADJUSTED else None,
            adjustment_version="v1" if basis is PriceBasis.ADJUSTED else None,
        ) for i in range(len(closes))
    )
    return PriceSeries(
        symbol="2330", price_basis=basis,
        adjustment_method="fixture" if basis is PriceBasis.ADJUSTED else None,
        adjustment_version="v1" if basis is PriceBasis.ADJUSTED else None,
        adjustment_as_of=bars[-1].trade_date if basis is PriceBasis.ADJUSTED else None,
        bars=bars,
    )


def test_indicators_are_causal_and_parameterized():
    data = series([10, 11, 12, 15], volumes=[100, 100, 200, 300])
    specs = (
        IndicatorSpec(kind=IndicatorKind.SMA, window=2),
        IndicatorSpec(kind=IndicatorKind.RETURN, window=2),
        IndicatorSpec(kind=IndicatorKind.VOLUME_RATIO, window=2),
        IndicatorSpec(kind=IndicatorKind.RSI, window=2),
    )
    values = calculate_indicators(data, specs)
    assert values["SMA_2"][:1] == (None,)
    assert values["SMA_2"][2] == 11.5
    assert values["RETURN_2"][2] == pytest.approx(0.2)
    assert values["VOLUME_RATIO_2"][2] == pytest.approx(2.0)
    assert values["RSI_2"][2] == pytest.approx(100.0)
    # Appending a future bar cannot change any earlier indicator value.
    longer = calculate_indicators(series([10, 11, 12, 15, 100], volumes=[100, 100, 200, 300, 400]), specs)
    for key in values:
        assert longer[key][:-1] == values[key]


def test_screen_uses_custom_indicator_windows_and_exact_session():
    data = series([10, 11, 12], volumes=[100, 100, 200])
    spec = ScreenSpec(
        indicators=(
            IndicatorSpec(kind=IndicatorKind.RETURN, window=2),
            IndicatorSpec(kind=IndicatorKind.VOLUME_RATIO, window=2),
        ),
        rules=(
            ScreenRule(indicator="RETURN_2", operator=">=", threshold=0.19),
            ScreenRule(indicator="VOLUME_RATIO_2", operator=">=", threshold=2),
        ),
    )
    matches = screen_universe((data,), spec, as_of=data.bars[-1].trade_date)
    assert len(matches) == 1
    assert matches[0].indicator_values == {"RETURN_2": pytest.approx(0.2), "VOLUME_RATIO_2": 2.0}
    with pytest.raises(ValueError, match="requested session"):
        screen_universe((data,), spec, as_of=date(2026, 1, 10))


def test_screen_can_match_a_user_defined_moving_average_cross():
    data = series([10, 10, 10, 11])
    spec = ScreenSpec(
        indicators=(
            IndicatorSpec(kind=IndicatorKind.SMA, window=2),
            IndicatorSpec(kind=IndicatorKind.SMA, window=3),
        ),
        rules=(ScreenRule(indicator="SMA_2", operator="crosses_above", compare_to="SMA_3"),),
    )
    matches = screen_universe((data,), spec, as_of=data.bars[-1].trade_date)
    assert len(matches) == 1
    assert matches[0].matched_rules == ("SMA_2crosses_aboveSMA_3",)


def test_backtest_fills_signals_on_next_session_open_and_applies_costs():
    data = series(
        [10, 10, 12, 13, 11, 10, 10],
        opens=[10, 10, 12, 13, 11, 9, 10],
    )
    strategy = BacktestStrategy(
        indicators=(IndicatorSpec(kind=IndicatorKind.RETURN, window=2),),
        entry_rules=(ScreenRule(indicator="RETURN_2", operator=">=", threshold=0.19),),
        exit_rules=(ScreenRule(indicator="RETURN_2", operator="<=", threshold=0),),
        commission_bps=10, sell_tax_bps=30, slippage_bps=0,
    )
    report = run_backtest(data, strategy)
    trade = report.trades[0]
    assert trade.entry_signal_date == data.bars[2].trade_date
    assert trade.entry_date == data.bars[3].trade_date
    assert trade.entry_price == 13
    assert trade.exit_signal_date == data.bars[4].trade_date
    assert trade.exit_date == data.bars[5].trade_date
    assert trade.exit_price == 9
    assert trade.net_return < trade.gross_return
    assert report.trade_count == 1


def test_open_position_estimated_exit_includes_sell_side_slippage():
    data = series([100, 100, 100, 100], opens=[100, 100, 100, 100])
    strategy = BacktestStrategy(
        indicators=(IndicatorSpec(kind=IndicatorKind.RETURN, window=2),),
        entry_rules=(ScreenRule(indicator="RETURN_2", operator=">=", threshold=0),),
        exit_rules=(ScreenRule(indicator="RETURN_2", operator=">", threshold=10),),
        commission_bps=0, sell_tax_bps=0, slippage_bps=100,
    )

    report = run_backtest(data, strategy)

    assert report.open_position is not None
    assert report.open_position.mark_price == 100
    assert report.open_position.unrealized_net_return == pytest.approx(99 / 101 - 1)
    assert report.total_return == pytest.approx(report.open_position.unrealized_net_return)


def test_research_rejects_adjusted_series_to_avoid_future_adjustment_leakage():
    adjusted = series([10, 11, 12], basis=PriceBasis.ADJUSTED)
    spec = (IndicatorSpec(kind=IndicatorKind.SMA, window=2),)
    with pytest.raises(ValueError, match="RAW"):
        calculate_indicators(adjusted, spec)


def test_screen_cli_reads_json_and_emits_deterministic_json(tmp_path, capsys):
    data = series([10, 11, 12], volumes=[100, 100, 200])
    data_path = tmp_path / "universe.json"
    data_path.write_text(json.dumps([data.model_dump(mode="json")]), encoding="utf-8")
    spec = ScreenSpec(
        indicators=(IndicatorSpec(kind=IndicatorKind.RETURN, window=2),),
        rules=(ScreenRule(indicator="RETURN_2", operator=">", threshold=0.1),),
    )
    spec_path = tmp_path / "screen.json"
    spec_path.write_text(spec.model_dump_json(), encoding="utf-8")
    assert main(["screen", "--data", str(data_path), "--spec", str(spec_path),
                 "--as-of", str(data.bars[-1].trade_date)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result[0]["symbol"] == "2330"
    assert result[0]["indicator_values"]["RETURN_2"] == pytest.approx(0.2)

