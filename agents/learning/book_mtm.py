"""Daily mark-to-market NAV update for virtual portfolio books (0351/0357/0361/0364).

Runs nightly after market close. For each virtual book:
  1. Reconstructs net holdings from virtual_fills.
  2. Closes positions older than BOOK_HOLD_SESSIONS trading sessions (0357/0361).
  3. Fetches closing prices for remaining open positions via exact-date yfinance (0364).
  4. Writes one virtual_book_nav row per book with fully marked-to-market NAV.

Scheduled via systemd timer: book-mtm.timer (Mon–Fri 18:30 America/New_York).
"""
from __future__ import annotations

import json
import time
from datetime import date as _date, datetime, timedelta, timezone

import agent_db
from trade_engine.market_calendar import trading_sessions_between, is_market_open_on_date

# Exit positions held longer than this many trading sessions (0361: 63 sessions ≈ 91 calendar days)
BOOK_HOLD_SESSIONS = 63

_SPY_ANCHOR_KEY = "SPY_ANCHOR"  # stored as special ticker in virtual_books.label for SPY reference


def _get_closing_price(ticker: str, date_str: str) -> float | None:
    """Fetch the official closing price for date_str exactly. Returns None if unavailable (0364)."""
    try:
        import yfinance as yf
        d = _date.fromisoformat(date_str)
        hist = yf.download(
            ticker,
            start=(d - timedelta(days=5)).isoformat(),
            end=(d + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            progress=False,
            multi_level_column=False,
        )
        if hist.empty:
            return None
        hist.index = hist.index.astype(str).str[:10]
        if date_str in hist.index:
            return float(hist.loc[date_str, "Close"])
        return None
    except Exception:
        return None


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
                new_qty = holdings[t]["qty"] - q
                if new_qty <= 0:
                    del holdings[t]  # 0361: clean exit; fresh BUY starts a new clock
                else:
                    holdings[t]["qty"] = new_qty

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

    Fetches exact-date closing prices for open positions (0364), emits synthetic
    SELL fills for positions older than BOOK_HOLD_SESSIONS trading sessions (0361),
    writes virtual_book_nav rows with fully marked NAV values and is_complete flag.

    Returns {"books_updated": int, "holds_expired": int, "errors": list}.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 0364: skip non-market days entirely — don't write partial rows
    if not is_market_open_on_date(date_str):
        return {"books_updated": 0, "holds_expired": 0, "errors": [], "skipped_non_market": True}

    errors: list[str] = []
    books_updated = 0
    holds_expired = 0

    conn = agent_db._connect()
    try:
        books = conn.execute(
            "SELECT book_id, starting_cash, current_cash FROM virtual_books"
        ).fetchall()

        # Fetch SPY close for the exact date
        spy_close: float | None = _get_closing_price("SPY", date_str)
        if spy_close is None:
            errors.append(f"SPY fetch: no close for {date_str}")

        # Get SPY close at the earliest virtual_fills date (anchor for SPY NAV series)
        spy_anchor: float | None = None
        try:
            first_fill_row = conn.execute(
                "SELECT filled_at FROM virtual_fills ORDER BY filled_at ASC LIMIT 1"
            ).fetchone()
            if first_fill_row:
                anchor_date = (first_fill_row["filled_at"] or "")[:10]
                spy_anchor = _get_closing_price("SPY", anchor_date)
                if spy_anchor is None:
                    # try a few days forward in case anchor fell on a holiday
                    for delta in range(1, 6):
                        d_try = (_date.fromisoformat(anchor_date) + timedelta(days=delta)).isoformat()
                        spy_anchor = _get_closing_price("SPY", d_try)
                        if spy_anchor is not None:
                            break
        except Exception as e:
            errors.append(f"SPY anchor fetch: {e}")

        for book in books:
            book_id = book["book_id"]
            starting_cash = float(book["starting_cash"])

            try:
                # 1. Reconstruct current holdings
                holdings = _get_holdings(conn, book_id)

                # 2. Expire positions older than BOOK_HOLD_SESSIONS trading sessions (0361)
                for ticker, info in list(holdings.items()):
                    sessions = trading_sessions_between(info["first_buy_date"], date_str)
                    if sessions >= BOOK_HOLD_SESSIONS:
                        exit_price = _get_closing_price(ticker, date_str) or info["avg_cost"]
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

                # 3. Mark open positions to exact-date closing prices (0364)
                prices: dict[str, float] = {}
                any_incomplete = False
                for ticker in holdings:
                    p = _get_closing_price(ticker, date_str)
                    if p is not None:
                        prices[ticker] = p
                    else:
                        errors.append(f"{ticker}: no close for {date_str}")
                        any_incomplete = True

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

                # 6. Write the NAV row with is_complete flag (0364)
                is_complete = 0 if any_incomplete else 1
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
                       (book_id, date, cash, positions_json, total_nav, spy_nav,
                        daily_return, is_complete, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (book_id, date_str, current_cash, positions_json,
                     total_nav, spy_nav, daily_return, is_complete, time.time()),
                )
                books_updated += 1

            except Exception as e:
                errors.append(f"{book_id}: {e}")

        conn.commit()
    finally:
        conn.close()

    return {"books_updated": books_updated, "holds_expired": holds_expired, "errors": errors}


def mtm_rows_available(conn, min_rows: int = 30) -> bool:
    """Return True when enough complete MTM rows exist to remove the 'experimental' badge (0351/0364)."""
    try:
        row = conn.execute(
            """SELECT COUNT(DISTINCT date) as n FROM virtual_book_nav
               WHERE spy_nav IS NOT NULL AND daily_return IS NOT NULL AND is_complete=1"""
        ).fetchone()
    except Exception:
        # is_complete column may not exist on very old DBs — fall back without filter
        row = conn.execute(
            """SELECT COUNT(DISTINCT date) as n FROM virtual_book_nav
               WHERE spy_nav IS NOT NULL AND daily_return IS NOT NULL"""
        ).fetchone()
    return bool(row and row["n"] >= min_rows)


if __name__ == "__main__":
    result = run_mark_to_market()
    print(f"[book_mtm] {result}")
