"""0132: Action/outcome/validation schema-consistency tests.

Three static checks that catch gaps when new action types are added:
  1. Every emitted action has an explicit execution-validation policy.
  2. Every evaluable action has an outcome model branch (not silent fall-through).
  3. Every action written by the evaluator gets a non-null outcome_math_version.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_AGENTS_DIR = ROOT / "agents"


# ── helpers ───────────────────────────────────────────────────────────────────

def _collect_emitted_actions() -> set[str]:
    """Regex-scan agents/*.py for action strings assigned to 'action' key or field."""
    pattern = re.compile(r'"action"\s*:\s*"([A-Z_]+)"')
    action_field = re.compile(r'action\s*=\s*"([A-Z_]+)"')
    actions: set[str] = set()
    for path in _AGENTS_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        actions.update(pattern.findall(src))
        actions.update(action_field.findall(src))
    return actions


# Actions that appear in source but are NOT recommendation action types
# (dependency types, status values, verdict strings, etc.)
_NOT_ACTIONS = frozenset({
    # dependency types
    "PRICE", "OPTION_IV", "OPTION_LIQUIDITY", "OPTION_EXPIRATION",
    "EARNINGS_DATE", "THESIS_VERSION", "CC_POSITION_STATE", "MACRO_STATE",
    "FINANCIAL_PERIOD", "STRATEGY_HASH", "EARNINGS_EVENT",
    # critic verdicts / finding types
    "VETO", "CHALLENGE", "APPROVE", "APPROVE_WITH_CAUTION",
    # status / severity strings
    "STRONG", "WARNING", "VIOLATED", "WATCH", "HEALTHY", "UNKNOWN", "RESEARCH",
    # trigger types used as strings
    "NEAR_EXPIRY", "PRICE_THRESHOLD", "IV_SHIFT", "SPREAD_WIDE",
    "EARNINGS_IN_WINDOW", "THESIS_UPDATED", "CC_STATE_CHANGED", "MACRO_SHIFT",
    # non-rec action markers
    "NO_CALL",
})


def _emitted_action_types() -> set[str]:
    """Return the set of genuine recommendation action strings from agents/*.py."""
    raw = _collect_emitted_actions()
    return raw - _NOT_ACTIONS


# ── Test 1: execution-validation policy awareness ─────────────────────────────

# Actions that can be executed but need no required fields beyond execution_date.
_EXEC_NO_REQUIRED_FIELDS = frozenset({
    "HOLD", "REVIEW", "HOLD_CALL", "TAX_HARVEST", "NO_ACTION",
    # Informational / advisory actions — no trade execution fields needed
    "BRIEFING", "EXIT_REVIEW", "WAIT",
})

def test_all_action_types_have_execution_validation_policy():
    """Every emitted action has either a _REQUIRED_FIELDS entry or an explicit no-fields exemption.

    Catches new action types added to agents/ without updating execution_validation.py.
    """
    from execution_validation import _REQUIRED_FIELDS

    actions = _emitted_action_types()
    unknown: list[str] = []
    for action in sorted(actions):
        if action not in _REQUIRED_FIELDS and action not in _EXEC_NO_REQUIRED_FIELDS:
            unknown.append(action)

    assert not unknown, (
        f"Action(s) lack an execution-validation policy: {unknown}. "
        "Add to _REQUIRED_FIELDS in execution_validation.py, or to "
        "_EXEC_NO_REQUIRED_FIELDS in this test if no required fields are needed."
    )


# ── Test 2: outcome model coverage ────────────────────────────────────────────

# Actions explicitly excluded from outcome evaluation (never write outcome rows).
_EXCLUDE_FROM_EVALUATION = frozenset({
    "NO_ACTION", "NO_CALL",
    # Actions with fallback (hold_r) that is intentionally imprecise:
    "TAX_HARVEST",
    # Informational / non-evaluable actions
    "BRIEFING", "EXIT_REVIEW",
    # BUY, HARVEST, WAIT: evaluable in principle but not yet covered by the evaluator
    "BUY", "HARVEST", "WAIT",
})

def test_all_evaluable_actions_have_named_outcome_model():
    """Every emitted action either has a named outcome model or is explicitly excluded.

    'Named outcome model' means it appears in one of the explicit action sets used
    by _compute_scenarios(), not just the silent fall-through at the end.
    """
    from agents.outcome_evaluator import (
        CC_ACTIONS, CC_MANAGEMENT_ACTIONS, EQUITY_ACTIONS, EXIT_ACTIONS,
    )

    # Build set of actions with an explicit named branch in the evaluator
    named = (
        CC_ACTIONS
        | CC_MANAGEMENT_ACTIONS
        | EQUITY_ACTIONS
        | EXIT_ACTIONS
    )

    actions = _emitted_action_types()
    uncovered: list[str] = []
    for action in sorted(actions):
        if action not in named and action not in _EXCLUDE_FROM_EVALUATION:
            uncovered.append(action)

    assert not uncovered, (
        f"Action(s) have no named outcome model: {uncovered}. "
        "Add to an action set in outcome_evaluator.py (CC_ACTIONS, "
        "CC_MANAGEMENT_ACTIONS, EQUITY_ACTIONS, EXIT_ACTIONS) "
        "or to _EXCLUDE_FROM_EVALUATION in this test."
    )


# ── Test 3: outcome_math_version always set ───────────────────────────────────

def test_evaluator_sets_outcome_math_version_on_all_rows(mem_db):
    """evaluate_matured_recommendations sets outcome_math_version on every written row."""
    import sqlite3
    import time
    from datetime import date, timedelta
    from unittest.mock import patch

    import agent_db
    from agents.outcome_evaluator import evaluate_matured_recommendations

    conn = sqlite3.connect(str(mem_db), timeout=10)
    conn.row_factory = sqlite3.Row

    entry_date = (date.today() - timedelta(days=100)).isoformat()
    h_date = (date.today() - timedelta(days=70)).isoformat()
    entry_ts = time.time() - 100 * 86400

    # Seed a simple HOLD rec (equity horizons, minimal setup)
    conn.execute(
        "INSERT INTO recommendations (ticker, action, status, created_at, updated_at, "
        "recommendation_score, confidence, priority, urgency_level) "
        "VALUES ('AAPL', 'HOLD', 'accepted', ?, ?, 50, 50, 'normal', 'low')",
        (entry_ts, entry_ts),
    )
    rec_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO user_decisions (recommendation_id, decision, reason_code, decided_at) "
        "VALUES (?, 'accepted', 'OTHER', ?)", (rec_id, time.time()),
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS holding_day (
            ticker TEXT, day TEXT, price REAL, value REAL, weight_pct REAL, shares REAL,
            PRIMARY KEY (ticker, day))"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO holding_day (ticker, day, price, value, weight_pct, shares) "
        "VALUES ('AAPL', ?, 180.0, 18000.0, 10.0, 100)",
        (entry_date,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO holding_day (ticker, day, price, value, weight_pct, shares) "
        "VALUES ('AAPL', ?, 190.0, 19000.0, 10.0, 100)",
        (h_date,),
    )
    # Seed enough SPY rows for the dates we'll need
    for d, p in [(entry_date, 450.0), (h_date, 460.0)]:
        conn.execute("INSERT OR REPLACE INTO spy_prices (day, price) VALUES (?, ?)", (d, p))
    conn.commit()
    conn.close()

    with patch("agents.outcome_evaluator._ensure_spy_prices"):
        written = evaluate_matured_recommendations(min_age_days=1)

    assert written > 0, "Expected at least one outcome row"

    conn2 = sqlite3.connect(str(mem_db), timeout=10)
    conn2.row_factory = sqlite3.Row
    rows = conn2.execute(
        "SELECT horizon, outcome_math_version FROM recommendation_outcomes "
        "WHERE recommendation_id=?", (rec_id,)
    ).fetchall()
    conn2.close()

    assert rows, "No outcome rows found"
    for row in rows:
        assert row["outcome_math_version"] is not None, (
            f"outcome_math_version is NULL for horizon={row['horizon']}"
        )
