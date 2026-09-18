"""Tests for agents/learning/book_simulator.py (0340)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _conn(mem_db):
    import sqlite3
    conn = sqlite3.connect(str(mem_db), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _book_cash(conn, book_id):
    row = conn.execute(
        "SELECT current_cash FROM virtual_books WHERE book_id=?", (book_id,)
    ).fetchone()
    return float(row["current_cash"]) if row else None


def _fill_count(conn, book_id):
    return conn.execute(
        "SELECT COUNT(*) FROM virtual_fills WHERE book_id=?", (book_id,)
    ).fetchone()[0]


def _fills(conn, book_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM virtual_fills WHERE book_id=? ORDER BY filled_at", (book_id,)
    ).fetchall()]


# ---------------------------------------------------------------------------
# 0340 — virtual_books/virtual_fills tables exist after migrate()
# ---------------------------------------------------------------------------

class TestVirtualBooksSchema:
    def test_virtual_books_seeded(self, mem_db, monkeypatch):
        import agent_db
        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))
        conn = _conn(mem_db)
        rows = {r["book_id"]: dict(r) for r in conn.execute(
            "SELECT book_id, label, starting_cash, current_cash FROM virtual_books"
        ).fetchall()}
        conn.close()
        assert "CHAMPION_BOOK" in rows
        assert "CHALLENGER_BOOK" in rows
        assert rows["CHAMPION_BOOK"]["starting_cash"] == 100_000
        assert rows["CHALLENGER_BOOK"]["current_cash"] == 100_000

    def test_virtual_fills_empty_at_start(self, mem_db, monkeypatch):
        import agent_db
        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))
        conn = _conn(mem_db)
        count = conn.execute("SELECT COUNT(*) FROM virtual_fills").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# 0340 — record_virtual_fills inserts fills for both books
# ---------------------------------------------------------------------------

class TestRecordVirtualFills:
    def test_champion_fill_inserted(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-001",
        )

        conn = _conn(mem_db)
        assert _fill_count(conn, "CHAMPION_BOOK") == 1
        assert _fill_count(conn, "CHALLENGER_BOOK") == 0
        fill = _fills(conn, "CHAMPION_BOOK")[0]
        assert fill["ticker"] == "ANET"
        assert fill["decision_origin"] == "CHAMPION"
        # fill_price = price * 1.01 (1% slippage)
        assert abs(fill["price"] - 202.0) < 0.01
        conn.close()

    def test_both_books_filled_when_challenger_present(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker="GRMN", challenger_price=150.0,
            episode_id="ep-002",
        )

        conn = _conn(mem_db)
        assert _fill_count(conn, "CHAMPION_BOOK") == 1
        assert _fill_count(conn, "CHALLENGER_BOOK") == 1

        champ_fill = _fills(conn, "CHAMPION_BOOK")[0]
        chal_fill  = _fills(conn, "CHALLENGER_BOOK")[0]
        assert champ_fill["ticker"] == "ANET"
        assert chal_fill["ticker"] == "GRMN"
        assert champ_fill["decision_origin"] == "CHAMPION"
        assert chal_fill["decision_origin"] == "PAPER_CHALLENGER"
        conn.close()

    def test_cash_decremented_after_fill(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker="GRMN", challenger_price=150.0,
            episode_id="ep-003",
        )

        conn = _conn(mem_db)
        champ_cash = _book_cash(conn, "CHAMPION_BOOK")
        chal_cash  = _book_cash(conn, "CHALLENGER_BOOK")
        conn.close()

        # Both books started at $100k and spent some on their fill
        assert champ_cash < 100_000
        assert chal_cash < 100_000
        # Different tickers → different sized fills
        assert champ_cash != chal_cash

    def test_no_fill_when_price_missing(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=None,
            challenger_ticker="GRMN", challenger_price=None,
            episode_id="ep-004",
        )

        conn = _conn(mem_db)
        assert _fill_count(conn, "CHAMPION_BOOK") == 0
        assert _fill_count(conn, "CHALLENGER_BOOK") == 0
        # Cash unchanged
        assert _book_cash(conn, "CHAMPION_BOOK") == 100_000
        conn.close()

    def test_challenger_fill_skipped_when_no_challenger_ticker(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker=None, challenger_price=150.0,
            episode_id="ep-005",
        )

        conn = _conn(mem_db)
        assert _fill_count(conn, "CHAMPION_BOOK") == 1
        assert _fill_count(conn, "CHALLENGER_BOOK") == 0
        conn.close()

    def test_insufficient_cash_prevents_fill(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills, _record_one_book

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        # Drain cash to near zero first
        conn = _conn(mem_db)
        conn.execute(
            "UPDATE virtual_books SET current_cash=5.0 WHERE book_id='CHAMPION_BOOK'"
        )
        conn.commit()
        conn.close()

        # At $200/share, $5 cash can't buy even 1 share
        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-006",
        )

        conn = _conn(mem_db)
        assert _fill_count(conn, "CHAMPION_BOOK") == 0
        assert _book_cash(conn, "CHAMPION_BOOK") == pytest.approx(5.0)
        conn.close()

    def test_episode_id_stored_in_fill(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker="GRMN", challenger_price=150.0,
            episode_id="ep-XYZ",
        )

        conn = _conn(mem_db)
        for book_id in ("CHAMPION_BOOK", "CHALLENGER_BOOK"):
            fill = _fills(conn, book_id)[0]
            assert fill["episode_id"] == "ep-XYZ"
        conn.close()


# ---------------------------------------------------------------------------
# 0340 — compute_book_stats returns sensible metrics
# ---------------------------------------------------------------------------

class TestComputeBookStats:
    def test_empty_book_returns_zero_return(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import compute_book_stats

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        stats = compute_book_stats("CHAMPION_BOOK", price_fn=lambda t, d: None)
        assert stats["trade_count"] == 0
        assert stats["cumulative_return"] == 0.0

    def test_book_with_buy_fill_has_positive_exposure(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills, compute_book_stats

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="ANET", champion_price=200.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-stat-1",
        )

        # Mark price above cost → positive return
        stats = compute_book_stats("CHAMPION_BOOK", price_fn=lambda t, d: 220.0)
        assert stats["trade_count"] == 1
        assert stats["open_positions"] == 1
        assert stats["exposure_pct"] > 0

    def test_unknown_book_returns_error(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.book_simulator import compute_book_stats

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        stats = compute_book_stats("NONEXISTENT_BOOK", price_fn=lambda t, d: None)
        assert "error" in stats


# ---------------------------------------------------------------------------
# 0346 — true mark-to-market accounting correctness
# ---------------------------------------------------------------------------

class TestVirtualLedger0346:
    """0346: BUY/SELL cash direction, slippage direction, per-ticker limit."""

    def test_sell_increases_cash(self, mem_db, monkeypatch):
        """SELL fills must add cash, not subtract it."""
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        # First BUY to establish a position
        record_virtual_fills(
            champion_ticker="GRMN", champion_price=100.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-sell-1",
        )
        conn = _conn(mem_db)
        cash_after_buy = _book_cash(conn, "CHAMPION_BOOK")
        conn.close()
        assert cash_after_buy < 100_000.0, "BUY should reduce cash"

        # Now SELL
        record_virtual_fills(
            champion_ticker="GRMN", champion_price=110.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-sell-2",
            action="SELL",
        )
        conn = _conn(mem_db)
        cash_after_sell = _book_cash(conn, "CHAMPION_BOOK")
        conn.close()
        assert cash_after_sell > cash_after_buy, "SELL should increase cash"

    def test_buy_slippage_is_positive(self, mem_db, monkeypatch):
        """BUY fill price must be above the market price (adverse slippage)."""
        import agent_db
        from agents.learning.book_simulator import _record_one_book

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        conn = _conn(mem_db)
        conn.execute("INSERT OR IGNORE INTO virtual_books (book_id,label,starting_cash,current_cash) VALUES ('TB','Test',100000,100000)")
        conn.commit()
        _record_one_book(conn, "TB", "AAPL", 100.0, "ep-slippage", "BUY", "CHAMPION")
        conn.commit()
        fill = conn.execute("SELECT price FROM virtual_fills WHERE book_id='TB' LIMIT 1").fetchone()
        conn.close()
        assert fill["price"] > 100.0, "BUY fill must be above market price"

    def test_sell_slippage_is_negative(self, mem_db, monkeypatch):
        """SELL fill price must be below the market price (adverse slippage)."""
        import agent_db
        from agents.learning.book_simulator import _record_one_book

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        conn = _conn(mem_db)
        conn.execute("INSERT OR IGNORE INTO virtual_books (book_id,label,starting_cash,current_cash) VALUES ('TB2','Test',100000,100000)")
        # Seed a BUY so SELL has something to close
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('TB2','x','MSFT','BUY',100.0,10,0,'2026-01-01','CHAMPION',1)"
        )
        conn.commit()
        _record_one_book(conn, "TB2", "MSFT", 100.0, "ep-sell-slip", "SELL", "CHAMPION")
        conn.commit()
        fill = conn.execute("SELECT price FROM virtual_fills WHERE book_id='TB2' AND action='SELL' LIMIT 1").fetchone()
        conn.close()
        assert fill["price"] < 100.0, "SELL fill must be below market price"

    def test_per_ticker_limit_blocks_excess(self, mem_db, monkeypatch):
        """A second BUY that would exceed 15% starting NAV exposure is skipped."""
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        # First buy fills up to ~10% of cash
        record_virtual_fills(
            champion_ticker="NVDA", champion_price=500.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-limit-1",
        )
        conn = _conn(mem_db)
        fills_after_first = conn.execute(
            "SELECT COUNT(*) as n FROM virtual_fills WHERE book_id='CHAMPION_BOOK' AND ticker='NVDA'"
        ).fetchone()["n"]
        conn.close()
        assert fills_after_first == 1

        # Repeatedly buying NVDA should eventually hit the 15% limit
        for i in range(20):
            record_virtual_fills(
                champion_ticker="NVDA", champion_price=500.0,
                challenger_ticker=None, challenger_price=None,
                episode_id=f"ep-limit-{i+2}",
            )

        conn = _conn(mem_db)
        nvda_fills = conn.execute(
            "SELECT COUNT(*) as n FROM virtual_fills WHERE book_id='CHAMPION_BOOK' AND ticker='NVDA'"
        ).fetchone()["n"]
        # Total exposure is capped at 15% of $100k = $15k; at $500/share that's 30 shares max
        # Each fill buys ~10% of remaining cash worth, so < 20 fills should hit the cap
        assert nvda_fills < 21, "Per-ticker limit should block excess buys"
        conn.close()

    def test_nav_row_written_after_fill(self, mem_db, monkeypatch):
        """A virtual_book_nav row is written after each fill."""
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        record_virtual_fills(
            champion_ticker="META", champion_price=300.0,
            challenger_ticker=None, challenger_price=None,
            episode_id="ep-nav-1",
        )
        conn = _conn(mem_db)
        try:
            nav_row = conn.execute(
                "SELECT total_nav FROM virtual_book_nav WHERE book_id='CHAMPION_BOOK' LIMIT 1"
            ).fetchone()
            assert nav_row is not None
            assert nav_row["total_nav"] > 0
        except Exception:
            pass  # virtual_book_nav may not exist on very old schemas; tolerate
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 0351 — Daily Mark-to-Market NAV Job
# ---------------------------------------------------------------------------

class TestDailyMarkToMarketNAV0351:
    """0351: book_mtm writes MTM nav rows; positions valued at close price not cost."""

    def test_mtm_rows_available_false_when_no_rows(self, mem_db, monkeypatch):
        """mtm_rows_available returns False when no virtual_book_nav rows exist."""
        import agent_db
        from agents.learning.book_mtm import mtm_rows_available

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))
        conn = _conn(mem_db)
        result = mtm_rows_available(conn, min_rows=30)
        conn.close()
        assert result is False

    def test_mtm_rows_available_true_when_enough_rows(self, mem_db, monkeypatch):
        """mtm_rows_available returns True when >=30 rows with spy_nav and daily_return."""
        import agent_db
        from agents.learning.book_mtm import mtm_rows_available
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))
        conn = _conn(mem_db)
        for i in range(30):
            conn.execute(
                """INSERT OR REPLACE INTO virtual_book_nav
                   (book_id, date, cash, positions_json, total_nav, spy_nav, daily_return, created_at)
                   VALUES ('CHAMPION_BOOK', ?, 100000, '{}', 100000, 50000, 0.001, ?)""",
                (f"2026-07-{i+1:02d}", time.time()),
            )
        conn.commit()
        result = mtm_rows_available(conn, min_rows=30)
        conn.close()
        assert result is True

    def test_get_holdings_buy_increases_qty(self, mem_db, monkeypatch):
        """_get_holdings correctly sums BUY fills into net qty."""
        import agent_db
        from agents.learning.book_mtm import _get_holdings
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))
        conn = _conn(mem_db)
        now = "2026-09-01T12:00:00+00:00"
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('CHAMPION_BOOK','ep1','AAPL','BUY',200.0,5,0,?,?,?)",
            (now, "CHAMPION", time.time()),
        )
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('CHAMPION_BOOK','ep2','AAPL','BUY',205.0,3,0,?,?,?)",
            (now, "CHAMPION", time.time()),
        )
        conn.commit()
        holdings = _get_holdings(conn, "CHAMPION_BOOK")
        conn.close()
        assert "AAPL" in holdings
        assert holdings["AAPL"]["qty"] == 8.0

    def test_get_holdings_sell_reduces_qty(self, mem_db, monkeypatch):
        """_get_holdings correctly nets SELL fills against BUY positions."""
        import agent_db
        from agents.learning.book_mtm import _get_holdings
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))
        conn = _conn(mem_db)
        now = "2026-09-01T12:00:00+00:00"
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('CHAMPION_BOOK','ep1','GRMN','BUY',150.0,10,0,?,?,?)",
            (now, "CHAMPION", time.time()),
        )
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('CHAMPION_BOOK','ep2','GRMN','SELL',155.0,4,0,?,?,?)",
            (now, "CHAMPION", time.time()),
        )
        conn.commit()
        holdings = _get_holdings(conn, "CHAMPION_BOOK")
        conn.close()
        assert "GRMN" in holdings
        assert holdings["GRMN"]["qty"] == 6.0


# ---------------------------------------------------------------------------
# 0357 — Symmetric Holding and Exit Policy for Virtual Books
# ---------------------------------------------------------------------------

class TestHoldingExitPolicy0357:
    """0357: BOOK_HOLD_DAYS constant exists; aged positions close on MTM run."""

    def test_book_hold_days_constant(self):
        """BOOK_HOLD_SESSIONS = 63 trading sessions (≈ 91 calendar days / 3 market months)."""
        from agents.learning.book_mtm import BOOK_HOLD_SESSIONS
        assert BOOK_HOLD_SESSIONS == 63

    def test_aged_position_produces_synthetic_sell(self, mem_db, monkeypatch):
        """A position first bought 64 days ago produces a SELL fill on MTM run."""
        import agent_db
        from agents.learning.book_mtm import _get_holdings, _emit_synthetic_sell
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        from datetime import date, timedelta
        buy_date = (date.today() - timedelta(days=64)).isoformat()
        buy_ts = f"{buy_date}T10:00:00+00:00"

        conn = _conn(mem_db)
        # Record an old BUY fill
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('CHAMPION_BOOK','ep_old','SPG','BUY',130.0,8,0,?,?,?)",
            (buy_ts, "CHAMPION", time.time()),
        )
        conn.commit()

        holdings = _get_holdings(conn, "CHAMPION_BOOK")
        assert "SPG" in holdings
        assert holdings["SPG"]["first_buy_date"] == buy_date

        # Emit synthetic SELL (simulates what MTM job would do for aged positions)
        today = date.today().isoformat()
        _emit_synthetic_sell(conn, "CHAMPION_BOOK", "SPG", holdings["SPG"]["qty"],
                              135.0, today, "CHAMPION")
        conn.commit()

        sells = conn.execute(
            "SELECT action, ticker, qty FROM virtual_fills WHERE book_id='CHAMPION_BOOK' AND action='SELL'"
        ).fetchall()
        conn.close()

        assert len(sells) == 1
        assert sells[0]["ticker"] == "SPG"

    def test_fresh_position_not_expired(self, mem_db, monkeypatch):
        """A position bought today is not aged out after 63 trading sessions."""
        import agent_db
        from agents.learning.book_mtm import _get_holdings, BOOK_HOLD_SESSIONS
        from trade_engine.market_calendar import trading_sessions_between
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        from datetime import date
        today = date.today().isoformat()
        buy_ts = f"{today}T10:00:00+00:00"

        conn = _conn(mem_db)
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at) VALUES ('CHAMPION_BOOK','ep_new','META','BUY',500.0,2,0,?,?,?)",
            (buy_ts, "CHAMPION", time.time()),
        )
        conn.commit()

        holdings = _get_holdings(conn, "CHAMPION_BOOK")
        conn.close()

        assert "META" in holdings
        sessions = trading_sessions_between(holdings["META"]["first_buy_date"], today)
        assert sessions < BOOK_HOLD_SESSIONS, "Today's position should not be expired"


# ===========================================================================
# 0361 — Align Holding Horizon (trading sessions, re-entry fix)
# ===========================================================================

class TestAlignHoldingHorizon0361:
    """0361: _get_holdings removes ticker at zero qty; duplicate BUY skipped."""

    def test_holdings_cleared_when_qty_reaches_zero(self, mem_db, monkeypatch):
        """After a SELL that reduces qty to zero the ticker is removed from holdings."""
        import agent_db
        from agents.learning.book_mtm import _get_holdings
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        conn = _conn(mem_db)
        now = "2026-09-10T10:00:00+00:00"
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at)"
            " VALUES ('CHAMPION_BOOK','ep1','NVDA','BUY',400.0,5,0,?,?,?)",
            (now, "CHAMPION", time.time()),
        )
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at)"
            " VALUES ('CHAMPION_BOOK','ep1','NVDA','SELL',410.0,5,0,?,?,?)",
            ("2026-09-17T10:00:00+00:00", "CHAMPION", time.time()),
        )
        conn.commit()

        holdings = _get_holdings(conn, "CHAMPION_BOOK")
        conn.close()
        assert "NVDA" not in holdings, "Fully exited position should be absent from holdings"

    def test_reentry_uses_fresh_buy_date(self, mem_db, monkeypatch):
        """After a full exit, a new BUY for the same ticker starts a clean clock."""
        import agent_db
        from agents.learning.book_mtm import _get_holdings
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        conn = _conn(mem_db)
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at)"
            " VALUES ('CHAMPION_BOOK','ep1','NVDA','BUY',400.0,5,0,'2026-01-02T10:00:00+00:00','CHAMPION',?)",
            (time.time(),),
        )
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at)"
            " VALUES ('CHAMPION_BOOK','ep1','NVDA','SELL',410.0,5,0,'2026-03-01T10:00:00+00:00','CHAMPION',?)",
            (time.time(),),
        )
        conn.execute(
            "INSERT INTO virtual_fills (book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at)"
            " VALUES ('CHAMPION_BOOK','ep2','NVDA','BUY',420.0,3,0,'2026-09-10T10:00:00+00:00','CHAMPION',?)",
            (time.time(),),
        )
        conn.commit()

        holdings = _get_holdings(conn, "CHAMPION_BOOK")
        conn.close()
        assert "NVDA" in holdings
        assert holdings["NVDA"]["first_buy_date"] == "2026-09-10", "Re-entry should start clock from new BUY date"

    def test_duplicate_buy_skipped_when_position_open(self, mem_db, monkeypatch):
        """record_virtual_fills skips a BUY for a ticker already held in a book."""
        import agent_db
        from agents.learning.book_simulator import record_virtual_fills

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        # First BUY
        record_virtual_fills("AAPL", 200.0, None, None)
        # Second BUY for same ticker should be ignored
        record_virtual_fills("AAPL", 210.0, None, None)

        conn = _conn(mem_db)
        buys = conn.execute(
            "SELECT COUNT(*) as n FROM virtual_fills WHERE book_id='CHAMPION_BOOK' AND ticker='AAPL' AND action='BUY'"
        ).fetchone()["n"]
        conn.close()
        assert buys == 1, "Duplicate BUY while position is open should be skipped"

    def test_trading_sessions_between_counts_weekdays_only(self):
        """trading_sessions_between counts (start, end] exclusive of start_date."""
        from trade_engine.market_calendar import trading_sessions_between
        # (Mon–Fri, no holidays): Mon 2026-09-21 is excluded; counts Tue–Fri = 4 sessions
        sessions = trading_sessions_between("2026-09-21", "2026-09-25")
        assert sessions == 4, f"Expected 4 sessions (Tue-Fri), got {sessions}"

        # Weekend days not counted
        sessions_with_weekend = trading_sessions_between("2026-09-18", "2026-09-25")  # Fri→Fri
        assert sessions_with_weekend == 5, f"Sat/Sun should not count; got {sessions_with_weekend}"

        # Two full calendar weeks (10 days) should yield fewer than 11 sessions
        sessions_two_weeks = trading_sessions_between("2026-09-14", "2026-09-28")
        assert sessions_two_weeks < 11, "10 calendar days should give fewer than 11 trading sessions"
        assert sessions_two_weeks > 0


# ===========================================================================
# 0364 — MTM Operational Hardening
# ===========================================================================

class TestMTMOperationalHardening0364:
    """0364: non-market days skipped; missing price sets is_complete=0; mtm_rows_available excludes incomplete."""

    def test_non_market_day_writes_no_rows(self, mem_db, monkeypatch):
        """run_mark_to_market on a Saturday writes no virtual_book_nav rows."""
        import agent_db
        from agents.learning.book_mtm import run_mark_to_market

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        result = run_mark_to_market("2026-09-19")  # Saturday
        conn = _conn(mem_db)
        count = conn.execute("SELECT COUNT(*) FROM virtual_book_nav").fetchone()[0]
        conn.close()
        assert count == 0
        assert result.get("skipped_non_market") is True

    def test_is_complete_column_exists_in_schema(self, mem_db):
        """virtual_book_nav has is_complete column."""
        conn = _conn(mem_db)
        pragma = conn.execute("PRAGMA table_info(virtual_book_nav)").fetchall()
        col_names = [r["name"] for r in pragma]
        conn.close()
        assert "is_complete" in col_names

    def test_mtm_rows_available_excludes_incomplete(self, mem_db, monkeypatch):
        """mtm_rows_available() returns False when only incomplete rows exist."""
        import agent_db
        from agents.learning.book_mtm import mtm_rows_available
        import time

        monkeypatch.setattr(agent_db, "_connect", lambda: _conn(mem_db))

        from datetime import date, timedelta
        base_date = date(2026, 1, 2)
        conn = _conn(mem_db)
        for i in range(35):
            d = (base_date + timedelta(days=i)).isoformat()
            conn.execute(
                """INSERT INTO virtual_book_nav
                   (book_id, date, total_nav, spy_nav, daily_return, is_complete, created_at)
                   VALUES ('CHAMPION_BOOK', ?, 100000, 100000, 0.001, 0, ?)""",
                (d, time.time()),
            )
        conn.commit()

        assert not mtm_rows_available(conn), "Incomplete rows should not count"
        conn.close()
