"""Outcome Evaluator — scores matured recommendations against actual price history.

Runs weekly via the serve.py scheduler. For each accepted/rejected recommendation
that is at least MIN_AGE_DAYS old and has no existing outcome row:

  1. Look up the holding_day price closest to the recommendation's created_at date.
  2. Look up the most recent holding_day price (current price proxy).
  3. Compute actual_return = (current - entry) / entry.
  4. For SELL_CC: recommended_path_return = exec_premium / entry_price
     (simplified: income captured if call expires worthless).
     For all others: recommended_path_return = None (no specific return target).
  5. opportunity_cost = actual_return - recommended_path_return (when both defined).
     Positive = user override outperformed the recommendation.

Deferred and vetoed recommendations are skipped — no clear counterfactual.
"""
import json
import time
from datetime import datetime, timezone

import agent_db
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

MIN_AGE_DAYS = 14  # days before a rec is considered matured


def _price_at(ticker: str, target_ts: float) -> float | None:
    """Return holding_day price closest to target_ts (unix epoch). Returns None if no data."""
    target_date = datetime.fromtimestamp(target_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    conn = agent_db._connect()
    # Try exact date first, then nearest past date
    row = conn.execute(
        "SELECT price FROM holding_day WHERE ticker=? AND day<=? ORDER BY day DESC LIMIT 1",
        (ticker, target_date),
    ).fetchone()
    conn.close()
    return float(row["price"]) if row else None


def _current_price(ticker: str) -> float | None:
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT price FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()
    return float(row["price"]) if row else None


def _already_evaluated(rec_id: int) -> bool:
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT 1 FROM recommendation_outcomes WHERE recommendation_id=? LIMIT 1",
        (rec_id,),
    ).fetchone()
    conn.close()
    return row is not None


def _payload(rec: dict) -> dict:
    try:
        return json.loads(rec.get("action_payload_json") or "{}") or {}
    except Exception:
        return {}


def evaluate_matured_recommendations(min_age_days: int = MIN_AGE_DAYS) -> int:
    """Evaluate all matured accepted/rejected recs without an outcome row.
    Returns count of outcomes written."""
    cutoff = time.time() - min_age_days * 86400
    conn = agent_db._connect()
    recs = conn.execute(
        """SELECT r.id, r.ticker, r.action, r.created_at, r.action_payload_json
           FROM recommendations r
           LEFT JOIN recommendation_outcomes ro ON ro.recommendation_id = r.id
           WHERE r.status IN ('accepted', 'rejected')
             AND r.created_at <= ?
             AND ro.id IS NULL""",
        (cutoff,),
    ).fetchall()
    conn.close()

    written = 0
    for row in recs:
        rec = dict(row)
        ticker = rec["ticker"]
        action = rec["action"]
        created_at = rec["created_at"]
        pl = _payload(rec)

        entry_price = _price_at(ticker, created_at)
        cur_price = _current_price(ticker)

        if entry_price is None or entry_price == 0 or cur_price is None:
            continue

        actual_return = (cur_price - entry_price) / entry_price

        recommended_path_return = None
        opportunity_cost = None
        notes_parts = [f"entry=${entry_price:.2f} current=${cur_price:.2f}"]

        if action == "SELL_CC":
            exec_premium = pl.get("exec_premium") or pl.get("premium")
            if exec_premium:
                recommended_path_return = float(exec_premium) / entry_price
                opportunity_cost = actual_return - recommended_path_return
                notes_parts.append(f"premium=${exec_premium:.2f}")

        agent_db.insert_outcome(
            recommendation_id=rec["id"],
            actual_return=round(actual_return, 6),
            recommended_path_return=round(recommended_path_return, 6) if recommended_path_return is not None else None,
            opportunity_cost=round(opportunity_cost, 6) if opportunity_cost is not None else None,
            notes="; ".join(notes_parts),
        )
        written += 1
        print(f"[outcome_evaluator] {ticker} {action}: actual={actual_return:.2%}"
              + (f" rec={recommended_path_return:.2%} opp_cost={opportunity_cost:.2%}"
                 if opportunity_cost is not None else ""))

    return written


def run_outcome_evaluator(ctx: AgentContext) -> list[Recommendation]:
    n = evaluate_matured_recommendations()
    print(f"[outcome_evaluator] evaluated {n} matured recommendation(s)")
    return []


register_agent("outcome_evaluator", run_outcome_evaluator)
