"""
Dependency checker — runs after each price refresh.

Loads all open recommendations that have dependency rows, evaluates
each dependency against current data, and supersedes any whose
premise has been invalidated. Superseded recs trigger re-evaluation
via the orchestrator for the same ticker + agent.
"""

import time
import sqlite3
from pathlib import Path

import agent_db

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"


def _latest_prices() -> dict[str, float]:
    """Return {ticker: price} from the most recent holding_day rows."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    day = conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute(
        "SELECT ticker, price FROM holding_day WHERE day=?", (day,)
    ).fetchall()
    conn.close()
    return {r["ticker"]: float(r["price"]) for r in rows if r["price"]}


def _latest_thesis_versions() -> dict[str, int]:
    """Return {ticker: version} for the most recent active thesis per ticker."""
    conn = agent_db._connect()
    rows = conn.execute(
        """SELECT ticker, MAX(version) as version
           FROM investment_theses
           WHERE status='active'
           GROUP BY ticker"""
    ).fetchall()
    conn.close()
    return {r["ticker"]: int(r["version"]) for r in rows}


def _check_price(dep: dict, prices: dict[str, float]) -> str | None:
    """Return violation reason string, or None if still valid."""
    ticker = dep["dependency_key"]
    current = prices.get(ticker)
    if current is None:
        return None  # can't check — no price data, leave open
    try:
        original = float(dep["original_value"])
    except (TypeError, ValueError):
        return None
    tolerance = dep.get("tolerance") or 0.02
    pct_move = abs(current - original) / original if original else 0
    if pct_move > tolerance:
        direction = "up" if current > original else "down"
        return (
            f"Price moved {pct_move * 100:.1f}% {direction} "
            f"(was ${original:.2f}, now ${current:.2f}; tolerance ±{tolerance * 100:.0f}%)"
        )
    return None


def _check_thesis_version(dep: dict, versions: dict[str, int]) -> str | None:
    ticker = dep["dependency_key"]
    current_version = versions.get(ticker)
    if current_version is None:
        return None
    try:
        original_version = int(dep["original_value"])
    except (TypeError, ValueError):
        return None
    if current_version != original_version:
        return (
            f"Thesis updated from v{original_version} to v{current_version}"
        )
    return None


def _trigger_reeval(ticker: str, agent_type: str) -> None:
    """Fire the original agent via the full orchestrator pipeline (agent → Critic → persist)."""
    try:
        from agents.snapshot import build_portfolio_snapshot
        from agents.triggers import TriggerEvent
        from agents.orchestrator import run_agents

        snapshot = build_portfolio_snapshot()
        event = TriggerEvent(
            trigger_type="dep_superseded",
            agent_type=agent_type,
            ticker=ticker,
        )
        recs = run_agents(snapshot, [event])
        print(f"[DepChecker] Re-eval {agent_type}/{ticker}: {len(recs)} new rec(s)")
    except Exception as e:
        print(f"[DepChecker] Re-eval failed for {agent_type}/{ticker}: {e}")


def check_all_dependencies() -> int:
    """
    Check every open recommendation's dependencies against current data.
    Supersedes those whose premise changed; triggers re-evaluation.
    Returns the count of recs superseded.
    """
    recs = agent_db.get_open_recs_with_deps()
    if not recs:
        return 0

    prices = _latest_prices()
    versions = _latest_thesis_versions()

    superseded_count = 0
    reeval_queue: list[tuple[str, str]] = []  # (ticker, agent_type)

    for rec in recs:
        rec_id = rec["id"]
        ticker = rec["ticker"]
        agent_type = rec.get("agent_type") or ""

        violated_reasons = []
        for dep in rec["deps"]:
            dtype = dep["dependency_type"]
            if dtype == "PRICE":
                reason = _check_price(dep, prices)
            elif dtype == "THESIS_VERSION":
                reason = _check_thesis_version(dep, versions)
            else:
                reason = None
            if reason:
                violated_reasons.append(reason)

        if violated_reasons:
            combined = "; ".join(violated_reasons)
            agent_db.supersede_recommendation(rec_id, combined)
            superseded_count += 1
            print(f"[DepChecker] Superseded rec {rec_id} ({ticker}/{rec['action']}): {combined}")
            if agent_type and (ticker, agent_type) not in reeval_queue:
                reeval_queue.append((ticker, agent_type))

    for ticker, agent_type in reeval_queue:
        _trigger_reeval(ticker, agent_type)

    if superseded_count:
        print(f"[DepChecker] {superseded_count} recommendation(s) superseded, "
              f"{len(reeval_queue)} re-eval(s) triggered.")
    return superseded_count
