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


class TestRiskCounterfactualPipeline:
    """0332: risk rejection → counterfactual capture → outcome labeling."""

    def _insert_base_rejection(self, conn, ticker="AAPL", days_old=10, intent_id=None):
        import uuid
        intent_id = intent_id or str(uuid.uuid4())
        decision_date = (date.today() - timedelta(days=days_old)).isoformat()
        conn.execute("PRAGMA foreign_keys=OFF")
        # Dummy trade_intent row so FK on risk_counterfactual_outcomes resolves
        conn.execute(
            """INSERT OR IGNORE INTO trade_intents
               (intent_id, symbol, side, quantity, limit_price, order_type,
                time_in_force, strategy, valid_until, created_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (intent_id, ticker, "BUY", 10.0, 150.0, "LIMIT", "DAY",
             "test", "2099-01-01", "2026-01-01", "REJECTED"),
        )
        conn.execute(
            """INSERT INTO risk_counterfactual_outcomes
               (intent_id, ticker, side, quantity, limit_price,
                rejected_at, reject_rule, rejection_reason, decision_date, horizon)
               VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
            (intent_id, ticker, "BUY", 10.0, 150.0,
             _days_ago(days_old), "MAX_POSITION_PCT", "position would exceed 10%", decision_date),
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        return intent_id, decision_date

    def test_labeler_writes_counterfactual_horizon(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_risk_counterfactuals

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        intent_id, _ = self._insert_base_rejection(conn, days_old=10)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=150.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.03, -0.01)):
            result = label_risk_counterfactuals(min_age_days=7)

        assert result["rejections_checked"] == 1
        assert result["horizons_written"] >= 1

        conn = _make_conn(mem_db)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM risk_counterfactual_outcomes WHERE intent_id=? AND horizon IS NOT NULL",
            (intent_id,),
        ).fetchall()]
        conn.close()

        assert len(rows) >= 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["horizon"] in ("1w", "1m", "3m")
        assert rows[0]["ticker_return"] == pytest.approx(0.0)  # 150/150 - 1

    def test_labeler_skips_already_labeled(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_risk_counterfactuals

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        intent_id, decision_date = self._insert_base_rejection(conn, days_old=10)
        # Pre-insert a labeled row for 1w
        conn.execute(
            """INSERT INTO risk_counterfactual_outcomes
               (intent_id, ticker, decision_date, horizon, ticker_return, labeled_at)
               VALUES (?,?,?,?,?,?)""",
            (intent_id, "AAPL", decision_date, "1w", 0.05, time.time()),
        )
        conn.commit()
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=150.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.03, -0.01)):
            result = label_risk_counterfactuals(min_age_days=7)

        # 1w was already labeled; should have labeled 1m (since 10 days > 7 but < 30 for 1m)
        # Actually 10 days is not enough for 1m (30 days), so only 1w was eligible
        # so total written should be 0 for 1w (already done) and 0 for 1m/3m (not mature)
        conn = _make_conn(mem_db)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM risk_counterfactual_outcomes WHERE intent_id=? AND horizon='1w'",
            (intent_id,),
        ).fetchall()]
        conn.close()
        assert len(rows) == 1  # original only, not duplicated

    def test_risk_engine_writes_counterfactual_on_rejection(self, mem_db, monkeypatch):
        """Rejected intents produce a base counterfactual row."""
        import agent_db
        from trade_engine.risk_engine import _write_counterfactual_rejection

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        # Insert prerequisite account, then trade_intent with episode_id
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO trading_accounts (account_id, broker, mode)
               VALUES ('ACC','alpaca','paper')"""
        )
        conn.execute(
            """INSERT INTO trade_intents
               (intent_id, account_id, instrument_type, symbol, side, quantity, limit_price,
                order_type, time_in_force, strategy, valid_until, created_at, status, episode_id)
               VALUES ('int-001','ACC','EQUITY','AAPL','BUY',10,150,
                       'LIMIT','DAY','test','2099-01-01','2026-09-01','PENDING','ep-xyz')"""
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()

        class _FakeCheck:
            def __init__(self, rule, result, reason=None):
                self.rule = rule
                self.result = type("R", (), {"value": result})()
                self.reason = reason

        checks = [
            _FakeCheck("MAX_POSITION_PCT", "FAIL", "position too large"),
            _FakeCheck("CASH_FLOOR", "PASS"),
        ]

        _write_counterfactual_rejection("int-001", checks, "2026-09-17T14:00:00+00:00", conn)

        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM risk_counterfactual_outcomes WHERE intent_id='int-001' AND horizon IS NULL"
        ).fetchall()]
        conn.close()

        assert len(rows) == 1
        assert rows[0]["reject_rule"] == "MAX_POSITION_PCT"
        assert rows[0]["rejection_reason"] == "position too large"
        assert rows[0]["episode_id"] == "ep-xyz"
        assert rows[0]["ticker"] == "AAPL"
