#!/usr/bin/env python3
"""Read-only validator for Portfolio Decision Brief DB invariants.

Checks invariants against the production (or snapshot) investment DB.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_ai import BRIEF_POLICY_VERSION  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parent.parent / "out" / "investment.db"

VALID_PORTFOLIO_STATES = {"STABLE", "ATTENTION", "URGENT", "UNKNOWN"}
CURRENT_POLICY_VERSION = BRIEF_POLICY_VERSION  # "v2"

# Versions that existed before v2; rows with these versions are historical legacy.
KNOWN_LEGACY_VERSIONS: set = {None, "v1"}

# UTC timestamp when BRIEF_POLICY_VERSION="v2" was first deployed to production.
# Rows captured before this timestamp with a missing/None version → LEGACY (historical).
# Rows captured after this timestamp with a missing/unknown version → UNKNOWN_VERSION violation.
V2_DEPLOY_TIMESTAMP = "2026-09-24T19:26:00"


# ── Independent v2 policy oracle ────────────────────────────────────────────
# Deliberately does NOT import _derive_portfolio_state or any other policy
# function from portfolio_ai.  The duplication is intentional: two independent
# implementations of the same specification catch bugs in either one.
# When the policy changes to v3, a new _expected_v3_state() oracle must be
# written at that time, bound to the v3 specification.

def _expected_v2_state(snapshot: dict) -> str:
    """Independent re-implementation of the v2 portfolio_state derivation rule.

    Inputs only the brief_state snapshot (no LLM output).
    Does not import _derive_portfolio_state, _sev_int, or _HIGH_SEVERITY_THRESHOLD.
    """
    items = snapshot.get("attention_items", [])

    def sev(item: dict) -> int:
        v = item.get("severity", 0)
        if isinstance(v, str):
            return {"high": 80, "medium": 50, "low": 20}.get(v.lower(), 0)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    if any(sev(i) >= 70 for i in items):
        return "URGENT"
    if items:
        return "ATTENTION"
    if snapshot.get("brief_health") == "HEALTHY":
        return "STABLE"
    return "UNKNOWN"


def _row_classification(briefing_output: dict, captured_at: str) -> str:
    """Return 'CURRENT', 'LEGACY', or 'UNKNOWN_VERSION'.

    CURRENT        — brief_policy_version == CURRENT_POLICY_VERSION → validate all invariants
    LEGACY         — known pre-v2 version on an old record → warning only
    UNKNOWN_VERSION — unexpected version string, or missing version on a post-v2 record → violation
    """
    version = briefing_output.get("brief_policy_version")
    if version == CURRENT_POLICY_VERSION:
        return "CURRENT"
    if version in KNOWN_LEGACY_VERSIONS and (captured_at or "") < V2_DEPLOY_TIMESTAMP:
        return "LEGACY"
    return "UNKNOWN_VERSION"


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
                classification = _row_classification(output, row["captured_at"] or "")
                if classification == "LEGACY":
                    warnings.append(
                        f"[INV-1/LEGACY] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                        f"portfolio_state={ps!r} not in {VALID_PORTFOLIO_STATES}"
                    )
                else:
                    violations.append(
                        f"[INV-1] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                        f"portfolio_state={ps!r} not in {VALID_PORTFOLIO_STATES}"
                    )

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
                classification = _row_classification(output, row["captured_at"] or "")
                if classification == "LEGACY":
                    warnings.append(
                        f"[INV-2/LEGACY] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                        f"portfolio_state=STABLE with non-empty attention_items"
                    )
                else:
                    violations.append(
                        f"[INV-2] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                        f"portfolio_state=STABLE with non-empty attention_items"
                    )

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
                classification = _row_classification(insight, row["generated_at"] or "")
                if classification == "LEGACY":
                    warnings.append(
                        f"[INV-3/LEGACY] day={row['day']} generated_at={row['generated_at']}: "
                        f"ai_insights portfolio_state={ps!r} not in {VALID_PORTFOLIO_STATES}"
                    )
                else:
                    violations.append(
                        f"[INV-3] day={row['day']} generated_at={row['generated_at']}: "
                        f"ai_insights portfolio_state={ps!r} not in {VALID_PORTFOLIO_STATES}"
                    )

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

    # ── Invariant 6 (placeholder for INV-5 mirror) ───────────────────────────
    # Already covered by INV-5.

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

    # ── Invariant 8: recomputation (v2 rows only) ────────────────────────────
    # For every CURRENT (v2) provenance row, _expected_v2_state(brief_snapshot)
    # must equal the persisted portfolio_state.  Uses the independent oracle —
    # not _derive_portfolio_state() from production — so a bug in the production
    # function is detectable here.
    if _table_exists(conn, "portfolio_brief_provenance"):
        rows = conn.execute(
            "SELECT brief_id, captured_at, brief_snapshot_json, briefing_output_json "
            "FROM portfolio_brief_provenance"
        ).fetchall()
        for row in rows:
            try:
                output = json.loads(row["briefing_output_json"] or "{}")
                snapshot = json.loads(row["brief_snapshot_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            classification = _row_classification(output, row["captured_at"] or "")
            if classification != "CURRENT":
                continue
            expected = _expected_v2_state(snapshot)
            actual = output.get("portfolio_state")
            if actual != expected:
                violations.append(
                    f"[INV-8] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                    f"oracle state={expected!r} != persisted state={actual!r}"
                )
            # Belt-and-suspenders spot checks (still independent — no production imports)
            attention_items = snapshot.get("attention_items", [])

            def _sev_local(item: dict) -> int:
                v = item.get("severity", 0)
                if isinstance(v, str):
                    return {"high": 80, "medium": 50, "low": 20}.get(v.lower(), 0)
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return 0

            has_high = any(_sev_local(i) >= 70 for i in attention_items)
            if has_high and actual != "URGENT":
                violations.append(
                    f"[INV-8/HIGH-SEV] brief_id={row['brief_id']}: "
                    f"high-severity attention present but portfolio_state={actual!r} (expected URGENT)"
                )
            if not attention_items and snapshot.get("brief_health") == "HEALTHY" and actual != "STABLE":
                violations.append(
                    f"[INV-8/STABLE-CEIL] brief_id={row['brief_id']}: "
                    f"no attention + HEALTHY brief but portfolio_state={actual!r} (expected STABLE)"
                )

    # ── Invariant 9: fail-closed version classification ──────────────────────
    # A missing or unrecognized brief_policy_version on a post-v2 record is a
    # violation, not a legacy warning.  This catches a failure of the versioning
    # mechanism itself (e.g. a persistence regression that omits the version field).
    if _table_exists(conn, "portfolio_brief_provenance"):
        rows = conn.execute(
            "SELECT brief_id, captured_at, briefing_output_json FROM portfolio_brief_provenance"
        ).fetchall()
        for row in rows:
            try:
                output = json.loads(row["briefing_output_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            classification = _row_classification(output, row["captured_at"] or "")
            if classification == "UNKNOWN_VERSION":
                version = output.get("brief_policy_version")
                violations.append(
                    f"[INV-9] brief_id={row['brief_id']} captured_at={row['captured_at']}: "
                    f"unrecognized or missing brief_policy_version={version!r} on post-v2 record "
                    f"(expected {CURRENT_POLICY_VERSION!r} or a known legacy version before {V2_DEPLOY_TIMESTAMP})"
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
        print(f"\n=== {len(warnings)} pre-v2 legacy warning(s) (informational) ===")
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
