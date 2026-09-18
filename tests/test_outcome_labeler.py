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
        # No duplicate rows per (episode_id, horizon, horizon_definition_version) — 0372
        triples = [(o["episode_id"], o["horizon"], o["horizon_definition_version"] or "calendar_v1")
                   for o in outcomes]
        assert len(triples) == len(set(triples))

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


class TestTradeOutcomePipeline:
    """0333: fill ingestion → trade_outcomes row → labeler populates returns."""

    def _insert_trade_outcome(self, conn, ticker="ANET", days_old=10, fill_id=None, fill_price=200.0):
        import uuid
        fill_id = fill_id or f"fill-{uuid.uuid4()}"
        fill_date = (date.today() - timedelta(days=days_old)).isoformat()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO trade_outcomes
               (fill_id, ticker, action, fill_date, fill_price, fill_qty, fill_fees,
                label_type, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (fill_id, ticker, "BUY", fill_date, fill_price, 10.0, 0.0,
             "EXECUTED_TRADE_RETURN", time.time()),
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        return fill_id, fill_date

    def test_labeler_writes_1w_return(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        fill_id, _ = self._insert_trade_outcome(conn, days_old=10, fill_price=200.0)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=210.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            result = label_trade_outcomes(min_age_days=7)

        assert result["fills_checked"] == 1
        assert result["horizons_written"] >= 1

        conn = _make_conn(mem_db)
        row = dict(conn.execute(
            "SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)
        ).fetchone())
        conn.close()

        assert row["return_1w"] == pytest.approx(0.05, abs=0.001)  # 210/200 - 1
        assert row["labeled_1w_at"] is not None

    def test_labeler_idempotent(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        self._insert_trade_outcome(conn, days_old=10, fill_price=200.0)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=210.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)
            result2 = label_trade_outcomes(min_age_days=7)

        assert result2["horizons_written"] == 0  # already labeled

    def test_spawn_trade_outcome_on_fill(self, mem_db, monkeypatch):
        """apply_broker_fill spawns a trade_outcomes row."""
        import agent_db
        from trade_engine.execution_engine import apply_broker_fill
        from trade_engine.broker_types import BrokerFill

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        # Seed account, trade_intent, order
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id, broker, mode, current_cash)"
            " VALUES ('ACC','alpaca','paper',50000)"
        )
        conn.execute(
            """INSERT OR IGNORE INTO trade_intents
               (intent_id, account_id, symbol, side, quantity, limit_price,
                order_type, time_in_force, strategy, valid_until, created_at, status)
               VALUES ('int-to','ACC','ANET','BUY',5,200,'LIMIT','DAY',
                       'test','2099-01-01','2026-01-01','PENDING')"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO orders
               (order_id, intent_id, account_id, symbol, side, quantity,
                order_type, time_in_force, broker_order_id, state)
               VALUES ('ord-to','int-to','ACC','ANET','BUY',5,'LIMIT','DAY',
                       'brk-ord-to','WORKING')"""
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()

        bf = BrokerFill(
            broker_fill_id="fill-to-001",
            broker_order_id="brk-ord-to",
            local_order_id="ord-to",
            account_id="ACC",
            symbol="ANET",
            side="BUY",
            qty=5,
            price=201.0,
            fee=0.0,
            filled_at="2026-09-10T14:30:00+00:00",
        )

        apply_broker_fill(bf, "ACC", conn)
        conn.close()

        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT * FROM trade_outcomes WHERE fill_id='fill-to-001'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["ticker"] == "ANET"
        assert row["fill_price"] == pytest.approx(201.0)
        assert row["label_type"] == "EXECUTED_TRADE_RETURN"

    def test_entry_date_uses_et_not_utc(self):
        """_entry_date uses ET, so 2025-01-01T04:00:00 UTC = 2024-12-31 ET (UTC-5 in winter)."""
        from agents.learning.outcome_labeler import _entry_date
        # 2025-01-01 00:00 UTC = 1735689600; +4h = 1735704000
        # In ET (UTC-5): 2024-12-31 23:00 → date is 2024-12-31
        ts = 1735704000.0  # 2025-01-01T04:00:00Z
        result = _entry_date(ts)
        assert result == "2024-12-31"


class TestDirectionAwareOutcomes0338:
    """0338: BUY/SELL/EXIT decision returns have correct sign semantics."""

    def _insert_trade_outcome_with_action(self, conn, action, days_old=10, fill_price=100.0):
        import uuid
        fill_id = f"fill-{uuid.uuid4()}"
        fill_date = (date.today() - timedelta(days=days_old)).isoformat()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO trade_outcomes
               (fill_id, ticker, action, fill_date, fill_price, fill_qty, fill_fees,
                label_type, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (fill_id, "ANET", action, fill_date, fill_price, 10.0, 0.0,
             "EXECUTED_TRADE_RETURN", time.time()),
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        return fill_id, fill_date

    def test_buy_fill_positive_return_gives_positive_decision_return(self, mem_db, monkeypatch):
        """BUY: price rises after fill → decision_return positive (good decision)."""
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        fill_id, _ = self._insert_trade_outcome_with_action(conn, "BUY", fill_price=100.0)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=110.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)
        ).fetchone()
        conn.close()

        assert row["return_1w"] == pytest.approx(0.10)
        assert row["decision_return_1w"] == pytest.approx(0.10)

    def test_exit_fill_price_drops_gives_positive_decision_return(self, mem_db, monkeypatch):
        """EXIT: price drops after fill → decision_return positive (exiting before drop was good)."""
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        fill_id, _ = self._insert_trade_outcome_with_action(conn, "EXIT", fill_price=100.0)
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=70.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)
        ).fetchone()
        conn.close()

        assert row["return_1w"] == pytest.approx(-0.30)           # price fell 30%
        assert row["decision_return_1w"] == pytest.approx(0.30)   # but exit decision was right

    def test_counterfactual_buy_blocked_then_price_falls_is_good_gate(self, mem_db, monkeypatch):
        """Blocked BUY: price falls → directional_return negative (gate correctly blocked it)."""
        import agent_db
        from agents.learning.outcome_labeler import label_risk_counterfactuals

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        import uuid
        intent_id = str(uuid.uuid4())
        decision_date = (date.today() - timedelta(days=10)).isoformat()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO trade_intents
               (intent_id, symbol, side, quantity, limit_price, order_type,
                time_in_force, strategy, valid_until, created_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (intent_id, "ANET", "BUY", 5.0, 200.0, "LIMIT", "DAY",
             "test", "2099-01-01", "2026-01-01", "REJECTED"),
        )
        conn.execute(
            """INSERT INTO risk_counterfactual_outcomes
               (intent_id, ticker, side, quantity, limit_price,
                rejected_at, reject_rule, rejection_reason, decision_date, horizon)
               VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
            (intent_id, "ANET", "BUY", 5.0, 200.0,
             time.time() - 10 * 86400, "MAX_POSITION_PCT", "test", decision_date),
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        conn.close()

        # Price falls 20% after blocked buy — gate was good
        # entry price = 200.0 (decision_date), horizon price = 160.0
        prices = {"entry": 200.0, "horizon": 160.0}
        call_count = {"n": 0}
        def _price_side_effect(ticker, date_str):
            call_count["n"] += 1
            return 200.0 if call_count["n"] % 2 == 1 else 160.0
        with patch("agents.learning.outcome_labeler._get_ticker_price", side_effect=_price_side_effect), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.0, -0.2)):
            label_risk_counterfactuals(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT * FROM risk_counterfactual_outcomes WHERE intent_id=? AND horizon IS NOT NULL LIMIT 1",
            (intent_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["ticker_return"] == pytest.approx(-0.20)
        assert row["directional_return"] == pytest.approx(-0.20)  # BUY: same sign as ticker_return

    def test_counterfactual_exit_blocked_then_price_falls_is_bad_gate(self, mem_db, monkeypatch):
        """Blocked SELL: price falls → directional_return positive (gate wrongly blocked the exit)."""
        import agent_db
        from agents.learning.outcome_labeler import label_risk_counterfactuals

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        import uuid
        intent_id = str(uuid.uuid4())
        decision_date = (date.today() - timedelta(days=10)).isoformat()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO trade_intents
               (intent_id, symbol, side, quantity, limit_price, order_type,
                time_in_force, strategy, valid_until, created_at, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (intent_id, "ANET", "SELL", 5.0, 200.0, "LIMIT", "DAY",
             "test", "2099-01-01", "2026-01-01", "REJECTED"),
        )
        conn.execute(
            """INSERT INTO risk_counterfactual_outcomes
               (intent_id, ticker, side, quantity, limit_price,
                rejected_at, reject_rule, rejection_reason, decision_date, horizon)
               VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
            (intent_id, "ANET", "SELL", 5.0, 200.0,
             time.time() - 10 * 86400, "MAX_POSITION_PCT", "test", decision_date),
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        conn.close()

        # Price falls 30% — the blocked SELL was the right call, gate was wrong
        # entry price = 200.0, horizon price = 140.0
        call_count2 = {"n": 0}
        def _price_side_effect2(ticker, date_str):
            call_count2["n"] += 1
            return 200.0 if call_count2["n"] % 2 == 1 else 140.0
        with patch("agents.learning.outcome_labeler._get_ticker_price", side_effect=_price_side_effect2), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0), \
             patch("agents.learning.outcome_labeler._compute_mfe_mae", return_value=(0.0, -0.3)):
            label_risk_counterfactuals(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT * FROM risk_counterfactual_outcomes WHERE intent_id=? AND horizon IS NOT NULL LIMIT 1",
            (intent_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["ticker_return"] == pytest.approx(-0.30)
        # SELL: directional_return = -ticker_return = +0.30 (the exit decision was right)
        assert row["directional_return"] == pytest.approx(0.30)


class TestExecutionCostAccounting0339:
    """0339: fee-adjusted returns and implementation shortfall."""

    def _insert_trade_outcome_with_fees(self, conn, fill_price=100.0, fill_qty=10.0,
                                        fill_fees=1.0, arrival_price=None, action="BUY",
                                        days_old=10):
        import uuid
        fill_id = f"fill-{uuid.uuid4()}"
        fill_date = (date.today() - timedelta(days=days_old)).isoformat()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT OR IGNORE INTO trade_outcomes
               (fill_id, ticker, action, fill_date, fill_price, fill_qty, fill_fees,
                arrival_price, label_type, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (fill_id, "ANET", action, fill_date, fill_price, fill_qty, fill_fees,
             arrival_price, "EXECUTED_TRADE_RETURN", time.time()),
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        return fill_id, fill_date

    def test_zero_fee_return_equals_gross_return(self, mem_db, monkeypatch):
        """Zero-fee fills: net return == gross price-change return."""
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        fill_id, _ = self._insert_trade_outcome_with_fees(conn, fill_price=100.0, fill_qty=10.0,
                                                          fill_fees=0.0, action="BUY")
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=110.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute("SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)).fetchone()
        conn.close()
        assert row["return_1w"] == pytest.approx(0.10)

    def test_fee_reduces_buy_return(self, mem_db, monkeypatch):
        """BUY: fees increase effective cost, reducing net return vs gross."""
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        # fill_price=100, qty=10, fees=10 → fees_per_share=1 → effective_entry=101
        # h_price=110 → return = 110/101 - 1 ≈ 8.91%
        fill_id, _ = self._insert_trade_outcome_with_fees(conn, fill_price=100.0, fill_qty=10.0,
                                                          fill_fees=10.0, action="BUY")
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=110.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute("SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)).fetchone()
        conn.close()
        expected = 110.0 / 101.0 - 1.0
        assert row["return_1w"] == pytest.approx(expected, rel=1e-4)
        assert row["return_1w"] < 0.10  # less than gross 10% due to fees

    def test_implementation_shortfall_written_when_arrival_price_present(self, mem_db, monkeypatch):
        """IS = (fill_price - arrival_price) / arrival_price for BUY; written to DB."""
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        # arrival=98.0, fill=100.0 → IS = (100-98)/98 ≈ 2.04%
        fill_id, _ = self._insert_trade_outcome_with_fees(conn, fill_price=100.0, fill_qty=10.0,
                                                          fill_fees=0.0, arrival_price=98.0,
                                                          action="BUY")
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=105.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute("SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)).fetchone()
        conn.close()
        expected_is = (100.0 - 98.0) / 98.0
        assert row["implementation_shortfall"] == pytest.approx(expected_is, rel=1e-4)

    def test_implementation_shortfall_null_when_no_arrival_price(self, mem_db, monkeypatch):
        """IS remains NULL when arrival_price is not set."""
        import agent_db
        from agents.learning.outcome_labeler import label_trade_outcomes

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        fill_id, _ = self._insert_trade_outcome_with_fees(conn, fill_price=100.0, fill_qty=10.0,
                                                          fill_fees=0.0, arrival_price=None,
                                                          action="BUY")
        conn.close()

        with patch("agents.learning.outcome_labeler._get_ticker_price", return_value=105.0), \
             patch("agents.learning.outcome_labeler._spy_price_at", return_value=500.0):
            label_trade_outcomes(min_age_days=7)

        conn = _make_conn(mem_db)
        row = conn.execute("SELECT * FROM trade_outcomes WHERE fill_id=?", (fill_id,)).fetchone()
        conn.close()
        assert row["implementation_shortfall"] is None
