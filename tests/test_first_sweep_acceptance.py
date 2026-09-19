"""Tests for scripts/first_sweep_acceptance.py (0456 / 0457 / 0458)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.first_sweep_acceptance import (
    _DbError,
    _check_paper_variant_agreement,
    _find_any_completed_paper_sweep,
    _find_paper_sweep,
    _find_shadow_sweep,
    run_paper_acceptance,
    run_shadow_acceptance,
)


# ─────────────────────────────────────────────────────────────────────────────
# Minimal DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_db(tmp_path) -> Path:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE learning_sweep_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cohort_id TEXT,
            model_version TEXT,
            agent_run_id TEXT,
            phase TEXT,
            expected_candidates INTEGER,
            scored_candidates INTEGER,
            base_recommendation_eligible INTEGER,
            started_at TEXT,
            completed_at TEXT,
            status TEXT,
            error TEXT
        );
        CREATE TABLE model_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT,
            decision_cohort_id TEXT,
            model_version TEXT,
            would_select INTEGER DEFAULT 0,
            base_would_select INTEGER DEFAULT 0
        );
        CREATE TABLE decision_episodes (
            episode_id TEXT PRIMARY KEY,
            run_id TEXT
        );
        CREATE TABLE decision_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_cohort_id TEXT,
            challenger_model_version TEXT,
            challenger_episode_id TEXT
        );
    """)
    conn.commit()
    conn.close()
    return db


def _conn(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


def _insert_sweep(db: Path, *, phase="OBSERVE", status="COMPLETED",
                   base_eligible=None, cohort_id="C1", model_version="v1",
                   agent_run_id="R1", expected=5, scored=5) -> int:
    conn = _conn(db)
    cur = conn.execute(
        """INSERT INTO learning_sweep_runs
           (cohort_id, model_version, agent_run_id, phase, expected_candidates,
            scored_candidates, base_recommendation_eligible, status)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cohort_id, model_version, agent_run_id, phase, expected, scored,
         base_eligible, status),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def _insert_obs(db: Path, *, cohort_id="C1", model_version="v1",
                episode_id="E1", would_select=0, base_would_select=0):
    conn = _conn(db)
    conn.execute(
        """INSERT INTO model_observations
           (episode_id, decision_cohort_id, model_version, would_select, base_would_select)
           VALUES (?,?,?,?,?)""",
        (episode_id, cohort_id, model_version, would_select, base_would_select),
    )
    conn.commit()
    conn.close()


def _insert_episode(db: Path, *, episode_id="E1", run_id="R1"):
    conn = _conn(db)
    conn.execute("INSERT OR IGNORE INTO decision_episodes (episode_id, run_id) VALUES (?,?)",
                 (episode_id, run_id))
    conn.commit()
    conn.close()


def _insert_variant(db: Path, *, cohort_id="C1", model_version="v1",
                    challenger_episode_id="E1"):
    conn = _conn(db)
    conn.execute(
        """INSERT INTO decision_variants
           (decision_cohort_id, challenger_model_version, challenger_episode_id)
           VALUES (?,?,?)""",
        (cohort_id, model_version, challenger_episode_id),
    )
    conn.commit()
    conn.close()


def _seed_minimal_passing_shadow(db: Path):
    """Seed enough data for shadow acceptance to pass (integrity mocked separately)."""
    _insert_sweep(db, phase="OBSERVE", status="COMPLETED",
                  expected=2, scored=2, base_eligible=None)
    _insert_obs(db, episode_id="E1", would_select=1, base_would_select=0)
    _insert_obs(db, episode_id="E2", would_select=0, base_would_select=1)
    _insert_episode(db, episode_id="E1")
    _insert_episode(db, episode_id="E2")


# ─────────────────────────────────────────────────────────────────────────────
# 0456 — Sweep locators
# ─────────────────────────────────────────────────────────────────────────────

class TestSweepLocators0456:
    def test_shadow_returns_none_with_no_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        conn = _conn(db)
        assert _find_shadow_sweep(conn) is None
        conn.close()

    def test_shadow_ignores_incomplete_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="OBSERVE", status="RUNNING")
        conn = _conn(db)
        assert _find_shadow_sweep(conn) is None
        conn.close()

    def test_shadow_finds_completed_observe(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="OBSERVE", status="COMPLETED")
        conn = _conn(db)
        sweep = _find_shadow_sweep(conn)
        assert sweep is not None
        assert sweep["phase"] == "OBSERVE"
        conn.close()

    def test_shadow_ignores_paper_active_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=1)
        conn = _conn(db)
        assert _find_shadow_sweep(conn) is None
        conn.close()

    def test_paper_returns_none_with_no_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        conn = _conn(db)
        assert _find_paper_sweep(conn) is None
        conn.close()

    def test_paper_ignores_observe_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="OBSERVE", status="COMPLETED")
        conn = _conn(db)
        assert _find_paper_sweep(conn) is None
        conn.close()

    def test_paper_ignores_not_eligible_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=0)
        conn = _conn(db)
        assert _find_paper_sweep(conn) is None
        conn.close()

    def test_paper_ignores_incomplete_paper_sweeps(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="RUNNING", base_eligible=1)
        conn = _conn(db)
        assert _find_paper_sweep(conn) is None
        conn.close()

    def test_paper_finds_eligible_completed_sweep(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=1)
        conn = _conn(db)
        sweep = _find_paper_sweep(conn)
        assert sweep is not None
        assert sweep["phase"] == "PAPER_ACTIVE"
        assert sweep["base_recommendation_eligible"] == 1
        conn.close()

    def test_paper_picks_latest_when_multiple_eligible(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED",
                       base_eligible=1, cohort_id="OLD")
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED",
                       base_eligible=1, cohort_id="NEW")
        conn = _conn(db)
        sweep = _find_paper_sweep(conn)
        assert sweep["cohort_id"] == "NEW"
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 0457 — Integrity fail-closed
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrityFailClosed0457:
    """Anything other than "ok" must cause acceptance to fail unless waived (WARN only)."""

    def _run_shadow(self, tmp_path, integrity_overall, waive=False):
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)
        with patch("scripts.first_sweep_acceptance._run_integrity_audit",
                   return_value=(integrity_overall, {"overall": integrity_overall})):
            return run_shadow_acceptance(str(db), waive_integrity_warn=waive)

    def test_integrity_ok_does_not_fail(self, tmp_path):
        result = self._run_shadow(tmp_path, "ok")
        assert "integrity" not in " ".join(result.get("failures", []))

    def test_integrity_error_causes_fail(self, tmp_path):
        result = self._run_shadow(tmp_path, "error")
        assert result["status"] == "FAIL"
        assert any("integrity" in f for f in result["failures"])

    def test_integrity_warn_causes_fail_without_waiver(self, tmp_path):
        result = self._run_shadow(tmp_path, "WARN")
        assert result["status"] == "FAIL"
        assert any("integrity" in f for f in result["failures"])

    def test_integrity_warn_passes_with_waiver(self, tmp_path):
        result = self._run_shadow(tmp_path, "WARN", waive=True)
        # No integrity failure in the failure list
        assert not any("integrity" in f for f in result.get("failures", []))
        assert result.get("integrity_waived_warn") is True

    def test_integrity_block_causes_fail(self, tmp_path):
        result = self._run_shadow(tmp_path, "BLOCK")
        assert result["status"] == "FAIL"
        assert any("integrity" in f for f in result["failures"])

    def test_integrity_unknown_string_causes_fail(self, tmp_path):
        result = self._run_shadow(tmp_path, "something_unexpected")
        assert result["status"] == "FAIL"
        assert any("integrity" in f for f in result["failures"])

    def test_waive_only_covers_warn_not_error(self, tmp_path):
        result = self._run_shadow(tmp_path, "error", waive=True)
        assert result["status"] == "FAIL"
        assert any("integrity" in f for f in result["failures"])


# ─────────────────────────────────────────────────────────────────────────────
# 0457 — Git state gating (before artifact write)
# ─────────────────────────────────────────────────────────────────────────────

class TestGitStateGating0457:
    """Dirty worktree or absent SHA must abort before writing any artifact."""

    def _run_passing_shadow_acceptance(self, db_path: str) -> dict:
        with patch("scripts.first_sweep_acceptance._run_integrity_audit",
                   return_value=("ok", {"overall": "ok"})):
            return run_shadow_acceptance(db_path)

    def test_dirty_worktree_blocks_artifact_write(self, tmp_path):
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)

        out_path = tmp_path / "shadow_out.json"
        with (
            patch("scripts.first_sweep_acceptance._SHADOW_OUT", out_path),
            patch("scripts.first_sweep_acceptance._run_integrity_audit",
                  return_value=("ok", {"overall": "ok"})),
            patch("scripts.first_sweep_acceptance._git_sha", return_value="abc123"),
            patch("scripts.first_sweep_acceptance._git_dirty", return_value=True),
        ):
            import scripts.first_sweep_acceptance as mod
            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
            try:
                with pytest.raises(SystemExit) as exc:
                    mod.main()
            finally:
                _sys.argv = old_argv
        assert exc.value.code == 3
        assert not out_path.exists()

    def test_missing_sha_blocks_artifact_write(self, tmp_path):
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)
        result = self._run_passing_shadow_acceptance(str(db))
        assert result["status"] == "PASS"

        out_path = tmp_path / "shadow_out.json"
        with (
            patch("scripts.first_sweep_acceptance._SHADOW_OUT", out_path),
            patch("scripts.first_sweep_acceptance._run_integrity_audit",
                  return_value=("ok", {"overall": "ok"})),
            patch("scripts.first_sweep_acceptance._git_sha", return_value=None),
            patch("scripts.first_sweep_acceptance._git_dirty", return_value=False),
        ):
            import scripts.first_sweep_acceptance as mod
            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
            try:
                with pytest.raises(SystemExit) as exc:
                    mod.main()
            finally:
                _sys.argv = old_argv
        assert exc.value.code == 3
        assert not out_path.exists()

    def test_clean_sha_allows_artifact_write(self, tmp_path):
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)

        out_path = tmp_path / "shadow_out.json"
        with (
            patch("scripts.first_sweep_acceptance._SHADOW_OUT", out_path),
            patch("scripts.first_sweep_acceptance._run_integrity_audit",
                  return_value=("ok", {"overall": "ok"})),
            patch("scripts.first_sweep_acceptance._git_sha", return_value="abc123"),
            patch("scripts.first_sweep_acceptance._git_dirty", return_value=False),
        ):
            import scripts.first_sweep_acceptance as mod
            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
            try:
                mod.main()
            except SystemExit:
                pass
            finally:
                _sys.argv = old_argv
        assert out_path.exists()
        record = json.loads(out_path.read_text())
        assert record["source_commit_sha"] == "abc123"
        assert record["git_dirty"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 0458 — Paper variant eligibility semantics
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperVariantAgreement0458:
    """_check_paper_variant_agreement uses base_recommendation_eligible correctly."""

    def _make_db_with_obs(self, tmp_path, winner_ep="E1") -> sqlite3.Connection:
        db = _make_db(tmp_path)
        _insert_obs(db, episode_id=winner_ep, would_select=1, base_would_select=0)
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        return conn

    def test_eligible_no_variant_is_fail(self, tmp_path):
        conn = self._make_db_with_obs(tmp_path)
        failures, status = _check_paper_variant_agreement(conn, "C1", "v1", 1)
        conn.close()
        assert len(failures) == 1
        assert "missing" in failures[0].lower() or "required" in failures[0].lower()
        assert status == "fail_missing_variant"

    def test_eligible_variant_matches_episode(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_obs(db, episode_id="E1", would_select=1)
        _insert_variant(db, challenger_episode_id="E1")
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        failures, status = _check_paper_variant_agreement(conn, "C1", "v1", 1)
        conn.close()
        assert failures == []
        assert status == "pass"

    def test_eligible_variant_episode_mismatch_is_fail(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_obs(db, episode_id="E1", would_select=1)
        _insert_variant(db, challenger_episode_id="E_OTHER")
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        failures, status = _check_paper_variant_agreement(conn, "C1", "v1", 1)
        conn.close()
        assert len(failures) == 1
        assert "mismatch" in failures[0].lower() or "!=" in failures[0]
        assert status == "fail_episode_mismatch"

    def test_not_eligible_no_variant_is_not_expected(self, tmp_path):
        conn = self._make_db_with_obs(tmp_path)
        failures, status = _check_paper_variant_agreement(conn, "C1", "v1", 0)
        conn.close()
        assert failures == []
        assert status == "not_expected"

    def test_null_eligible_treated_as_eligible_fail(self, tmp_path):
        """NULL base_recommendation_eligible → fail-closed, must have variant."""
        conn = self._make_db_with_obs(tmp_path)
        failures, status = _check_paper_variant_agreement(conn, "C1", "v1", None)
        conn.close()
        assert len(failures) == 1
        assert status == "fail_missing_variant"

    def test_variant_null_episode_id_is_fail(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_obs(db, episode_id="E1", would_select=1)
        # Insert variant with NULL challenger_episode_id
        conn_rw = sqlite3.connect(str(db))
        conn_rw.execute(
            "INSERT INTO decision_variants (decision_cohort_id, challenger_model_version, "
            "challenger_episode_id) VALUES ('C1','v1',NULL)"
        )
        conn_rw.commit()
        conn_rw.close()
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        failures, status = _check_paper_variant_agreement(conn, "C1", "v1", 1)
        conn.close()
        assert len(failures) == 1
        assert status == "fail_null_episode"


# ─────────────────────────────────────────────────────────────────────────────
# 0456 — Shadow output messaging
# ─────────────────────────────────────────────────────────────────────────────

class TestShadowModeMissaging0456:
    """Shadow acceptance artifact must NOT say "architecture is frozen"."""

    def test_shadow_artifact_says_pipeline_verified(self, tmp_path):
        from scripts.first_sweep_acceptance import _build_artifact, _find_shadow_sweep
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)
        conn = _conn(db)
        sweep = _find_shadow_sweep(conn)
        conn.close()
        result = {"mode": "shadow", "sweep": sweep, "integrity_overall": "ok",
                  "integrity_waived_warn": False}
        artifact = _build_artifact(result, "abc", False)
        note = artifact["_note"].lower()
        assert "observation pipeline verified" in note
        assert "architecture is now frozen" not in note

    def test_paper_artifact_says_architecture_validated(self, tmp_path):
        from scripts.first_sweep_acceptance import _build_artifact
        sweep = {"agent_run_id": "R1", "cohort_id": "C1", "model_version": "v1",
                 "phase": "PAPER_ACTIVE", "expected_candidates": 5, "scored_candidates": 5,
                 "base_recommendation_eligible": 1}
        result = {"mode": "paper", "sweep": sweep, "integrity_overall": "ok",
                  "integrity_waived_warn": False}
        artifact = _build_artifact(result, "abc", False)
        note = artifact["_note"].lower()
        assert "full architecture validated" in note
        assert "architecture is now frozen" in note

    def test_shadow_mode_does_not_write_paper_artifact(self, tmp_path):
        """Shadow run must write shadow output path, not paper output path."""
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)
        shadow_out = tmp_path / "shadow.json"
        paper_out  = tmp_path / "paper.json"
        with (
            patch("scripts.first_sweep_acceptance._SHADOW_OUT", shadow_out),
            patch("scripts.first_sweep_acceptance._PAPER_OUT", paper_out),
            patch("scripts.first_sweep_acceptance._run_integrity_audit",
                  return_value=("ok", {"overall": "ok"})),
            patch("scripts.first_sweep_acceptance._git_sha", return_value="abc123"),
            patch("scripts.first_sweep_acceptance._git_dirty", return_value=False),
        ):
            import scripts.first_sweep_acceptance as mod
            import sys as _sys
            old_argv = _sys.argv
            _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
            try:
                mod.main()
            except SystemExit:
                pass
            finally:
                _sys.argv = old_argv
        assert shadow_out.exists()
        assert not paper_out.exists()


# ─────────────────────────────────────────────────────────────────────────────
# 0456 — NO_SWEEP exit codes
# ─────────────────────────────────────────────────────────────────────────────

class TestNoSweepHandling0456:
    def test_shadow_no_sweep_returns_no_sweep(self, tmp_path):
        db = _make_db(tmp_path)
        result = run_shadow_acceptance(str(db))
        assert result["status"] == "NO_SWEEP"

    def test_paper_no_sweep_returns_no_sweep(self, tmp_path):
        db = _make_db(tmp_path)
        result = run_paper_acceptance(str(db))
        assert result["status"] == "NO_SWEEP"

    def test_paper_observe_only_returns_no_sweep(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="OBSERVE", status="COMPLETED")
        result = run_paper_acceptance(str(db))
        assert result["status"] == "NO_SWEEP"

    def test_shadow_missing_table_returns_db_error(self, tmp_path):
        """DB without learning_sweep_runs is a hard DB_ERROR, not NO_SWEEP (0462)."""
        db = tmp_path / "bare.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE placeholder (id INTEGER)")
        conn.commit()
        conn.close()
        result = run_shadow_acceptance(str(db))
        assert result["status"] == "DB_ERROR"


# ─────────────────────────────────────────────────────────────────────────────
# 0461 — git_dirty=None must block artifact write
# ─────────────────────────────────────────────────────────────────────────────

class TestGitDirtyNone0461:
    """_git_dirty() returning None (status unknowable) must block artifact creation."""

    def _run_main(self, tmp_path, dirty_value):
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)
        out_path = tmp_path / "shadow_out.json"
        import scripts.first_sweep_acceptance as mod
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
        try:
            with (
                patch("scripts.first_sweep_acceptance._SHADOW_OUT", out_path),
                patch("scripts.first_sweep_acceptance._run_integrity_audit",
                      return_value=("ok", {"overall": "ok"})),
                patch("scripts.first_sweep_acceptance._git_sha", return_value="abc123"),
                patch("scripts.first_sweep_acceptance._git_dirty", return_value=dirty_value),
                pytest.raises(SystemExit) as exc,
            ):
                mod.main()
        finally:
            _sys.argv = old_argv
        return exc.value.code, out_path

    def test_none_blocks_with_exit_3(self, tmp_path):
        code, out_path = self._run_main(tmp_path, None)
        assert code == 3
        assert not out_path.exists()

    def test_true_still_blocks_with_exit_3(self, tmp_path):
        code, out_path = self._run_main(tmp_path, True)
        assert code == 3
        assert not out_path.exists()

    def test_false_allows_write(self, tmp_path):
        import scripts.first_sweep_acceptance as mod
        import sys as _sys
        db = _make_db(tmp_path)
        _seed_minimal_passing_shadow(db)
        out_path = tmp_path / "shadow_out.json"
        old_argv = _sys.argv
        _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
        try:
            with (
                patch("scripts.first_sweep_acceptance._SHADOW_OUT", out_path),
                patch("scripts.first_sweep_acceptance._run_integrity_audit",
                      return_value=("ok", {"overall": "ok"})),
                patch("scripts.first_sweep_acceptance._git_sha", return_value="abc123"),
                patch("scripts.first_sweep_acceptance._git_dirty", return_value=False),
            ):
                try:
                    mod.main()
                except SystemExit:
                    pass
        finally:
            _sys.argv = old_argv
        assert out_path.exists()


# ─────────────────────────────────────────────────────────────────────────────
# 0460 — NULL paper eligibility fails closed end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestNullEligibilityEndToEnd0460:
    """A completed PAPER_ACTIVE sweep with NULL eligibility must fail, not return NO_SWEEP."""

    def test_null_eligibility_returns_fail_not_no_sweep(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=None)
        result = run_paper_acceptance(str(db))
        assert result["status"] == "FAIL", (
            f"Expected FAIL for NULL eligibility, got {result['status']!r}"
        )
        assert any("eligibility" in f.lower() or "null" in f.lower()
                   for f in result["failures"])

    def test_null_eligibility_is_not_no_sweep(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=None)
        result = run_paper_acceptance(str(db))
        assert result["status"] != "NO_SWEEP"

    def test_eligible_1_still_qualifies(self, tmp_path):
        """eligible=1 sweep still reaches normal acceptance checks (not NO_SWEEP/FAIL early)."""
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED",
                      base_eligible=1, expected=2, scored=2)
        _insert_obs(db, episode_id="E1", would_select=1, base_would_select=0)
        _insert_obs(db, episode_id="E2", would_select=0, base_would_select=1)
        _insert_episode(db, episode_id="E1")
        _insert_episode(db, episode_id="E2")
        _insert_variant(db, challenger_episode_id="E1")
        with patch("scripts.first_sweep_acceptance._run_integrity_audit",
                   return_value=("ok", {"overall": "ok"})):
            result = run_paper_acceptance(str(db))
        # Should reach acceptance logic (PASS or FAIL on checks, not NO_SWEEP)
        assert result["status"] in ("PASS", "FAIL")
        assert result.get("mode") == "paper"

    def test_eligible_0_returns_no_sweep(self, tmp_path):
        """eligible=0 sweep → NO_SWEEP (not yet qualifying, not a hard failure)."""
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=0)
        result = run_paper_acceptance(str(db))
        assert result["status"] == "NO_SWEEP"

    def test_find_any_completed_paper_sweep_finds_null_eligible(self, tmp_path):
        """_find_any_completed_paper_sweep must return sweeps with NULL eligibility."""
        db = _make_db(tmp_path)
        _insert_sweep(db, phase="PAPER_ACTIVE", status="COMPLETED", base_eligible=None)
        conn = _conn(db)
        sweep = _find_any_completed_paper_sweep(conn)
        conn.close()
        assert sweep is not None
        assert not isinstance(sweep, _DbError)
        assert sweep.get("base_recommendation_eligible") is None


# ─────────────────────────────────────────────────────────────────────────────
# 0462 — DB query errors are distinct from NO_SWEEP
# ─────────────────────────────────────────────────────────────────────────────

class TestDbErrorDistinction0462:
    """sqlite3.OperationalError must produce DB_ERROR, not NO_SWEEP."""

    def _bare_db(self, tmp_path) -> Path:
        db = tmp_path / "bare.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        return db

    def test_shadow_db_error_status_is_db_error(self, tmp_path):
        db = self._bare_db(tmp_path)
        result = run_shadow_acceptance(str(db))
        assert result["status"] == "DB_ERROR"

    def test_shadow_db_error_is_not_no_sweep(self, tmp_path):
        db = self._bare_db(tmp_path)
        result = run_shadow_acceptance(str(db))
        assert result["status"] != "NO_SWEEP"

    def test_paper_db_error_status_is_db_error(self, tmp_path):
        db = self._bare_db(tmp_path)
        result = run_paper_acceptance(str(db))
        assert result["status"] == "DB_ERROR"

    def test_paper_db_error_is_not_no_sweep(self, tmp_path):
        db = self._bare_db(tmp_path)
        result = run_paper_acceptance(str(db))
        assert result["status"] != "NO_SWEEP"

    def test_find_shadow_sweep_returns_db_error_sentinel(self, tmp_path):
        db = self._bare_db(tmp_path)
        conn = _conn(db)
        result = _find_shadow_sweep(conn)
        conn.close()
        assert isinstance(result, _DbError)

    def test_find_any_paper_sweep_returns_db_error_sentinel(self, tmp_path):
        db = self._bare_db(tmp_path)
        conn = _conn(db)
        result = _find_any_completed_paper_sweep(conn)
        conn.close()
        assert isinstance(result, _DbError)

    def test_empty_db_returns_no_sweep_not_db_error(self, tmp_path):
        """Successful query with no rows → NO_SWEEP, not DB_ERROR."""
        db = _make_db(tmp_path)  # has the table, just no rows
        result = run_shadow_acceptance(str(db))
        assert result["status"] == "NO_SWEEP"

    def test_main_exits_3_on_db_error(self, tmp_path):
        db = self._bare_db(tmp_path)
        import scripts.first_sweep_acceptance as mod
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["acceptance", "--db", str(db), "--mode", "shadow"]
        try:
            with pytest.raises(SystemExit) as exc:
                mod.main()
        finally:
            _sys.argv = old_argv
        assert exc.value.code == 3
