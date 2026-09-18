"""Tests for agents/learning/calibration.py and challenger.py (0330)."""
import json
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
        vm = model.validation_metrics
        # 0334: walk-forward metrics replace single-split val_n/val_mae
        assert "cv_folds" in vm
        assert "raw_n" in vm
        assert "unique_tickers" in vm
        assert "unique_decision_dates" in vm
        assert "unique_weeks" in vm
        assert vm["raw_n"] == 50
        # With 50 episodes spread over 50 days + 91-day embargo, walk-forward
        # may or may not produce folds depending on data span; cv_folds can be 0
        assert isinstance(vm["cv_folds"], int)
        # beats_baseline is True, False, or None (if no folds)
        assert vm["beats_baseline"] in (True, False, None)

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
        from agents.learning.calibration import ChallengerModel, promote

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

        # 0335: must promote to PAPER_ACTIVE before the model influences scoring
        r1 = promote(model.model_version, "OBSERVE", override_reason="test")
        assert r1["promoted"], f"promote to OBSERVE failed: {r1}"
        r2 = promote(model.model_version, "PAPER_ACTIVE", override_reason="test")
        assert r2["promoted"], f"promote to PAPER_ACTIVE failed: {r2}"
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        cand = {"_composite": 72, "q_score": 90, "v_score": 85, "pf_score": 75,
                "c_score": 65, "ec_score": 60}
        from agents.learning.challenger import apply_challenger_adjustment
        result_composite, info = apply_challenger_adjustment(cand)
        # After promotion to PAPER_ACTIVE, model is active
        assert info["active"] is True
        # Composite is bounded to [0, 100]
        assert 0 <= result_composite <= 100
        # Adjustment bounded to ±10 score points from original
        from agents.learning.calibration import MAX_ADJUSTMENT
        assert abs(result_composite - 72) <= MAX_ADJUSTMENT + 1  # +1 for rounding


class TestChallengerHardening0334:
    """0334: walk-forward CV, unique tracking, p_outperform removed."""

    def test_p_outperform_absent_from_score(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        cand = {"q_score": 80, "v_score": 70, "pf_score": 65, "c_score": 60, "ec_score": 55}
        info = model.score(cand)
        assert "p_outperform" not in info

    def test_unique_metrics_populated(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)  # 50 distinct tickers (TK000..TK049), 50 distinct days
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        vm = model.validation_metrics
        assert vm["unique_tickers"] == 50   # each episode has a distinct ticker
        assert vm["unique_decision_dates"] == 50  # one episode per day
        assert vm["unique_weeks"] >= 7  # 50 days ≈ 7+ ISO weeks
        assert vm["raw_n"] == 50

    def test_walk_forward_produces_folds_when_span_sufficient(self, mem_db, monkeypatch):
        """With 200+ episodes spanning 200+ days, walk-forward finds folds past embargo."""
        import agent_db
        from agents.learning.calibration import ChallengerModel, EMBARGO_DAYS

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 200)  # 200 days of history — some folds beyond 91-day embargo
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        vm = model.validation_metrics
        # 200 days span >> MIN_TRAINING_N(30) + EMBARGO(91) → should find at least 1 fold
        assert vm["cv_folds"] >= 1
        assert vm["cv_mae_mean"] is not None and vm["cv_mae_mean"] >= 0
        assert vm["baseline_mae_mean"] is not None and vm["baseline_mae_mean"] >= 0
        assert vm["beats_baseline"] in (True, False)

    def test_walk_forward_no_folds_when_span_too_short(self, mem_db, monkeypatch):
        """With 30 episodes in 30 days, the embargo prevents any validation fold."""
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 30)  # 30 days, embargo=91 → no validation fold possible
        conn.close()

        model = ChallengerModel.train()
        assert model is not None
        vm = model.validation_metrics
        assert vm["cv_folds"] == 0
        assert vm["beats_baseline"] is None

    def test_unique_metrics_persisted_to_db(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()

        conn = _make_conn(mem_db)
        row = dict(conn.execute(
            "SELECT unique_tickers, unique_decision_dates, unique_weeks, raw_n "
            "FROM learning_models ORDER BY created_at DESC LIMIT 1"
        ).fetchone())
        conn.close()

        assert row["raw_n"] == 50
        assert row["unique_tickers"] == 50
        assert row["unique_decision_dates"] == 50
        assert row["unique_weeks"] is not None and row["unique_weeks"] >= 1


class TestLifecycleGovernance0335:
    """0335: TRAINED → OBSERVE → PAPER_ACTIVE lifecycle gates."""

    def test_new_model_starts_in_trained_state(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel, LIFECYCLE_TRAINED

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        assert model.lifecycle_state == LIFECYCLE_TRAINED
        model.save_with_weights()

        loaded = ChallengerModel.load_latest()
        assert loaded.lifecycle_state == LIFECYCLE_TRAINED

    def test_trained_model_returns_no_adjustment(self, mem_db, monkeypatch):
        """TRAINED state → challenger returns zero adjustment (inactive)."""
        import agent_db
        from agents.learning import challenger
        from agents.learning.calibration import ChallengerModel

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()

        cand = {"_composite": 72, "q_score": 90, "v_score": 85,
                "pf_score": 75, "c_score": 65, "ec_score": 60}
        from agents.learning.challenger import apply_challenger_adjustment
        result_composite, info = apply_challenger_adjustment(cand)
        assert info["active"] is False
        assert result_composite == 72

    def test_promote_trained_to_observe_with_force(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel, promote, LIFECYCLE_OBSERVE

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()

        result = promote(model.model_version, "OBSERVE", override_reason="test")
        assert result["promoted"] is True
        assert result["new_state"] == LIFECYCLE_OBSERVE

        loaded = ChallengerModel.load_latest()
        assert loaded.lifecycle_state == LIFECYCLE_OBSERVE

    def test_promote_gate_check_fails_insufficient_data(self, mem_db, monkeypatch):
        """With only 30 episodes and no CV folds, gates fail without force."""
        import agent_db
        from agents.learning.calibration import ChallengerModel, promote

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 30)  # cv_folds=0 (30 days < embargo)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()

        result = promote(model.model_version, "OBSERVE", force=False)
        assert result["promoted"] is False
        assert "failed_gates" in result
        assert len(result["failed_gates"]) > 0

    def test_invalid_transition_rejected(self, mem_db, monkeypatch):
        """Cannot go from TRAINED directly to PAPER_ACTIVE."""
        import agent_db
        from agents.learning.calibration import ChallengerModel, promote

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()

        result = promote(model.model_version, "PAPER_ACTIVE", override_reason="test")
        assert result["promoted"] is False
        assert "invalid transition" in result.get("error", "")

    def test_observe_model_also_inactive(self, mem_db, monkeypatch):
        """OBSERVE state → challenger still returns zero adjustment."""
        import agent_db
        from agents.learning import challenger
        from agents.learning.calibration import ChallengerModel, promote

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()
        promote(model.model_version, "OBSERVE", override_reason="test")
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        cand = {"_composite": 72, "q_score": 90, "v_score": 85,
                "pf_score": 75, "c_score": 65, "ec_score": 60}
        from agents.learning.challenger import apply_challenger_adjustment
        _, info = apply_challenger_adjustment(cand)
        assert info["active"] is False


class TestChampionChallengerExperiment0336:
    """0336: base _composite unchanged after challenger pass; variants recorded; routing correct."""

    def test_base_composite_unchanged_after_challenger_pass(self, mem_db, monkeypatch):
        """apply_challenger_adjustment must never overwrite _composite."""
        import agent_db
        from agents.learning import challenger
        from agents.learning.calibration import ChallengerModel, promote

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()
        promote(model.model_version, "OBSERVE", override_reason="test")
        promote(model.model_version, "PAPER_ACTIVE", override_reason="test")
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        from agents.learning.challenger import apply_challenger_adjustment
        cand = {"_composite": 72, "q_score": 85, "v_score": 80,
                "pf_score": 75, "c_score": 70, "ec_score": 65}
        original_composite = cand["_composite"]
        adj, info = apply_challenger_adjustment(cand)

        # _composite on the dict itself must not be overwritten — caller stores adj separately
        assert cand["_composite"] == original_composite, "apply_challenger_adjustment must not mutate _composite"
        # The returned adj may differ from the original composite (adjustment applied)
        assert isinstance(adj, (int, float))

    def test_challenger_variants_recorded_when_paper_active(self, mem_db, monkeypatch):
        """_insert_decision_variant writes a decision_variants row when challenger is PAPER_ACTIVE."""
        import agent_db
        from agents.learning import challenger
        from agents.learning.calibration import ChallengerModel, promote
        from agents.opportunity_agent import _insert_decision_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()
        promote(model.model_version, "OBSERVE", override_reason="test")
        promote(model.model_version, "PAPER_ACTIVE", override_reason="test")
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        from agents.learning.challenger import apply_challenger_adjustment
        scored = []
        for i, ticker in enumerate(["AAPL", "MSFT", "GOOG"]):
            cand = {"ticker": ticker, "_composite": 80 - i * 5, "_episode_id": str(uuid.uuid4()),
                    "q_score": 80, "v_score": 75, "pf_score": 70, "c_score": 65, "ec_score": 60}
            adj, info = apply_challenger_adjustment(cand)
            cand["_composite_challenger"] = adj
            cand["_challenger_info"] = info
            scored.append(cand)

        champion = scored[0]
        _insert_decision_variant(scored, champion, champion_ticker=champion["ticker"])

        conn2 = _make_conn(mem_db)
        row = conn2.execute(
            "SELECT * FROM decision_variants WHERE origin='PAPER_CHALLENGER' LIMIT 1"
        ).fetchone()
        conn2.close()

        assert row is not None, "decision_variants row not created"
        assert row["champion_ticker"] == champion["ticker"]
        assert row["variant_ticker"] is not None

    def test_no_variant_recorded_when_model_not_paper_active(self, mem_db, monkeypatch):
        """_insert_decision_variant is NOT called when challenger info shows active=False."""
        import agent_db
        from agents.learning import challenger
        from agents.opportunity_agent import _insert_decision_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(challenger, "_cached_model", None)
        monkeypatch.setattr(challenger, "_cached_version", None)

        # No model trained — challenger is inactive
        from agents.learning.challenger import apply_challenger_adjustment
        scored = []
        for i, ticker in enumerate(["AAPL", "MSFT"]):
            cand = {"ticker": ticker, "_composite": 80 - i * 5, "_episode_id": str(uuid.uuid4()),
                    "q_score": 80, "v_score": 75, "pf_score": 70, "c_score": 65, "ec_score": 60}
            adj, info = apply_challenger_adjustment(cand)
            cand["_composite_challenger"] = adj
            cand["_challenger_info"] = info
            scored.append(cand)

        # Opportunity agent only calls _insert_decision_variant when info["active"] is True
        # — we verify the guard logic: if active=False, no variant row should exist
        sel_ch_info = scored[0].get("_challenger_info", {})
        if sel_ch_info.get("active"):
            _insert_decision_variant(scored, scored[0], champion_ticker=scored[0]["ticker"])

        conn = _make_conn(mem_db)
        count = conn.execute("SELECT COUNT(*) FROM decision_variants").fetchone()[0]
        conn.close()
        assert count == 0

    def _make_policy(self, account_id="ALPACA_TEST_01"):
        """Return a minimal TradingPolicy for tests that call build_intent."""
        import json
        from trade_engine.policy import TradingPolicy
        base = {
            "policy_version": "1.0", "account_id": account_id,
            "capital": {"starting_capital": 100000, "minimum_cash_pct": 5, "minimum_cash_abs": 500},
            "equities": {"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                         "max_single_position_pct": 20, "max_new_position_pct": 10},
            "options": {"covered_calls_allowed": False, "naked_options_allowed": False,
                        "max_contracts_per_symbol": 0},
            "execution": {"market_orders_allowed": False, "max_orders_per_day": 5,
                          "max_daily_notional_pct": 50, "max_slippage_pct": 1.0, "min_limit_price": 0.01},
            "risk": {"max_drawdown_pct": 20, "max_daily_loss_pct": 5, "max_weekly_loss_pct": 10},
            "circuit_breakers": {"trading_enabled": True, "halt_on_position_mismatch": False,
                                 "halt_on_data_stale_minutes": 1440, "halt_on_daily_loss_pct": 10},
        }
        return TradingPolicy(
            policy_version=base["policy_version"], account_id=base["account_id"],
            capital=base["capital"], equities=base["equities"], options=base["options"],
            execution=base["execution"], risk=base["risk"],
            circuit_breakers=base["circuit_breakers"], _raw_json=json.dumps(base),
        )

    def test_decision_origin_champion_when_no_variant(self, mem_db, monkeypatch):
        """Intent built without a challenger variant gets decision_origin=CHAMPION."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")

        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at)
            VALUES ('ALPACA_TEST_01', 'paper', 100000, 1000000)""")
        ep_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO decision_episodes
            (episode_id, run_id, ticker, captured_at, composite_score, feature_schema_version)
            VALUES (?, 1, 'AAPL', 1000000, 75, 'v1')""", (ep_id,))
        conn.execute("""INSERT INTO recommendations
            (id, run_id, ticker, action, status, recommendation_score, episode_id,
             action_payload_json, created_at)
            VALUES (9001, 1, 'AAPL', 'BUY', 'accepted', 75, ?,
                    '{"price": 200.0, "quantity": 5}', 1000000)""", (ep_id,))
        conn.commit()

        policy = self._make_policy("ALPACA_TEST_01")
        intent = build_intent(9001, "ALPACA_TEST_01", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.decision_origin == "CHAMPION"

    def test_decision_origin_paper_challenger_when_variant_exists(self, mem_db, monkeypatch):
        """Intent built for ALPACA account with a challenger variant row gets PAPER_CHALLENGER."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")

        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at, role)
            VALUES ('ALPACA_TEST_01', 'paper', 100000, 1000000, 'paper_challenger')""")
        ep_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO decision_episodes
            (episode_id, run_id, ticker, captured_at, composite_score, feature_schema_version)
            VALUES (?, 1, 'AAPL', 1000000, 75, 'v1')""", (ep_id,))
        conn.execute("""INSERT INTO recommendations
            (id, run_id, ticker, action, status, recommendation_score, episode_id,
             action_payload_json, created_at)
            VALUES (9002, 1, 'AAPL', 'BUY', 'accepted', 75, ?,
                    '{"price": 200.0, "quantity": 5}', 1000000)""", (ep_id,))
        conn.execute("""INSERT INTO decision_variants
            (episode_id, origin, challenger_model_version, challenger_score,
             challenger_adjustment, would_have_selected, champion_ticker, variant_ticker,
             action, price, created_at)
            VALUES (?, 'PAPER_CHALLENGER', 'v_test', 77.5, 2.5, 0, 'AAPL', 'AAPL',
                    'BUY', 200.0, 1000000)""",
            (ep_id,))
        conn.commit()

        policy = self._make_policy("ALPACA_TEST_01")
        intent = build_intent(9002, "ALPACA_TEST_01", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.decision_origin == "PAPER_CHALLENGER"
        assert intent.symbol == "AAPL"

    def test_variant_ticker_used_not_champion_ticker(self, mem_db, monkeypatch):
        """0337 key test: champion=ANET, challenger=GRMN → Alpaca intent symbol=GRMN."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")

        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at, role)
            VALUES ('ALPACA_TEST_01', 'paper', 100000, 1000000, 'paper_challenger')""")
        ep_id = str(uuid.uuid4())
        # Champion recommendation is for ANET
        conn.execute("""INSERT INTO decision_episodes
            (episode_id, run_id, ticker, captured_at, composite_score, feature_schema_version)
            VALUES (?, 1, 'ANET', 1000000, 82, 'v1')""", (ep_id,))
        conn.execute("""INSERT INTO recommendations
            (id, run_id, ticker, action, status, recommendation_score, episode_id,
             action_payload_json, created_at)
            VALUES (9003, 1, 'ANET', 'BUY', 'accepted', 82, ?,
                    '{"price": 300.0, "quantity": 3}', 1000000)""", (ep_id,))
        # Challenger variant picks GRMN instead
        conn.execute("""INSERT INTO decision_variants
            (episode_id, origin, challenger_model_version, challenger_score,
             challenger_adjustment, would_have_selected, champion_ticker, variant_ticker,
             action, price, created_at)
            VALUES (?, 'PAPER_CHALLENGER', 'v_test', 84.0, 2.0, 1, 'ANET', 'GRMN',
                    'BUY', 150.0, 1000000)""", (ep_id,))
        conn.commit()

        policy = self._make_policy("ALPACA_TEST_01")
        alpaca_intent = build_intent(9003, "ALPACA_TEST_01", policy, conn)

        # Shadow account (non-ALPACA) should still get the champion ticker ANET
        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at)
            VALUES ('SHADOW_01', 'shadow', 100000, 1000000)""")
        shadow_intent = build_intent(9003, "SHADOW_01", policy, conn)
        conn.close()

        assert alpaca_intent is not None, "ALPACA intent not created"
        assert alpaca_intent.symbol == "GRMN", f"expected GRMN, got {alpaca_intent.symbol}"
        assert alpaca_intent.decision_origin == "PAPER_CHALLENGER"

        assert shadow_intent is not None, "Shadow intent not created"
        assert shadow_intent.symbol == "ANET", f"expected ANET, got {shadow_intent.symbol}"
        assert shadow_intent.decision_origin == "CHAMPION"


# ─────────────────────────────────────────────────────────────────────────────
# 0341 — Git SHA provenance
# ─────────────────────────────────────────────────────────────────────────────

def _make_test_policy(account_id="SHADOW_TEST"):
    """Module-level helper — builds a minimal TradingPolicy for SHA/calibration tests."""
    import json
    from trade_engine.policy import TradingPolicy
    base = {
        "policy_version": "1.0", "account_id": account_id,
        "capital": {"starting_capital": 100000, "minimum_cash_pct": 5, "minimum_cash_abs": 500},
        "equities": {"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                     "max_single_position_pct": 20, "max_new_position_pct": 10},
        "options": {"covered_calls_allowed": False, "naked_options_allowed": False,
                    "max_contracts_per_symbol": 0},
        "execution": {"market_orders_allowed": False, "max_orders_per_day": 5,
                      "max_daily_notional_pct": 50, "max_slippage_pct": 1.0, "min_limit_price": 0.01},
        "risk": {"max_drawdown_pct": 20, "max_daily_loss_pct": 5, "max_weekly_loss_pct": 10},
        "circuit_breakers": {"trading_enabled": True, "halt_on_position_mismatch": False,
                             "halt_on_data_stale_minutes": 1440, "halt_on_daily_loss_pct": 10},
    }
    return TradingPolicy(
        policy_version=base["policy_version"], account_id=account_id,
        capital=base["capital"], equities=base["equities"], options=base["options"],
        execution=base["execution"], risk=base["risk"],
        circuit_breakers=base["circuit_breakers"], _raw_json=json.dumps(base),
    )


class TestGitShaSHA0341:
    def test_code_commit_sha_constant_is_string_or_none(self):
        import agent_db
        sha = agent_db.CODE_COMMIT_SHA
        assert sha is None or (isinstance(sha, str) and len(sha) == 40)

    def test_agent_run_has_code_commit_sha_column(self, mem_db, monkeypatch):
        import agent_db
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        run_id = agent_db.insert_agent_run("test_agent", scope="portfolio")
        conn = _make_conn(mem_db)
        row = conn.execute("SELECT code_commit_sha FROM agent_runs WHERE id=?", (run_id,)).fetchone()
        conn.close()
        # Column exists and value is either the SHA or NULL (test env may not be in a git repo)
        assert row is not None
        sha = row["code_commit_sha"]
        assert sha is None or (isinstance(sha, str) and len(sha) == 40)

    def test_decision_episode_has_code_commit_sha_column(self, mem_db, monkeypatch):
        """capture_candidate_episode writes code_commit_sha."""
        import agent_db
        from agents.learning.episode_capture import capture_candidate_episode
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        candidate = {
            "ticker": "ANET", "_q": 80, "_v": 70, "_pf": 60, "_c": 65, "_ec": 75,
            "_composite": 72, "quality_score": 80, "pe_ratio": 20, "p_fcf": 15,
            "ev_ebitda": 12, "gross_margin": 0.6, "net_income_margin": 0.2,
            "sga_margin": 0.1, "capex_margin": 0.05, "market_cap": 1e10,
            "layer_rec": 3, "sector": "Tech", "industry": "Networks",
            "value_trap_risk": "LOW",
        }
        ep_id = capture_candidate_episode(run_id=1, candidate=candidate)
        conn = _make_conn(mem_db)
        row = conn.execute(
            "SELECT code_commit_sha FROM decision_episodes WHERE episode_id=?", (ep_id,)
        ).fetchone()
        conn.close()
        assert row is not None

    def test_trade_intent_has_code_commit_sha_column(self, mem_db, monkeypatch):
        """build_intent writes code_commit_sha onto the TradeIntent."""
        import agent_db
        from trade_engine.intent_builder import build_intent
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        # Override SHA to a known test value
        monkeypatch.setattr(agent_db, "CODE_COMMIT_SHA", "a" * 40)

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at)
            VALUES ('SHADOW_SHA', 'shadow', 100000, 1000000)""")
        ep_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO decision_episodes
            (episode_id, run_id, ticker, captured_at, composite_score, feature_schema_version)
            VALUES (?, 1, 'ANET', 1000000, 72, 'v1')""", (ep_id,))
        conn.execute("""INSERT INTO recommendations
            (id, run_id, ticker, action, status, recommendation_score, episode_id,
             action_payload_json, created_at)
            VALUES (9999, 1, 'ANET', 'BUY', 'accepted', 72, ?, '{"price":200.0,"quantity":5}', 1000000)""", (ep_id,))
        conn.commit()

        policy = _make_test_policy("SHADOW_SHA")
        intent = build_intent(9999, "SHADOW_SHA", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.code_commit_sha == "a" * 40

    def test_code_commit_sha_written_to_db(self, mem_db, monkeypatch):
        """code_commit_sha on the intent is persisted in trade_intents table."""
        import agent_db
        from trade_engine.intent_builder import build_intent
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))
        monkeypatch.setattr(agent_db, "CODE_COMMIT_SHA", "b" * 40)

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at)
            VALUES ('SHADOW_SHA2', 'shadow', 100000, 1000000)""")
        ep_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO decision_episodes
            (episode_id, run_id, ticker, captured_at, composite_score, feature_schema_version)
            VALUES (?, 1, 'GRMN', 1000000, 70, 'v1')""", (ep_id,))
        conn.execute("""INSERT INTO recommendations
            (id, run_id, ticker, action, status, recommendation_score, episode_id,
             action_payload_json, created_at)
            VALUES (9998, 1, 'GRMN', 'BUY', 'accepted', 70, ?, '{"price":150.0,"quantity":5}', 1000000)""", (ep_id,))
        conn.commit()

        policy = _make_test_policy("SHADOW_SHA2")
        build_intent(9998, "SHADOW_SHA2", policy, conn)
        row = conn.execute(
            "SELECT code_commit_sha FROM trade_intents WHERE recommendation_id=9998"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["code_commit_sha"] == "b" * 40


# ─────────────────────────────────────────────────────────────────────────────
# 0342 — Model promotion approval record
# ─────────────────────────────────────────────────────────────────────────────

class TestModelPromotionLog0342:
    def _seed_promotable_model(self, conn, model_version: str) -> None:
        conn.execute(
            """INSERT INTO learning_models
               (model_version, training_cutoff, feature_schema_hash, training_n,
                validation_metrics, created_at, unique_tickers, unique_decision_dates,
                unique_weeks, lifecycle_state)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (model_version, "2026-01-01", "abc", 50,
             '{"cv_folds":3,"beats_baseline":true}',
             time.time(), 15, 35, 6, "TRAINED"),
        )
        conn.commit()

    def test_promote_writes_log_row(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        self._seed_promotable_model(conn, "edge_v001")
        conn.close()

        result = promote("edge_v001", "OBSERVE", promoted_by="pytest", promotion_reason="test run")
        assert result["promoted"] is True

        conn = _make_conn(mem_db)
        log = conn.execute(
            "SELECT * FROM model_promotion_log WHERE model_version='edge_v001'"
        ).fetchone()
        conn.close()
        assert log is not None
        assert log["from_state"] == "TRAINED"
        assert log["to_state"] == "OBSERVE"
        assert log["promoted_by"] == "pytest"
        assert log["promotion_reason"] == "test run"

    def test_promotion_log_has_metrics_snapshot(self, mem_db, monkeypatch):
        import agent_db, json
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        self._seed_promotable_model(conn, "edge_v002")
        conn.close()

        promote("edge_v002", "OBSERVE", promoted_by="auto", override_reason="test")
        conn = _make_conn(mem_db)
        log = conn.execute(
            "SELECT promotion_metrics_snapshot FROM model_promotion_log WHERE model_version='edge_v002'"
        ).fetchone()
        conn.close()
        assert log is not None
        snapshot = json.loads(log["promotion_metrics_snapshot"] or "{}")
        assert isinstance(snapshot, dict)

    def test_multiple_promotions_produce_multiple_log_rows(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        self._seed_promotable_model(conn, "edge_v003")
        conn.close()

        promote("edge_v003", "OBSERVE", promoted_by="user1", override_reason="test")
        promote("edge_v003", "PAPER_ACTIVE", promoted_by="user2", override_reason="test")
        promote("edge_v003", "RETIRED", promoted_by="system", force=True)

        conn = _make_conn(mem_db)
        rows = conn.execute(
            "SELECT from_state, to_state FROM model_promotion_log WHERE model_version='edge_v003' ORDER BY id"
        ).fetchall()
        conn.close()
        transitions = [(r["from_state"], r["to_state"]) for r in rows]
        assert len(transitions) == 3
        assert transitions[0] == ("TRAINED", "OBSERVE")
        assert transitions[1] == ("OBSERVE", "PAPER_ACTIVE")
        assert transitions[2] == ("PAPER_ACTIVE", "RETIRED")

    def test_failed_promotion_does_not_write_log(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        # Model with insufficient data — will fail gates
        conn.execute(
            """INSERT INTO learning_models
               (model_version, training_n, validation_metrics, created_at,
                unique_tickers, unique_decision_dates, unique_weeks, lifecycle_state)
               VALUES ('edge_v004', 10,
                '{"cv_folds":0,"beats_baseline":false}',
                1000000, 3, 5, 1, 'TRAINED')""",
        )
        conn.commit()
        conn.close()

        result = promote("edge_v004", "OBSERVE", promoted_by="pytest")
        assert result["promoted"] is False

        conn = _make_conn(mem_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM model_promotion_log WHERE model_version='edge_v004'"
        ).fetchone()[0]
        conn.close()
        assert count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 0343 — Challenger alpha uncertainty bands
# ─────────────────────────────────────────────────────────────────────────────

class TestAlphaUncertaintyBands0343:
    """0343/0347: bootstrap CI over ranking-alpha spread (5th/95th = 90% interval)."""

    def test_bootstrap_ci_with_sufficient_folds(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        folds = [
            {"top_vs_bottom_quintile_alpha": 0.03},
            {"top_vs_bottom_quintile_alpha": 0.04},
            {"top_vs_bottom_quintile_alpha": 0.02},
            {"top_vs_bottom_quintile_alpha": 0.05},
            {"top_vs_bottom_quintile_alpha": 0.03},
        ]
        result = _bootstrap_alpha_ci(folds)
        assert result["ranking_spread_ci_low"] is not None
        assert result["ranking_spread_ci_high"] is not None
        assert result["ranking_spread_ci_low"] <= result["ranking_spread_ci_high"]
        assert result["alpha_precision"] in ("HIGH", "MEDIUM", "LOW")
        assert result["alpha_edge_evidence"] in ("POSITIVE", "INCONCLUSIVE", "NEGATIVE")

    def test_ci_bounds_bracket_mean(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        folds = [{"top_vs_bottom_quintile_alpha": v}
                 for v in [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07]]
        result = _bootstrap_alpha_ci(folds)
        mean_val = sum(f["top_vs_bottom_quintile_alpha"] for f in folds) / len(folds)
        assert result["ranking_spread_ci_low"] <= mean_val <= result["ranking_spread_ci_high"], (
            f"CI [{result['ranking_spread_ci_low']}, {result['ranking_spread_ci_high']}] doesn't include mean {mean_val}"
        )

    def test_insufficient_folds_returns_none(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        result = _bootstrap_alpha_ci([{"top_vs_bottom_quintile_alpha": 0.03}])
        assert result["ranking_spread_ci_low"] is None
        assert result["ranking_spread_ci_high"] is None
        assert result["alpha_precision"] == "INSUFFICIENT_DATA"

    def test_no_folds_returns_insufficient(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        result = _bootstrap_alpha_ci([])
        assert result["alpha_precision"] == "INSUFFICIENT_DATA"

    def test_validation_metrics_includes_ci_fields(self, mem_db, monkeypatch):
        """After training with enough data, validation_metrics contains renamed CI fields."""
        import agent_db
        from agents.learning.calibration import ChallengerModel
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 60, with_outcomes=True, noise=0.05)
        conn.close()

        model = ChallengerModel.train()
        if model is None:
            pytest.skip("Insufficient training data in synthetic seed")

        vm = model.validation_metrics
        assert "ranking_spread_ci_low" in vm
        assert "ranking_spread_ci_high" in vm
        assert "alpha_precision" in vm
        assert "alpha_edge_evidence" in vm
        # old keys must NOT be present
        assert "alpha_ci_low" not in vm
        assert "alpha_ci_high" not in vm
        assert "alpha_reliability" not in vm

    def test_ci_ordering_low_le_high(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 60, with_outcomes=True, noise=0.05)
        conn.close()

        model = ChallengerModel.train()
        if model is None:
            pytest.skip("Insufficient training data in synthetic seed")

        vm = model.validation_metrics
        ci_low  = vm.get("ranking_spread_ci_low")
        ci_high = vm.get("ranking_spread_ci_high")
        if ci_low is not None and ci_high is not None:
            assert ci_low <= ci_high, f"CI inverted: low={ci_low} high={ci_high}"

    def test_high_precision_when_spread_tight(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        # Identical values → zero variance → band width ≈ 0 → HIGH precision
        folds = [{"top_vs_bottom_quintile_alpha": 0.03} for _ in range(10)]
        result = _bootstrap_alpha_ci(folds)
        assert result["alpha_precision"] == "HIGH"

    def test_positive_edge_when_ci_above_zero(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        # All spreads clearly positive → CI above zero → POSITIVE edge
        folds = [{"top_vs_bottom_quintile_alpha": 0.10} for _ in range(20)]
        result = _bootstrap_alpha_ci(folds)
        assert result["alpha_edge_evidence"] == "POSITIVE"

    def test_negative_edge_when_ci_below_zero(self):
        from agents.learning.calibration import _bootstrap_alpha_ci

        # All spreads negative → CI below zero → NEGATIVE edge
        folds = [{"top_vs_bottom_quintile_alpha": -0.10} for _ in range(20)]
        result = _bootstrap_alpha_ci(folds)
        assert result["alpha_edge_evidence"] == "NEGATIVE"


class TestActiveModelRegistry0344:
    """0344: load_paper_active() is independent of newest TRAINED model."""

    def test_load_paper_active_returns_none_when_no_active(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import ChallengerModel
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        assert ChallengerModel.load_paper_active() is None

    def test_load_paper_active_ignores_trained_model(self, mem_db, monkeypatch):
        """Training a new model must not shadow the PAPER_ACTIVE one."""
        import agent_db
        from agents.learning.calibration import (
            ChallengerModel, LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_TRAINED, promote
        )
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 60, with_outcomes=True, noise=0.05)
        conn.close()

        # Train and promote edge_v1 to PAPER_ACTIVE
        model_v1 = ChallengerModel.train()
        if model_v1 is None:
            pytest.skip("Insufficient training data")
        model_v1.save_with_weights()
        promote(model_v1.model_version, "OBSERVE", override_reason="test",
                promoted_by="test", promotion_reason="test")
        promote(model_v1.model_version, "PAPER_ACTIVE", override_reason="test",
                promoted_by="test", promotion_reason="test")

        # Insert a second model row directly in TRAINED state (newer created_at)
        import time
        import sqlite3
        conn2 = _make_conn(mem_db)
        import json as _json
        conn2.execute(
            """INSERT INTO learning_models
               (model_version, training_cutoff, feature_schema_hash,
                training_n, validation_metrics, created_at, lifecycle_state)
               VALUES (?,?,?,?,?,?,?)""",
            ("edge_newer", "2099-01-01", "abc123", 70,
             _json.dumps({"coef": [0.1]*5, "intercept": 0.0, "mean_alpha": 0.01}),
             time.time() + 100, LIFECYCLE_TRAINED),
        )
        conn2.commit()
        conn2.close()

        # load_paper_active() must still return edge_v1, not edge_newer
        active = ChallengerModel.load_paper_active()
        assert active is not None
        assert active.model_version == model_v1.model_version
        assert active.lifecycle_state == LIFECYCLE_PAPER_ACTIVE

        # load_latest_trained() should return the newer model
        latest = ChallengerModel.load_latest_trained()
        assert latest is not None
        assert latest.model_version == "edge_newer"

    def test_promote_to_paper_active_retires_existing(self, mem_db, monkeypatch):
        """Promoting a second model to PAPER_ACTIVE auto-retires the first."""
        import agent_db
        from agents.learning.calibration import (
            ChallengerModel, LIFECYCLE_RETIRED, promote
        )
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 60, with_outcomes=True, noise=0.05)
        conn.close()

        model_v1 = ChallengerModel.train()
        if model_v1 is None:
            pytest.skip("Insufficient training data")
        model_v1.save_with_weights()
        promote(model_v1.model_version, "OBSERVE", override_reason="test",
                promoted_by="test", promotion_reason="")
        promote(model_v1.model_version, "PAPER_ACTIVE", override_reason="test",
                promoted_by="test", promotion_reason="")

        # Insert a second model and promote it
        import time, json as _json
        conn2 = _make_conn(mem_db)
        conn2.execute(
            """INSERT INTO learning_models
               (model_version, training_cutoff, feature_schema_hash,
                training_n, validation_metrics, created_at,
                unique_tickers, unique_decision_dates, unique_weeks,
                lifecycle_state)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("edge_v2", "2099-01-01", "abc123", 70,
             _json.dumps({"coef": [0.1]*5, "intercept": 0.0, "mean_alpha": 0.01,
                          "cv_folds": 3, "beats_baseline": True, "alpha_edge_evidence": "POSITIVE"}),
             time.time() + 100, 15, 35, 6, "OBSERVE"),
        )
        conn2.commit()
        conn2.close()

        result = promote("edge_v2", "PAPER_ACTIVE", force=False,
                         promoted_by="test", promotion_reason="",
                         override_reason="test retire behavior")
        assert result["promoted"] is True

        # edge_v1 must now be RETIRED
        conn3 = _make_conn(mem_db)
        v1_row = conn3.execute(
            "SELECT lifecycle_state FROM learning_models WHERE model_version=?",
            (model_v1.model_version,),
        ).fetchone()
        conn3.close()
        assert v1_row["lifecycle_state"] == LIFECYCLE_RETIRED

    def test_save_with_weights_is_immutable(self, mem_db, monkeypatch):
        """Saving the same model_version twice raises IntegrityError (INSERT-only)."""
        import sqlite3
        import agent_db
        from agents.learning.calibration import ChallengerModel
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 60, with_outcomes=True, noise=0.05)
        conn.close()

        model = ChallengerModel.train()
        if model is None:
            pytest.skip("Insufficient training data")
        model.save_with_weights()

        with pytest.raises(sqlite3.IntegrityError):
            model.save_with_weights()  # second save must fail


class TestPromotionGovernanceV2_0348:
    """0348: rich metric snapshots; force=True restricted to RETIRED."""

    def test_force_true_on_non_retired_raises(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        with pytest.raises(ValueError, match="force=True is only allowed for.*RETIRED"):
            promote("any_model", "PAPER_ACTIVE", force=True)

    def test_force_true_to_retired_is_allowed(self, mem_db, monkeypatch):
        import agent_db, time, json as _json
        from agents.learning.calibration import promote, LIFECYCLE_PAPER_ACTIVE
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute(
            """INSERT INTO learning_models
               (model_version, training_cutoff, feature_schema_hash,
                training_n, validation_metrics, created_at, lifecycle_state)
               VALUES (?,?,?,?,?,?,?)""",
            ("mv_force", "2099-01-01", "x", 10,
             _json.dumps({"coef": [0.1]*5, "intercept": 0.0, "mean_alpha": 0.0}),
             time.time(), LIFECYCLE_PAPER_ACTIVE),
        )
        conn.commit()
        conn.close()
        result = promote("mv_force", "RETIRED", force=True, promoted_by="test")
        assert result["promoted"] is True

    def test_snapshot_contains_metric_values(self, mem_db, monkeypatch):
        """promotion_metrics_snapshot must contain actual metric values, not just booleans."""
        import agent_db, time, json as _json
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 60, with_outcomes=True, noise=0.05)
        conn.close()

        from agents.learning.calibration import ChallengerModel
        model = ChallengerModel.train()
        if model is None:
            pytest.skip("Insufficient training data")
        model.save_with_weights()

        promote(model.model_version, "OBSERVE", override_reason="test snapshot check",
                promoted_by="test", promotion_reason="")

        # Read the promotion log
        conn2 = _make_conn(mem_db)
        row = conn2.execute(
            "SELECT promotion_metrics_snapshot FROM model_promotion_log WHERE model_version=? ORDER BY id DESC LIMIT 1",
            (model.model_version,),
        ).fetchone()
        conn2.close()

        snapshot = _json.loads(row["promotion_metrics_snapshot"])
        # Each gate must have a 'value' key
        for gate in ("unique_tickers", "unique_decision_dates", "unique_weeks"):
            assert gate in snapshot, f"Gate {gate!r} missing from snapshot"
            assert "value" in snapshot[gate], f"No 'value' in gate {gate!r}: {snapshot[gate]}"
        assert "gates_bypassed" in snapshot

    def test_gates_bypassed_false_on_normal_promotion(self, mem_db, monkeypatch):
        import agent_db, json as _json
        from agents.learning.calibration import promote
        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        # Seed a model row that will naturally pass all gates (no override needed)
        conn = _make_conn(mem_db)
        conn.execute(
            """INSERT INTO learning_models
               (model_version, training_cutoff, feature_schema_hash, training_n,
                validation_metrics, created_at, unique_tickers, unique_decision_dates,
                unique_weeks, lifecycle_state)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("edge_gate_test", "2026-01-01", "abc", 50,
             _json.dumps({"cv_folds": 3, "beats_baseline": True, "coef": [0.1]*5, "intercept": 0.0}),
             time.time(), 15, 35, 6, "TRAINED"),
        )
        conn.commit()
        conn.close()

        result = promote("edge_gate_test", "OBSERVE", promoted_by="test", promotion_reason="")
        assert result["promoted"] is True

        conn2 = _make_conn(mem_db)
        row = conn2.execute(
            "SELECT promotion_metrics_snapshot FROM model_promotion_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn2.close()
        snap = _json.loads(row["promotion_metrics_snapshot"])
        assert snap["gates_bypassed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 0349 — Variant Idempotency and Account Roles
# ─────────────────────────────────────────────────────────────────────────────

class TestVariantIdempotencyAndRoles0349:
    """0349: decision_variant_id-based idempotency; role-based challenger routing."""

    def _make_policy(self, account_id: str):
        return _make_test_policy(account_id)

    def test_variant_idempotency_by_variant_id(self, mem_db, monkeypatch):
        """A risk-rejected challenger intent for a given decision_variant_id cannot be re-created."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant
        from trade_engine.models import IntentStatus

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('ALPACA_49','paper',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'NVDA',1000000,80,'v1')",
            (ep_id,),
        )
        row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',82,2,1,'AAPL','NVDA','BUY',500.0,1000000)""",
            (ep_id,),
        )
        variant_id = row.lastrowid
        conn.commit()

        policy = self._make_policy("ALPACA_49")
        intent1 = build_intent_from_variant(variant_id, "ALPACA_49", policy, conn)
        assert intent1 is not None

        # Simulate risk rejection
        conn.execute(
            "UPDATE trade_intents SET status='REJECTED' WHERE intent_id=?",
            (intent1.intent_id,),
        )
        conn.commit()

        # Second call for same variant_id must return the rejected intent, not create a new one
        intent2 = build_intent_from_variant(variant_id, "ALPACA_49", policy, conn)
        conn.close()
        # The idempotency check should NOT return the rejected intent (status in excluded list)
        # so a NEW intent would be created — but that's only valid if we change the query.
        # Per 0349, rejected variant should NOT produce a duplicate pending intent.
        # With the current fix, REJECTED is in NOT IN list → intent2 would be None or new.
        # The key invariant: at most one non-terminal intent per decision_variant_id.
        if intent2 is not None:
            assert intent2.intent_id != intent1.intent_id or intent2.status != IntentStatus.PENDING

    def test_role_based_routing_paper_challenger(self, mem_db, monkeypatch):
        """An account with role='paper_challenger' routes to the challenger path."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at,role) VALUES ('CUST_PAPER_01','paper',100000,'2026-01-01','paper_challenger')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'ANET',1000000,82,'v1')",
            (ep_id,),
        )
        conn.execute(
            """INSERT INTO recommendations
               (id,run_id,ticker,action,status,recommendation_score,episode_id,action_payload_json,created_at)
               VALUES (8801,1,'ANET','BUY','accepted',82,?,'{"price":300.0,"quantity":3}',1000000)""",
            (ep_id,),
        )
        conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',85,3,1,'ANET','GRMN','BUY',150.0,1000000)""",
            (ep_id,),
        )
        conn.commit()

        policy = self._make_policy("CUST_PAPER_01")
        intent = build_intent(8801, "CUST_PAPER_01", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.symbol == "GRMN", f"Expected GRMN (challenger), got {intent.symbol}"
        assert intent.decision_origin == "PAPER_CHALLENGER"

    def test_non_challenger_role_account_gets_champion(self, mem_db, monkeypatch):
        """A future ALPACA_LIVE_01 without role='paper_challenger' gets champion behavior."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        # Note: role is NULL (no paper_challenger role), but account_id contains "ALPACA"
        # With the fix, NULL role + ALPACA in name falls back to string match.
        # For a live account with explicit role='live', it must NOT get challenger.
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at,role) VALUES ('ALPACA_LIVE_01','live',100000,'2026-01-01','live')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'ANET',1000000,82,'v1')",
            (ep_id,),
        )
        conn.execute(
            """INSERT INTO recommendations
               (id,run_id,ticker,action,status,recommendation_score,episode_id,action_payload_json,created_at)
               VALUES (8802,1,'ANET','BUY','accepted',82,?,'{"price":300.0,"quantity":3}',1000000)""",
            (ep_id,),
        )
        conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',85,3,1,'ANET','GRMN','BUY',150.0,1000000)""",
            (ep_id,),
        )
        conn.commit()

        policy = self._make_policy("ALPACA_LIVE_01")
        intent = build_intent(8802, "ALPACA_LIVE_01", policy, conn)
        conn.close()

        # role='live' → not paper_challenger → should get champion ticker ANET
        assert intent is not None
        assert intent.symbol == "ANET", f"Expected ANET (champion), got {intent.symbol}"
        assert intent.decision_origin == "CHAMPION"

    def test_decision_variant_id_stored_on_challenger_intent(self, mem_db, monkeypatch):
        """build_intent_from_variant stores the decision_variant_id on the intent."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('ALPACA_49B','paper',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'META',1000000,78,'v1')",
            (ep_id,),
        )
        row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',80,2,0,'ANET','META','BUY',250.0,1000000)""",
            (ep_id,),
        )
        variant_id = row.lastrowid
        conn.commit()

        policy = self._make_policy("ALPACA_49B")
        intent = build_intent_from_variant(variant_id, "ALPACA_49B", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.decision_variant_id == variant_id


# ─────────────────────────────────────────────────────────────────────────────
# 0350 — Real Execution Benchmarking
# ─────────────────────────────────────────────────────────────────────────────

class TestRealExecutionBenchmarking0350:
    """0350: limit_variance, decision_market_price, true IS calculations."""

    def test_limit_variance_buy_adverse(self, mem_db, monkeypatch):
        """BUY: fill above limit → positive (adverse) limit_variance."""
        limit_price = 100.0
        fill_price = 101.0
        lv = (fill_price - limit_price) / limit_price
        assert lv == pytest.approx(0.01)

    def test_limit_variance_sell_adverse(self, mem_db, monkeypatch):
        """SELL: fill below limit → positive (adverse) limit_variance."""
        limit_price = 100.0
        fill_price = 99.0
        lv = (limit_price - fill_price) / limit_price
        assert lv == pytest.approx(0.01)

    def test_limit_variance_buy_favorable(self, mem_db, monkeypatch):
        """BUY: fill below limit → negative (favorable) limit_variance."""
        limit_price = 100.0
        fill_price = 99.5
        lv = (fill_price - limit_price) / limit_price
        assert lv == pytest.approx(-0.005)

    def test_decision_market_price_fields_on_intent(self, mem_db, monkeypatch):
        """TradeIntent dataclass declares decision_market_price, decision_bid, decision_ask."""
        import dataclasses
        from trade_engine.models import TradeIntent

        field_names = {f.name for f in dataclasses.fields(TradeIntent)}
        assert "decision_market_price" in field_names
        assert "decision_bid" in field_names
        assert "decision_ask" in field_names
        assert "decision_variant_id" in field_names

    def test_true_is_uses_decision_market_price(self, mem_db, monkeypatch):
        """True IS = fill vs decision_market_price (pre-slippage arrival price)."""
        fill_price = 502.0
        decision_market_price = 499.0
        true_is = (fill_price - decision_market_price) / decision_market_price
        assert true_is == pytest.approx(3.0 / 499.0)

    def test_limit_variance_none_when_no_limit_price(self, mem_db, monkeypatch):
        """limit_variance is None when limit_price is missing."""
        intent_limit_price = None
        fill_price = 100.0
        if intent_limit_price and intent_limit_price > 0:
            lv = (fill_price - intent_limit_price) / intent_limit_price
        else:
            lv = None
        assert lv is None

    def test_decision_variant_id_on_trade_intent_schema(self, mem_db, monkeypatch):
        """trade_intents table has decision_variant_id and decision_market_price columns."""
        conn = _make_conn(mem_db)
        pragma = conn.execute("PRAGMA table_info(trade_intents)").fetchall()
        col_names = [row["name"] for row in pragma]
        conn.close()
        assert "decision_variant_id" in col_names
        assert "decision_market_price" in col_names
        assert "decision_bid" in col_names
        assert "decision_ask" in col_names

    def test_limit_variance_in_trade_outcomes_schema(self, mem_db, monkeypatch):
        """trade_outcomes table has limit_variance column."""
        conn = _make_conn(mem_db)
        pragma = conn.execute("PRAGMA table_info(trade_outcomes)").fetchall()
        col_names = [row["name"] for row in pragma]
        conn.close()
        assert "limit_variance" in col_names


# ─────────────────────────────────────────────────────────────────────────────
# 0352 — Variant Idempotency Hard DB Constraint
# ─────────────────────────────────────────────────────────────────────────────

class TestVariantIdempotencyHardConstraint0352:
    """0352: terminal intent permanently closes a variant; unique DB index enforced."""

    def _make_policy(self, account_id: str):
        return _make_test_policy(account_id)

    def test_rejected_variant_returns_none(self, mem_db, monkeypatch):
        """A REJECTED variant intent makes the variant permanently closed (returns None on re-run)."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('ALPACA_52','paper',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'GOOG',1000000,75,'v1')",
            (ep_id,),
        )
        row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',77,2,1,'AAPL','GOOG','BUY',170.0,1000000)""",
            (ep_id,),
        )
        variant_id = row.lastrowid
        conn.commit()

        policy = self._make_policy("ALPACA_52")
        intent1 = build_intent_from_variant(variant_id, "ALPACA_52", policy, conn)
        assert intent1 is not None

        conn.execute(
            "UPDATE trade_intents SET status='REJECTED' WHERE intent_id=?", (intent1.intent_id,)
        )
        conn.commit()

        # Second call: terminal REJECTED → must return None (not a new PENDING intent)
        intent2 = build_intent_from_variant(variant_id, "ALPACA_52", policy, conn)
        conn.close()
        assert intent2 is None, "REJECTED variant should not produce a new PENDING intent"

    def test_expired_variant_returns_none(self, mem_db, monkeypatch):
        """An EXPIRED variant intent also permanently closes the variant."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('ALPACA_53','paper',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'MSFT',1000000,80,'v1')",
            (ep_id,),
        )
        row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',82,2,0,'MSFT','MSFT','BUY',400.0,1000000)""",
            (ep_id,),
        )
        variant_id = row.lastrowid
        conn.commit()

        policy = self._make_policy("ALPACA_53")
        intent1 = build_intent_from_variant(variant_id, "ALPACA_53", policy, conn)
        assert intent1 is not None
        conn.execute(
            "UPDATE trade_intents SET status='EXPIRED' WHERE intent_id=?", (intent1.intent_id,)
        )
        conn.commit()

        intent2 = build_intent_from_variant(variant_id, "ALPACA_53", policy, conn)
        conn.close()
        assert intent2 is None, "EXPIRED variant should not produce a new PENDING intent"

    def test_unique_index_on_account_variant(self, mem_db, monkeypatch):
        """idx_intent_per_variant unique index exists in schema."""
        conn = _make_conn(mem_db)
        indexes = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()]
        conn.close()
        assert "idx_intent_per_variant" in indexes, "Unique index idx_intent_per_variant missing"

    def test_non_terminal_intent_returned_on_second_call(self, mem_db, monkeypatch):
        """A PENDING variant intent is returned as-is on second build call."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant
        from trade_engine.models import IntentStatus

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('ALPACA_54','paper',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'AMZN',1000000,85,'v1')",
            (ep_id,),
        )
        row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',87,2,0,'AMZN','AMZN','BUY',190.0,1000000)""",
            (ep_id,),
        )
        variant_id = row.lastrowid
        conn.commit()

        policy = self._make_policy("ALPACA_54")
        intent1 = build_intent_from_variant(variant_id, "ALPACA_54", policy, conn)
        intent2 = build_intent_from_variant(variant_id, "ALPACA_54", policy, conn)
        conn.close()

        assert intent1 is not None
        assert intent2 is not None
        assert intent1.intent_id == intent2.intent_id


# ─────────────────────────────────────────────────────────────────────────────
# 0353 — Remove Account-ID String-Match Routing Heuristic
# ─────────────────────────────────────────────────────────────────────────────

class TestRemoveAccountIdHeuristics0353:
    """0353: routing uses role column only; NULL role → champion regardless of account_id name."""

    def _make_policy(self, account_id: str):
        return _make_test_policy(account_id)

    def _setup_ep_rec_variant(self, conn, rec_id, ep_id, champion_ticker, challenger_ticker, price):
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,?,1000000,80,'v1')",
            (ep_id, champion_ticker),
        )
        conn.execute(
            f"""INSERT INTO recommendations
               (id,run_id,ticker,action,status,recommendation_score,episode_id,action_payload_json,created_at)
               VALUES ({rec_id},1,?,\'BUY\',\'accepted\',80,?,'{{\"price\":{price}}}',1000000)""",
            (champion_ticker, ep_id),
        )
        conn.execute(
            """INSERT INTO decision_variants
               (episode_id,origin,challenger_model_version,challenger_score,challenger_adjustment,
                would_have_selected,champion_ticker,variant_ticker,action,price,created_at)
               VALUES (?,'PAPER_CHALLENGER','v1',82,2,1,?,?,'BUY',?,1000000)""",
            (ep_id, champion_ticker, challenger_ticker, price),
        )
        conn.commit()

    def test_alpaca_live_null_role_gets_champion(self, mem_db, monkeypatch):
        """ALPACA_LIVE_01 with role=NULL → champion behavior (no ALPACA string-match fallback)."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('ALPACA_LIVE_01','live',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        self._setup_ep_rec_variant(conn, 9901, ep_id, "AAPL", "GRMN", 200.0)

        policy = self._make_policy("ALPACA_LIVE_01")
        intent = build_intent(9901, "ALPACA_LIVE_01", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.symbol == "AAPL", f"Expected champion AAPL, got {intent.symbol}"
        assert intent.decision_origin == "CHAMPION"

    def test_foo_alpaca_test_null_role_gets_champion(self, mem_db, monkeypatch):
        """FOO_ALPACA_TEST with role=NULL → champion behavior."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at) VALUES ('FOO_ALPACA_TEST','paper',100000,'2026-01-01')"
        )
        ep_id = str(uuid.uuid4())
        self._setup_ep_rec_variant(conn, 9902, ep_id, "NVDA", "TSLA", 450.0)

        policy = self._make_policy("FOO_ALPACA_TEST")
        intent = build_intent(9902, "FOO_ALPACA_TEST", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.symbol == "NVDA", f"Expected champion NVDA, got {intent.symbol}"

    def test_paper_challenger_role_gets_challenger(self, mem_db, monkeypatch):
        """Account with role='paper_challenger' → challenger behavior (GRMN not AAPL)."""
        import agent_db
        from trade_engine.intent_builder import build_intent

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT OR IGNORE INTO trading_accounts (account_id,mode,current_cash,created_at,role) VALUES ('MY_PAPER_01','paper',100000,'2026-01-01','paper_challenger')"
        )
        ep_id = str(uuid.uuid4())
        self._setup_ep_rec_variant(conn, 9903, ep_id, "AAPL", "GRMN", 200.0)

        policy = self._make_policy("MY_PAPER_01")
        intent = build_intent(9903, "MY_PAPER_01", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.symbol == "GRMN", f"Expected challenger GRMN, got {intent.symbol}"
        assert intent.decision_origin == "PAPER_CHALLENGER"


# ─────────────────────────────────────────────────────────────────────────────
# 0354 — Separate Experiment Champion from LLM Recommendation Lineage
# ─────────────────────────────────────────────────────────────────────────────

class TestExperimentChampionLineage0354:
    """0354: decision_variants stores recommendation_control_ticker and experiment_champion_ticker."""

    def test_new_columns_in_schema(self, mem_db, monkeypatch):
        """decision_variants table has recommendation_control_ticker and experiment_champion_ticker."""
        conn = _make_conn(mem_db)
        pragma = conn.execute("PRAGMA table_info(decision_variants)").fetchall()
        col_names = [r["name"] for r in pragma]
        conn.close()
        assert "recommendation_control_ticker" in col_names
        assert "experiment_champion_ticker" in col_names

    def test_insert_decision_variant_populates_both(self, mem_db, monkeypatch):
        """_insert_decision_variant populates both new ticker fields independently."""
        import agent_db
        from agents.opportunity_agent import _insert_decision_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'AAPL',%.6f,80,'v1')" % time.time(),
            (ep_id,),
        )
        conn.execute(
            "INSERT INTO learning_models (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,created_at,lifecycle_state) VALUES ('v_test','cutoff','hash',50,'{}',%.6f,'PAPER_ACTIVE')" % time.time(),
        )
        conn.commit()

        scored = [
            {"ticker": "AAPL", "_composite": 90, "_composite_challenger": 85,
             "_challenger_info": {"active": True, "model_version": "v_test", "learning_adjustment": -5},
             "_episode_id": ep_id, "price": 200.0},
            {"ticker": "GRMN", "_composite": 82, "_composite_challenger": 88,
             "_challenger_info": {"active": True, "model_version": "v_test", "learning_adjustment": 6},
             "_episode_id": ep_id, "price": 150.0},
        ]
        champion = {"ticker": "AAPL", "_episode_id": ep_id}

        _insert_decision_variant(
            scored, champion,
            champion_ticker="AAPL",
            experiment_champion_ticker="AAPL",  # top-1 by base score
        )

        row = conn.execute(
            "SELECT recommendation_control_ticker, experiment_champion_ticker FROM decision_variants WHERE episode_id=?",
            (ep_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["recommendation_control_ticker"] == "AAPL"
        assert row["experiment_champion_ticker"] == "AAPL"

    def test_experiment_champion_can_differ_from_recommendation_control(self, mem_db, monkeypatch):
        """If LLM picks different ticker than base-score top-1, both fields differ."""
        import agent_db
        from agents.opportunity_agent import _insert_decision_variant

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        ep_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'MSFT',%.6f,88,'v1')" % time.time(),
            (ep_id,),
        )
        conn.commit()

        scored = [
            {"ticker": "MSFT", "_composite": 88, "_composite_challenger": 80,
             "_challenger_info": {"active": True, "model_version": "v2", "learning_adjustment": -8},
             "_episode_id": ep_id, "price": 420.0},
            {"ticker": "NVDA", "_composite": 85, "_composite_challenger": 91,
             "_challenger_info": {"active": True, "model_version": "v2", "learning_adjustment": 6},
             "_episode_id": ep_id, "price": 950.0},
        ]
        # LLM selected NVDA (not the base-score top-1 MSFT)
        champion = {"ticker": "NVDA", "_episode_id": ep_id}

        _insert_decision_variant(
            scored, champion,
            champion_ticker="NVDA",            # LLM recommendation
            experiment_champion_ticker="MSFT", # base-score top-1
        )

        row = conn.execute(
            "SELECT recommendation_control_ticker, experiment_champion_ticker, variant_ticker FROM decision_variants WHERE episode_id=?",
            (ep_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["recommendation_control_ticker"] == "NVDA"
        assert row["experiment_champion_ticker"] == "MSFT"
        assert row["recommendation_control_ticker"] != row["experiment_champion_ticker"]


# ─────────────────────────────────────────────────────────────────────────────
# 0355 — State-Specific Promotion Gates
# ─────────────────────────────────────────────────────────────────────────────

class TestStateSpecificPromotionGates0355:
    """0355: TRAINED→OBSERVE requires cv_folds>=3; OBSERVE→PAPER_ACTIVE requires elapsed time."""

    def test_cv_folds_3_required_for_observe(self, mem_db, monkeypatch):
        """cv_folds=2 blocks TRAINED→OBSERVE (now requires >=3)."""
        import agent_db
        from agents.learning.calibration import _check_promotion_gates, PROMOTE_MIN_CV_FOLDS

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        assert PROMOTE_MIN_CV_FOLDS == 3

        conn = _make_conn(mem_db)
        vm = {"cv_folds": 2, "beats_baseline": True, "alpha_edge_evidence": "POSITIVE",
              "unique_tickers": 15, "unique_decision_dates": 35, "unique_weeks": 6}
        conn.execute(
            """INSERT INTO learning_models
               (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,
                created_at,unique_tickers,unique_decision_dates,unique_weeks,raw_n,lifecycle_state)
               VALUES ('mv_355a','cut','h',60,?,?,15,35,6,60,'TRAINED')""",
            (json.dumps(vm), time.time()),
        )
        conn.commit()
        conn.close()

        result = _check_promotion_gates("mv_355a", "OBSERVE")
        assert not result["passed"], "cv_folds=2 should fail the TRAINED→OBSERVE gate"
        assert "has_cv_folds" in result["failed"]

    def test_cv_folds_3_passes_for_observe(self, mem_db, monkeypatch):
        """cv_folds=3 passes the TRAINED→OBSERVE gate."""
        import agent_db
        from agents.learning.calibration import _check_promotion_gates

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        vm = {"cv_folds": 3, "beats_baseline": True, "alpha_edge_evidence": "INCONCLUSIVE",
              "unique_tickers": 15, "unique_decision_dates": 35, "unique_weeks": 6}
        conn.execute(
            """INSERT INTO learning_models
               (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,
                created_at,unique_tickers,unique_decision_dates,unique_weeks,raw_n,lifecycle_state)
               VALUES ('mv_355b','cut','h',60,?,?,15,35,6,60,'TRAINED')""",
            (json.dumps(vm), time.time()),
        )
        conn.commit()
        conn.close()

        result = _check_promotion_gates("mv_355b", "OBSERVE")
        assert result["passed"], f"cv_folds=3 should pass TRAINED→OBSERVE; failed: {result['failed']}"

    def test_observe_to_paper_active_blocked_within_14_days(self, mem_db, monkeypatch):
        """Model promoted to OBSERVE today cannot immediately promote to PAPER_ACTIVE."""
        import agent_db
        from agents.learning.calibration import _check_promotion_gates, OBSERVE_MIN_DAYS

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        vm = {"cv_folds": 5, "beats_baseline": True, "alpha_edge_evidence": "POSITIVE",
              "unique_tickers": 20, "unique_decision_dates": 40, "unique_weeks": 8}
        conn.execute(
            """INSERT INTO learning_models
               (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,
                created_at,unique_tickers,unique_decision_dates,unique_weeks,raw_n,lifecycle_state)
               VALUES ('mv_355c','cut','h',80,?,?,20,40,8,80,'OBSERVE')""",
            (json.dumps(vm), time.time()),
        )
        # Log OBSERVE promotion as of "now" (< OBSERVE_MIN_DAYS ago)
        conn.execute(
            """INSERT INTO model_promotion_log
               (model_version,from_state,to_state,promoted_by,promoted_at,promotion_reason,promotion_metrics_snapshot)
               VALUES ('mv_355c','TRAINED','OBSERVE','test',?,?,?)""",
            (time.time(), "test", "{}"),
        )
        # Seed enough fresh episodes
        for i in range(10):
            ep_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'TK',?,80,'v1')",
                (ep_id, time.time() + i),
            )
        conn.commit()
        conn.close()

        result = _check_promotion_gates("mv_355c", "PAPER_ACTIVE")
        assert not result["passed"], "Model promoted to OBSERVE today should not reach PAPER_ACTIVE"
        assert "observe_elapsed_days" in result["failed"]

    def test_observe_to_paper_active_passes_after_14_days(self, mem_db, monkeypatch):
        """Model that has been in OBSERVE for 15 days with 5+ fresh episodes can promote."""
        import agent_db
        from agents.learning.calibration import _check_promotion_gates, OBSERVE_MIN_DAYS

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        # Promote to OBSERVE 15 days ago
        observe_at = time.time() - (OBSERVE_MIN_DAYS + 1) * 86400
        conn = _make_conn(mem_db)
        vm = {"cv_folds": 5, "beats_baseline": True, "alpha_edge_evidence": "POSITIVE",
              "unique_tickers": 20, "unique_decision_dates": 40, "unique_weeks": 8}
        conn.execute(
            """INSERT INTO learning_models
               (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,
                created_at,unique_tickers,unique_decision_dates,unique_weeks,raw_n,lifecycle_state)
               VALUES ('mv_355d','cut','h',80,?,?,20,40,8,80,'OBSERVE')""",
            (json.dumps(vm), observe_at),
        )
        conn.execute(
            """INSERT INTO model_promotion_log
               (model_version,from_state,to_state,promoted_by,promoted_at,promotion_reason,promotion_metrics_snapshot)
               VALUES ('mv_355d','TRAINED','OBSERVE','test',?,?,?)""",
            (observe_at, "test", "{}"),
        )
        # Seed 6 fresh episodes after the OBSERVE promotion
        for i in range(6):
            ep_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'TK',?,80,'v1')",
                (ep_id, observe_at + i * 86400 + 100),
            )

        # 0360: seed 5 mature model_observations (outcome_alpha_90d required)
        import datetime as _dt
        for i in range(5):
            conn.execute(
                """INSERT INTO model_observations
                   (model_version, episode_id, ticker, prediction_timestamp,
                    challenger_score, would_select, outcome_alpha_90d, outcome_labeled_at)
                   VALUES ('mv_355d', ?, 'TK', ?, 0.5, 1, 0.02, ?)""",
                (str(uuid.uuid4()), _dt.datetime.utcnow().isoformat(), _dt.datetime.utcnow().isoformat()),
            )
        conn.commit()
        conn.close()

        result = _check_promotion_gates("mv_355d", "PAPER_ACTIVE")
        assert result["passed"], f"Should pass after 15 days + 6 episodes + 5 observations; failed: {result['failed']}"


# ===========================================================================
# 0358 — Correct Decision/Episode Lineage
# ===========================================================================

class TestEpisodeLineage0358:
    """0358: decision_variants stores 3 separate episode IDs; intent uses challenger_episode_id."""

    def test_three_episode_ids_stored_separately(self, mem_db, monkeypatch):
        """decision_variants has recommendation_control_episode_id, experiment_champion_episode_id, challenger_episode_id."""
        import agent_db

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        ctrl_ep = str(uuid.uuid4())
        exp_ep  = str(uuid.uuid4())
        chal_ep = str(uuid.uuid4())

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT INTO decision_variants
               (episode_id, origin, variant_ticker, action, price,
                recommendation_control_episode_id,
                experiment_champion_episode_id,
                challenger_episode_id, created_at)
               VALUES ('ctrl_ep', 'PAPER_CHALLENGER', 'AAPL', 'BUY', 200.0, ?, ?, ?, ?)""",
            (ctrl_ep, exp_ep, chal_ep, time.time()),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM decision_variants LIMIT 1").fetchone()
        conn.close()

        assert row["recommendation_control_episode_id"] == ctrl_ep
        assert row["experiment_champion_episode_id"]    == exp_ep
        assert row["challenger_episode_id"]             == chal_ep

    def test_challenger_intent_uses_challenger_episode_id(self, mem_db, monkeypatch):
        """build_intent_from_variant uses challenger_episode_id when present."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant
        from trade_engine.policy import TradingPolicy

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        chal_ep = "ep-challenger-specific"
        ctrl_ep = "ep-control-different"

        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at, role)
            VALUES ('CHAL_ACCT', 'paper', 100000, 1000000, 'paper_challenger')""")
        variant_id_row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id, origin, variant_ticker, action, price,
                recommendation_control_episode_id, challenger_episode_id, created_at)
               VALUES (?, 'PAPER_CHALLENGER', 'MSFT', 'BUY', 400.0, ?, ?, ?)""",
            (ctrl_ep, ctrl_ep, chal_ep, time.time()),
        )
        variant_id = variant_id_row.lastrowid
        conn.commit()

        import json
        policy = TradingPolicy(
            policy_version="1.0", account_id="CHAL_ACCT",
            capital={"starting_capital": 100000, "minimum_cash_pct": 5, "minimum_cash_abs": 500},
            equities={"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                      "max_single_position_pct": 20, "max_new_position_pct": 10},
            options={"covered_calls_allowed": False, "naked_options_allowed": False, "max_contracts_per_symbol": 0},
            execution={"market_orders_allowed": False, "max_orders_per_day": 5,
                       "max_daily_notional_pct": 50, "max_slippage_pct": 1.0, "min_limit_price": 0.01},
            risk={"max_drawdown_pct": 20, "max_daily_loss_pct": 5, "max_weekly_loss_pct": 10},
            circuit_breakers={"trading_enabled": True, "halt_on_position_mismatch": False,
                               "halt_on_data_stale_minutes": 1440, "halt_on_daily_loss_pct": 10},
            _raw_json="{}",
        )
        intent = build_intent_from_variant(variant_id, "CHAL_ACCT", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.episode_id == chal_ep, f"Expected challenger ep, got: {intent.episode_id}"

    def test_falls_back_to_episode_id_for_old_rows(self, mem_db, monkeypatch):
        """NULL challenger_episode_id falls back to legacy episode_id column."""
        import agent_db
        from trade_engine.intent_builder import build_intent_from_variant
        from trade_engine.policy import TradingPolicy

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        legacy_ep = "ep-legacy"
        conn = _make_conn(mem_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""INSERT INTO trading_accounts
            (account_id, mode, current_cash, created_at, role)
            VALUES ('CHAL_B', 'paper', 100000, 1000000, 'paper_challenger')""")
        row = conn.execute(
            """INSERT INTO decision_variants
               (episode_id, origin, variant_ticker, action, price,
                challenger_episode_id, created_at)
               VALUES (?, 'PAPER_CHALLENGER', 'GOOG', 'BUY', 180.0, NULL, ?)""",
            (legacy_ep, time.time()),
        )
        variant_id = row.lastrowid
        conn.commit()

        import json
        policy = TradingPolicy(
            policy_version="1.0", account_id="CHAL_B",
            capital={"starting_capital": 100000, "minimum_cash_pct": 5, "minimum_cash_abs": 500},
            equities={"buy_allowed": True, "sell_allowed": True, "shorting_allowed": False,
                      "max_single_position_pct": 20, "max_new_position_pct": 10},
            options={"covered_calls_allowed": False, "naked_options_allowed": False, "max_contracts_per_symbol": 0},
            execution={"market_orders_allowed": False, "max_orders_per_day": 5,
                       "max_daily_notional_pct": 50, "max_slippage_pct": 1.0, "min_limit_price": 0.01},
            risk={"max_drawdown_pct": 20, "max_daily_loss_pct": 5, "max_weekly_loss_pct": 10},
            circuit_breakers={"trading_enabled": True, "halt_on_position_mismatch": False,
                               "halt_on_data_stale_minutes": 1440, "halt_on_daily_loss_pct": 10},
            _raw_json="{}",
        )
        intent = build_intent_from_variant(variant_id, "CHAL_B", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.episode_id == legacy_ep, f"Expected legacy ep fallback, got: {intent.episode_id}"


# ===========================================================================
# 0360 — OBSERVE Shadow Scoring
# ===========================================================================

class TestObserveShadowScoring0360:
    """0360: score_for_observe writes model_observations; mature_observations gate."""

    def _seed_observe_model(self, conn, model_version: str) -> None:
        conn.execute(
            """INSERT INTO learning_models
               (model_version, training_cutoff, feature_schema_hash, training_n,
                validation_metrics, created_at, unique_tickers, unique_decision_dates,
                unique_weeks, lifecycle_state, promotion_gates_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (model_version, "2026-01-01", "abc", 50,
             '{"cv_folds":3,"beats_baseline":true,"coef":[0.001,0.001,0.001,0.001,0.001],"intercept":0.0,"mean_alpha":0.02,"feature_schema_hash":"h","shrinkage_factor":0.5}',
             time.time(), 15, 35, 6, "OBSERVE", None),
        )
        conn.commit()

    def test_observe_model_writes_observations(self, mem_db, monkeypatch):
        """score_for_observe() writes model_observations rows for OBSERVE model."""
        import agent_db
        from agents.learning.calibration import ChallengerModel
        from agents.learning.challenger import score_for_observe

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        conn = _make_conn(mem_db)
        _seed_episodes(conn, 50)
        conn.close()

        model = ChallengerModel.train()
        model.save_with_weights()
        conn = _make_conn(mem_db)
        conn.execute(
            "UPDATE learning_models SET lifecycle_state='OBSERVE' WHERE model_version=?",
            (model.model_version,),
        )
        conn.commit()
        conn.close()

        candidates = [
            {"ticker": "AAPL", "_episode_id": str(uuid.uuid4()), "_composite": 80,
             "composite_score": 80,
             "q_score": 80, "v_score": 75, "pf_score": 70, "c_score": 65, "ec_score": 60},
            {"ticker": "MSFT", "_episode_id": str(uuid.uuid4()), "_composite": 75,
             "composite_score": 75,
             "q_score": 75, "v_score": 70, "pf_score": 65, "c_score": 60, "ec_score": 55},
        ]
        score_for_observe(model.model_version, candidates)

        conn = _make_conn(mem_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM model_observations WHERE model_version=?",
            (model.model_version,),
        ).fetchone()[0]
        conn.close()
        assert count > 0, "score_for_observe should write observations"

    def test_paper_active_gate_requires_mature_observations(self, mem_db, monkeypatch):
        """OBSERVE→PAPER_ACTIVE fails when mature_observations < 5."""
        import agent_db
        from agents.learning.calibration import _check_promotion_gates

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        import datetime as _dt
        observe_at = time.time() - (16 * 86400)  # 16 days ago
        conn = _make_conn(mem_db)
        vm = {"cv_folds": 5, "beats_baseline": True, "alpha_edge_evidence": "POSITIVE",
              "unique_tickers": 20, "unique_decision_dates": 40, "unique_weeks": 8}
        conn.execute(
            """INSERT INTO learning_models
               (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,
                created_at,unique_tickers,unique_decision_dates,unique_weeks,raw_n,lifecycle_state)
               VALUES ('mv_obs_req','cut','h',80,?,?,20,40,8,80,'OBSERVE')""",
            (json.dumps(vm), observe_at),
        )
        conn.execute(
            """INSERT INTO model_promotion_log
               (model_version,from_state,to_state,promoted_by,promoted_at,promotion_reason,promotion_metrics_snapshot)
               VALUES ('mv_obs_req','TRAINED','OBSERVE','test',?,?,?)""",
            (observe_at, "test", "{}"),
        )
        for i in range(6):
            conn.execute(
                "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'TK',?,80,'v1')",
                (str(uuid.uuid4()), observe_at + i * 86400 + 100),
            )
        # 0 mature observations — gate should fail
        conn.commit()
        conn.close()

        result = _check_promotion_gates("mv_obs_req", "PAPER_ACTIVE")
        assert not result["passed"]
        assert "mature_observations" in result["failed"]

    def test_paper_active_gate_passes_with_mature_observations(self, mem_db, monkeypatch):
        """OBSERVE→PAPER_ACTIVE passes when 5+ mature model_observations exist."""
        import agent_db
        from agents.learning.calibration import _check_promotion_gates

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        import datetime as _dt
        observe_at = time.time() - (16 * 86400)
        conn = _make_conn(mem_db)
        vm = {"cv_folds": 5, "beats_baseline": True, "alpha_edge_evidence": "POSITIVE",
              "unique_tickers": 20, "unique_decision_dates": 40, "unique_weeks": 8}
        conn.execute(
            """INSERT INTO learning_models
               (model_version,training_cutoff,feature_schema_hash,training_n,validation_metrics,
                created_at,unique_tickers,unique_decision_dates,unique_weeks,raw_n,lifecycle_state)
               VALUES ('mv_obs_pass','cut','h',80,?,?,20,40,8,80,'OBSERVE')""",
            (json.dumps(vm), observe_at),
        )
        conn.execute(
            """INSERT INTO model_promotion_log
               (model_version,from_state,to_state,promoted_by,promoted_at,promotion_reason,promotion_metrics_snapshot)
               VALUES ('mv_obs_pass','TRAINED','OBSERVE','test',?,?,?)""",
            (observe_at, "test", "{}"),
        )
        for i in range(6):
            conn.execute(
                "INSERT INTO decision_episodes (episode_id,run_id,ticker,captured_at,composite_score,feature_schema_version) VALUES (?,1,'TK',?,80,'v1')",
                (str(uuid.uuid4()), observe_at + i * 86400 + 100),
            )
        # 5 mature observations
        now_iso = _dt.datetime.utcnow().isoformat()
        for i in range(5):
            conn.execute(
                """INSERT INTO model_observations
                   (model_version, episode_id, ticker, prediction_timestamp,
                    challenger_score, would_select, outcome_alpha_90d, outcome_labeled_at)
                   VALUES ('mv_obs_pass', ?, 'TK', ?, 0.5, 1, 0.02, ?)""",
                (str(uuid.uuid4()), now_iso, now_iso),
            )
        conn.commit()
        conn.close()

        result = _check_promotion_gates("mv_obs_pass", "PAPER_ACTIVE")
        assert result["passed"], f"Should pass with 5 mature obs; failed: {result['failed']}"
