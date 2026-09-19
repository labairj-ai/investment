#!/usr/bin/env python3
"""Freeze the current experiment baseline snapshot.

Run ONCE before material evidence accumulates to capture the exact
experimental conditions under which challenger vs. base evidence is collected.
Writes config/experiment_baseline.json (committed, not gitignored).

DO NOT re-run this script after the experiment has started — doing so would
overwrite the immutable record of starting conditions and contaminate future
comparisons. When a model is promoted to OBSERVE or PAPER_ACTIVE, the
model_promotion_log records those conditions separately.

Usage:
    python scripts/freeze_baseline.py [--db PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUT_PATH = _REPO_ROOT / "config" / "experiment_baseline.json"
_SHADOW_ACCOUNT_ID = "AGENTIC_SHADOW_01"


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO_ROOT), text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _git_dirty() -> bool | None:
    """Return True if the worktree has uncommitted changes, False if clean, None if git unavailable."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(_REPO_ROOT), text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(out.strip())
    except Exception:
        return None


def _load_db_fields(db_path: str) -> dict:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Probe schema for presence of lifecycle_state column (absent on unmigrated DBs)
    has_lifecycle = bool(conn.execute(
        "SELECT 1 FROM pragma_table_info('learning_models') WHERE name='lifecycle_state'"
    ).fetchone())

    # Active model (OBSERVE or PAPER_ACTIVE if column exists, else latest)
    model_row = None
    if has_lifecycle:
        for state in ("PAPER_ACTIVE", "OBSERVE"):
            model_row = conn.execute(
                "SELECT * FROM learning_models WHERE lifecycle_state=? ORDER BY created_at DESC LIMIT 1",
                (state,),
            ).fetchone()
            if model_row:
                break
    if model_row is None:
        model_row = conn.execute(
            "SELECT * FROM learning_models ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    def _col(row, name):
        try:
            return row[name] if row and name in row.keys() else None
        except Exception:
            return None

    model_version = _col(model_row, "model_version")
    model_id = _col(model_row, "model_id")
    ev_raw = _col(model_row, "evidence_contract_version")
    ev_contract = int(ev_raw) if ev_raw is not None else None
    lifecycle = _col(model_row, "lifecycle_state")

    # Shadow account initial capital from trading_accounts (if recorded)
    acct_row = conn.execute(
        "SELECT starting_capital FROM trading_accounts WHERE account_id=? LIMIT 1",
        (_SHADOW_ACCOUNT_ID,),
    ).fetchone() if _table_exists(conn, "trading_accounts") else None
    initial_capital_db = float(acct_row["starting_capital"]) if acct_row else None

    conn.close()
    return {
        "model_version": model_version,
        "model_id": model_id,
        "evidence_contract_version": ev_contract,
        "lifecycle_state": lifecycle,
        "initial_capital_db": initial_capital_db,
    }


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _load_policy_fields() -> dict:
    # 0452: raises on failure — partial baselines are not authoritative
    sys.path.insert(0, str(_REPO_ROOT))
    from trade_engine.policy import load_policy
    try:
        policy = load_policy(_SHADOW_ACCOUNT_ID)
        return {
            "policy_version": policy.policy_version,
            "policy_hash": policy.policy_hash(),
            "shadow_account_initial_capital": policy.starting_capital(),
        }
    except Exception as e:
        raise RuntimeError(f"Cannot load policy for {_SHADOW_ACCOUNT_ID}: {e}") from e


def _load_virtual_book_capital() -> float:
    # 0449: import from opportunity_config (pure module, no side effects)
    # 0452: raises on failure
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from agents.opportunity_config import VIRTUAL_BOOK_STARTING_CASH
        return float(VIRTUAL_BOOK_STARTING_CASH)
    except Exception as e:
        raise RuntimeError(f"Cannot load VIRTUAL_BOOK_STARTING_CASH: {e}") from e


def _load_formula_params() -> dict:
    # 0449: import from opportunity_config — the genuine production source
    # 0452: raises on failure
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from agents.opportunity_config import COMPOSITE_WEIGHTS, MIN_COMPOSITE
    except Exception as e:
        raise RuntimeError(f"Cannot import from opportunity_config: {e}") from e
    weights = dict(COMPOSITE_WEIGHTS)
    formula_str = " + ".join(f"{v:.2f}*{k}" for k, v in weights.items())
    return {
        "composite_formula": formula_str,
        "composite_weights": weights,
        "min_composite_threshold": int(MIN_COMPOSITE),
    }


def _load_strategy_hash() -> str:
    # 0452: raises on failure
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        import strategy_config
        return strategy_config.get_hash()
    except Exception as e:
        raise RuntimeError(f"Cannot load strategy hash: {e}") from e


def build_baseline(db_path: str) -> dict:
    db_fields = _load_db_fields(db_path)
    policy_fields = _load_policy_fields()
    formula_params = _load_formula_params()
    strategy_hash = _load_strategy_hash()
    virtual_book_capital = _load_virtual_book_capital()
    sha = _git_sha()
    dirty = _git_dirty()
    frozen_at = datetime.now(timezone.utc).isoformat()

    return {
        "_note": (
            "Frozen experiment baseline — DO NOT modify or re-run during this experiment. "
            "This file records the conditions in place before the learner was activated. "
            "Model activation conditions are recorded separately in model_promotion_log."
        ),
        "frozen_at": frozen_at,
        "git_commit_sha": sha,
        "git_dirty": dirty,
        "model_version": db_fields["model_version"],
        "model_id": db_fields["model_id"],
        "lifecycle_state_at_freeze": db_fields["lifecycle_state"],
        "evidence_contract_version": db_fields["evidence_contract_version"],
        "shadow_account_id": _SHADOW_ACCOUNT_ID,
        # 0444: record both capital bases separately
        "shadow_account_initial_capital": (
            policy_fields.get("shadow_account_initial_capital")
            or db_fields.get("initial_capital_db")
        ),
        "virtual_book_starting_cash": virtual_book_capital,
        "_capital_note": (
            "shadow_account_initial_capital = real-money risk limit for the shadow brokerage account; "
            "virtual_book_starting_cash = notional starting cash for the champion/challenger virtual books."
        ),
        "policy_version": policy_fields.get("policy_version"),
        "policy_hash": policy_fields.get("policy_hash"),
        "strategy_hash": strategy_hash,
        "base_formula": formula_params,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_REPO_ROOT / "out" / "investment.db"),
                        help="Path to investment.db")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the snapshot without writing the file")
    parser.add_argument("--force", action="store_true",
                        help="Allow freeze from a dirty worktree (records git_dirty=true)")
    args = parser.parse_args()

    # 0447: refuse to write from a dirty tree so git_commit_sha is trustworthy
    if not args.dry_run and not args.force:
        dirty = _git_dirty()
        if dirty is True:
            print("ERROR: worktree is dirty. Commit all changes before freezing the baseline.")
            print("  The git_commit_sha in the snapshot must match the exact source tree.")
            print("  Pass --force to override (recorded as git_dirty=true).")
            sys.exit(1)

    if _OUT_PATH.exists() and not args.dry_run:
        print(f"WARNING: {_OUT_PATH} already exists.")
        print("Re-running freeze_baseline.py overwrites the immutable experiment record.")
        answer = input("Overwrite? Only do this if starting a brand-new experiment. [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    # 0452: loaders raise RuntimeError on failure; abort rather than writing a partial baseline
    try:
        baseline = build_baseline(args.db)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        print("Baseline freeze aborted — fix the above error before proceeding.")
        if args.dry_run:
            print("(dry-run mode: no file would have been written)")
        sys.exit(1)

    if args.dry_run:
        print(json.dumps(baseline, indent=2))
        return

    _OUT_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline frozen to {_OUT_PATH}")
    print(f"  model_version:                 {baseline['model_version']}")
    print(f"  evidence_contract:             {baseline['evidence_contract_version']}")
    print(f"  shadow_account_initial_capital:{baseline['shadow_account_initial_capital']}")
    print(f"  virtual_book_starting_cash:    {baseline['virtual_book_starting_cash']}")
    print(f"  git_commit_sha:                {baseline['git_commit_sha']}")
    print(f"  frozen_at:                     {baseline['frozen_at']}")


if __name__ == "__main__":
    main()
