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
