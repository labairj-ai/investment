"""Daily mark-to-market NAV update for virtual portfolio books (0351/0357).

Runs nightly after market close. For each virtual book:
  1. Reconstructs net holdings from virtual_fills.
  2. Closes positions older than BOOK_HOLD_DAYS with a synthetic SELL fill (0357).
  3. Fetches closing prices for remaining open positions via yfinance.
  4. Writes one virtual_book_nav row per book with fully marked-to-market NAV.

Scheduled via systemd timer: book-mtm.timer (Mon–Fri 18:30 ET, after outcome-labeler).
"""
from __future__ import annotations

import json
import time
from datetime import date as _date, datetime, timedelta, timezone

import agent_db

# Exit positions held longer than this many calendar days (0357)
BOOK_HOLD_DAYS = 63  # ~3 months, matching the alpha labeling horizon

_SPY_ANCHOR_KEY = "SPY_ANCHOR"  # stored as special ticker in virtual_books.label for SPY reference


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_holdings(conn, book_id: str) -> dict[str, dict]:
    """Reconstruct net holdings from virtual_fills.

    Returns {ticker: {qty, first_buy_date, avg_cost}} for all tickers with qty > 0.
    """
    rows = conn.execute(
        """SELECT ticker, action, qty, price, filled_at FROM virtual_fills
           WHERE book_id=? ORDER BY filled_at""",
        (book_id,),
    ).fetchall()

    holdings: dict[str, dict] = {}
    for row in rows:
        t = row["ticker"]
        a = (row["action"] or "BUY").upper()
        q = float(row["qty"])
        p = float(row["price"])
        date_str = (row["filled_at"] or "")[:10]

        if a == "BUY":
            if t not in holdings:
                holdings[t] = {"qty": 0.0, "avg_cost": 0.0, "first_buy_date": date_str}
            prev = holdings[t]
            new_qty = prev["qty"] + q
            new_cost = (prev["avg_cost"] * prev["qty"] + p * q) / new_qty if new_qty else p
            holdings[t] = {
                "qty": new_qty,
                "avg_cost": new_cost,
                "first_buy_date": prev["first_buy_date"],
            }
        elif a in ("SELL", "EXIT", "TRIM"):
            if t in holdings:
                holdings[t]["qty"] = max(0.0, holdings[t]["qty"] - q)

    return {t: d for t, d in holdings.items() if d["qty"] > 0}


def _emit_synthetic_sell(conn, book_id: str, ticker: str, qty: float, price: float,
                         date_str: str, origin: str) -> float:
    """Insert a synthetic SELL fill and update virtual_books.current_cash.

    Returns proceeds added to cash.
    """
    from agents.learning.book_simulator import _DEFAULT_SLIPPAGE_PCT
    fill_price = round(price * (1 - _DEFAULT_SLIPPAGE_PCT / 100), 2)
    proceeds = int(qty) * fill_price
    now = _now_iso()
    conn.execute(
        """INSERT INTO virtual_fills
           (book_id, episode_id, ticker, action, price, qty, fees, filled_at,
            decision_origin, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (book_id, None, ticker, "SELL", fill_price, int(qty), 0.0, now, origin, time.time()),
    )
    conn.execute(
        """UPDATE virtual_books
           SET current_cash = current_cash + ?, as_of = ?
           WHERE book_id = ?""",
        (proceeds, date_str, book_id),
    )
    return proceeds


def run_mark_to_market(date_str: str | None = None) -> dict:
    """Compute mark-to-market NAV for all virtual books for a given date.

    Fetches closing prices for open positions, emits synthetic SELL fills for
    positions older than BOOK_HOLD_DAYS, writes virtual_book_nav rows with
    fully marked NAV values.

    Returns {"books_updated": int, "holds_expired": int, "errors": list}.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        import yfinance as yf
    except ImportError:
        return {"books_updated": 0, "holds_expired": 0, "errors": ["yfinance not available"]}

    today = _date.fromisoformat(date_str)
    errors: list[str] = []
    books_updated = 0
    holds_expired = 0

    conn = agent_db._connect()
    try:
        books = conn.execute(
            "SELECT book_id, starting_cash, current_cash FROM virtual_books"
        ).fetchall()

        # Fetch SPY close for NAV-indexing
        spy_close: float | None = None
        try:
            hist = yf.Ticker("SPY").history(period="5d", auto_adjust=False)
            if not hist.empty:
                spy_close = float(hist["Close"].iloc[-1])
        except Exception as e:
            errors.append(f"SPY fetch: {e}")

        # Get SPY close at the earliest virtual_fills date (anchor for SPY NAV series)
        spy_anchor: float | None = None
        try:
            first_fill_row = conn.execute(
                "SELECT filled_at FROM virtual_fills ORDER BY filled_at ASC LIMIT 1"
            ).fetchone()
            if first_fill_row:
                anchor_date = (first_fill_row["filled_at"] or "")[:10]
                anchor_hist = yf.Ticker("SPY").history(start=anchor_date, end=anchor_date,
                                                        auto_adjust=False)
                if anchor_hist.empty:
                    # try a few days forward in case of weekend/holiday
                    anchor_hist = yf.Ticker("SPY").history(
                        start=anchor_date,
                        end=(_date.fromisoformat(anchor_date) + timedelta(days=5)).isoformat(),
                        auto_adjust=False,
                    )
                if not anchor_hist.empty:
                    spy_anchor = float(anchor_hist["Close"].iloc[0])
        except Exception as e:
            errors.append(f"SPY anchor fetch: {e}")

        for book in books:
            book_id = book["book_id"]
            starting_cash = float(book["starting_cash"])

            try:
                # 1. Reconstruct current holdings
                holdings = _get_holdings(conn, book_id)

                # 2. Expire positions older than BOOK_HOLD_DAYS (0357)
                expire_cutoff = (today - timedelta(days=BOOK_HOLD_DAYS)).isoformat()
                for ticker, info in list(holdings.items()):
                    if info["first_buy_date"] <= expire_cutoff:
                        # Fetch closing price for the exit
                        exit_price = info["avg_cost"]  # fallback
                        try:
                            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
                            if not hist.empty:
                                exit_price = float(hist["Close"].iloc[-1])
                        except Exception:
                            pass
                        origin = "CHAMPION" if book_id == "CHAMPION_BOOK" else "PAPER_CHALLENGER"
                        _emit_synthetic_sell(
                            conn, book_id, ticker, info["qty"], exit_price, date_str, origin
                        )
                        del holdings[ticker]
                        holds_expired += 1

                # Reload cash after exits
                cash_row = conn.execute(
                    "SELECT current_cash FROM virtual_books WHERE book_id=?", (book_id,)
                ).fetchone()
                current_cash = float(cash_row["current_cash"]) if cash_row else starting_cash

                # 3. Mark open positions to closing prices
                prices: dict[str, float] = {}
                for ticker in holdings:
                    try:
                        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
                        if not hist.empty:
                            prices[ticker] = float(hist["Close"].iloc[-1])
                    except Exception as e:
                        errors.append(f"{ticker} price: {e}")

                market_value = sum(
                    info["qty"] * prices.get(t, info["avg_cost"])
                    for t, info in holdings.items()
                )
                total_nav = current_cash + market_value

                # 4. SPY NAV indexed to starting_cash
                spy_nav: float | None = None
                if spy_close is not None and spy_anchor and spy_anchor > 0:
                    spy_nav = (spy_close / spy_anchor) * starting_cash
                elif spy_close is not None:
                    spy_nav = spy_close  # raw fallback

                # 5. Daily return vs previous row
                prev_row = conn.execute(
                    """SELECT total_nav FROM virtual_book_nav
                       WHERE book_id=? ORDER BY date DESC LIMIT 1""",
                    (book_id,),
                ).fetchone()
                daily_return: float | None = None
                if prev_row and prev_row["total_nav"] and float(prev_row["total_nav"]) > 0:
                    daily_return = (total_nav / float(prev_row["total_nav"])) - 1.0

                # 6. Write the NAV row
                positions_json = json.dumps({
                    t: {
                        "qty": info["qty"],
                        "mark_price": prices.get(t),
                        "avg_cost": info["avg_cost"],
                        "market_value": info["qty"] * prices.get(t, info["avg_cost"]),
                    }
                    for t, info in holdings.items()
                })
                conn.execute(
                    """INSERT OR REPLACE INTO virtual_book_nav
                       (book_id, date, cash, positions_json, total_nav, spy_nav, daily_return, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (book_id, date_str, current_cash, positions_json,
                     total_nav, spy_nav, daily_return, time.time()),
                )
                books_updated += 1

            except Exception as e:
                errors.append(f"{book_id}: {e}")

        conn.commit()
    finally:
        conn.close()

    return {"books_updated": books_updated, "holds_expired": holds_expired, "errors": errors}


def mtm_rows_available(conn, min_rows: int = 30) -> bool:
    """Return True when enough MTM rows exist to remove the 'experimental' badge (0351)."""
    row = conn.execute(
        """SELECT COUNT(DISTINCT date) as n FROM virtual_book_nav
           WHERE spy_nav IS NOT NULL AND daily_return IS NOT NULL"""
    ).fetchone()
    return bool(row and row["n"] >= min_rows)


if __name__ == "__main__":
    result = run_mark_to_market()
    print(f"[book_mtm] {result}")
