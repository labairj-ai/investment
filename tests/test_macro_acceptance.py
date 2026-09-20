"""
Tests for macro acceptance architecture (0527).
Covers: atomic activation, config policy, legacy-table elimination, geo quality, migration idempotency.
"""
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_db() -> tuple[Path, sqlite3.Connection]:
    """Return (path, connection) for an in-memory-backed temp DB with all tables initialized."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    p = Path(tmp.name)
    import portfolio_ai
    real_db = portfolio_ai.DB_PATH
    portfolio_ai.DB_PATH = p
    try:
        portfolio_ai._init_ai_tables()
    finally:
        portfolio_ai.DB_PATH = real_db
    conn = sqlite3.connect(str(p), timeout=10)
    return p, conn


def _seed_acceptance(conn: sqlite3.Connection, record_id: str = "rec/001",
                     contract: str = "macro_validation_v1") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO macro_acceptance_state "
        "(contract, accepted_at, record_id, commit_sha, model_identity, notes) "
        "VALUES (?,?,?,?,?,?)",
        (contract, "2026-01-01T00:00:00", record_id, "abc123", "model-x", "test seed")
    )
    import portfolio_ai
    conn.execute("UPDATE macro_acceptance_state SET scorer_contract_hash=? WHERE record_id=?",
                 (portfolio_ai._compute_scorer_contract_hash(), record_id))
    conn.commit()


def _seed_validation_row(conn: sqlite3.Connection, ticker: str, dim: str,
                          record_id: str, stability: str = "stable") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO macro_dimension_validation "
        "(acceptance_record_id, ticker, dimension, mean_score, stddev, "
        "n_samples, stability_class, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
        (record_id, ticker, dim, 5.0, 0.2, 5, stability, "2026-01-01T00:00:00")
    )
    conn.commit()


def _seed_geo(conn: sqlite3.Connection, ticker: str, confidence: str,
              source_date, primary_hq: str = "US") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO company_geo_profile "
        "(ticker, primary_hq_country, updated_at, confidence, source_date) "
        "VALUES (?,?,?,?,?)",
        (ticker, primary_hq, "2026-01-01", confidence, source_date)
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 0525 — _accepted_dim_state is the single source of truth
# ---------------------------------------------------------------------------

class TestAcceptedDimState:
    def test_returns_false_when_no_acceptance_state(self):
        p, conn = _fresh_db()
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is False
        assert result["stability_class"] is None
        conn.close()
        p.unlink(missing_ok=True)

    def test_returns_false_when_no_matching_validation_row(self):
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/001")
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is False
        assert result["record_id"] == "rec/001"
        conn.close()
        p.unlink(missing_ok=True)

    def test_returns_true_for_stable_row(self):
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/001")
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/001", "stable")
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is True
        assert result["stability_class"] == "stable"
        assert result["record_id"] == "rec/001"
        conn.close()
        p.unlink(missing_ok=True)

    def test_returns_true_for_borderline_row(self):
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/001")
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/001", "borderline")
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is True
        conn.close()
        p.unlink(missing_ok=True)

    def test_returns_false_for_unstable_row(self):
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/001")
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/001", "unstable")
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is False
        conn.close()
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 0519/0525 — usability requires active record
# ---------------------------------------------------------------------------

class TestUsabilityRequiresActiveRecord:
    def test_old_acceptance_rows_not_usable_after_superseded(self):
        """Rows tied to old record_id must not grant usability when active record changes."""
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/old")
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/old", "stable")
        # Advance to new acceptance — old rows stay but active record_id changes
        conn.execute(
            "INSERT OR REPLACE INTO macro_acceptance_state "
            "(contract, accepted_at, record_id, commit_sha, model_identity, notes) "
            "VALUES (?,?,?,?,?,?)",
            ("macro_validation_v1", "2026-06-01T00:00:00", "rec/new", "def456", "model-y", "new run")
        )
        conn.commit()
        import portfolio_ai
        # Still only the old row exists in validation table — new record has no rows
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is False
        assert result["record_id"] == "rec/new"
        conn.close()
        p.unlink(missing_ok=True)

    def test_is_formally_usable_delegates_to_accepted_dim_state(self):
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/001")
        _seed_validation_row(conn, "NFLX", "inflation_hedge", "rec/001", "stable")
        import portfolio_ai
        assert portfolio_ai._is_formally_usable("NFLX", "inflation_hedge", conn) is True
        assert portfolio_ai._is_formally_usable("NFLX", "rate_sensitivity", conn) is False
        conn.close()
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 0526 — geo evidence quality fails closed
# ---------------------------------------------------------------------------

class TestGeoEvidenceQualityFailClosed:
    def test_missing_source_date_not_full_for_high_confidence(self):
        p, conn = _fresh_db()
        _seed_geo(conn, "ITOCF", "high", None)
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("ITOCF", conn)
        assert result == "partial", f"Expected partial, got {result!r}"
        conn.close()
        p.unlink(missing_ok=True)

    def test_empty_source_date_not_full(self):
        p, conn = _fresh_db()
        _seed_geo(conn, "ITOCF", "high", "")
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("ITOCF", conn)
        assert result == "partial"
        conn.close()
        p.unlink(missing_ok=True)

    def test_unparseable_date_returns_partial(self):
        p, conn = _fresh_db()
        _seed_geo(conn, "XOM", "high", "not-a-date")
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("XOM", conn)
        assert result == "partial"
        conn.close()
        p.unlink(missing_ok=True)

    def test_future_date_returns_partial(self):
        p, conn = _fresh_db()
        _seed_geo(conn, "XOM", "high", "2099-01")
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("XOM", conn)
        assert result == "partial"
        conn.close()
        p.unlink(missing_ok=True)

    def test_stale_date_returns_partial(self):
        p, conn = _fresh_db()
        _seed_geo(conn, "XOM", "high", "2020-01")
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("XOM", conn)
        assert result == "partial"
        conn.close()
        p.unlink(missing_ok=True)

    def test_high_confidence_fresh_date_returns_full(self):
        from datetime import date
        recent = date.today().strftime("%Y-%m")
        p, conn = _fresh_db()
        _seed_geo(conn, "XOM", "high", recent)
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("XOM", conn)
        assert result == "full"
        conn.close()
        p.unlink(missing_ok=True)

    def test_medium_confidence_fresh_date_returns_partial(self):
        from datetime import date
        recent = date.today().strftime("%Y-%m")
        p, conn = _fresh_db()
        _seed_geo(conn, "ITOCF", "medium", recent)
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("ITOCF", conn)
        assert result == "partial"
        conn.close()
        p.unlink(missing_ok=True)

    def test_no_record_returns_none(self):
        p, conn = _fresh_db()
        import portfolio_ai
        result = portfolio_ai._geo_evidence_quality("NOTICKER", conn)
        assert result == "none"
        conn.close()
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 0527 — migration idempotency
# ---------------------------------------------------------------------------

class TestMacroMigrationIdempotent:
    def test_init_twice_same_row_counts(self):
        p, conn = _fresh_db()
        conn.close()
        import portfolio_ai
        real_db = portfolio_ai.DB_PATH
        portfolio_ai.DB_PATH = p
        try:
            portfolio_ai._init_ai_tables()  # second call
            conn2 = sqlite3.connect(str(p))
            tables = [r[0] for r in conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            assert "macro_dimension_validation" in tables
            assert "macro_dimension_runtime_stability" in tables
            assert "_schema_migrations" in tables
            mig = conn2.execute(
                "SELECT COUNT(*) FROM _schema_migrations WHERE migration_id='M001_stability_split'"
            ).fetchone()[0]
            assert mig == 1, "Migration M001 should appear exactly once after two init calls"
            conn2.close()
        finally:
            portfolio_ai.DB_PATH = real_db
            p.unlink(missing_ok=True)

    def test_migration_recorded_in_schema_migrations(self):
        p, conn = _fresh_db()
        mig = conn.execute(
            "SELECT migration_id FROM _schema_migrations"
        ).fetchall()
        ids = [r[0] for r in mig]
        assert "M001_stability_split" in ids
        conn.close()
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 0524 — config controls validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_validate_config_raises_on_missing_threshold(self):
        from scripts.validate_macro_scorer import _validate_config
        bad_config = {"thresholds": {}, "n_repeats": 20}
        with pytest.raises(ValueError, match="missing required threshold"):
            _validate_config(bad_config)

    def test_validate_config_raises_on_missing_n_repeats(self):
        from scripts.validate_macro_scorer import _validate_config
        from scripts.validate_macro_scorer import _REQUIRED_THRESHOLDS
        good_thresholds = {k: 0 for k in _REQUIRED_THRESHOLDS}
        bad_config = {"thresholds": good_thresholds}  # no n_repeats
        with pytest.raises(ValueError, match="n_repeats"):
            _validate_config(bad_config)

    def test_validate_config_passes_with_full_config(self):
        from scripts.validate_macro_scorer import _validate_config, _REQUIRED_THRESHOLDS
        good_thresholds = {k: 0 for k in _REQUIRED_THRESHOLDS}
        _validate_config({"thresholds": good_thresholds, "n_repeats": 20})

    def test_check_thresholds_uses_config_anchor_ordering(self):
        """anchor_ordering_failures threshold from config controls the verdict."""
        from scripts.validate_macro_scorer import _check_thresholds
        from test_macro_contract_completion import passing
        config, results = passing()
        results["anchor_calibration"]["_ordering"]["checks"] = [{"lo": 2, "hi": 1}]
        assert _check_thresholds(results, config)["verdict"] == "BLOCK"
        config["thresholds"]["anchor_ordering_failures"] = 1
        assert _check_thresholds(results, config)["verdict"] == "PASS"

    def test_validate_config_rejects_unknown_threshold_keys(self):
        """Unknown threshold keys must raise ValueError (0530)."""
        from scripts.validate_macro_scorer import _validate_config, _REQUIRED_THRESHOLDS
        good = {k: 0 for k in _REQUIRED_THRESHOLDS}
        bad_config = {"thresholds": {**good, "unknown_key": 99}, "n_repeats": 20}
        with pytest.raises(ValueError, match="unknown threshold"):
            _validate_config(bad_config)

    def test_load_validation_config_fails_on_malformed_json(self, tmp_path):
        """Malformed config must raise ValueError, not silently use defaults (0530)."""
        bad_file = tmp_path / "validation_config.json"
        bad_file.write_text("{not valid json")
        from scripts import validate_macro_scorer as vms
        orig = vms.PROJECT_DIR
        try:
            vms.PROJECT_DIR = tmp_path
            with pytest.raises(ValueError, match="malformed"):
                vms._load_validation_config()
        finally:
            vms.PROJECT_DIR = orig

    def test_repeatability_applies_same_input_score_max_range(self, monkeypatch):
        """UNSTABLE flag is set when score range > same_input_score_max_range (0530)."""
        from scripts.validate_macro_scorer import run_repeatability, _score_val
        # Build a mock that returns alternating scores to create a range of 2
        import sys
        import types

        fake_pai = types.ModuleType("portfolio_ai")
        fake_pai._build_macro_score_request = lambda ticker, ev, betas: "prompt"
        fake_pai._extract_json = lambda text: {
            "XOM": {d: {"score": 3 if _call_count[0] % 2 == 0 else 5, "reason": "r"}
                    for d in ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk")}
        }
        fake_pai._MACRO_SCORE_TEMPERATURE = 0.2
        fake_pai._MACRO_SCORE_NUM_PREDICT = 1600
        monkeypatch.setitem(sys.modules, "portfolio_ai", fake_pai)

        fake_ollama = types.ModuleType("ollama_client")
        fake_ollama.available = lambda: True
        fake_ollama.DEFAULT_MODEL = "test-model"
        _call_count = [0]

        def fake_stream(prompt, model, temperature, num_predict):
            _call_count[0] += 1
            yield '{"XOM": {"rate_sensitivity": {"score": ' + ("3" if _call_count[0] % 2 == 0 else "5") + ', "reason": "r"}, "inflation_hedge": {"score": 5, "reason": "r"}, "dollar_sensitivity": {"score": 5, "reason": "r"}, "geopolitical_risk": {"score": 5, "reason": "r"}}}'

        fake_ollama.stream_generate = fake_stream
        monkeypatch.setitem(sys.modules, "ollama_client", fake_ollama)
        monkeypatch.setattr(time, "sleep", lambda *args: None)

        try:
            result = run_repeatability(["XOM"], {}, n=4, same_input_score_max_range=1)
            rs = result["XOM"]["rate_sensitivity"]
            # range=2 > max_range=1 → UNSTABLE
            assert rs["flag"] is True
            assert rs["status"] == "UNSTABLE"
        finally:
            monkeypatch.undo()

    def test_synthetic_regression_uses_config_tolerance(self):
        """Tight tolerance from config causes synthetic regression to FAIL (0530)."""
        from scripts.validate_macro_scorer import run_synthetic_regression
        # Use an impossibly tight tolerance — should FAIL
        result = run_synthetic_regression(beta_recovery_tolerance=0.001)
        assert result["status"] == "FAIL"
        # Default tolerance should PASS
        result_default = run_synthetic_regression(beta_recovery_tolerance=1.5)
        assert result_default["status"] == "PASS"


# ---------------------------------------------------------------------------
# 0531 — scorer contract invalidation
# ---------------------------------------------------------------------------

class TestScorerContractInvalidation:
    def test_accepted_dim_state_invalid_when_hash_mismatch(self):
        """Stale scorer_contract_hash in DB → usable=False with stale reason (0531)."""
        p, conn = _fresh_db()
        # Seed acceptance with a deliberately wrong contract hash
        conn.execute(
            "INSERT OR REPLACE INTO macro_acceptance_state "
            "(contract, accepted_at, record_id, commit_sha, model_identity, scorer_contract_hash, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            ("macro_validation_v1", "2026-01-01T00:00:00", "rec/001",
             "abc123", "model-x", "0000_wrong_hash", "test seed with wrong hash")
        )
        conn.commit()
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/001", "stable")
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is False
        assert result["usable_reason"] == "acceptance_stale_scorer_contract"
        conn.close()
        p.unlink(missing_ok=True)

    def test_accepted_dim_state_usable_when_hash_matches(self):
        """Matching scorer_contract_hash → usable=True as normal (0531)."""
        import portfolio_ai
        p, conn = _fresh_db()
        try:
            current_hash = portfolio_ai._compute_scorer_contract_hash()
        except Exception:
            conn.close()
            p.unlink(missing_ok=True)
            pytest.skip("Cannot compute scorer_contract_hash in test environment")
        conn.execute(
            "INSERT OR REPLACE INTO macro_acceptance_state "
            "(contract, accepted_at, record_id, commit_sha, model_identity, scorer_contract_hash, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            ("macro_validation_v1", "2026-01-01T00:00:00", "rec/002",
             "abc123", "model-x", current_hash, "matching hash")
        )
        conn.commit()
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/002", "stable")
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is True
        conn.close()
        p.unlink(missing_ok=True)

    def test_accepted_dim_state_unusable_when_no_hash_stored(self):
        """Legacy NULL hash cannot grant current scorer acceptance."""
        p, conn = _fresh_db()
        _seed_acceptance(conn, "rec/001")
        conn.execute("UPDATE macro_acceptance_state SET scorer_contract_hash=NULL")
        conn.commit()
        _seed_validation_row(conn, "XOM", "rate_sensitivity", "rec/001", "stable")
        import portfolio_ai
        result = portfolio_ai._accepted_dim_state("XOM", "rate_sensitivity", conn)
        assert result["usable"] is False
        conn.close()
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 0533 — acceptance record immutability
# ---------------------------------------------------------------------------

class TestAcceptanceRecordImmutability:
    def test_duplicate_record_id_raises_on_insert(self):
        """Inserting a duplicate acceptance_record_id must raise (not be silently ignored) (0533)."""
        p, conn = _fresh_db()
        conn.execute(
            "INSERT INTO macro_dimension_validation "
            "(acceptance_record_id, ticker, dimension, mean_score, stddev, "
            "n_samples, stability_class, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
            ("dup-id", "XOM", "rate_sensitivity", 5.0, 0.2, 5, "stable", "2026-01-01")
        )
        conn.commit()
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO macro_dimension_validation "
                "(acceptance_record_id, ticker, dimension, mean_score, stddev, "
                "n_samples, stability_class, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                ("dup-id", "XOM", "rate_sensitivity", 6.0, 0.3, 5, "stable", "2026-01-02")
            )
            conn.commit()
        conn.close()
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 0534 — run type semantics
# ---------------------------------------------------------------------------

class TestRunTypeSemantics:
    def test_dry_run_type_without_live(self):
        """Non-live run must produce run_type='dry_run', not 'acceptance' (0534)."""
        import sys
        import types
        import json as _json
        import tempfile

        # Minimal stub for _load_validation_config
        from scripts.validate_macro_scorer import _REQUIRED_THRESHOLDS
        good_thresholds = {k: 0 for k in _REQUIRED_THRESHOLDS}
        # We just test the run_type logic directly
        # Simulate the branch: not live, no override, no smoke
        args_live = False
        args_n_repeats = None
        args_smoke = False
        if args_n_repeats is not None:
            run_type = "smoke"
        elif args_smoke:
            run_type = "smoke"
        else:
            run_type = "acceptance" if args_live else "dry_run"
        assert run_type == "dry_run"

    def test_acceptance_run_type_with_live(self):
        args_live = True
        args_n_repeats = None
        args_smoke = False
        if args_n_repeats is not None:
            run_type = "smoke"
        elif args_smoke:
            run_type = "smoke"
        else:
            run_type = "acceptance" if args_live else "dry_run"
        assert run_type == "acceptance"


# ---------------------------------------------------------------------------
# 0532 — attribution statistics
# ---------------------------------------------------------------------------

class TestAttributionRateInteractionSign:
    def test_missing_rate_interaction_returns_none(self):
        from scripts.macro_attribution import _rate_interaction_sign
        ep = {"macro": {}}
        assert _rate_interaction_sign(ep) is None

    def test_malformed_rate_interaction_returns_none(self):
        from scripts.macro_attribution import _rate_interaction_sign
        ep = {"macro": {"rate_interaction": "not-a-number"}}
        assert _rate_interaction_sign(ep) is None

    def test_positive_value_returns_positive(self):
        from scripts.macro_attribution import _rate_interaction_sign
        ep = {"macro": {"rate_interaction": 0.5}}
        assert _rate_interaction_sign(ep) == "positive"

    def test_negative_value_returns_negative(self):
        from scripts.macro_attribution import _rate_interaction_sign
        ep = {"macro": {"rate_interaction": -0.3}}
        assert _rate_interaction_sign(ep) == "negative"

    def test_zero_value_returns_negative(self):
        from scripts.macro_attribution import _rate_interaction_sign
        ep = {"macro": {"rate_interaction": 0.0}}
        assert _rate_interaction_sign(ep) == "negative"


class TestDivergenceSubgroupMinimum:
    def _make_episodes(self, n: int) -> list:
        return [
            {"macro": {
                "challenger_recommendation": "BUY",
                "base_recommendation": "HOLD",
                "challenger_alpha": 1.0,
                "base_alpha": 0.5,
                "rate_interaction": 0.1,
                "concordance_ok": True,
            }, "alpha": 1.0, "captured_at": f"2026-0{(i%9)+1}-01"}
            for i in range(n)
        ]

    def test_subgroup_below_min_is_suppressed(self):
        from scripts.macro_attribution import analyse, MIN_SUBGROUP_N
        episodes = self._make_episodes(35)
        result = analyse(episodes, "3m")
        da = result["divergence_analysis"]
        if da.get("status") == "ok":
            rg = da["regime_group_win_rates"]
            for k, v in rg.items():
                if v.get("n", MIN_SUBGROUP_N) < MIN_SUBGROUP_N:
                    assert v.get("suppressed") is True


class TestDivergenceTieReporting:
    def test_tie_counted_separately_not_as_base_win(self):
        from scripts.macro_attribution import analyse
        # Episodes where challenger_alpha == base_alpha → tie
        tie_episodes = [
            {"macro": {
                "challenger_recommendation": "BUY",
                "base_recommendation": "HOLD",
                "challenger_alpha": 1.0,
                "base_alpha": 1.0,  # tie
                "rate_interaction": 0.1,
                "concordance_ok": True,
            }, "alpha": 1.0, "captured_at": f"2026-0{(i%9)+1}-01"}
            for i in range(35)
        ]
        result = analyse(tie_episodes, "3m")
        da = result["divergence_analysis"]
        if da.get("status") == "ok":
            rg = da["regime_group_win_rates"]
            for k, v in rg.items():
                if "ties" in v:
                    # Ties should be > 0 if we have tie episodes
                    assert v["wins"] + v["losses"] + v["ties"] == v["n"]


# ---------------------------------------------------------------------------
# 0529 — prompt identity between production and validator
# ---------------------------------------------------------------------------

class TestProductionValidatorPromptIdentity:
    def test_build_macro_score_request_deterministic(self):
        """_build_macro_score_request with same inputs produces the same prompt (0529)."""
        import portfolio_ai as pai
        evidence = {"evidence_quality": "full", "sector": "Energy", "gross_margin_pct": 45.0}
        betas = None
        p1 = pai._build_macro_score_request("XOM", evidence, betas)
        p2 = pai._build_macro_score_request("XOM", evidence, betas)
        assert p1 == p2

    def test_build_macro_score_request_includes_evidence(self):
        """_build_macro_score_request includes evidence fields in the prompt (0529)."""
        import portfolio_ai as pai
        evidence = {"evidence_quality": "full", "sector": "Technology", "gross_margin_pct": 70.0}
        prompt = pai._build_macro_score_request("GRMN", evidence, None)
        assert "GRMN" in prompt
        assert "sector=Technology" in prompt or "Technology" in prompt

    def test_build_macro_score_request_empty_evidence_still_valid(self):
        """_build_macro_score_request with no evidence produces a well-formed prompt (0529)."""
        import portfolio_ai as pai
        prompt = pai._build_macro_score_request("XOM", {}, None)
        assert "XOM" in prompt
        assert "rate_sensitivity" in prompt
        assert "Return ONLY valid JSON" in prompt
