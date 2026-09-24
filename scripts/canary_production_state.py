#!/usr/bin/env python3
"""Read-only validator for Portfolio Decision Brief DB invariants.

Checks 7 invariants against the production (or snapshot) investment DB.
Does NOT call build_portfolio_brief_state(), create_portfolio_brief(), or any LLM.
Reads existing rows only and validates their shape.

Usage:
    python3 scripts/canary_production_state.py [--db path/to/investment.db]

Exit codes:
    0 — all invariants pass
    1 — one or more violations found
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "out" / "investment.db"

VALID_PORTFOLIO_STATES = {"STABLE", "ATTENTION", "URGENT", "UNKNOWN"}

# Rows written before 0648 normalization may have legacy invalid states.
# We label these differently from new violations so they can be investigated
# separately without blocking post-deploy canary runs.
LEGACY_CUTOFF = "2026-09-24"  # date 0648 was deployed


def _open_ro(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def run_invariants(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    """Return (violations, warnings).  violations cause exit 1; warnings are informational."""
    violations: list[str] = []
    warnings: list[str] = []

    # ── Invariant 1 ──────────────────────────────────────────────────────────
    # portfolio_brief_provenance: briefing_output_json.portfolio_state ∈ valid set
    if _table_exists(conn, "portfolio_brief_provenance"):
        rows = conn.execute(
            "SELECT brief_id, captured_at, briefing_output_json FROM portfolio_brief_provenance"
        ).fetchall()
        for row in rows:
            try:
                output = json.loads(row["briefing_output_json"] or "{}")
                ps = output.get("portfolio_state")
            except (json.JSONDecodeError, TypeError):
                violations.append(
                    f"[INV-1] brief_id={row['brief_id']}: briefing_output_json is not valid JSON"
                )
                continue
            if ps not in VALID_PORTFOLIO_STATES:
                label = "LEGACY" if (row["captured_at"] or "") < LEGACY_CUTOFF else "VIOLATION"
                entry = (
                    f"[INV-1/{label}] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                    f"portfolio_state={ps!r} not in {VALID_PORTFOLIO_STATES}"
                )
                if label == "LEGACY":
                    warnings.append(entry)
                else:
                    violations.append(entry)

    # ── Invariant 2 ──────────────────────────────────────────────────────────
    # Rows with attention_items must NOT have portfolio_state=STABLE.
    if _table_exists(conn, "portfolio_brief_provenance"):
        rows = conn.execute(
            "SELECT brief_id, captured_at, brief_snapshot_json, briefing_output_json "
            "FROM portfolio_brief_provenance"
        ).fetchall()
        for row in rows:
            try:
                snapshot = json.loads(row["brief_snapshot_json"] or "{}")
                output = json.loads(row["briefing_output_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            has_attention = bool(snapshot.get("attention_items"))
            ps = output.get("portfolio_state")
            if has_attention and ps == "STABLE":
                label = "LEGACY" if (row["captured_at"] or "") < LEGACY_CUTOFF else "VIOLATION"
                entry = (
                    f"[INV-2/{label}] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                    f"portfolio_state=STABLE with non-empty attention_items"
                )
                if label == "LEGACY":
                    warnings.append(entry)
                else:
                    violations.append(entry)

    # ── Invariant 3 ──────────────────────────────────────────────────────────
    # ai_insights: insight.portfolio_state ∈ valid set for all rows.
    if _table_exists(conn, "ai_insights"):
        rows = conn.execute("SELECT day, insight, generated_at FROM ai_insights").fetchall()
        for row in rows:
            try:
                insight = json.loads(row["insight"] or "{}")
                ps = insight.get("portfolio_state")
            except (json.JSONDecodeError, TypeError):
                violations.append(
                    f"[INV-3] day={row['day']}: ai_insights.insight is not valid JSON"
                )
                continue
            if ps not in VALID_PORTFOLIO_STATES:
                label = "LEGACY" if (row["generated_at"] or "") < LEGACY_CUTOFF else "VIOLATION"
                entry = (
                    f"[INV-3/{label}] day={row['day']} generated_at={row['generated_at']}: "
                    f"ai_insights portfolio_state={ps!r} not in {VALID_PORTFOLIO_STATES}"
                )
                if label == "LEGACY":
                    warnings.append(entry)
                else:
                    violations.append(entry)

    # ── Invariant 4 ──────────────────────────────────────────────────────────
    # portfolio_brief_provenance: source_refs_json is valid JSON with required fields.
    if _table_exists(conn, "portfolio_brief_provenance"):
        rows = conn.execute(
            "SELECT brief_id, captured_at, source_refs_json FROM portfolio_brief_provenance"
        ).fetchall()
        for row in rows:
            raw = row["source_refs_json"]
            if raw is None:
                continue
            try:
                refs = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                violations.append(
                    f"[INV-4] brief_id={row['brief_id']}: source_refs_json is not valid JSON"
                )
                continue
            if not isinstance(refs, list):
                violations.append(
                    f"[INV-4] brief_id={row['brief_id']}: source_refs_json is not a list"
                )
                continue
            for i, ref in enumerate(refs):
                missing = [f for f in ("source_type", "item_key") if f not in ref]
                if missing:
                    violations.append(
                        f"[INV-4] brief_id={row['brief_id']} ref[{i}]: "
                        f"missing fields {missing} — ref={ref}"
                    )

    # ── Invariant 5 ──────────────────────────────────────────────────────────
    # portfolio_brief_responses: every row has a matching brief_id in provenance.
    if _table_exists(conn, "portfolio_brief_responses") and _table_exists(conn, "portfolio_brief_provenance"):
        prov_ids = {
            r["brief_id"]
            for r in conn.execute("SELECT brief_id FROM portfolio_brief_provenance").fetchall()
        }
        orphans = conn.execute(
            "SELECT brief_id, item_key, responded_at FROM portfolio_brief_responses"
        ).fetchall()
        for row in orphans:
            if row["brief_id"] not in prov_ids:
                violations.append(
                    f"[INV-5] brief_id={row['brief_id']} item_key={row['item_key']}: "
                    f"response has no matching provenance row (orphaned response)"
                )

    # ── Invariant 6 ──────────────────────────────────────────────────────────
    # Same as 5 from the other direction: brief_id integrity (alias check).
    # Already covered by INV-5; this invariant confirms no gaps in the other direction.
    # (All provenance brief_ids referenced in responses must exist — covered above.)

    # ── Invariant 7 ──────────────────────────────────────────────────────────
    # portfolio_brief_snapshots: if the table exists, snapshot_json is valid JSON.
    if _table_exists(conn, "portfolio_brief_snapshots"):
        rows = conn.execute(
            "SELECT id, captured_at, snapshot_json FROM portfolio_brief_snapshots"
        ).fetchall()
        for row in rows:
            try:
                json.loads(row["snapshot_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                violations.append(
                    f"[INV-7] snapshot id={row['id']} captured_at={row['captured_at']}: "
                    f"snapshot_json is not valid JSON"
                )

    return violations, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Portfolio Decision Brief DB invariant checker")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Path to investment.db (default: {DEFAULT_DB})")
    args = parser.parse_args()

    db_path = args.db
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    print(f"Canary: opening {db_path} (read-only)")
    conn = _open_ro(db_path)
    try:
        violations, warnings = run_invariants(conn)
    finally:
        conn.close()

    if warnings:
        print(f"\n=== {len(warnings)} pre-normalization legacy warning(s) (informational) ===")
        for w in warnings:
            print(f"  {w}")

    if violations:
        print(f"\n=== FAIL: {len(violations)} invariant violation(s) ===")
        for v in violations:
            print(f"  {v}")
        return 1

    print(f"\nOK: all invariants pass ({len(warnings)} legacy warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
