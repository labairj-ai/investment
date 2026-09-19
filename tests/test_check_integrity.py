"""Tests for check_integrity.py rollup (0459)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import check_integrity


def _minimal_conn():
    """In-memory DB with just enough structure to satisfy non-throwing checks."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE model_observations (
            id INTEGER PRIMARY KEY,
            model_version TEXT,
            decision_cohort_id TEXT,
            would_select INTEGER DEFAULT 0,
            base_would_select INTEGER DEFAULT 0,
            observation_phase TEXT,
            scored_at_date TEXT,
            outcome_alpha_90d REAL,
            target_horizon_version TEXT
        );
        CREATE TABLE learning_models (
            model_version TEXT PRIMARY KEY,
            training_horizon_version TEXT,
            lifecycle_state TEXT
        );
        CREATE TABLE decision_variants (
            id INTEGER PRIMARY KEY,
            decision_cohort_id TEXT,
            challenger_model_version TEXT,
            challenger_episode_id TEXT
        );
        CREATE TABLE learning_sweep_runs (
            id INTEGER PRIMARY KEY,
            cohort_id TEXT,
            model_version TEXT,
            phase TEXT,
            expected_candidates INTEGER,
            scored_candidates INTEGER,
            status TEXT,
            error TEXT,
            started_at TEXT
        );
    """)
    return conn


class TestIntegrityErrorRollup0459:
    """Any individual check with status='error' must make overall integrity 'error'."""

    def test_thrown_check_produces_error_overall(self):
        """A check that throws an exception → overall='error', not 'ok'."""
        conn = _minimal_conn()

        def _raising_check(_conn):
            raise RuntimeError("simulated internal failure")

        original_checks = check_integrity._CHECKS
        try:
            check_integrity._CHECKS = [_raising_check]
            result = check_integrity.run_integrity_audit(conn)
        finally:
            check_integrity._CHECKS = original_checks
            conn.close()

        assert result["overall"] == "error", (
            f"Expected overall='error' when a check throws, got {result['overall']!r}"
        )
        assert result["checks"][0]["status"] == "error"

    def test_error_status_returned_by_check_produces_error_overall(self):
        """A check that returns status='error' explicitly also rolls up to 'error'."""
        conn = _minimal_conn()

        def _error_check(_conn):
            return {"name": "explicit_error", "severity": "WARN",
                    "count": -1, "detail": {}, "status": "error"}

        original_checks = check_integrity._CHECKS
        try:
            check_integrity._CHECKS = [_error_check]
            result = check_integrity.run_integrity_audit(conn)
        finally:
            check_integrity._CHECKS = original_checks
            conn.close()

        assert result["overall"] == "error"

    def test_error_does_not_override_block(self):
        """BLOCK takes priority over error."""
        conn = _minimal_conn()

        def _block_check(_conn):
            return {"name": "blocker", "severity": "BLOCK",
                    "count": 1, "detail": [], "status": "BLOCK"}

        def _error_check(_conn):
            raise RuntimeError("also broken")

        original_checks = check_integrity._CHECKS
        try:
            check_integrity._CHECKS = [_block_check, _error_check]
            result = check_integrity.run_integrity_audit(conn)
        finally:
            check_integrity._CHECKS = original_checks
            conn.close()

        assert result["overall"] == "BLOCK"

    def test_error_takes_priority_over_warn(self):
        """error takes priority over WARN."""
        conn = _minimal_conn()

        def _warn_check(_conn):
            return {"name": "warner", "severity": "WARN",
                    "count": 1, "detail": [], "status": "WARN"}

        def _error_check(_conn):
            raise RuntimeError("broken")

        original_checks = check_integrity._CHECKS
        try:
            check_integrity._CHECKS = [_warn_check, _error_check]
            result = check_integrity.run_integrity_audit(conn)
        finally:
            check_integrity._CHECKS = original_checks
            conn.close()

        assert result["overall"] == "error"

    def test_all_ok_checks_produce_ok_overall(self):
        """Sanity: all-ok checks still produce overall='ok'."""
        conn = _minimal_conn()

        def _ok_check(_conn):
            return {"name": "fine", "severity": "ok",
                    "count": 0, "detail": [], "status": "ok"}

        original_checks = check_integrity._CHECKS
        try:
            check_integrity._CHECKS = [_ok_check]
            result = check_integrity.run_integrity_audit(conn)
        finally:
            check_integrity._CHECKS = original_checks
            conn.close()

        assert result["overall"] == "ok"

    def test_acceptance_cannot_pass_when_integrity_is_error(self, tmp_path):
        """End-to-end: thrown check → overall='error' → acceptance FAIL (0459+0457)."""
        import scripts.first_sweep_acceptance as mod

        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE learning_sweep_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cohort_id TEXT, model_version TEXT, agent_run_id TEXT,
                phase TEXT, expected_candidates INTEGER, scored_candidates INTEGER,
                base_recommendation_eligible INTEGER, started_at TEXT,
                completed_at TEXT, status TEXT, error TEXT
            );
            CREATE TABLE model_observations (
                id INTEGER PRIMARY KEY, episode_id TEXT,
                decision_cohort_id TEXT, model_version TEXT,
                would_select INTEGER DEFAULT 0, base_would_select INTEGER DEFAULT 0
            );
            CREATE TABLE decision_episodes (episode_id TEXT PRIMARY KEY, run_id TEXT);
            CREATE TABLE decision_variants (
                id INTEGER PRIMARY KEY, decision_cohort_id TEXT,
                challenger_model_version TEXT, challenger_episode_id TEXT
            );
        """)
        conn.execute(
            "INSERT INTO learning_sweep_runs "
            "(cohort_id, model_version, agent_run_id, phase, expected_candidates, "
            "scored_candidates, base_recommendation_eligible, status) "
            "VALUES ('C1','v1','R1','OBSERVE',2,2,NULL,'COMPLETED')"
        )
        for ep, ws, bs in [("E1", 1, 0), ("E2", 0, 1)]:
            conn.execute(
                "INSERT INTO model_observations "
                "(episode_id, decision_cohort_id, model_version, would_select, base_would_select) "
                "VALUES (?,?,?,?,?)", (ep, "C1", "v1", ws, bs)
            )
            conn.execute(
                "INSERT INTO decision_episodes VALUES (?,?)", (ep, "R1")
            )
        conn.commit()
        conn.close()

        def _raising_check(_conn):
            raise RuntimeError("simulated broken integrity check")

        original_checks = check_integrity._CHECKS
        try:
            check_integrity._CHECKS = [_raising_check]
            # _run_integrity_audit calls check_integrity.py as a subprocess, so patch
            # the in-process version directly
            with patch("scripts.first_sweep_acceptance._run_integrity_audit",
                       return_value=("error", {"overall": "error"})):
                result = mod.run_shadow_acceptance(str(db))
        finally:
            check_integrity._CHECKS = original_checks

        assert result["status"] == "FAIL"
        assert any("integrity" in f for f in result["failures"])
