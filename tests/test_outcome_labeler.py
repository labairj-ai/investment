"""Tests for agents/learning/outcome_labeler.py (0328)."""
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _days_ago(n: int) -> float:
    return time.time() - n * 86400


def _date_n_days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _insert_episode(conn, ticker="ANET", days_old=30, ep_id=None):
    import uuid
    ep_id = ep_id or str(uuid.uuid4())
    conn.execute(
        """INSERT INTO decision_episodes
           (episode_id, run_id, ticker, captured_at, selected, composite_score,
            feature_schema_version)
           VALUES (?,?,?,?,?,?,?)""",
        (ep_id, 1, ticker, _days_ago(days_old), 1, 72, "v1"),
    )
    conn.commit()
    return ep_id


def _fetch_outcomes(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM episode_outcomes").fetchall()]


def _make_conn(db_file):
    import sqlite3
    conn = sqlite3.connect(str(db_file), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class TestLabelMatureEpisodes:
    def test_labels_1w_horizon(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        ep_id = _insert_episode(conn, ticker="ANET", days_old=10)
        conn.close()

        # Mock price fetches: entry price 300, horizon price 315 (+5%)
        # SPY: entry 500, horizon 505 (+1%)
        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=300.0) as mock_price, \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.06, -0.01)):
            # Make horizon price different from entry price
            def price_side_effect(ticker, d):
                # Return slightly higher price for horizon date (second call per horizon)
                return 300.0 if d <= _date_n_days_ago(10) else 315.0
            mock_price.side_effect = price_side_effect

            result = label_mature_episodes(min_age_days=7)

        assert result["episodes_checked"] == 1
        assert result["horizons_written"] >= 1

        conn = _make_conn(mem_db)
        outcomes = _fetch_outcomes(conn)
        conn.close()

        assert any(o["horizon"] == "1w" and o["episode_id"] == ep_id for o in outcomes)

    def test_skips_future_horizons(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _insert_episode(conn, ticker="ANET", days_old=10)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=300.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.05, -0.02)):
            result = label_mature_episodes(min_age_days=7)

        conn = _make_conn(mem_db)
        horizons = {o["horizon"] for o in _fetch_outcomes(conn)}
        conn.close()
        # 10-day-old episode should NOT have 1m/3m/6m/12m labeled
        assert "1m" not in horizons
        assert "3m" not in horizons

    def test_skips_episodes_too_young(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _insert_episode(conn, ticker="ANET", days_old=3)  # only 3 days old
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=300.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(None, None)):
            result = label_mature_episodes(min_age_days=7)

        assert result["episodes_checked"] == 0
        assert result["horizons_written"] == 0

    def test_idempotent_no_duplicate_rows(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _insert_episode(conn, ticker="ANET", days_old=10)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=300.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.05, -0.02)):
            label_mature_episodes(min_age_days=7)
            result2 = label_mature_episodes(min_age_days=7)

        # Second run should write 0 new horizons (already labeled)
        assert result2["horizons_written"] == 0

        conn = _make_conn(mem_db)
        outcomes = _fetch_outcomes(conn)
        conn.close()
        # No duplicate rows per (episode_id, horizon)
        pairs = [(o["episode_id"], o["horizon"]) for o in outcomes]
        assert len(pairs) == len(set(pairs))

    def test_alpha_computed_correctly(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        ep_id = _insert_episode(conn, ticker="ANET", days_old=10)
        conn.close()

        def price_side_effect(ticker, d):
            # entry=300, horizon=330 → +10%
            return 300.0 if d <= _date_n_days_ago(10) else 330.0

        def spy_side_effect(d):
            # SPY entry=500, horizon=505 → +1%
            return 500.0 if d <= _date_n_days_ago(10) else 505.0

        with patch("agents.learning.outcome_labeler._get_ticker_price",
                   side_effect=price_side_effect), \
             patch("agents.learning.outcome_labeler._spy_price_at",
                   side_effect=spy_side_effect), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.12, -0.02)):
            label_mature_episodes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT * FROM episode_outcomes WHERE episode_id=? AND horizon='1w'",
            (ep_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["ticker_return"] == pytest.approx(0.10, abs=0.001)
        assert row["spy_return"] == pytest.approx(0.01, abs=0.001)
        assert row["alpha"] == pytest.approx(0.09, abs=0.001)
        assert row["mfe"] == pytest.approx(0.12, abs=0.001)
        assert row["mae"] == pytest.approx(-0.02, abs=0.001)

    def test_missing_price_skips_horizon(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _insert_episode(conn, ticker="DELISTED", days_old=10)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=None):
            result = label_mature_episodes(min_age_days=7)

        assert result["horizons_written"] == 0

    def test_dry_run_writes_nothing(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_mature_episodes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _insert_episode(conn, ticker="ANET", days_old=10)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=300.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.05, -0.02)):
            label_mature_episodes(min_age_days=7, dry_run=True)

        conn = _make_conn(mem_db)
        outcomes = _fetch_outcomes(conn)
        conn.close()
        assert outcomes == []
