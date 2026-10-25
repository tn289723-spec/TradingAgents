from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from tradingagents_tw.contracts import PriceSeries
from .backtest import BacktestStrategy, run_backtest
from .screener import ScreenSpec, screen_universe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradingagents-research")
    commands = parser.add_subparsers(dest="command", required=True)
    screen = commands.add_parser("screen", help="screen a JSON array of PriceSeries")
    screen.add_argument("--data", required=True, type=Path)
    screen.add_argument("--spec", required=True, type=Path)
    screen.add_argument("--as-of", required=True)
    backtest = commands.add_parser("backtest", help="backtest one JSON PriceSeries")
    backtest.add_argument("--data", required=True, type=Path)
    backtest.add_argument("--strategy", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "screen":
        raw = json.loads(args.data.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("screen --data must contain a JSON array")
        series = tuple(PriceSeries.model_validate(item) for item in raw)
        spec = ScreenSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
        result = screen_universe(series, spec, as_of=date.fromisoformat(args.as_of))
    else:
        data = PriceSeries.model_validate_json(args.data.read_text(encoding="utf-8"))
        strategy = BacktestStrategy.model_validate_json(args.strategy.read_text(encoding="utf-8"))
        result = run_backtest(data, strategy)
    print(json.dumps(
        [item.model_dump(mode="json") for item in result] if isinstance(result, tuple)
        else result.model_dump(mode="json"),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
