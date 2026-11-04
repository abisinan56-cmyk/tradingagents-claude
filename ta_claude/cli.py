"""ta-claude: TradingAgents on Claude, with replay, ensembles and honest backtests."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date

from dotenv import load_dotenv

DISCLAIMER = "Research output only. Not financial, investment or trading advice."


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--deep", help="Deep-tier model (managers). Default claude-opus-5-5")
    p.add_argument("--quick", help="Quick-tier model (analysts, trader). Default claude-sonnet-5")
    p.add_argument("--debate-rounds", type=int, default=1)
    p.add_argument("--risk-rounds", type=int, default=1)
    p.add_argument("--effort", choices=["low", "medium", "high"])
    p.add_argument("--analysts", help="Comma list: market,social,news,fundamentals (default: per market)")
    p.add_argument("--portfolio", help="JSON file with cash, currency and positions")
    p.add_argument("--json", action="store_true", help="Print machine-readable output")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="ta-claude", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="Single analysis with a saved HTML report")
    r.add_argument("ticker")
    r.add_argument("--date", default=date.today().isoformat())
    r.add_argument("--no-replay", action="store_true", help="Do not record/replay LLM and data calls")
    _common(r)

    e = sub.add_parser("ensemble", help="N independent runs, majority vote and agreement score")
    e.add_argument("ticker")
    e.add_argument("--date", default=date.today().isoformat())
    e.add_argument("-n", type=int, default=5)
    _common(e)

    b = sub.add_parser("backtest", help="Grid backtest after the model cutoff, with baselines and costs")
    b.add_argument("tickers", help="Comma list, e.g. NVDA,EMAAR.AE,EURUSD,BTC-USD")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.add_argument("--every", type=int, default=7, help="Days between decisions")
    b.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip cost in basis points")
    b.add_argument("--run-id")
    b.add_argument("--allow-contaminated", action="store_true",
                   help="Allow dates before the model cutoff (results flagged)")
    _common(b)

    m = sub.add_parser("market", help="Show how a ticker is classified, without running anything")
    m.add_argument("tickers")

    args = ap.parse_args(argv)

    from .markets import classify
    if args.cmd == "market":
        for t in args.tickers.split(","):
            print(json.dumps(asdict(classify(t)), indent=2))
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 2

    from .config import build_config
    from . import runner

    cfg = build_config(args.deep, args.quick, args.debate_rounds, args.risk_rounds, effort=args.effort)
    analysts = args.analysts.split(",") if args.analysts else None

    if args.cmd == "report":
        out = runner.run_report(args.ticker, args.date, cfg, analysts, args.portfolio,
                                use_replay=not args.no_replay)
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(f"{out['ticker']} ({out['market']}) {out['date']}: {out['rating']}")
            print(f"Report: {out['report_dir']}")
            for w in out["warnings"]:
                print(f"Note: {w}")
    elif args.cmd == "ensemble":
        res = runner.run_ensemble(args.ticker, args.date, cfg, args.n, analysts, args.portfolio)
        if args.json:
            print(json.dumps({**asdict(res), "confidence": res.confidence}, indent=2))
        else:
            print(f"{res.ticker} {res.date}: {res.rating} · agreement {res.agreement:.0%} "
                  f"({res.confidence}) · votes {res.votes}")
            if res.report_dir:
                print(f"Report (majority member): {res.report_dir}")
            for w in res.warnings:
                print(f"Note: {w}")
    elif args.cmd == "backtest":
        progress = None if args.json else (lambda i, n, t, d: print(f"[{i}/{n}] {t} {d}", file=sys.stderr))
        rep, log = runner.run_backtest_job(args.tickers.split(","), args.start, args.end, args.every,
                                           cfg, args.cost_bps, args.allow_contaminated, args.run_id,
                                           args.portfolio, progress)
        if args.json:
            print(json.dumps({**asdict(rep), "log": log}, indent=2, default=str))
        else:
            print(rep.render())
            print(f"Log: {log}")
    print(DISCLAIMER, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
