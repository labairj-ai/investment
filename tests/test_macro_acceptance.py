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
        results = {
            "synthetic_regression": {"status": "PASS"},
            "regime_direction": {"status": "PASS"},
            "fund_classification": {"status": "PASS"},
            "ledger_integrity": {"status": "SKIP"},
            "anchor_calibration": {
                "_ordering": {"checks": [{"status": "FAIL"}]},
            },
            "drift": {},
            "repeatability": {},
        }
        # With threshold=0 ordering failures allowed → BLOCK
        config_strict = {"thresholds": {"anchor_ordering_failures": 0, "unexplained_large_swings": 0,
                                         "beta_recovery_tolerance": 1.5, "fund_unsupported_pct": 100,
                                         "ledger_integrity_pct": 100, "schema_valid_pct": 100,
                                         "missing_data_unknown_pct": 100}}
        r_strict = _check_thresholds(results, config_strict)
        assert r_strict["verdict"] == "BLOCK"

        # With threshold=1 → PASS
        config_lenient = {"thresholds": {**config_strict["thresholds"], "anchor_ordering_failures": 1}}
        r_lenient = _check_thresholds(results, config_lenient)
        assert r_lenient["verdict"] == "PASS"
