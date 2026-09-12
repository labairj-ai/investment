from __future__ import annotations
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
CC_MANAGEMENT_ACTIONS = {"BUY_TO_CLOSE", "ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT",
                         "ALLOW_ASSIGNMENT", "HOLD_CALL"}
# CC management actions that use CC horizons (at_expiry/30d/90d) vs equity horizons.
# HOLD_CALL moved to CC horizons (0126): evaluate at expiry so terminal option payoff is known.
_CC_MGMT_CC_HORIZONS = {"ALLOW_ASSIGNMENT", "HOLD_CALL",
                         "ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT"}

# 0128: outcome_math_version tags — bump when evaluator formula changes
_OUTCOME_MATH_VERSION_CC_MGMT = 2   # 0125-0127 NAV-corrected CC management formulas
_OUTCOME_MATH_VERSION_DEFAULT  = 1  # all other actions (unchanged)
EQUITY_ACTIONS = {"HOLD", "REVIEW", "TRIM", "EXIT", "ALLOCATE", "REBALANCE",
                  "TAX_HARVEST", "TAX_SELL", "NO_ACTION"}

# Actions where the agent recommendation means "exit position" (B = 0)
EXIT_ACTIONS = {"EXIT", "TAX_SELL"}

# Actions where accepted-but-not-executed means we cannot estimate the return
_ACCEPTED_NO_EXEC_NULL = {*EXIT_ACTIONS, "TRIM", "ALLOCATE", "REBALANCE"}


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


# ── Actual-return helpers per action type (0103) ─────────────────────────────

def _compute_actual_trim(
    exec_rec: dict,
    entry_price: float,
    hold_r: float | None,
) -> tuple[float | None, bool]:
    """Two-component TRIM actual return.

    actual_r = f*(exec_price/entry_price - 1) + (1-f)*hold_r

    The sold fraction earns the gain from entry to execution price; the retained
    fraction earns the full hold return to the horizon date.
    """
    if hold_r is None:
        return None, False
    exec_price = float(exec_rec["execution_price"])
    frac = exec_rec.get("execution_fraction")
    if frac is not None:
        f = float(frac)
    elif exec_rec.get("position_shares_before") and exec_rec.get("quantity"):
        f = float(exec_rec["quantity"]) / float(exec_rec["position_shares_before"])
    else:
        f = 0.5
    exec_gain = (exec_price / entry_price) - 1 if entry_price else 0.0
    return f * exec_gain + (1 - f) * hold_r, False


def _compute_actual_allocate(
    exec_rec: dict,
    h_price: float | None,
) -> tuple[float | None, bool]:
    """ALLOCATE actual return: exec_price is the cost basis; return to horizon price."""
    exec_price = float(exec_rec["execution_price"])
    if h_price is None or exec_price <= 0:
        return None, True
    return (h_price - exec_price) / exec_price, False


def _compute_actual_rebalance(
    exec_rec: dict,
    entry_price: float,
    pl: dict,
    horizon_date: str,
) -> tuple[float | None, bool]:
    """REBALANCE actual return: from-ticker sold at exec_price; to-ticker from exec_date.

    The from-ticker gain is exact (exec_price vs entry_price). The to-ticker
    purchase price is approximated as the exec_date price (same day as the sale).
    estimated=True when to-ticker price is unavailable.
    """
    exec_price = float(exec_rec["execution_price"])
    fraction = float(pl.get("fraction") or 0.5)
    from_gain = (exec_price / entry_price) - 1 if entry_price else 0.0

    to_ticker = pl.get("to_ticker")
    if to_ticker:
        exec_date = exec_rec.get("execution_date")
        to_entry = _ticker_price_at(to_ticker, exec_date) if exec_date else None
        to_h = _ticker_price_at(to_ticker, horizon_date)
        if to_entry and to_h and to_entry > 0:
            to_r = (to_h - to_entry) / to_entry
            return (1 - fraction) * from_gain + fraction * to_r, False

    return (1 - fraction) * from_gain, True


# ── CC management outcome models (0105 / 0125-0127) ──────────────────────────

def _compute_cc_management_returns(
    action: str,
    pl: dict,
    entry_price: float,
    h_price: float | None,
    exec_rec=None,
    horizon_label: str = "",
    new_expiry_price: float | None = None,
    net_nav: float | None = None,
    rec_id: int | None = None,
) -> "tuple[float | None, float | None, bool, int | None]":
    """Returns (actual_r, agent_r, actual_is_estimated, roll_chain_depth) for CC management actions.

    roll_chain_depth is None for non-ROLL actions; ≥1 for ROLL actions that resolved a chain.

    entry_price     : stock price at the CC management recommendation date (S_rec)
    h_price         : stock price at the horizon date
    exec_rec        : aggregated execution record (may be None)
    horizon_label   : "at_expiry", "30d_post", "90d_post" etc.
    new_expiry_price: for ROLL/HOLD_CALL/ALLOW_ASSIGNMENT post-horizons, stock price
                      at the (new) expiry date — pre-fetched by caller
    net_nav         : 0125 — true MTM basis = S_rec − C_rec (stock minus short-call mark).
                      Falls back to entry_price when unavailable (older recs without C_rec).
    """
    # 0125: all CC management returns are normalised by the true covered-position NAV.
    # nav = S_rec − C_rec; C_rec is the call's current mark at the management rec date.
    # Callers may pass net_nav directly (from _compute_scenarios); otherwise derive from
    # the payload's btc_price/btc_mark field.  Fallback to entry_price for legacy recs
    # with no call mark stored (preserves backward-compat with older DB rows).
    if net_nav is not None and net_nav > 0:
        nav = net_nav
    else:
        _c_rec = float(pl.get("btc_price") or pl.get("btc_mark") or 0.0)
        nav = (entry_price - _c_rec) if (_c_rec > 0 and entry_price and _c_rec < entry_price) else entry_price
    hold_r = (h_price - entry_price) / nav if (h_price is not None and nav) else None

    if action == "BUY_TO_CLOSE":
        # After BTC the investor holds only stock from S_rec → horizon.
        # agent_r: closed at rec-date mark (C_rec) → net option P&L = 0 → just stock return.
        # actual_r: saved (btc_mark − btc_exec) vs mark; positive = cheaper than marked.
        btc_mark = float(pl.get("btc_price") or pl.get("btc_mark") or 0.0)
        agent_r = hold_r
        if exec_rec and exec_rec.get("execution_price"):
            btc_exec = float(exec_rec["execution_price"])
            net = btc_mark - btc_exec
            actual_r = (hold_r + net / nav) if (hold_r is not None and nav) else None
            return actual_r, agent_r, actual_r is None, None
        return hold_r, agent_r, True, None

    elif action in {"HOLD_CALL", "ALLOW_ASSIGNMENT"}:
        # 0126/0127: both actions mean "hold the covered position to expiry".
        # Economic formula (first-principles from net_NAV):
        #   at-expiry P&L = min(S_exp, K) − S_rec + C_rec
        #   normalized by nav = S_rec − C_rec
        # Branches on actual assignment state (S_exp vs K) — 0127.
        # Post-expiry horizons lock at the at-expiry value.
        K   = float(pl.get("strike") or 0.0)
        C_rec = float(pl.get("btc_mark") or pl.get("btc_price") or 0.0)
        if K and nav:
            if "post" in horizon_label:
                # Use pre-fetched expiry price to determine terminal state
                s_exp = new_expiry_price if new_expiry_price is not None else h_price
            else:
                s_exp = h_price  # at_expiry: h_price IS S_exp
            if s_exp is not None:
                actual_r = (min(s_exp, K) - entry_price + C_rec) / nav
                return actual_r, actual_r, False, None
        return hold_r, hold_r, hold_r is None, None

    elif action in {"ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT"}:
        new_strike = float(pl.get("new_strike") or pl.get("strike") or 0.0)
        btc_mark   = float(pl.get("btc_price") or pl.get("btc_mark") or 0.0)
        sto_mark   = float(pl.get("sto_premium") or pl.get("new_premium") or 0.0)
        agent_net  = sto_mark - btc_mark

        if exec_rec and exec_rec.get("execution_price"):
            btc_exec   = float(exec_rec["execution_price"])
            sto_exec   = float(exec_rec.get("sto_premium") or sto_mark)
            net_credit = sto_exec - btc_exec
        else:
            net_credit = None

        # 0136/0180/0183: walk chain, accumulate every hop's option cash flows
        def _resolve_chain(start_rec_id, depth=0, max_depth=10,
                           accumulated_extra=0.0, has_missing_exec=False):
            """Return (terminal_child, chain_open, depth, extra_credit, any_missing_exec).

            extra_credit: per-share net option cash flow from all hops AFTER the root.
            has_missing_exec: True if any hop lacks a confirmed execution (→ estimated).
            """
            if start_rec_id is None:
                return None, False, depth, accumulated_extra, has_missing_exec
            if depth >= max_depth:
                return None, True, depth, accumulated_extra, has_missing_exec
            if agent_db.has_chain_child(start_rec_id):
                return None, True, depth, accumulated_extra, has_missing_exec
            child = agent_db.get_completed_chain_child(start_rec_id)
            if child is None:
                return None, False, depth, accumulated_extra, has_missing_exec
            child_action = child["action"]
            child_exec = child.get("exec_rec")

            if child_action in {"ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT"}:
                # Intermediate roll hop — exec_rec for ROLL uses ROLL branch in
                # aggregate_executions(), so execution_price = net STO-BTC per share.
                if child_exec and child_exec.get("execution_price"):
                    hop_net = float(child_exec["execution_price"])
                else:
                    hop_net = 0.0
                    has_missing_exec = True
                return _resolve_chain(child["id"], depth + 1, max_depth,
                                      accumulated_extra + hop_net, has_missing_exec)

            elif child_action == "BUY_TO_CLOSE":
                # Terminal BTC — 0185: use aggregate_executions for contract-weighted avg
                raw_execs = agent_db.get_executions_for_rec(child["id"])
                btc_summary = agent_db.aggregate_executions(raw_execs, "BUY_TO_CLOSE")
                if btc_summary and btc_summary.get("execution_price"):
                    terminal_btc = float(btc_summary.get("execution_price"))
                    extra = accumulated_extra - terminal_btc
                else:
                    extra = accumulated_extra
                    has_missing_exec = True
                return child, False, depth + 1, extra, has_missing_exec

            else:
                # ALLOW_ASSIGNMENT or other terminal — no option cash flow at termination
                return child, False, depth + 1, accumulated_extra, has_missing_exec

        terminal_child, chain_open, chain_depth, extra_credit, chain_has_missing_exec = \
            _resolve_chain(rec_id)

        if new_strike and h_price is not None and nav:
            # Base stock return: default to at-expiry cap formula.
            if "post" in horizon_label:
                if new_expiry_price is not None and new_expiry_price > new_strike:
                    base_r = (new_strike - entry_price) / nav
                else:
                    base_r = hold_r
            else:
                # at_expiry: h_price IS stock at new_expiry
                base_r = (new_strike - entry_price) / nav if h_price > new_strike else hold_r

            # 0136/0180: when a fully-resolved terminal child exists, revise base_r.
            if terminal_child and not chain_open:
                child_action = terminal_child["action"]
                if child_action == "BUY_TO_CLOSE":
                    base_r = hold_r
                elif child_action == "ALLOW_ASSIGNMENT":
                    child_strike = float(
                        terminal_child["payload"].get("strike") or
                        terminal_child["payload"].get("new_strike") or
                        new_strike
                    )
                    if child_strike and nav:
                        base_r = (child_strike - entry_price) / nav if (h_price is not None and h_price > child_strike) else hold_r

            agent_r = (base_r + agent_net / nav) if base_r is not None else None
            if net_credit is not None:
                full_net = net_credit + extra_credit   # 0183: include all subsequent hops
                actual_r = (base_r + full_net / nav) if base_r is not None else None
                is_estimated = chain_open or chain_has_missing_exec or (actual_r is None)
                return actual_r, agent_r, is_estimated, chain_depth
            return hold_r, agent_r, True, chain_depth
        else:
            # Fallback when new_strike absent: net-credit vs mark only
            agent_r = (hold_r + agent_net / nav) if (hold_r is not None and nav) else None
            if net_credit is not None:
                full_net = net_credit + extra_credit   # 0183: include all subsequent hops
                actual_r = (hold_r + full_net / nav) if hold_r is not None else None
                is_estimated = chain_open or chain_has_missing_exec or (actual_r is None)
                return actual_r, agent_r, is_estimated, chain_depth
            return hold_r, agent_r, True, chain_depth

    return hold_r, hold_r, True, None


# ── Scenario return computation ───────────────────────────────────────────────

def _compute_scenarios(
    ticker: str,
    action: str,
    entry_date: str,
    horizon_date: str,
    pl: dict,
    entry_price: float,
    decision: str | None = None,
    **kwargs,
) -> tuple[float | None, float | None, float | None, float | None, bool,
           float | None, float | None, int | None]:
    """Return (actual_r, agent_r, hold_r, spy_r, actual_is_estimated,
               cc_strategy_return, cc_incremental_alpha, roll_chain_depth) for one horizon.

    Scenario A — actual_return           : decision-adjusted return (see branching below)
    Scenario B — recommended_path_return : cc_strategy_return for CC, else agent-specific
    Scenario C — hold_return             : ticker return entry→horizon (always)
    Scenario D — benchmark_return        : SPY return entry→horizon
    """
    h_price    = _ticker_price_at(ticker, horizon_date)
    spy_entry  = _spy_price_at(entry_date)
    spy_h      = _spy_price_at(horizon_date)

    hold_r = (h_price - entry_price) / entry_price if h_price is not None else None
    spy_r  = (spy_h  - spy_entry)   / spy_entry   if (spy_entry and spy_h) else None

    # Scenario A: branch on what the user actually chose to do.
    # Execution record present  → use actual execution price and date (most accurate)
    # accepted EXIT (no record) → actual_r = None, estimated = True (0071: no longer 0.0)
    # rejected (any)            → user held regardless → actual_r = hold_r
    # anything else             → we don't have execution records → fall back, flag estimated
    exec_rec = kwargs.get("exec_rec")  # optional: first executed_action row for this rec

    # CC management actions: dedicated outcome models (0105/0125-0127)
    if action in CC_MANAGEMENT_ACTIONS:
        horizon_label = kwargs.get("horizon_label", "")

        # 0125: compute true covered-position NAV = S_rec − C_rec.
        # C_rec (call mark at rec date) lives in the payload as btc_price or btc_mark.
        _btc_mark_for_nav = float(pl.get("btc_price") or pl.get("btc_mark") or 0.0)
        net_nav_val: float | None = (
            (entry_price - _btc_mark_for_nav) if (_btc_mark_for_nav > 0 and entry_price) else None
        )

        # 0126/0127: for ROLL/HOLD_CALL/ALLOW_ASSIGNMENT post-horizons, pre-fetch the stock
        # price at the (new) expiry date so assignment state is known without a second DB call.
        new_expiry_price: float | None = None
        if action in _CC_MGMT_CC_HORIZONS and "post" in horizon_label:
            if action.startswith("ROLL"):
                _expiry_key = pl.get("new_expiration") or pl.get("new_expiry")
            else:
                _expiry_key = pl.get("expiration") or pl.get("expiry")
            if _expiry_key:
                new_expiry_price = _ticker_price_at(ticker, _expiry_key)

        actual_r, agent_r, actual_is_estimated, _roll_chain_depth = _compute_cc_management_returns(
            action, pl, entry_price, h_price,
            exec_rec=exec_rec,
            horizon_label=horizon_label,
            new_expiry_price=new_expiry_price,
            net_nav=net_nav_val,
            rec_id=kwargs.get("rec_id"),
        )
        return actual_r, agent_r, hold_r, spy_r, actual_is_estimated, None, None, _roll_chain_depth

    # CC-specific actual-return path (0073/0106): must come BEFORE generic exec_rec branch
    horizon_label  = kwargs.get("horizon_label", "")
    cc_expiry_date = kwargs.get("cc_expiry_date")
    if action == "SELL_CC" and exec_rec and exec_rec.get("execution_price") and exec_rec.get("strike"):
        actual_premium = float(exec_rec["execution_price"])  # premium per share
        actual_strike  = float(exec_rec["strike"])
        if h_price is not None and entry_price:
            # 0106: post-expiry horizons must respect assignment state
            if "post" in horizon_label and cc_expiry_date:
                s_exp = _ticker_price_at(ticker, cc_expiry_date)
                if s_exp is not None:
                    if s_exp > actual_strike:
                        # Locked at assignment return; cash sits idle post-assignment
                        actual_r = (actual_strike - entry_price + actual_premium) / entry_price
                    else:
                        # call expired worthless → investor holds uncapped stock
                        actual_r = (h_price - entry_price + actual_premium) / entry_price
                    actual_is_estimated = False
                else:
                    actual_exit = min(h_price, actual_strike)
                    actual_r = (actual_exit - entry_price + actual_premium) / entry_price
                    actual_is_estimated = False
            else:
                actual_exit = min(h_price, actual_strike)
                actual_r = (actual_exit - entry_price + actual_premium) / entry_price
                actual_is_estimated = False
        else:
            actual_r = actual_premium / entry_price if entry_price else None
            actual_is_estimated = False
    elif exec_rec and exec_rec.get("execution_price") and exec_rec.get("execution_date"):
        exec_price = float(exec_rec["execution_price"])
        # Route by action to dedicated actual-return helpers (0103)
        if action in EXIT_ACTIONS:
            actual_r = (exec_price - entry_price) / entry_price if entry_price else None
            actual_is_estimated = False
        elif action == "TRIM":
            actual_r, actual_is_estimated = _compute_actual_trim(exec_rec, entry_price, hold_r)
        elif action == "ALLOCATE":
            actual_r, actual_is_estimated = _compute_actual_allocate(exec_rec, h_price)
        elif action == "REBALANCE":
            actual_r, actual_is_estimated = _compute_actual_rebalance(
                exec_rec, entry_price, pl, horizon_date)
        else:
            actual_r = hold_r
            actual_is_estimated = True
    elif decision == "accepted" and action in _ACCEPTED_NO_EXEC_NULL:
        # 0071/0099: accepted but no execution record — cannot confirm actual return
        actual_r = None
        actual_is_estimated = True
    elif decision == "rejected":
        actual_r = hold_r
        actual_is_estimated = False
    else:
        actual_r = hold_r
        actual_is_estimated = True

    # Scenario B: agent recommended path; CC gets two sub-fields
    cc_strategy_return:   float | None = None
    cc_incremental_alpha: float | None = None

    if action in EXIT_ACTIONS:
        # Agent said sell/exit → no exposure after rec date → return = 0
        agent_r = 0.0
    elif action == "SELL_CC":
        exec_premium = pl.get("exec_premium") or pl.get("premium")
        strike       = pl.get("strike")
        if exec_premium and entry_price and h_price is not None:
            premium = float(exec_premium)
            k       = float(strike) if strike is not None else None
            # 0106: post-expiry horizons branch on assignment state
            if "post" in horizon_label and cc_expiry_date and k is not None:
                s_exp = _ticker_price_at(ticker, cc_expiry_date)
                if s_exp is not None:
                    if s_exp > k:
                        # Locked at assignment return; cash sits idle post-assignment
                        cc_strategy_return = (k - entry_price + premium) / entry_price
                    else:
                        cc_strategy_return = (h_price - entry_price + premium) / entry_price
                    cc_incremental_alpha = cc_strategy_return - hold_r if hold_r is not None else None
                    agent_r = cc_strategy_return
                else:
                    effective_exit = min(h_price, k)
                    cc_strategy_return   = (effective_exit - entry_price + premium) / entry_price
                    cc_incremental_alpha = cc_strategy_return - hold_r if hold_r is not None else None
                    agent_r              = cc_strategy_return
            else:
                # at_expiry or no expiry data: standard formula
                effective_exit = min(h_price, k) if k is not None else h_price
                cc_strategy_return   = (effective_exit - entry_price + premium) / entry_price
                cc_incremental_alpha = cc_strategy_return - hold_r if hold_r is not None else None
                agent_r              = cc_strategy_return
        elif exec_premium and entry_price:
            # No horizon price yet — just premium yield (at-expiry will have it)
            agent_r = float(exec_premium) / entry_price
        else:
            agent_r = hold_r  # fallback: no premium data
    elif action == "TRIM":
        f = float(pl.get("trim_fraction") or 0.5)
        replacement = pl.get("replacement_ticker")
        if replacement and h_price is not None:
            repl_entry = _ticker_price_at(replacement, entry_date)
            repl_h     = _ticker_price_at(replacement, horizon_date)
            if repl_entry and repl_h and repl_entry > 0:
                repl_r = (repl_h - repl_entry) / repl_entry
                agent_r = (1 - f) * hold_r + f * repl_r if hold_r is not None else None
            else:
                agent_r = (1 - f) * hold_r if hold_r is not None else None
        elif hold_r is not None:
            agent_r = (1 - f) * hold_r  # trimmed portion goes to cash (return = 0)
        else:
            agent_r = None
    elif action == "ALLOCATE":
        alloc_ticker = pl.get("ticker") or ticker
        alloc_entry = _ticker_price_at(alloc_ticker, entry_date)
        alloc_h     = _ticker_price_at(alloc_ticker, horizon_date)
        if alloc_entry and alloc_h and alloc_entry > 0:
            agent_r = (alloc_h - alloc_entry) / alloc_entry
        else:
            agent_r = None
    elif action == "REBALANCE":
        from_ticker = pl.get("from_ticker") or ticker
        to_ticker   = pl.get("to_ticker")
        fraction    = float(pl.get("fraction") or 0.5)
        if to_ticker and h_price is not None:
            to_entry = _ticker_price_at(to_ticker, entry_date)
            to_h     = _ticker_price_at(to_ticker, horizon_date)
            to_r = (to_h - to_entry) / to_entry if (to_entry and to_h and to_entry > 0) else None
            if to_r is not None and hold_r is not None:
                agent_r = (1 - fraction) * hold_r + fraction * to_r
            else:
                agent_r = None
        else:
            agent_r = None
    else:
        # HOLD / REVIEW — recommended path = hold unchanged
        agent_r = hold_r

    return actual_r, agent_r, hold_r, spy_r, actual_is_estimated, cc_strategy_return, cc_incremental_alpha, None


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
        """SELECT r.id, r.ticker, r.action, r.created_at, r.action_payload_json,
                  ud.decision
           FROM recommendations r
           LEFT JOIN user_decisions ud ON ud.recommendation_id = r.id
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
        elif rec["action"] in CC_MANAGEMENT_ACTIONS:
            pl = _payload(rec)
            if rec["action"] in _CC_MGMT_CC_HORIZONS:
                exp_key = "new_expiration" if rec["action"].startswith("ROLL") else "expiration"
                pl_exp = pl.get(exp_key) or pl.get("expiry") or pl.get("expiration")
                if pl_exp:
                    for _, h_date in _cc_horizons({"expiration": pl_exp}, entry_date):
                        all_dates.add(h_date)
            else:
                for _, days in EQUITY_HORIZONS[:3]:
                    all_dates.add(_horizon_date(entry_date, days))
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
        elif action in CC_MANAGEMENT_ACTIONS:
            if action in _CC_MGMT_CC_HORIZONS:
                exp_key = "new_expiration" if action.startswith("ROLL") else "expiration"
                pl_exp = pl.get(exp_key) or pl.get("expiry") or pl.get("expiration")
                horizons_to_eval = _cc_horizons({"expiration": pl_exp}, entry_date) if pl_exp else []
            else:
                horizons_to_eval = [
                    (label, _horizon_date(entry_date, days))
                    for label, days in EQUITY_HORIZONS[:3]
                ]
        else:
            horizons_to_eval = [
                (label, _horizon_date(entry_date, days))
                for label, days in EQUITY_HORIZONS
            ]

        # 0091: aggregate all fills into a single ExecutionSummary (replaces executions[0])
        executions = agent_db.get_executions_for_rec(rec["id"])
        exec_rec = agent_db.aggregate_executions(executions, action)

        # 0106: for CC actions, extract the expiry date once for post-expiry branching
        cc_expiry_date: str | None = None
        if action in CC_ACTIONS:
            cc_expiry_date = pl.get("expiration") or pl.get("expiry")

        for horizon_label, h_date in horizons_to_eval:
            if h_date > today:
                continue  # not elapsed yet
            if _already_evaluated(rec["id"], horizon_label):
                continue

            actual_r, agent_r, hold_r, spy_r, actual_is_estimated, \
                cc_strategy_return, cc_incremental_alpha, _roll_chain_depth = _compute_scenarios(
                ticker, action, entry_date, h_date, pl, entry_price,
                decision=rec.get("decision"),
                exec_rec=exec_rec,
                horizon_label=horizon_label,
                cc_expiry_date=cc_expiry_date,
                rec_id=rec["id"],
            )

            # 0106: determine cc_assignment_state for all CC horizon rows
            cc_assignment_state: str | None = None
            if action in CC_ACTIONS:
                k_val = float(pl.get("strike") or (exec_rec.get("strike") if exec_rec else None) or 0.0)
                if k_val:
                    if horizon_label == "at_expiry":
                        s_at_expiry = _ticker_price_at(ticker, h_date)
                        if s_at_expiry is not None:
                            cc_assignment_state = "assigned" if s_at_expiry > k_val else "expired"
                    elif "post" in horizon_label and cc_expiry_date:
                        s_exp = _ticker_price_at(ticker, cc_expiry_date)
                        if s_exp is not None:
                            cc_assignment_state = "assigned" if s_exp > k_val else "expired"

            # opportunity_cost: positive = user override outperformed agent rec
            opp_cost = None
            if actual_r is not None and agent_r is not None:
                opp_cost = round(actual_r - agent_r, 6)

            notes = (
                f"entry={entry_date} horizon={h_date} "
                f"entry_px={entry_price:.2f}"
            )

            # 0128: tag outcome row with formula version for future DQ gating
            omv = (
                _OUTCOME_MATH_VERSION_CC_MGMT
                if action in CC_MANAGEMENT_ACTIONS
                else _OUTCOME_MATH_VERSION_DEFAULT
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
                actual_is_estimated=int(actual_is_estimated),
                cc_strategy_return=round(cc_strategy_return, 6) if cc_strategy_return is not None else None,
                cc_incremental_alpha=round(cc_incremental_alpha, 6) if cc_incremental_alpha is not None else None,
                cc_assignment_state=cc_assignment_state,
                outcome_math_version=omv,
                roll_chain_depth=_roll_chain_depth,
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
