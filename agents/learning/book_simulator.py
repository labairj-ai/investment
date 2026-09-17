"""Virtual portfolio book simulator for champion/challenger experiment (0340).

Maintains two simulated books (CHAMPION_BOOK, CHALLENGER_BOOK) that receive
fill records whenever an opportunity hunter run produces a decision.  Both books
use identical execution assumptions (same limit_price, same slippage model) so
their cumulative returns are directly comparable.

Called by opportunity_agent.py after the champion recommendation and challenger
variant are produced.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import agent_db

_STARTING_CASH = 100_000.0
_DEFAULT_SLIPPAGE_PCT = 1.0    # mirror TradingPolicy default
_MAX_POSITION_PCT = 10.0       # cap per position


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_virtual_fills(
    champion_ticker: str,
    champion_price: float | None,
    challenger_ticker: str | None,
    challenger_price: float | None,
    episode_id: str | None,
    action: str = "BUY",
) -> None:
    """Insert simulated fills into CHAMPION_BOOK and CHALLENGER_BOOK (0340).

    Uses limit_price * (1 + slippage) as the simulated fill price (same as
    build_intent_from_variant), capped by available cash in each book.
    No-ops when a required price is missing.
    """
    try:
        conn = agent_db._connect()
        try:
            _record_one_book(conn, "CHAMPION_BOOK", champion_ticker, champion_price,
                             episode_id, action, "CHAMPION")
            if challenger_ticker and challenger_price:
                _record_one_book(conn, "CHALLENGER_BOOK", challenger_ticker, challenger_price,
                                 episode_id, action, "PAPER_CHALLENGER")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[book_simulator] WARNING: failed to record virtual fills: {e}")


def _record_one_book(conn, book_id, ticker, price, episode_id, action, origin):
    if not ticker or not price or price <= 0:
        return

    book = conn.execute(
        "SELECT current_cash FROM virtual_books WHERE book_id=?", (book_id,)
    ).fetchone()
    cash = float(book["current_cash"]) if book else _STARTING_CASH

    # Apply slippage to simulate the fill price
    fill_price = round(price * (1 + _DEFAULT_SLIPPAGE_PCT / 100), 2)

    # Size: up to MAX_POSITION_PCT of current cash (simple heuristic — no full NAV)
    max_dollars = cash * _MAX_POSITION_PCT / 100
    qty = int(max_dollars / fill_price) if fill_price > 0 else 0
    if qty < 1:
        return

    cost = qty * fill_price
    if cost > cash:
        return  # insufficient cash

    now = _now_iso()
    conn.execute(
        """INSERT INTO virtual_fills
           (book_id, episode_id, ticker, action, price, qty, fees, filled_at,
            decision_origin, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (book_id, episode_id, ticker, action, fill_price, qty, 0.0, now, origin, time.time()),
    )
    conn.execute(
        "UPDATE virtual_books SET current_cash=?, as_of=? WHERE book_id=?",
        (cash - cost, now[:10], book_id),
    )


def compute_book_stats(book_id: str, price_fn) -> dict:
    """Compute portfolio-level stats for one virtual book.

    price_fn(ticker, date_str) → float | None — passed in so callers can use
    the same price source as the outcome labeler.

    Returns a dict with cumulative_return, max_drawdown, turnover, trade_count,
    win_rate, avg_winner, avg_loser, profit_factor, exposure_pct.
    """
    conn = agent_db._connect()
    try:
        book = conn.execute(
            "SELECT starting_cash, current_cash FROM virtual_books WHERE book_id=?",
            (book_id,),
        ).fetchone()
        if not book:
            return {"book_id": book_id, "error": "not found"}

        starting_cash = float(book["starting_cash"])
        current_cash  = float(book["current_cash"])

        fills = conn.execute(
            """SELECT ticker, action, price, qty, filled_at FROM virtual_fills
               WHERE book_id=? ORDER BY filled_at""",
            (book_id,),
        ).fetchall()

        if not fills:
            return {
                "book_id": book_id, "trade_count": 0,
                "cumulative_return": 0.0, "max_drawdown": 0.0,
                "turnover": 0.0, "win_rate": None,
                "avg_winner": None, "avg_loser": None, "profit_factor": None,
            }

        # Build simple position state
        positions: dict[str, tuple[float, float]] = {}  # ticker → (qty, avg_cost)
        trade_returns: list[float] = []
        total_notional = 0.0
        peak_nav = starting_cash
        max_drawdown = 0.0

        for fill in fills:
            ticker = fill["ticker"]
            action = (fill["action"] or "BUY").upper()
            price  = float(fill["price"])
            qty    = float(fill["qty"])
            total_notional += price * qty

            if action == "BUY":
                prev_qty, prev_cost = positions.get(ticker, (0, 0))
                new_qty = prev_qty + qty
                new_cost = (prev_cost * prev_qty + price * qty) / new_qty if new_qty else price
                positions[ticker] = (new_qty, new_cost)
            elif action in ("SELL", "EXIT", "TRIM"):
                prev_qty, prev_cost = positions.get(ticker, (qty, price))
                trade_ret = (price / prev_cost - 1) if prev_cost else 0
                trade_returns.append(trade_ret)
                new_qty = max(0, prev_qty - qty)
                positions[ticker] = (new_qty, prev_cost) if new_qty > 0 else (0, 0)

            # Current NAV = cash + mark-to-market positions
            nav = current_cash
            today = _now_iso()[:10]
            for t, (pq, pc) in positions.items():
                if pq > 0:
                    mark = price_fn(t, today)
                    nav += pq * (mark if mark else pc)

            peak_nav = max(peak_nav, nav)
            drawdown = (peak_nav - nav) / peak_nav if peak_nav > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        # Final NAV
        final_nav = current_cash
        today = _now_iso()[:10]
        for t, (pq, pc) in positions.items():
            if pq > 0:
                mark = price_fn(t, today)
                final_nav += pq * (mark if mark else pc)

        cum_return = (final_nav - starting_cash) / starting_cash if starting_cash else 0
        avg_nav = (starting_cash + final_nav) / 2
        turnover = total_notional / avg_nav if avg_nav > 0 else 0

        winners = [r for r in trade_returns if r > 0]
        losers  = [r for r in trade_returns if r <= 0]
        win_rate    = len(winners) / len(trade_returns) if trade_returns else None
        avg_winner  = sum(winners) / len(winners) if winners else None
        avg_loser   = sum(losers) / len(losers) if losers else None
        gross_profit = sum(winners)
        gross_loss   = abs(sum(losers)) if losers else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

        pos_tickers = sum(1 for _, (q, _) in positions.items() if q > 0)
        exposure_pct = (1 - current_cash / final_nav) * 100 if final_nav > 0 else 0

        return {
            "book_id": book_id,
            "trade_count": len(fills),
            "cumulative_return": round(cum_return, 6),
            "max_drawdown": round(max_drawdown, 6),
            "turnover": round(turnover, 4),
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "avg_winner": round(avg_winner, 6) if avg_winner is not None else None,
            "avg_loser": round(avg_loser, 6) if avg_loser is not None else None,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "exposure_pct": round(exposure_pct, 2),
            "open_positions": pos_tickers,
        }
    finally:
        conn.close()
