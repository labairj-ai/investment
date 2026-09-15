"""Tests for agents/learning/calibration.py and challenger.py (0330)."""
import sys
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_conn(db_file):
    import sqlite3
    conn = sqlite3.connect(str(db_file), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _seed_episodes(conn, n: int, with_outcomes: bool = True, noise: float = 0.1):
    """Seed n episodes with synthetic feature data and 3m alpha outcomes."""
    rng = np.random.default_rng(42)
    base_time = time.time() - (400 * 86400)  # 400 days ago
    eps = []
    for i in range(n):
        ep_id = str(uuid.uuid4())
        q  = float(rng.uniform(40, 95))
        v  = float(rng.uniform(40, 95))
        pf = float(rng.uniform(40, 95))
        c  = float(rng.uniform(40, 95))
        ec = float(rng.uniform(40, 95))
        comp = int(round(0.30*q + 0.25*v + 0.20*pf + 0.15*c + 0.10*ec))
        # Synthetic alpha: positively correlated with quality and valuation
        alpha = 0.001 * q + 0.001 * v - 0.04 + float(rng.normal(0, noise))
        captured_at = base_time + i * 86400  # one per day
        conn.execute(
            """INSERT INTO decision_episodes
               (episode_id, run_id, ticker, captured_at, selected, composite_score,
                q_score, v_score, pf_score, c_score, ec_score, feature_schema_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ep_id, 1, f"TK{i:03d}", captured_at, 1, comp, q, v, pf, c, ec, "v1"),
        )
        eps.append((ep_id, alpha))
    conn.commit()
    if with_outcomes:
        for ep_id, alpha in eps:
            conn.execute(
                """INSERT INTO episode_outcomes
                   (episode_id, horizon, ticker_return, spy_return, alpha, labeled_at)
                   VALUES (?,?,?,?,?,?)""",
                (ep_id, "3m", alpha + 0.05, 0.05, alpha, time.time()),
            )
        conn.commit()
    return eps


class TestRidgeFit:
    def test_zero_alpha_returns_mean_predictor(self):
        from agents.learning.calibration import _ridge_fit

        X = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]])
        y = np.array([2.0, 2.0, 2.0, 2.0])
        coef, intercept = _ridge_fit(X, y, alpha=1.0)
        preds = X @ coef + intercept
        assert np.allclose(preds, 2.0, atol=0.01)

    def test_recovers_known_coefficients(self):
        from agents.learning.calibration import _ridge_fit

        rng = np.random.default_rng(0)
        true_coef = np.array([0.01, 0.005, 0.002, 0.0, -0.001])
        X = rng.uniform(40, 90, (200, 5))
        y = X @ true_coef + 0.02 + rng.normal(0, 0.005, 200)

        coef, _ = _ridge_fit(X, y, alpha=0.001)
        # Recovered coefficients should have same sign as true
        for tc, rc in zip(true_coef, coef):
            if abs(tc) > 0.001:
                assert tc * rc > 0, f"sign mismatch: true={tc:.4f} recovered={rc:.4f}"


class TestChallengerModel:
    def test_train_returns_none_when_insufficient_data(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 10, with_outcomes=True)  # only 10, need 30
        conn.close()

        model = ChallengerModel.train()
        assert model is None

    def test_train_succeeds_with_enough_data(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50, with_outcomes=True)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        assert model.training_n == 50
        assert len(model.coef) == 5
        assert model.model_version.startswith("edge_v")

    def test_validation_metrics_present(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        assert "val_n" in model.validation_metrics
        assert "val_mae" in model.validation_metrics
        assert model.validation_metrics["val_mae"] >= 0

    def test_shrinkage_formula(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel, SHRINKAGE_LAMBDA

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        expected_reliability = 50 / (50 + SHRINKAGE_LAMBDA)
        assert model.reliability == pytest.approx(expected_reliability, rel=0.01)

    def test_adjustment_bounded(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel, MAX_ADJUSTMENT

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None

        # Extreme candidate should still be bounded
        extreme = {"q_score": 100, "v_score": 100, "pf_score": 100, "c_score": 100,
                   "ec_score": 100, "_composite": 100}
        info = model.score(extreme)
        if info["active"]:
            assert abs(info["learning_adjustment"]) <= MAX_ADJUSTMENT + 0.001

        extreme_low = {"q_score": 0, "v_score": 0, "pf_score": 0, "c_score": 0,
                       "ec_score": 0, "_composite": 0}
        info_low = model.score(extreme_low)
        if info_low["active"]:
            assert abs(info_low["learning_adjustment"]) <= MAX_ADJUSTMENT + 0.001

    def test_inactive_when_below_min_training(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel, MIN_TRAINING_N

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        eps = _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        # Manually set training_n below threshold to test inactive path
        model.training_n = MIN_TRAINING_N - 1
        cand = {"q_score": 80, "v_score": 70, "pf_score": 65, "c_score": 60, "ec_score": 55}
        info = model.score(cand)
        assert info["active"] is False
        assert info["learning_adjustment"] == 0.0

    def test_save_and_load(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        model.save_with_weights()

        loaded = ChallengerModel.load_latest()
        assert loaded is not None
        assert loaded.training_n == model.training_n
        assert loaded.model_version == model.model_version
        assert np.allclose(loaded.coef, model.coef, atol=1e-10)

    def test_missing_feature_returns_zero_adjustment(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        # Missing v_score
        cand = {"q_score": 80, "pf_score": 65, "c_score": 60, "ec_score": 55}
        info = model.score(cand)
        assert info["learning_adjustment"] == 0.0


class TestChallengerWiring:
    def test_no_active_model_returns_base_composite(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning import challenger

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        # No model in DB — get_model should return None
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        cand = {"_composite": 72, "q_score": 80, "v_score": 70, "pf_score": 65,
                "c_score": 60, "ec_score": 55}
        from agents.learning.challenger import apply_challenger_adjustment
        result_composite, info = apply_challenger_adjustment(cand)
        assert result_composite == 72
        assert info["active"] is False

    def test_active_model_adjusts_composite(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning import calibration, challenger
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        model.save_with_weights()

        cand = {"_composite": 72, "q_score": 90, "v_score": 85, "pf_score": 75,
                "c_score": 65, "ec_score": 60}
        from agents.learning.challenger import apply_challenger_adjustment
        result_composite, info = apply_challenger_adjustment(cand)
        # With training_n=50, model is active
        assert info["active"] is True
        # Composite is bounded to [0, 100]
        assert 0 <= result_composite <= 100
        # Adjustment bounded to ±10 score points from original
        from agents.learning.calibration import MAX_ADJUSTMENT
        assert abs(result_composite - 72) <= MAX_ADJUSTMENT + 1  # +1 for rounding
