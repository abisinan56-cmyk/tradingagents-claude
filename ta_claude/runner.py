"""The four jobs: report, ensemble, backtest, and (via --portfolio) portfolio-aware runs."""
from __future__ import annotations

import json
import random
import shutil
import statistics
import tempfile
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.agents.rating import RATING_REVIEW
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.memory.log import TradingMemoryLog
from tradingagents.portfolio import PortfolioContext

from .config import HOME
from .cutoff import check_dates
from .markets import Market, backtest_analysts, classify
from .replay import replay

DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


def load_portfolio(path: str | None) -> PortfolioContext | None:
    if not path:
        return None
    return PortfolioContext.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def _replay_ctx(enabled: bool, market: Market, date: str, cfg: dict):
    if not enabled:
        return nullcontext()
    name = f"{market.symbol}_{date}_{cfg['quick_think_llm']}_{cfg['deep_think_llm']}.db".replace("/", "_")
    return replay(HOME / "replay" / name)


# --------------------------------------------------------------------------- report
def run_report(ticker: str, date: str, cfg: dict, analysts: list[str] | None = None,
               portfolio: str | None = None, use_replay: bool = True, html: bool = True) -> dict:
    market = classify(ticker)
    analysts = analysts or market.analysts
    with _replay_ctx(use_replay, market, date, cfg):
        graph = TradingAgentsGraph(analysts, config=cfg)
        state, rating = graph.propagate(market.symbol, date, market.asset_type,
                                        portfolio=load_portfolio(portfolio))
        path = graph.save_reports(state, market.symbol, html=html)
    return {"ticker": market.symbol, "market": market.name, "date": date, "rating": rating,
            "report_dir": str(path), "analysts": analysts, "warnings": market.warnings}


# ------------------------------------------------------------------------- ensemble
@dataclass
class EnsembleResult:
    ticker: str
    date: str
    rating: str
    agreement: float
    votes: dict[str, int]
    report_dir: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        return "high" if self.agreement >= 0.8 else "medium" if self.agreement >= 0.6 else "low"


def run_ensemble(ticker: str, date: str, cfg: dict, n: int = 5, analysts: list[str] | None = None,
                 portfolio: str | None = None) -> EnsembleResult:
    """Run the pipeline n times independently and take a majority vote.

    Each member reads a copy of the memory log (so it sees past lessons) but writes
    to its own copy, so n runs do not leave n entries. The consensus decision is
    recorded once in the real log afterwards. Replay is off here: identical cached
    answers would make every member agree by construction.
    """
    market = classify(ticker)
    analysts = analysts or market.analysts
    pf = load_portfolio(portfolio)
    main = TradingAgentsGraph(analysts, config=cfg)
    main.settle_pending(market.symbol)  # settle once, not once per member

    main_log = Path(cfg["memory_log_path"])
    members, work = [], Path(tempfile.mkdtemp(prefix="ta-ensemble-"))
    try:
        for i in range(n):
            log_copy = work / f"member{i}.md"
            if main_log.exists():
                shutil.copy(main_log, log_copy)
            member_cfg = {**cfg, "memory_log_path": str(log_copy)}
            state, rating = TradingAgentsGraph(analysts, config=member_cfg).propagate(
                market.symbol, date, market.asset_type, portfolio=pf)
            members.append((state, rating))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    votes = Counter(r for _, r in members)
    tradeable = Counter({r: c for r, c in votes.items() if r != RATING_REVIEW})
    rating, count = (tradeable or votes).most_common(1)[0]
    winner_state = next(s for s, r in members if r == rating)

    report_dir = None
    if rating != RATING_REVIEW:
        main.memory_log.store_decision(ticker=market.symbol, trade_date=date,
                                       final_trade_decision=winner_state.get("final_trade_decision", ""),
                                       rating=rating)
        report_dir = str(main.save_reports(winner_state, market.symbol))
    return EnsembleResult(market.symbol, date, rating, count / n, dict(votes), report_dir, market.warnings)


# ------------------------------------------------------------------------- backtest
@dataclass
class BacktestReport:
    cells: int
    scored: int
    pending: int
    cost_bps: float
    strategy_mean: float | None = None
    strategy_ci: tuple[float, float] | None = None
    always_long_mean: float | None = None
    benchmark_mean: float | None = None
    random_mean: float | None = None
    hit_rate: float | None = None
    by_rating: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        pct = lambda x: "n/a" if x is None else f"{x:+.2%}"
        lines = [f"Cells: {self.cells} · scored: {self.scored} · pending: {self.pending} · "
                 f"round-trip cost: {self.cost_bps:g} bps"]
        if self.scored:
            ci = (f" (95% CI {pct(self.strategy_ci[0])} to {pct(self.strategy_ci[1])})"
                  if self.strategy_ci else "")
            lines += [
                f"Strategy, net of costs: {pct(self.strategy_mean)} per decision{ci}",
                f"Hit rate on directional calls: {'n/a' if self.hit_rate is None else f'{self.hit_rate:.0%}'}",
                f"Baseline always long: {pct(self.always_long_mean)}",
                f"Baseline benchmark: {pct(self.benchmark_mean)}",
                f"Baseline random direction (net): {pct(self.random_mean)}",
                "By rating: " + ", ".join(f"{k} n={v['n']} raw {pct(v['raw'])}"
                                          for k, v in self.by_rating.items()),
            ]
            if self.strategy_ci and self.strategy_ci[0] <= 0 <= self.strategy_ci[1]:
                lines.append("The CI spans zero: no evidence of an edge at this sample size.")
        lines += self.notes
        return "\n".join(lines)


def _pct(text: str | None) -> float | None:
    try:
        return float((text or "").strip().rstrip("%")) / 100
    except ValueError:
        return None


def score_log(log_path: Path, cost_bps: float = 10.0, seed: int = 7) -> BacktestReport:
    entries = TradingMemoryLog({"memory_log_path": str(log_path)}).load_entries()
    cost = cost_bps / 10_000
    rows = []
    for e in entries:
        raw, alpha = _pct(e.get("raw")), _pct(e.get("alpha"))
        if e["pending"] or e["rating"] == RATING_REVIEW or raw is None:
            continue
        d = DIRECTION.get(e["rating"], 0)
        rows.append({"rating": e["rating"], "d": d, "raw": raw,
                     "bench": raw - alpha if alpha is not None else None,
                     "net": d * raw - (cost if d else 0.0)})
    rep = BacktestReport(cells=len(entries), scored=len(rows),
                         pending=sum(e["pending"] for e in entries), cost_bps=cost_bps)
    if not rows:
        return rep

    nets = [r["net"] for r in rows]
    rep.strategy_mean = statistics.fmean(nets)
    rng = random.Random(seed)
    if len(nets) >= 5:
        boots = sorted(statistics.fmean(rng.choices(nets, k=len(nets))) for _ in range(2000))
        rep.strategy_ci = (boots[49], boots[1949])
    directional = [r for r in rows if r["d"]]
    if directional:
        rep.hit_rate = sum(r["d"] * r["raw"] > 0 for r in directional) / len(directional)
    rep.always_long_mean = statistics.fmean(r["raw"] - cost for r in rows)
    benches = [r["bench"] for r in rows if r["bench"] is not None]
    rep.benchmark_mean = statistics.fmean(benches) if benches else None
    rep.random_mean = statistics.fmean(
        statistics.fmean(rng.choice((1, -1)) * r["raw"] - cost for r in rows) for _ in range(500))
    for rating in dict.fromkeys(r["rating"] for r in rows):
        raws = [r["raw"] for r in rows if r["rating"] == rating]
        rep.by_rating[rating] = {"n": len(raws), "raw": statistics.fmean(raws)}
    if rep.scored < 30:
        rep.notes.append(f"Only {rep.scored} scored decisions: too few to conclude anything.")
    return rep


def run_backtest_job(tickers: list[str], start: str, end: str, every: int, cfg: dict,
                     cost_bps: float = 10.0, allow_contaminated: bool = False,
                     run_id: str | None = None, portfolio: str | None = None,
                     progress=None) -> tuple[BacktestReport, str]:
    from tradingagents.backtest import iter_grid, run_backtest

    dates = iter_grid(start, end, every_n_days=every)
    notes = check_dates(dates, [cfg["quick_think_llm"], cfg["deep_think_llm"]], allow_contaminated)

    markets = [classify(t) for t in tickers]
    by_pipeline: dict[tuple, list[Market]] = {}
    for m in markets:  # one sweep per (asset type, analyst set) the tickers need
        by_pipeline.setdefault((m.asset_type, tuple(backtest_analysts(m))), []).append(m)

    run_id = run_id or f"bt_{start}_{end}_{every}d"
    logs, failures = [], []
    for (asset_type, analysts), group in by_pipeline.items():
        result = run_backtest([m.symbol for m in group], dates, cfg, asset_type=asset_type,
                              portfolio=load_portfolio(portfolio), selected_analysts=analysts,
                              run_id=f"{run_id}_{asset_type}_{'-'.join(analysts)}", progress=progress)
        logs.append(result.log_path)
        failures += result.failures

    merged = Path(cfg["results_dir"]) / "backtest" / f"{run_id}_merged.md"
    merged.parent.mkdir(parents=True, exist_ok=True)
    sep = TradingMemoryLog._SEPARATOR
    merged.write_text(sep.join(p.read_text(encoding="utf-8").strip() for p in logs if p.exists()) + sep,
                      encoding="utf-8")

    rep = score_log(merged, cost_bps)
    rep.notes = notes + [w for m in markets for w in m.warnings] + rep.notes
    if failures:
        rep.notes.append(f"{len(failures)} cell(s) failed; first: {failures[0]}")
    rep.notes.append("Social feeds are excluded from backtests (fetched as of today, not the run date).")
    return rep, str(merged)
