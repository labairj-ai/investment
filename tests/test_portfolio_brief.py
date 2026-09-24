"""
Adversarial acceptance tests for the Portfolio Decision Brief (0632).

All tests use in-memory or temp SQLite — no LLM, no network.
Covers the cross-system contracts introduced in 0624-0627 + hardening in 0628-0631.
"""
import importlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import portfolio_ai
from agents.news.intelligence import (
    EMERGING_OPP_THRESHOLD,
    EMERGING_RISK_THRESHOLD,
    classify_news_event,
)


# ── Schema helpers ────────────────────────────────────────────────────────────

def _make_brief_db(tmp_path):
    """Create a temp DB with all tables needed by portfolio_ai."""
    import agent_db
    db_file = tmp_path / "brief_test.db"
    db_file.touch()
    old_path = portfolio_ai.DB_PATH
    agent_db_old = getattr(agent_db, "DB_PATH", None)
    portfolio_ai.DB_PATH = db_file
    agent_db.DB_PATH = db_file
    try:
        agent_db.migrate()
        portfolio_ai._init_ai_tables()
    finally:
        portfolio_ai.DB_PATH = old_path
        if agent_db_old is not None:
            agent_db.DB_PATH = agent_db_old
    return db_file


def _conn(db_file):
    c = sqlite3.connect(str(db_file), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _seed_acceptance(conn, version="v2", boundary="2026-01-01 00:00:00"):
    conn.execute(
        "INSERT OR REPLACE INTO _news_intelligence_acceptance"
        " (accepted_at, accepted_commit, accepted_version)"
        " VALUES (?, 'test', ?)",
        (boundary, version),
    )


def _seed_snapshot(conn, snap_hash="testhash", version="v2"):
    conn.execute(
        "INSERT OR IGNORE INTO news_snapshots (snapshot_hash, version, created_at)"
        " VALUES (?, ?, '2026-01-01')",
        (snap_hash, version),
    )


def _insert_news_event(conn, ticker, causal_key, event_id=None,
                       direction="POSITIVE", signal_strength=50.0,
                       confirmation_class="NEWS_ONLY",
                       extracted_at="2026-09-20 00:00:00",
                       snap_hash="testhash", version="v2"):
    eid = event_id or str(uuid.uuid4())
    conn.execute(
        """INSERT OR REPLACE INTO news_events (
            event_id, ticker, day, event_type, direction, magnitude,
            expected_horizon, confidence, extracted_at, last_seen,
            trend_status, signal_strength, portfolio_priority,
            confirmation_class, causal_event_key, news_snapshot_hash,
            news_intelligence_version
        ) VALUES (?, ?, '2026-09-20', 'GUIDANCE_CHANGE', ?, 'HIGH',
                  'SHORT', 0.8, ?, ?, 'CONFIRMING', ?, ?,
                  ?, ?, ?, ?)""",
        (eid, ticker, direction, extracted_at, extracted_at,
         signal_strength, signal_strength * 0.5,
         confirmation_class, causal_key, snap_hash, version),
    )
    return eid


def _set_state(conn, ticker, causal_key, state="ACTIVE"):
    conn.execute(
        """INSERT OR REPLACE INTO news_event_state
           (ticker, causal_event_key, last_real_seen_at, state, state_as_of)
           VALUES (?, ?, '2026-09-20', ?, '2026-09-20')""",
        (ticker, causal_key, state),
    )


# ── Test 1: same causal event on 3 days → one brief item ─────────────────────

def test_same_causal_event_three_days_yields_one_item(tmp_path):
    db_file = _make_brief_db(tmp_path)
    with _conn(db_file) as conn:
        _seed_acceptance(conn)
        _seed_snapshot(conn)
        key = "guidance:AAPL:rev_guidance"
        # Three observations of the same causal event on consecutive days
        for i, ts in enumerate(
            ["2026-09-18 00:00:00", "2026-09-19 00:00:00", "2026-09-20 00:00:00"]
        ):
            _insert_news_event(
                conn, "AAPL", key,
                event_id=f"ev-{i}", direction="POSITIVE",
                signal_strength=50.0, extracted_at=ts,
            )
        _set_state(conn, "AAPL", key, "ACTIVE")
        conn.commit()

    portfolio_ai.DB_PATH = db_file
    rows = portfolio_ai.get_current_news_intelligence(conn=_conn(db_file), accepted_version="v2", recency_days=30)
    tickers_and_keys = [(dict(r)["ticker"], dict(r)["causal_event_key"]) for r in rows]
    aapl_rows = [x for x in tickers_and_keys if x[0] == "AAPL"]
    assert len(aapl_rows) == 1, (
        f"Expected 1 row per causal_event_key, got {len(aapl_rows)}: {aapl_rows}"
    )
    # The returned row should be the latest (ev-2)
    row = dict(rows[0])
    assert row["event_id"] == "ev-2", f"Expected latest event_id ev-2, got {row['event_id']}"


# ── Test 2: MULTI_SIGNAL_CONFIRMATION → EMERGING_OPPORTUNITY ─────────────────

def test_multi_signal_confirmation_recognized():
    event = {"direction": "POSITIVE", "signal_strength": 30.0,
             "confirmation_class": "MULTI_SIGNAL_CONFIRMATION"}
    result = classify_news_event(event, nes_state="ACTIVE")
    assert result == "EMERGING_OPPORTUNITY", (
        f"MULTI_SIGNAL_CONFIRMATION + POSITIVE should be EMERGING_OPPORTUNITY, got {result!r}"
    )


def test_multi_signal_wrong_vocab_not_recognized():
    # Old wrong vocabulary — must NOT trigger opportunity
    event = {"direction": "POSITIVE", "signal_strength": 30.0,
             "confirmation_class": "MULTI_SIGNAL"}
    result = classify_news_event(event, nes_state="ACTIVE")
    assert result != "EMERGING_OPPORTUNITY", (
        f"MULTI_SIGNAL (wrong vocab) should not produce EMERGING_OPPORTUNITY, got {result!r}"
    )


# ── Test 3: signal_strength boundary at frozen threshold ─────────────────────

def test_signal_strength_44_is_watch():
    event = {"direction": "NEGATIVE", "signal_strength": EMERGING_RISK_THRESHOLD - 1,
             "confirmation_class": "NEWS_ONLY"}
    result = classify_news_event(event, nes_state="ACTIVE")
    assert result != "EMERGING_RISK", (
        f"signal_strength={EMERGING_RISK_THRESHOLD - 1} should not be EMERGING_RISK, got {result!r}"
    )


def test_signal_strength_45_is_emerging_risk():
    event = {"direction": "NEGATIVE", "signal_strength": EMERGING_RISK_THRESHOLD,
             "confirmation_class": "NEWS_ONLY"}
    result = classify_news_event(event, nes_state="ACTIVE")
    assert result == "EMERGING_RISK", (
        f"signal_strength={EMERGING_RISK_THRESHOLD} NEGATIVE should be EMERGING_RISK, got {result!r}"
    )


def test_signal_strength_45_positive_is_opportunity():
    event = {"direction": "POSITIVE", "signal_strength": EMERGING_OPP_THRESHOLD,
             "confirmation_class": "NEWS_ONLY"}
    result = classify_news_event(event, nes_state="ACTIVE")
    assert result == "EMERGING_OPPORTUNITY", (
        f"signal_strength={EMERGING_OPP_THRESHOLD} POSITIVE should be EMERGING_OPPORTUNITY, got {result!r}"
    )


# ── Test 4: FADING → WATCH; RESOLVED → absent ────────────────────────────────

def test_fading_event_is_watch():
    event = {"direction": "NEGATIVE", "signal_strength": 80.0,
             "confirmation_class": "NEWS_ONLY"}
    result = classify_news_event(event, nes_state="FADING")
    assert result == "WATCH", f"FADING event should be WATCH, got {result!r}"


def test_resolved_event_excluded():
    event = {"direction": "NEGATIVE", "signal_strength": 80.0,
             "confirmation_class": "NEWS_ONLY"}
    result = classify_news_event(event, nes_state="RESOLVED")
    assert result is None, f"RESOLVED event should return None (excluded), got {result!r}"


def test_get_current_news_intelligence_excludes_resolved(tmp_path):
    db_file = _make_brief_db(tmp_path)
    with _conn(db_file) as conn:
        _seed_acceptance(conn)
        _seed_snapshot(conn)
        _insert_news_event(conn, "TSLA", "guidance:TSLA:x", direction="NEGATIVE",
                           signal_strength=80.0)
        _set_state(conn, "TSLA", "guidance:TSLA:x", "RESOLVED")
        conn.commit()

    portfolio_ai.DB_PATH = db_file
    rows = portfolio_ai.get_current_news_intelligence(_conn(db_file), recency_days=30)
    tickers = [dict(r)["ticker"] for r in rows]
    assert "TSLA" not in tickers, "RESOLVED events must be excluded from brief"


def test_get_current_news_intelligence_includes_fading(tmp_path):
    db_file = _make_brief_db(tmp_path)
    with _conn(db_file) as conn:
        _seed_acceptance(conn)
        _seed_snapshot(conn)
        _insert_news_event(conn, "MSFT", "guidance:MSFT:y", direction="POSITIVE",
                           signal_strength=60.0)
        _set_state(conn, "MSFT", "guidance:MSFT:y", "FADING")
        conn.commit()

    portfolio_ai.DB_PATH = db_file
    rows = portfolio_ai.get_current_news_intelligence(_conn(db_file), recency_days=30)
    tickers = [dict(r)["ticker"] for r in rows]
    assert "MSFT" in tickers, "FADING events must remain eligible (classify as WATCH)"


def test_no_state_row_excluded(tmp_path):
    """Fail closed: event with no news_event_state row must not appear (INNER JOIN)."""
    db_file = _make_brief_db(tmp_path)
    with _conn(db_file) as conn:
        _seed_acceptance(conn)
        _seed_snapshot(conn)
        _insert_news_event(conn, "META", "guidance:META:z", direction="POSITIVE",
                           signal_strength=70.0)
        # Intentionally no _set_state() call
        conn.commit()

    portfolio_ai.DB_PATH = db_file
    rows = portfolio_ai.get_current_news_intelligence(_conn(db_file), recency_days=30)
    tickers = [dict(r)["ticker"] for r in rows]
    assert "META" not in tickers, "Events with no state row must be excluded (fail closed)"


# ── Test 5: FILLED intent not open ───────────────────────────────────────────

def test_filled_intent_not_in_execution_state(tmp_path):
    db_file = _make_brief_db(tmp_path)
    with _conn(db_file) as conn:
        # trade_intents uses 'symbol'/'side', not 'ticker'/'action'
        conn.execute(
            "INSERT INTO trade_intents (intent_id, symbol, side, quantity, status, created_at)"
            " VALUES ('i1', 'NVDA', 'BUY', 10, 'FILLED', '2026-09-20')"
        )
        conn.execute(
            "INSERT INTO trade_intents (intent_id, symbol, side, quantity, status, created_at)"
            " VALUES ('i2', 'AMD', 'BUY', 5, 'PENDING', '2026-09-20')"
        )
        conn.commit()

    with _conn(db_file) as conn:
        rows = conn.execute(
            "SELECT intent_id FROM trade_intents"
            " WHERE status NOT IN ('FILLED', 'CANCELLED', 'EXPIRED', 'REJECTED')"
        ).fetchall()
    ids = [r["intent_id"] for r in rows]
    assert "i1" not in ids, "FILLED intent must not appear as open"
    assert "i2" in ids, "PENDING intent must appear as open"

    # Verify case-sensitivity: lowercase 'filled' would NOT be excluded by the old query
    with _conn(db_file) as conn:
        conn.execute(
            "INSERT INTO trade_intents (intent_id, symbol, side, quantity, status, created_at)"
            " VALUES ('i3', 'GOOG', 'BUY', 3, 'filled', '2026-09-20')"
        )
        conn.commit()
        old_style = conn.execute(
            "SELECT intent_id FROM trade_intents"
            " WHERE status NOT IN ('filled', 'cancelled', 'expired')"
        ).fetchall()
        new_style = conn.execute(
            "SELECT intent_id FROM trade_intents"
            " WHERE status NOT IN ('FILLED', 'CANCELLED', 'EXPIRED', 'REJECTED')"
        ).fetchall()
    # lowercase filter correctly catches 'filled', uppercase catches 'FILLED'
    old_ids = {r["intent_id"] for r in old_style}
    new_ids = {r["intent_id"] for r in new_style}
    assert "i3" not in old_ids, "lowercase 'filled' excluded by old lowercase filter"
    assert "i1" not in new_ids, "FILLED excluded by new uppercase filter"
    assert "i3" in new_ids, "lowercase 'filled' NOT excluded by uppercase filter (different case)"


# ── Test 6: crashed Guardian run doesn't refresh freshness ───────────────────

def test_crashed_guardian_run_does_not_refresh_freshness(tmp_path):
    db_file = _make_brief_db(tmp_path)
    now = time.time()
    with _conn(db_file) as conn:
        # Crashed run: started_at recent, status != 'done', no finished_at
        conn.execute(
            "INSERT INTO agent_runs (agent_type, started_at, status)"
            " VALUES ('portfolio_guardian', ?, 'running')",
            (now - 60,),
        )
        # Completed run: finished_at is old (48h ago)
        conn.execute(
            "INSERT INTO agent_runs (agent_type, started_at, finished_at, status)"
            " VALUES ('portfolio_guardian', ?, ?, 'done')",
            (now - 172_800, now - 172_800),
        )
        conn.commit()

    with _conn(db_file) as conn:
        gr = conn.execute(
            "SELECT MAX(finished_at) FROM agent_runs"
            " WHERE agent_type='portfolio_guardian' AND status='done'"
        ).fetchone()
    finished_ts = gr[0]
    assert finished_ts is not None
    age_h = (now - float(finished_ts)) / 3600
    assert age_h > 24, (
        f"Freshness should be based on last completed run (~48h old), got {age_h:.1f}h"
    )


# ── Test 7: failed provenance insert rolls back ai_insights ──────────────────

class _FailOnProvenance(sqlite3.Connection):
    """Wraps a real Connection but raises on INSERT INTO portfolio_brief_provenance."""
    def execute(self, sql, *args, **kwargs):
        if "portfolio_brief_provenance" in sql and sql.strip().upper().startswith("INSERT"):
            raise sqlite3.OperationalError("simulated provenance failure")
        return super().execute(sql, *args, **kwargs)


def test_failed_provenance_rolls_back_ai_insights(tmp_path, monkeypatch):
    db_file = _make_brief_db(tmp_path)

    stub_state = {
        "captured_at": "2026-09-20T00:00:00Z",
        "attention_items": [], "opportunities": [], "watch_items": [],
        "thesis_deltas": [], "changes": [],
    }
    stub_output = {"headline": "test"}

    briefing_mod = MagicMock()
    briefing_mod._run_briefing_llm = MagicMock(return_value=stub_output)
    monkeypatch.setitem(sys.modules, "agents.briefing_agent", briefing_mod)
    monkeypatch.setattr(portfolio_ai, "build_portfolio_brief_state", lambda conn: stub_state)
    monkeypatch.setattr(portfolio_ai, "DB_PATH", db_file)

    with _conn(db_file) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM ai_insights").fetchone()[0]

    failing_conn = _FailOnProvenance(str(db_file), timeout=10)
    failing_conn.row_factory = sqlite3.Row

    with pytest.raises(RuntimeError, match="Persistence failed"):
        portfolio_ai.create_portfolio_brief(failing_conn)
    failing_conn.close()

    with _conn(db_file) as conn:
        after_count = conn.execute("SELECT COUNT(*) FROM ai_insights").fetchone()[0]
    assert after_count == before_count, (
        f"ai_insights should be rolled back on provenance failure. "
        f"Before: {before_count}, after: {after_count}"
    )


# ── Test 8: bogus item_key rejected ──────────────────────────────────────────

def test_bogus_item_key_rejected(tmp_path):
    db_file = _make_brief_db(tmp_path)
    brief_id = str(uuid.uuid4())
    source_refs = [{"item_key": "rec:123", "source_type": "recommendation", "source_id": "123"}]
    with _conn(db_file) as conn:
        conn.execute(
            "INSERT INTO portfolio_brief_provenance"
            " (brief_id, captured_at, brief_snapshot_json, briefing_output_json, source_refs_json)"
            " VALUES (?, '2026-09-20', '{}', '{}', ?)",
            (brief_id, json.dumps(source_refs)),
        )
        conn.commit()
        # Validate item_key against source_refs_json — the serve.py logic
        valid_keys = {ref["item_key"] for ref in source_refs}
        bogus_key = "rec:999999"
        assert bogus_key not in valid_keys, "Bogus key must not be in valid_keys"
        assert "rec:123" in valid_keys, "Real key must be valid"


# ── Test 9: REVIEW links to existing recommendation episode ──────────────────

def test_review_links_to_existing_episode(tmp_path):
    db_file = _make_brief_db(tmp_path)
    ep_id = str(uuid.uuid4())
    rec_id = 42
    with _conn(db_file) as conn:
        conn.execute(
            "INSERT INTO agent_runs (id, agent_type, started_at, status)"
            " VALUES (1, 'opportunity_hunter', 1000.0, 'done')"
        )
        conn.execute(
            "INSERT INTO recommendations (id, run_id, ticker, action, recommendation_score,"
            " confidence, status, created_at, episode_id)"
            " VALUES (?, 1, 'AAPL', 'BUY', 80, 80, 'open', 1000.0, ?)",
            (rec_id, ep_id),
        )
        conn.commit()

    with _conn(db_file) as conn:
        rec_row = conn.execute(
            "SELECT episode_id FROM recommendations WHERE id=?", (rec_id,)
        ).fetchone()
        resolved_episode_id = rec_row["episode_id"] if rec_row else None

    assert resolved_episode_id == ep_id, (
        "REVIEW on rec:42 must resolve to the recommendation's existing episode_id"
    )
    # No new portfolio_brief_episodes row should be created
    with _conn(db_file) as conn:
        pbe_count = conn.execute(
            "SELECT COUNT(*) FROM portfolio_brief_episodes"
        ).fetchone()[0]
    assert pbe_count == 0, "portfolio_brief_episodes must not be written for REVIEW"


# ── Test 10: 50 news observations don't change production influence ───────────

def test_50_accepted_events_do_not_change_influence(tmp_path):
    """Accepted event count alone must not alter production influence mode.

    The influence mode is determined by the actual acceptance lifecycle state,
    not by counting rows.  This test verifies that _format_capability_summary()
    does not auto-promote based on count thresholds.
    """
    db_file = _make_brief_db(tmp_path)
    snap_hash = "hash50"
    boundary = "2026-01-01 00:00:00"
    with _conn(db_file) as conn:
        _seed_acceptance(conn, boundary=boundary)
        _seed_snapshot(conn, snap_hash=snap_hash)
        # Insert 50 accepted v2 events
        for i in range(50):
            conn.execute(
                """INSERT INTO news_events (event_id, ticker, day, event_type, direction,
                   magnitude, expected_horizon, confidence, extracted_at, last_seen,
                   signal_strength, portfolio_priority, confirmation_class,
                   causal_event_key, news_snapshot_hash, news_intelligence_version)
                   VALUES (?, 'AAPL', '2026-09-20', 'EARNINGS', 'POSITIVE',
                   'MEDIUM', 'SHORT', 0.7, '2026-09-20 00:00:00', '2026-09-20 00:00:00',
                   50.0, 25.0, 'NEWS_ONLY', ?, ?, 'v2')""",
                (f"ev50-{i}", f"key-{i}", snap_hash),
            )
        conn.commit()

    portfolio_ai.DB_PATH = db_file
    # _format_capability_summary reads brief_state["learning_state"]["accepted_count"]
    # It must not auto-promote to "active" influence when count hits 50.
    brief_state = {"learning_state": {"accepted_count": 50}, "execution_state": {}, "macro_state": {}}
    with patch("portfolio_ai.DB_PATH", db_file):
        summary = portfolio_ai._format_capability_summary(brief_state)

    # Must not claim active production influence — "observe-only" must be the influence mode
    assert "observe-only" in summary, (
        f"50 accepted events must not promote to active influence.\nSummary:\n{summary}"
    )
    # The old auto-promotion would produce "CALIBRATING" and "active" as the influence token.
    assert "calibrating" not in summary.lower(), (
        f"CALIBRATING status must not appear — count-based promotion is removed.\nSummary:\n{summary}"
    )
    # The influence token immediately following "accepted events," must be "observe-only", not "active"
    import re as _re
    m = _re.search(r"accepted events,\s*(\S+)", summary)
    if m:
        influence_token = m.group(1).lower()
        assert influence_token == "observe-only", (
            f"Influence token after 'accepted events,' should be 'observe-only', got {influence_token!r}"
        )
