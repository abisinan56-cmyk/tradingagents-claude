"""ta-claude: TradingAgents on Claude, with replay, ensembles and honest backtests."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from datetime import date, timedelta

from dotenv import load_dotenv

DISCLAIMER = "Research output only. Not financial, investment or trading advice."


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--deep", help="Deep-tier model (managers). Default claude-opus-5-5")
    p.add_argument("--quick", help="Quick-tier model (analysts, trader). Default claude-opus-5-5")
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
    load_dotenv()  # .env in the current folder wins
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # then the repo's own .env
    ap = argparse.ArgumentParser(prog="ta-claude", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="Single analysis with a saved HTML report")
    r.add_argument("ticker")
    r.add_argument("--date", default=date.today().isoformat())
    r.add_argument("--no-replay", action="store_true", help="Do not record/replay LLM and data calls")
    r.add_argument("--plan", action="store_true", help="Add a deterministic trend and risk research plan")
    _common(r)

    e = sub.add_parser("ensemble", help="N independent runs, majority vote and agreement score")
    e.add_argument("ticker")
    e.add_argument("--date", default=date.today().isoformat())
    e.add_argument("-n", type=int, default=5)
    e.add_argument("--plan", action="store_true", help="Add a deterministic trend and risk research plan")
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
    src.add_argument("--quote", help="JSON file: symbol, price, source, captured_at, screen_time, change_pct, currency")
    src.add_argument("--price", type=float, help="Screen price, if no quote file")
    lv.add_argument("--source", default="", help="Where the price was read (URL or app)")
    lv.add_argument("--full", action="store_true",
                    help="Also attach a fresh analysis (keyless research pack; full agent run only if a key is set)")
    _common(lv)

    m = sub.add_parser("market", help="Show how a ticker is classified, without running anything")
    m.add_argument("tickers")

    plan = sub.add_parser("plan", help="Build a deterministic trend and risk research plan (no LLM calls)")
    plan.add_argument("ticker")
    plan.add_argument("--rating", choices=["Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"])
    plan.add_argument("--json", action="store_true", help="Print machine-readable output")

    strategy = sub.add_parser("strategy-backtest", help="Backtest deterministic 20/50 trend model (no LLM calls)")
    strategy.add_argument("ticker")
    strategy.add_argument("--start", required=True)
    strategy.add_argument("--end", required=True)
    strategy.add_argument("--fast-window", type=int, default=20)
    strategy.add_argument("--slow-window", type=int, default=50)
    strategy.add_argument("--cost-bps", type=float, default=10.0)
    strategy.add_argument("--json", action="store_true", help="Print machine-readable output")

    fx = sub.add_parser("fx-scan", help="Rank major FX technical research setups (no LLM calls by default)")
    fx.add_argument("--pairs", default=",".join(("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")),
                    help="Comma-separated Yahoo-style FX pairs")
    fx.add_argument("--with-news", action="store_true",
                    help="Attach news for the top directional candidate (keyless headlines; full agent run only if a key is set)")
    fx.add_argument("--json", action="store_true", help="Print machine-readable output")

    brief = sub.add_parser("fx-brief", help="Structured FX decision-support research brief (no LLM calls by default)")
    brief.add_argument("ticker", help="FX pair, e.g. EURUSD")
    brief.add_argument("--portfolio", help="Optional portfolio JSON for declared FX currency-overlap checks")
    brief.add_argument("--rating", choices=["Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"])
    brief.add_argument("--with-news", action="store_true",
                       help="Attach news (keyless headlines; full agent run only if a key is set)")
    brief.add_argument("--json", action="store_true", help="Print machine-readable output")

    suite = sub.add_parser("strategy-suite", help="Compare documented trend, mean-reversion, breakout and RSI strategies")
    suite.add_argument("ticker")
    suite.add_argument("--start", required=True)
    suite.add_argument("--end", required=True)
    suite.add_argument("--cost-bps", type=float, default=10.0)
    suite.add_argument("--json", action="store_true", help="Print machine-readable output")

    rs = sub.add_parser("research", help="Keyless research pack for the Claude session to analyse (no API key)")
    rs.add_argument("ticker")
    rs.add_argument("--date", default=date.today().isoformat())
    rs.add_argument("--json", action="store_true", help="Print machine-readable output")

    args = ap.parse_args(argv)

    from .markets import classify
    if args.cmd == "market":
        for t in args.tickers.split(","):
            print(json.dumps(asdict(classify(t)), indent=2))
        return 0

    if args.cmd == "live":
        return _live(args)

    if args.cmd in {"plan", "strategy-backtest", "strategy-suite", "fx-scan", "fx-brief"}:
        from .model import (backtest_strategy_suite, backtest_trend, build_fx_decision_brief, build_trade_plan,
                            fetch_daily_history, scan_fx, write_trade_plan_dashboard)
        if args.cmd == "strategy-suite":
            bars = fetch_daily_history(args.ticker, args.start, args.end)
            out = asdict(backtest_strategy_suite(args.ticker, bars, args.start, args.end, args.cost_bps))
            if args.json:
                print(json.dumps(out, indent=2))
            else:
                for result in out["results"]:
                    print(f"{result['strategy']}: {result['total_return_pct']:+.2f}% · drawdown {result['max_drawdown_pct']:.2f}% · "
                          f"buy-and-hold {result['buy_and_hold_return_pct']:+.2f}%")
                for warning in out["warnings"]:
                    print(f"Note: {warning}")
        elif args.cmd == "fx-brief":
            today = date.today()
            bars = fetch_daily_history(args.ticker, (today - timedelta(days=730)).isoformat(), today.isoformat())
            out = asdict(build_fx_decision_brief(args.ticker, bars, args.portfolio, args.rating))
            if args.with_news:
                if _has_key():
                    from .config import build_config
                    from . import runner
                    out["news_research"] = runner.run_report(out["pair"], today.isoformat(), build_config(),
                                                             use_replay=False)
                else:
                    out["news_research"] = _keyless_news(out["pair"])
            if args.json:
                print(json.dumps(out, indent=2))
            else:
                setup = out["setup"]
                print(f"{out['pair']} research brief · {setup['action']} · {out['market_regime']}")
                print(f"Reference entry {setup['entry_reference']} · stop {setup['stop_reference']} · target {setup['target_reference']}")
                candle = out["technical_analysis"]["last_candle"]
                print(f"Latest completed candle: {candle['direction']} · patterns: {', '.join(candle['patterns'])}")
                print("No-trade conditions: " + " ".join(out["no_trade_conditions"]))
                for warning in out["warnings"]:
                    print(f"Note: {warning}")
        elif args.cmd == "fx-scan":
            scan = scan_fx([pair.strip() for pair in args.pairs.split(",") if pair.strip()])
            out = asdict(scan)
            directional = next((candidate for candidate in scan.candidates if candidate["action"] != "flat"), None)
            if args.with_news:
                if directional is None:
                    out["news_research"] = {"status": "skipped", "reason": "No directional technical candidate."}
                elif _has_key():
                    from .config import build_config
                    from . import runner
                    out["news_research"] = runner.run_report(directional["ticker"], date.today().isoformat(),
                                                             build_config(), use_replay=False)
                else:
                    out["news_research"] = _keyless_news(directional["ticker"])
            if args.json:
                print(json.dumps(out, indent=2))
            else:
                candidate = directional or scan.candidates[0]
                print(f"Top research candidate: {candidate['ticker']} {candidate['action']} · "
                      f"trend strength {candidate['trend_strength']:.2f} · as of {candidate['as_of']}")
                print(f"Reference entry {candidate['entry_reference']} · stop {candidate['stop_reference']} · "
                      f"target {candidate['target_reference']} · model maximum notional {candidate['model_max_notional_pct']}%")
                if args.with_news:
                    news = out["news_research"]
                    print(f"News: {news.get('report_dir') or news.get('status') or str(len(news.get('news', []))) + ' headlines'}")
                for warning in scan.warnings:
                    print(f"Note: {warning}")
        elif args.cmd in {"plan", "strategy-backtest"}:
            if args.cmd == "plan":
                today = date.today().isoformat()
                bars = fetch_daily_history(args.ticker, (date.today().replace(year=date.today().year - 2)).isoformat(), today)
                trade_plan = build_trade_plan(args.ticker, bars, args.rating)
                out = {**asdict(trade_plan), "dashboard": write_trade_plan_dashboard(trade_plan)}
                if args.json:
                    print(json.dumps(out, indent=2))
                else:
                    print(f"{out['ticker']} {out['action']} ({out['confidence']}) · entry reference {out['entry_reference']}")
                    print(f"Dashboard: {out['dashboard']}")
                    for warning in out["warnings"]:
                        print(f"Note: {warning}")
            else:
                bars = fetch_daily_history(args.ticker, args.start, args.end)
                report = backtest_trend(args.ticker, bars, args.start, args.end, args.fast_window, args.slow_window, args.cost_bps)
                if args.json:
                    print(json.dumps(asdict(report), indent=2))
                else:
                    print(f"{report.ticker}: {report.total_return_pct:+.2f}% · buy-and-hold {report.buy_and_hold_return_pct:+.2f}% · ")
                    print(f"max drawdown {report.max_drawdown_pct:.2f}% · {report.trades} turnover events")
                    for warning in report.warnings:
                        print(f"Note: {warning}")
        print(DISCLAIMER, file=sys.stderr)
        return 0

    if args.cmd == "research" or (args.cmd in {"report", "ensemble"} and not _has_key()):
        # No key: the CLI gathers the data and the Claude session writes the agent analysis.
        pack = _research_pack(args.ticker, args.date)
        if args.cmd != "research":
            pack["warnings"].insert(0, f"No API key set: '{args.cmd}' returned the keyless research pack; "
                                       "the Claude session writes the TradingAgents analysis from it.")
        if args.json:
            print(json.dumps(pack, indent=2))
        else:
            print(f"{pack['ticker']} ({pack['market']}) keyless research pack · data through {pack['as_of']}")
            print(pack["technical_snapshot"] or "Technical snapshot unavailable.")
            for item in pack["news"]:
                print(f"News {item['date']}: {item['title']} ({item['source']})")
            for w in pack["warnings"]:
                print(f"Note: {w}")
        print(DISCLAIMER, file=sys.stderr)
        return 0

    if args.cmd == "backtest" and not _has_key():
        print("The agent backtest needs the optional key. For a keyless track record use "
              "`ta-claude strategy-suite <T> --start ... --end ...` or `strategy-backtest`.", file=sys.stderr)
        return 2

    from .config import build_config
    from . import runner

    cfg = build_config(args.deep, args.quick, args.debate_rounds, args.risk_rounds, effort=args.effort)
    analysts = args.analysts.split(",") if args.analysts else None

    if args.cmd == "report":
        out = runner.run_report(args.ticker, args.date, cfg, analysts, args.portfolio,
                                use_replay=not args.no_replay)
        if args.plan:
            out["trade_plan"] = _research_plan(out["ticker"], out["rating"])
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(f"{out['ticker']} ({out['market']}) {out['date']}: {out['rating']}")
            print(f"Report: {out['report_dir']}")
            if out.get("trade_plan"):
                print(f"Research plan: {out['trade_plan'].get('dashboard', out['trade_plan'].get('error'))}")
            for w in out["warnings"]:
                print(f"Note: {w}")
    elif args.cmd == "ensemble":
        res = runner.run_ensemble(args.ticker, args.date, cfg, args.n, analysts, args.portfolio)
        out = {**asdict(res), "confidence": res.confidence}
        if args.plan:
            out["trade_plan"] = _research_plan(res.ticker, res.rating)
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print(f"{res.ticker} {res.date}: {res.rating} · agreement {res.agreement:.0%} "
                  f"({res.confidence}) · votes {res.votes}")
            if res.report_dir:
                print(f"Report (majority member): {res.report_dir}")
            if out.get("trade_plan"):
                print(f"Research plan: {out['trade_plan'].get('dashboard', out['trade_plan'].get('error'))}")
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


def _has_key() -> bool:
    """The Anthropic key is optional; without it every command runs in keyless mode."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _research_pack(ticker: str, as_of: str) -> dict:
    from .research import build_research_pack
    return build_research_pack(ticker, as_of)


def _keyless_news(ticker: str) -> dict:
    from .research import CONNECTOR_STEPS, calendar_currencies, fetch_news
    try:
        news = fetch_news(ticker, date.today().isoformat())
    except Exception as exc:
        return {"mode": "keyless", "news": [], "warnings": [f"Yahoo news unavailable: {exc}"]}
    return {"mode": "keyless", "ticker": ticker, "news": news, "calendar_currencies": calendar_currencies(ticker),
            "connector_steps": CONNECTOR_STEPS}


def _research_plan(ticker: str, rating: str) -> dict:
    """Return a best-effort technical plan without hiding a completed LLM report."""
    from .model import build_trade_plan, fetch_daily_history, write_trade_plan_dashboard
    try:
        today = date.today()
        bars = fetch_daily_history(ticker, today.replace(year=today.year - 2).isoformat(), today.isoformat())
        plan = build_trade_plan(ticker, bars, rating)
        return {**asdict(plan), "dashboard": write_trade_plan_dashboard(plan)}
    except ValueError as exc:
        return {"error": str(exc), "warnings": ["No deterministic plan was generated."]}


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
        if _has_key():
            analysts = args.analysts.split(",") if args.analysts else None
            fresh = runner.run_report(market.symbol, date.today().isoformat(), cfg, analysts,
                                      args.portfolio, use_replay=False)
        else:
            fresh = _research_pack(market.symbol, date.today().isoformat())
    intraday = yahoo_intraday(market.symbol) if market.analysts else None
    check = assess(quote, intraday, latest_rating(market.symbol, cfg["memory_log_path"]))
    out = {**asdict(check), "fresh_run": fresh}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"{check.symbol} screen {quote.price} ({quote.source or 'screen'})")
        if check.yahoo:
            print(f"Yahoo last {check.yahoo['last']} at {check.yahoo['last_bar']} · "
                  f"screen vs Yahoo {check.screen_vs_yahoo_pct:+.2f}% · Yahoo lag "
                  f"{check.yahoo_lag_minutes} min · session {check.session_move_pct}%")
        if fresh and fresh.get("mode") == "keyless":
            print(f"Fresh keyless research pack: data through {fresh['as_of']}, {len(fresh['news'])} headlines")
        elif fresh:
            print(f"Fresh rating: {fresh['rating']} · report {fresh['report_dir']}")
        elif check.last_rating:
            print(f"Last rating: {check.last_rating['rating']} on {check.last_rating['date']}")
        for f in check.flags:
            print(f"Note: {f}")
    print(DISCLAIMER, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
