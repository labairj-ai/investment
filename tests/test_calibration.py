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
        r1 = promote(model.model_version, "OBSERVE", force=True)
        assert r1["promoted"], f"promote to OBSERVE failed: {r1}"
        r2 = promote(model.model_version, "PAPER_ACTIVE", force=True)
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

        result = promote(model.model_version, "OBSERVE", force=True)
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

        result = promote(model.model_version, "PAPER_ACTIVE", force=True)
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
        promote(model.model_version, "OBSERVE", force=True)
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
        promote(model.model_version, "OBSERVE", force=True)
        promote(model.model_version, "PAPER_ACTIVE", force=True)
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
        promote(model.model_version, "OBSERVE", force=True)
        promote(model.model_version, "PAPER_ACTIVE", force=True)
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
            (account_id, mode, current_cash, created_at)
            VALUES ('ALPACA_TEST_01', 'paper', 100000, 1000000)""")
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
             challenger_adjustment, would_have_selected, champion_ticker, variant_ticker, created_at)
            VALUES (?, 'PAPER_CHALLENGER', 'v_test', 77.5, 2.5, 0, 'AAPL', 'AAPL', 1000000)""",
            (ep_id,))
        conn.commit()

        policy = self._make_policy("ALPACA_TEST_01")
        intent = build_intent(9002, "ALPACA_TEST_01", policy, conn)
        conn.close()

        assert intent is not None
        assert intent.decision_origin == "PAPER_CHALLENGER"
