from __future__ import annotations
"""
Dependency checker — runs after each price refresh.

Loads all open recommendations that have dependency rows, evaluates
each dependency against current data, and supersedes any whose
premise has been invalidated. Superseded recs trigger re-evaluation
via the orchestrator for the same ticker + agent.
"""

import json
import time
import sqlite3
from datetime import date as _date
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


def _latest_weights() -> dict[str, float]:
    """Return {ticker: weight_pct} from the most recent holding_day rows."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    day = conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute(
        "SELECT ticker, weight_pct FROM holding_day WHERE day=?", (day,)
    ).fetchall()
    conn.close()
    return {r["ticker"]: float(r["weight_pct"]) for r in rows if r["weight_pct"] is not None}


def _latest_macro_scores() -> dict[str, dict]:
    """Return {ticker: scores_dict} from holding_macro_scores."""
    conn = agent_db._connect()
    rows = conn.execute("SELECT ticker, scores FROM holding_macro_scores").fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[r["ticker"]] = json.loads(r["scores"]) if r["scores"] else {}
        except Exception:
            pass
    return result


def _latest_financial_periods() -> dict[str, str]:
    """Return {ticker: newest period_end} from company_financials."""
    conn = agent_db._connect()
    rows = conn.execute(
        "SELECT ticker, MAX(period_end) as period_end FROM company_financials GROUP BY ticker"
    ).fetchall()
    conn.close()
    return {r["ticker"]: r["period_end"] for r in rows if r["period_end"]}


def _check_position_weight(dep: dict, weights: dict[str, float]) -> str | None:
    ticker = dep["dependency_key"]
    current = weights.get(ticker)
    if current is None:
        return None
    try:
        original = float(dep["original_value"])
    except (TypeError, ValueError):
        return None
    tolerance = dep.get("tolerance") or 2.0
    diff_pp = abs(current - original)
    if diff_pp > tolerance:
        direction = "increased" if current > original else "decreased"
        return (
            f"Portfolio weight {direction} by {diff_pp:.1f}pp "
            f"(was {original:.1f}%, now {current:.1f}%; tolerance ±{tolerance:.1f}pp)"
        )
    return None


def _check_macro_state(dep: dict, macro: dict[str, dict]) -> str | None:
    ticker = dep["dependency_key"]
    current_scores = macro.get(ticker)
    if not current_scores:
        return None
    try:
        original_scores = json.loads(dep["original_value"]) if dep["original_value"] else {}
    except Exception:
        return None
    tolerance = dep.get("tolerance") or 15.0
    violations = []
    for dim, orig_val in original_scores.items():
        curr_val = current_scores.get(dim)
        if curr_val is None or orig_val is None:
            continue
        try:
            diff = abs(float(curr_val) - float(orig_val))
        except (TypeError, ValueError):
            continue
        if diff > tolerance:
            violations.append(f"{dim} shifted {diff:.0f}pts (was {orig_val}, now {curr_val})")
    if violations:
        return f"Macro state changed: {'; '.join(violations)}"
    return None


def _check_financial_period(dep: dict, periods: dict[str, str]) -> str | None:
    ticker = dep["dependency_key"]
    newest = periods.get(ticker)
    if not newest:
        return None
    original = dep.get("original_value") or ""
    if newest > original:
        return f"New financial period available (was {original!r}, now {newest!r})"
    return None


def _check_option_expiration(dep: dict, _unused) -> str | None:
    """Supersede when the option expiration date has passed.

    dependency_key = ticker (or contract_id)
    original_value = option expiration date as YYYY-MM-DD ISO string
    """
    expiry_str = dep.get("original_value") or ""
    if not expiry_str:
        return None
    try:
        expiry = _date.fromisoformat(expiry_str)
    except ValueError:
        return None
    today = _date.today()
    if today >= expiry:
        return f"Option expired on {expiry_str}"
    days_left = (expiry - today).days
    if days_left <= 3:
        return f"Option expiring in {days_left} day(s) ({expiry_str}) — re-evaluate"
    return None


# Alias: OPTION_IV previously did expiration check; keep alias so existing deps still work.
# True IV check uses option_quote_snapshots table (stub until populated).
_check_option_iv = _check_option_expiration  # backwards compat alias


def _check_option_iv_true(dep: dict, _unused) -> str | None:
    """Supersede if stored IV dropped by > 20% from the value when rec was made.

    dependency_key = ticker
    original_value = IV at time of recommendation
    threshold = 0.20 (20% drop)

    Stub: returns None until option_quote_snapshots is populated.
    """
    ticker = dep.get("dependency_key")
    stored_iv = dep.get("original_value")
    if not ticker or not stored_iv:
        return None
    try:
        orig_iv = float(stored_iv)
    except (TypeError, ValueError):
        return None
    threshold = float(dep.get("threshold") or 0.20)
    # Query latest snapshot
    snap = agent_db.get_latest_option_snapshot(ticker, dep.get("strike"), dep.get("expiration"))
    if snap is None:
        return None  # stub: no data yet
    current_iv = snap.get("iv")
    if current_iv is None:
        return None
    drop = (orig_iv - float(current_iv)) / orig_iv if orig_iv else 0
    if drop > threshold:
        return (
            f"IV dropped {drop * 100:.0f}% from {orig_iv:.2f} to {current_iv:.2f} "
            f"(threshold {threshold * 100:.0f}%)"
        )
    return None


def _check_earnings_date(dep: dict, periods: dict[str, str]) -> str | None:
    """Supersede when estimated earnings have passed or are within 7 days.

    dependency_key = ticker
    original_value = estimated earnings date (period_end + 45 days at rec creation)
    Falls back to FINANCIAL_PERIOD logic if no original_value is set.
    """
    ticker = dep["dependency_key"]
    # 0075: prefer authoritative earnings_dates table over the heuristic original_value
    stored_row = agent_db.get_latest_earnings_date(ticker)
    if stored_row:
        earnings_str = stored_row["event_date"]
        confidence = stored_row.get("confidence", "estimated")
        # Tighter window for authoritative dates (7d), wider for heuristic (14d)
        imminence_days = 7 if confidence == "provider_estimated" else 14
    else:
        earnings_str = dep.get("original_value") or ""
        imminence_days = 7
    if not earnings_str:
        # Fall back: new period available?
        newest = periods.get(ticker)
        return f"New financial period available ({newest!r})" if newest else None
    try:
        earnings_date = _date.fromisoformat(earnings_str)
    except ValueError:
        return None
    today = _date.today()
    days_to = (earnings_date - today).days
    if today > earnings_date:
        return f"Estimated earnings date {earnings_str} has passed — new data expected"
    if days_to <= imminence_days:
        return f"Earnings imminent in {days_to} day(s) ({earnings_str}) — re-evaluate"
    # Also check if a newer period already landed
    newest = periods.get(ticker)
    if newest and newest > earnings_str[:10]:
        return f"New financial period available (earnings date was {earnings_str})"
    return None


# ── Stub handlers for dependency types that require data not yet in DB ────────

def _check_event_calendar(dep: dict, _unused) -> str | None:
    """Check if a relevant event has passed or moved inside the window.

    Queries event_calendar for ticker/event_type. Stub: returns None until populated.
    """
    ticker = dep.get("dependency_key")
    event_type = dep.get("event_type", "earnings")
    events = agent_db.get_events_for_ticker(ticker, event_type) if ticker else []
    if not events:
        # Stub: no event_calendar data yet
        return None
    today = _date.today()
    for evt in events:
        try:
            evt_date = _date.fromisoformat(evt["event_date"])
        except (ValueError, TypeError):
            continue
        days_to = (evt_date - today).days
        if today > evt_date:
            return f"Event {event_type!r} for {ticker} has passed ({evt['event_date']})"
        if days_to <= 7:
            return f"Event {event_type!r} imminent in {days_to} day(s) ({evt['event_date']})"
    return None


def _check_option_liquidity(dep: dict, _unused) -> str | None:
    """Supersede if the bid/ask spread has widened beyond threshold.

    Queries option_quote_snapshots. Stub: returns None until populated.
    """
    ticker = dep.get("dependency_key")
    threshold = float(dep.get("threshold") or 0.15)
    if not ticker:
        return None
    snap = agent_db.get_latest_option_snapshot(ticker, dep.get("strike"), dep.get("expiration"))
    if snap is None:
        return None  # stub: no data yet
    spread = snap.get("spread_pct")
    if spread is not None and float(spread) > threshold:
        return (
            f"Option spread {float(spread) * 100:.0f}% exceeds threshold "
            f"{threshold * 100:.0f}% — liquidity degraded"
        )
    return None


def _check_estimate_revision(dep: dict, _unused) -> str | None:
    """Supersede if analyst estimate has moved more than threshold.

    Queries estimate_history. Stub: returns None until populated.
    """
    ticker = dep.get("dependency_key")
    stored_estimate = dep.get("original_value")
    threshold = float(dep.get("threshold") or 0.10)
    if not ticker or not stored_estimate:
        return None
    try:
        orig = float(stored_estimate)
    except (TypeError, ValueError):
        return None
    # Stub: query estimate_history (table exists, may be empty)
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT estimate_value FROM estimate_history WHERE ticker=? ORDER BY captured_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()
    if row is None or row["estimate_value"] is None:
        return None
    current = float(row["estimate_value"])
    if orig == 0:
        return None
    change = abs(current - orig) / abs(orig)
    if change > threshold:
        direction = "up" if current > orig else "down"
        return (
            f"Estimate revised {direction} by {change * 100:.0f}% "
            f"(was {orig:.2f}, now {current:.2f}; threshold {threshold * 100:.0f}%)"
        )
    return None


def _check_cc_position_state(dep: dict, _unused) -> str | None:
    """Supersede if an open CC position was opened or closed since the recommendation.

    original_value: "open" if an open CC existed when rec was made, "none" if not.
    Fires when the current state differs (position opened externally, or closed).
    """
    ticker = dep.get("dependency_key")
    original_state = dep.get("original_value") or "none"
    if not ticker:
        return None
    current_cc = agent_db.get_open_cc_for_ticker(ticker)
    current_state = "open" if current_cc else "none"
    if current_state != original_state:
        return (f"CC position state changed: was '{original_state}', "
                f"now '{current_state}'")
    return None


_KNOWN_DEPENDENCY_TYPES = frozenset({
    "PRICE", "THESIS_VERSION", "POSITION_WEIGHT", "MACRO_STATE",
    "FINANCIAL_PERIOD", "OPTION_IV", "OPTION_EXPIRATION", "EARNINGS_DATE",
    "EVENT_CALENDAR", "OPTION_LIQUIDITY", "ESTIMATE_REVISION",
    "CC_POSITION_STATE",
})


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
        recs, _run_ids = run_agents(snapshot, [event])
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

    prices   = _latest_prices()
    versions = _latest_thesis_versions()
    weights  = _latest_weights()
    macro    = _latest_macro_scores()
    periods  = _latest_financial_periods()

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
            elif dtype == "POSITION_WEIGHT":
                reason = _check_position_weight(dep, weights)
            elif dtype == "MACRO_STATE":
                reason = _check_macro_state(dep, macro)
            elif dtype == "FINANCIAL_PERIOD":
                reason = _check_financial_period(dep, periods)
            elif dtype == "OPTION_IV":
                # True IV check using option_quote_snapshots (stub until data exists)
                reason = _check_option_iv_true(dep, None)
            elif dtype == "OPTION_EXPIRATION":
                # Expiration-date check (the original OPTION_IV behavior)
                reason = _check_option_expiration(dep, None)
            elif dtype == "EARNINGS_DATE":
                reason = _check_earnings_date(dep, periods)
            elif dtype == "EVENT_CALENDAR":
                reason = _check_event_calendar(dep, None)
            elif dtype == "OPTION_LIQUIDITY":
                reason = _check_option_liquidity(dep, None)
            elif dtype == "ESTIMATE_REVISION":
                reason = _check_estimate_revision(dep, None)
            elif dtype == "CC_POSITION_STATE":
                reason = _check_cc_position_state(dep, None)
            else:
                # Unknown dependency type: fail-safe — supersede rather than silently assume valid.
                reason = (f"Unknown dependency type {dtype!r}: cannot validate — "
                          "superseding to force re-evaluation")
                print(f"[DepChecker] WARNING: rec {rec_id} has unrecognised dependency type {dtype!r}")
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
