#!/usr/bin/env python3
"""Freeze the current experiment baseline snapshot.

Run once before material 63-session results arrive to capture the exact
experimental conditions under which challenger vs. base evidence is collected.
Writes config/experiment_baseline.json (committed, not gitignored).

The file is intentionally frozen: do NOT re-run this script unless you are
starting a new controlled experiment. Re-running mid-experiment contaminates
the comparison by silently redefining the baseline conditions.

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
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO_ROOT), text=True
        ).strip()
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
    sys.path.insert(0, str(_REPO_ROOT))
    from trade_engine.policy import load_policy
    try:
        policy = load_policy(_SHADOW_ACCOUNT_ID)
        return {
            "policy_version": policy.policy_version,
            "policy_hash": policy.policy_hash(),
            "initial_capital_policy": policy.starting_capital(),
        }
    except Exception as e:
        return {"policy_error": str(e)}


def _load_formula_params() -> dict:
    return {
        "composite_formula": "0.30*Q + 0.25*V + 0.20*PF + 0.15*C + 0.10*EC",
        "composite_weights": {"Q": 0.30, "V": 0.25, "PF": 0.20, "C": 0.15, "EC": 0.10},
        "min_composite_threshold": 45,
    }


def _load_strategy_hash() -> str | None:
    try:
        sys.path.insert(0, str(_REPO_ROOT))
        import strategy_config
        return strategy_config.get_hash()
    except Exception:
        return None


def build_baseline(db_path: str) -> dict:
    db_fields = _load_db_fields(db_path)
    policy_fields = _load_policy_fields()
    formula_params = _load_formula_params()
    strategy_hash = _load_strategy_hash()
    sha = _git_sha()
    frozen_at = datetime.now(timezone.utc).isoformat()

    initial_capital = (
        policy_fields.get("initial_capital_policy")
        or db_fields.get("initial_capital_db")
    )

    return {
        "_note": (
            "Frozen experiment baseline — DO NOT modify after initial freeze. "
            "Re-run freeze_baseline.py only if starting a new controlled experiment."
        ),
        "frozen_at": frozen_at,
        "git_commit_sha": sha,
        "model_version": db_fields["model_version"],
        "model_id": db_fields["model_id"],
        "lifecycle_state_at_freeze": db_fields["lifecycle_state"],
        "evidence_contract_version": db_fields["evidence_contract_version"],
        "shadow_account_id": _SHADOW_ACCOUNT_ID,
        "initial_capital": initial_capital,
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
    args = parser.parse_args()

    if _OUT_PATH.exists() and not args.dry_run:
        print(f"WARNING: {_OUT_PATH} already exists.")
        answer = input("Overwrite? This resets the baseline. [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    baseline = build_baseline(args.db)

    if args.dry_run:
        print(json.dumps(baseline, indent=2))
        return

    _OUT_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline frozen to {_OUT_PATH}")
    print(f"  model_version:           {baseline['model_version']}")
    print(f"  evidence_contract:       {baseline['evidence_contract_version']}")
    print(f"  git_commit_sha:          {baseline['git_commit_sha']}")
    print(f"  frozen_at:               {baseline['frozen_at']}")


if __name__ == "__main__":
    main()
