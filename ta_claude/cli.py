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
    try:
        return _main(argv)
    except ValueError as exc:  # ADX refusal, cutoff guard, bad dates: a message, not a traceback
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None = None) -> int:
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

    lv = sub.add_parser("live", help="Check a price read off your screen against Yahoo and the last rating")
    lv.add_argument("ticker")
    src = lv.add_mutually_exclusive_group(required=True)
    src.add_argument("--quote", help="JSON file: symbol, price, source, captured_at, change_pct, currency")
    src.add_argument("--price", type=float, help="Screen price, if no quote file")
    lv.add_argument("--source", default="", help="Where the price was read (URL or app)")
    lv.add_argument("--full", action="store_true", help="Also run a fresh multi-agent analysis (minutes, costs API)")
    _common(lv)

    m = sub.add_parser("market", help="Show how a ticker is classified, without running anything")
    m.add_argument("tickers")

    args = ap.parse_args(argv)

    from .markets import classify
    if args.cmd == "market":
        for t in args.tickers.split(","):
            print(json.dumps(asdict(classify(t)), indent=2))
        return 0

    if args.cmd == "live":
        return _live(args)

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


def _live(args) -> int:
    from .config import build_config
    from .live import LiveQuote, assess, latest_rating, yahoo_intraday
    from .markets import classify
    from . import runner

    market = classify(args.ticker)
    quote = (LiveQuote.load(args.quote) if args.quote
             else LiveQuote(market.symbol, args.price, source=args.source))
    quote.symbol = market.symbol
    cfg = build_config(args.deep, args.quick, args.debate_rounds, args.risk_rounds, effort=args.effort)
    fresh = None
    if args.full:
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set; --full needs it.", file=sys.stderr)
            return 2
        analysts = args.analysts.split(",") if args.analysts else None
        fresh = runner.run_report(market.symbol, date.today().isoformat(), cfg, analysts,
                                  args.portfolio, use_replay=False)
    intraday = yahoo_intraday(market.symbol) if market.analysts else None
    check = assess(quote, intraday, latest_rating(market.symbol, cfg["memory_log_path"]))
    out = {**asdict(check), "fresh_run": fresh}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"{check.symbol} screen {quote.price} ({quote.source or 'screen'})")
        if check.yahoo:
            print(f"Yahoo last {check.yahoo['last']} at {check.yahoo['last_bar']} · "
                  f"screen vs Yahoo {check.screen_vs_yahoo_pct:+.2f}% · session {check.session_move_pct}%")
        if fresh:
            print(f"Fresh rating: {fresh['rating']} · report {fresh['report_dir']}")
        elif check.last_rating:
            print(f"Last rating: {check.last_rating['rating']} on {check.last_rating['date']}")
        for f in check.flags:
            print(f"Note: {f}")
    print(DISCLAIMER, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
