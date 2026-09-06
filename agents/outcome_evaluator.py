"""Outcome Evaluator — multi-scenario counterfactual benchmarking.

For each accepted/rejected recommendation, writes one row per evaluation horizon
once that horizon has elapsed. Four scenarios per row:

  A  actual_return           — ticker return from rec date to horizon date
  B  recommended_path_return — agent-recommended path return
  C  hold_return             — return from holding unchanged (always ticker return)
  D  benchmark_return        — SPY return over same period

Alpha calculations (computed on-the-fly from stored columns):
  AgentAlpha_vs_Hold  = B − C   (did agent recommendation beat holding?)
  AgentAlpha_vs_SPY   = B − D   (did agent recommendation beat SPY?)
  UserOverrideAlpha   = A − B   (did user override outperform agent recommendation?)

Equity horizons  : 1w, 1m, 3m, 6m, 12m
CC horizons      : at_expiry, 30d_post, 90d_post

SPY prices are fetched from Yahoo Finance and cached in spy_prices table.
"""
import json
import time
from datetime import datetime, date, timedelta, timezone

import agent_db
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

MIN_AGE_DAYS = 14

EQUITY_HORIZONS: list[tuple[str, int]] = [
    ("1w",  7),
    ("1m",  30),
    ("3m",  90),
    ("6m",  180),
    ("12m", 365),
]

CC_ACTIONS = {"SELL_CC"}
EQUITY_ACTIONS = {"HOLD", "REVIEW", "TRIM", "EXIT", "ALLOCATE", "REBALANCE",
                  "TAX_HARVEST", "TAX_SELL", "NO_ACTION"}

# Actions where the agent recommendation means "exit position" (B = 0)
EXIT_ACTIONS = {"EXIT", "TAX_SELL"}


# ── Price helpers ─────────────────────────────────────────────────────────────

def _ticker_price_at(ticker: str, date_str: str) -> float | None:
    """Holding_day price on or before date_str."""
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT price FROM holding_day WHERE ticker=? AND day<=? ORDER BY day DESC LIMIT 1",
        (ticker, date_str),
    ).fetchone()
    conn.close()
    return float(row["price"]) if row else None


def _ensure_spy_prices(dates: list[str]) -> None:
    """Fetch and cache SPY prices for any dates not already stored."""
    if not dates:
        return
    stored = agent_db.get_spy_prices(dates)
    missing = [d for d in dates if d not in stored]
    if not missing:
        return
    try:
        import yfinance as yf
        earliest = min(missing)
        # Fetch a window starting one day before earliest to handle weekends
        start = (date.fromisoformat(earliest) - timedelta(days=5)).isoformat()
        end   = (date.fromisoformat(max(missing)) + timedelta(days=2)).isoformat()
        hist  = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=True)
        if hist.empty:
            return
        price_map: dict[str, float] = {}
        for idx, row in hist.iterrows():
            price_map[idx.strftime("%Y-%m-%d")] = float(row["Close"])
        # For each missing date, use the closest available price on or before
        for d in missing:
            # Try exact match first, then walk back up to 5 days
            for delta in range(6):
                candidate = (date.fromisoformat(d) - timedelta(days=delta)).isoformat()
                if candidate in price_map:
                    agent_db.upsert_spy_price(d, price_map[candidate])
                    break
    except Exception as e:
        print(f"[OutcomeEval] SPY fetch failed: {e}")


def _spy_price_at(date_str: str) -> float | None:
    prices = agent_db.get_spy_prices([date_str])
    return prices.get(date_str)


def _date_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _horizon_date(rec_date: str, days: int) -> str:
    return (date.fromisoformat(rec_date) + timedelta(days=days)).isoformat()


# ── Horizon gating ────────────────────────────────────────────────────────────

def _already_evaluated(rec_id: int, horizon: str) -> bool:
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT 1 FROM recommendation_outcomes WHERE recommendation_id=? AND horizon=? LIMIT 1",
        (rec_id, horizon),
    ).fetchone()
    conn.close()
    return row is not None


def _payload(rec: dict) -> dict:
    try:
        return json.loads(rec.get("action_payload_json") or "{}") or {}
    except Exception:
        return {}


# ── Scenario return computation ───────────────────────────────────────────────

def _compute_scenarios(
    ticker: str,
    action: str,
    entry_date: str,
    horizon_date: str,
    pl: dict,
    entry_price: float,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return (actual_r, agent_r, hold_r, spy_r) for one horizon.

    Scenario A — actual_return           : ticker return entry→horizon
    Scenario B — recommended_path_return : agent-specific (see below)
    Scenario C — hold_return             : ticker return entry→horizon (always)
    Scenario D — benchmark_return        : SPY return entry→horizon
    """
    h_price    = _ticker_price_at(ticker, horizon_date)
    spy_entry  = _spy_price_at(entry_date)
    spy_h      = _spy_price_at(horizon_date)

    hold_r = (h_price - entry_price) / entry_price if h_price is not None else None
    spy_r  = (spy_h  - spy_entry)   / spy_entry   if (spy_entry and spy_h) else None

    # Scenario A: same as hold for equity (user held or acted, but we track what the
    # stock did — the decision-level comparison is captured by UserOverrideAlpha = A − B)
    actual_r = hold_r

    # Scenario B: agent recommended path
    if action in EXIT_ACTIONS:
        # Agent said sell/exit → no exposure after rec date → return = 0
        agent_r = 0.0
    elif action == "SELL_CC":
        # Income from premium; if stock called away, opportunity cost is upside surrendered
        exec_premium = pl.get("exec_premium") or pl.get("premium")
        strike       = pl.get("strike")
        if exec_premium and entry_price:
            premium_yield = float(exec_premium) / entry_price
            # If stock above strike at horizon, upside surrendered
            if h_price is not None and strike is not None and h_price > float(strike):
                upside_surrendered = (h_price - float(strike)) / entry_price
                agent_r = premium_yield - upside_surrendered
            else:
                agent_r = premium_yield
        else:
            agent_r = hold_r  # fallback: no premium data
    else:
        # HOLD / REVIEW / TRIM / ALLOCATE / REBALANCE: agent recommendation is to
        # maintain or adjust but not fully exit — treat as holding for comparison
        agent_r = hold_r

    return actual_r, agent_r, hold_r, spy_r


# ── CC horizon helpers ────────────────────────────────────────────────────────

def _cc_horizons(pl: dict, rec_date: str) -> list[tuple[str, str]]:
    """Return [(horizon_label, horizon_date_str)] for CC-specific horizons."""
    expiry = pl.get("expiration") or pl.get("expiry")
    if not expiry:
        return []
    horizons = [("at_expiry", expiry)]
    try:
        exp_d = date.fromisoformat(expiry)
        horizons.append(("30d_post",  (exp_d + timedelta(days=30)).isoformat()))
        horizons.append(("90d_post",  (exp_d + timedelta(days=90)).isoformat()))
    except ValueError:
        pass
    return horizons


# ── Main evaluator ────────────────────────────────────────────────────────────

def evaluate_matured_recommendations(min_age_days: int = MIN_AGE_DAYS) -> int:
    """Evaluate all matured accepted/rejected recs.

    Writes one recommendation_outcomes row per (rec, horizon) that has elapsed
    and has not yet been evaluated. Returns count of new rows written.
    """
    cutoff = time.time() - min_age_days * 86400
    today  = date.today().isoformat()

    conn = agent_db._connect()
    recs = conn.execute(
        """SELECT r.id, r.ticker, r.action, r.created_at, r.action_payload_json
           FROM recommendations r
           WHERE r.status IN ('accepted', 'rejected')
             AND r.created_at <= ?
             AND r.action != 'NO_ACTION'""",
        (cutoff,),
    ).fetchall()
    conn.close()

    # Collect all dates we'll need for SPY
    all_dates: set[str] = set()
    rec_list = [dict(r) for r in recs]
    for rec in rec_list:
        entry_date = _date_of(rec["created_at"])
        all_dates.add(entry_date)
        if rec["action"] in CC_ACTIONS:
            pl = _payload(rec)
            for _, h_date in _cc_horizons(pl, entry_date):
                all_dates.add(h_date)
        else:
            for _, days in EQUITY_HORIZONS:
                all_dates.add(_horizon_date(entry_date, days))
    _ensure_spy_prices(list(all_dates))

    written = 0
    for rec in rec_list:
        ticker     = rec["ticker"]
        action     = rec["action"]
        entry_date = _date_of(rec["created_at"])
        pl         = _payload(rec)

        entry_price = _ticker_price_at(ticker, entry_date)
        if entry_price is None or entry_price == 0:
            continue

        if action in CC_ACTIONS:
            horizons_to_eval = _cc_horizons(pl, entry_date)
        else:
            horizons_to_eval = [
                (label, _horizon_date(entry_date, days))
                for label, days in EQUITY_HORIZONS
            ]

        for horizon_label, h_date in horizons_to_eval:
            if h_date > today:
                continue  # not elapsed yet
            if _already_evaluated(rec["id"], horizon_label):
                continue

            actual_r, agent_r, hold_r, spy_r = _compute_scenarios(
                ticker, action, entry_date, h_date, pl, entry_price
            )

            # opportunity_cost: positive = user override outperformed agent rec
            opp_cost = None
            if actual_r is not None and agent_r is not None:
                opp_cost = round(actual_r - agent_r, 6)

            notes = (
                f"entry={entry_date} horizon={h_date} "
                f"entry_px={entry_price:.2f}"
            )

            agent_db.insert_outcome(
                recommendation_id=rec["id"],
                actual_return=round(actual_r, 6) if actual_r is not None else None,
                recommended_path_return=round(agent_r, 6) if agent_r is not None else None,
                benchmark_return=round(spy_r, 6) if spy_r is not None else None,
                opportunity_cost=opp_cost,
                hold_return=round(hold_r, 6) if hold_r is not None else None,
                horizon=horizon_label,
                notes=notes,
            )
            written += 1
            print(
                f"[OutcomeEval] {ticker} {action} [{horizon_label}]: "
                f"hold={hold_r:.2%} agent={agent_r:.2%} spy={spy_r:.2%}"
                if (hold_r is not None and agent_r is not None and spy_r is not None)
                else f"[OutcomeEval] {ticker} {action} [{horizon_label}]: partial data"
            )

    return written


def run_outcome_evaluator(ctx: AgentContext) -> list[Recommendation]:
    n = evaluate_matured_recommendations()
    print(f"[OutcomeEval] evaluated {n} horizon row(s)")
    return []


register_agent("outcome_evaluator", run_outcome_evaluator)
