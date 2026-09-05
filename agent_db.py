"""Agent infrastructure DB layer.

All agent tables live in the same investment.db used by the rest of the app.
Call migrate() once at startup — it is idempotent and safe to re-run.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "out" / "investment.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Migration ─────────────────────────────────────────────────────────────────

def migrate() -> None:
    """Create all agent tables. Safe to call multiple times — uses IF NOT EXISTS."""
    if not DB_PATH.exists():
        return
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id                   INTEGER PRIMARY KEY,
            agent_type           TEXT    NOT NULL,
            scope                TEXT    NOT NULL DEFAULT 'portfolio',
            ticker               TEXT,
            trigger_type         TEXT,
            trigger_key          TEXT,
            status               TEXT    NOT NULL DEFAULT 'running',
            model                TEXT,
            prompt_version       TEXT,
            input_hash           TEXT,
            input_snapshot_json  TEXT,
            started_at           REAL    NOT NULL,
            finished_at          REAL,
            error                TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_findings (
            id           INTEGER PRIMARY KEY,
            run_id       INTEGER NOT NULL REFERENCES agent_runs(id),
            ticker       TEXT,
            finding_type TEXT    NOT NULL,
            severity     INTEGER NOT NULL DEFAULT 50,
            confidence   INTEGER NOT NULL DEFAULT 50,
            summary      TEXT    NOT NULL,
            why_now      TEXT,
            metrics_json TEXT,
            evidence_json TEXT,
            created_at   REAL    NOT NULL,
            expires_at   REAL
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id                   INTEGER PRIMARY KEY,
            run_id               INTEGER REFERENCES agent_runs(id),
            ticker               TEXT    NOT NULL,
            action               TEXT    NOT NULL,
            action_payload_json  TEXT,
            recommendation_score INTEGER NOT NULL DEFAULT 50,
            confidence           INTEGER NOT NULL DEFAULT 50,
            priority             TEXT    NOT NULL DEFAULT 'normal',
            why_now              TEXT,
            rationale            TEXT,
            counter_case         TEXT,
            no_action_case       TEXT,
            status               TEXT    NOT NULL DEFAULT 'open',
            valid_until          REAL,
            created_at           REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS critic_reviews (
            id                    INTEGER PRIMARY KEY,
            recommendation_id     INTEGER NOT NULL REFERENCES recommendations(id),
            verdict               TEXT    NOT NULL,
            strongest_objection   TEXT,
            missing_evidence_json TEXT,
            confidence_adjustment INTEGER NOT NULL DEFAULT 0,
            created_at            REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS investment_theses (
            id          INTEGER PRIMARY KEY,
            ticker      TEXT    NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            summary     TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'draft',
            created_at  REAL    NOT NULL,
            approved_at REAL,
            closed_at   REAL
        );

        CREATE TABLE IF NOT EXISTS thesis_claims (
            id                 INTEGER PRIMARY KEY,
            thesis_id          INTEGER NOT NULL REFERENCES investment_theses(id),
            claim              TEXT    NOT NULL,
            claim_type         TEXT    NOT NULL,
            metric_key         TEXT,
            operator           TEXT,
            threshold          REAL,
            persistence_periods INTEGER NOT NULL DEFAULT 1,
            weight             REAL    NOT NULL DEFAULT 1.0,
            current_status     TEXT    NOT NULL DEFAULT 'untested',
            last_evaluated_at  REAL
        );

        CREATE TABLE IF NOT EXISTS user_decisions (
            id                INTEGER PRIMARY KEY,
            recommendation_id INTEGER NOT NULL REFERENCES recommendations(id),
            decision          TEXT    NOT NULL,
            reason_code       TEXT    NOT NULL DEFAULT 'OTHER',
            notes             TEXT,
            decided_at        REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recommendation_outcomes (
            id                      INTEGER PRIMARY KEY,
            recommendation_id       INTEGER NOT NULL REFERENCES recommendations(id),
            evaluation_date         REAL    NOT NULL,
            benchmark_return        REAL,
            actual_return           REAL,
            recommended_path_return REAL,
            opportunity_cost        REAL,
            notes                   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_agent_runs_type_ticker
            ON agent_runs (agent_type, ticker, started_at DESC);

        CREATE INDEX IF NOT EXISTS idx_findings_run
            ON agent_findings (run_id);

        CREATE INDEX IF NOT EXISTS idx_findings_ticker
            ON agent_findings (ticker, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_recommendations_status
            ON recommendations (status, ticker);

        CREATE INDEX IF NOT EXISTS idx_recommendations_ticker
            ON recommendations (ticker, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_critic_rec
            ON critic_reviews (recommendation_id);

        CREATE INDEX IF NOT EXISTS idx_theses_ticker
            ON investment_theses (ticker, version DESC);

        CREATE INDEX IF NOT EXISTS idx_thesis_claims_thesis
            ON thesis_claims (thesis_id);

        CREATE INDEX IF NOT EXISTS idx_decisions_rec
            ON user_decisions (recommendation_id);

        CREATE INDEX IF NOT EXISTS idx_outcomes_rec
            ON recommendation_outcomes (recommendation_id);
    """)
    conn.commit()

    # Add columns introduced after the initial schema (safe to re-run)
    _new_cols = [
        ("investment_theses", "approved_by",  "TEXT"),
        ("investment_theses", "intake_json",  "TEXT"),
        ("investment_theses", "draft_json",   "TEXT"),
    ]
    for table, col, col_type in _new_cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.close()


# ── Insert helpers ────────────────────────────────────────────────────────────

def insert_agent_run(
    agent_type: str,
    scope: str = "portfolio",
    ticker: str | None = None,
    trigger_type: str | None = None,
    trigger_key: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    input_hash: str | None = None,
    input_snapshot: dict | None = None,
) -> int:
    """Insert a new agent_run row and return its id."""
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO agent_runs
           (agent_type, scope, ticker, trigger_type, trigger_key, status,
            model, prompt_version, input_hash, input_snapshot_json, started_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (agent_type, scope, ticker, trigger_type, trigger_key, "running",
         model, prompt_version, input_hash,
         json.dumps(input_snapshot) if input_snapshot else None,
         time.time()),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def finish_agent_run(run_id: int, status: str = "done", error: str | None = None) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE agent_runs SET status=?, finished_at=?, error=? WHERE id=?",
        (status, time.time(), error, run_id),
    )
    conn.commit()
    conn.close()


def insert_finding(
    run_id: int,
    finding_type: str,
    summary: str,
    ticker: str | None = None,
    severity: int = 50,
    confidence: int = 50,
    why_now: str | None = None,
    metrics: dict | None = None,
    evidence: dict | None = None,
    expires_at: float | None = None,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO agent_findings
           (run_id, ticker, finding_type, severity, confidence, summary,
            why_now, metrics_json, evidence_json, created_at, expires_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, ticker, finding_type, severity, confidence, summary,
         why_now,
         json.dumps(metrics) if metrics else None,
         json.dumps(evidence) if evidence else None,
         time.time(), expires_at),
    )
    finding_id = cur.lastrowid
    conn.commit()
    conn.close()
    return finding_id


def insert_recommendation(
    ticker: str,
    action: str,
    run_id: int | None = None,
    action_payload: dict | None = None,
    recommendation_score: int = 50,
    confidence: int = 50,
    priority: str = "normal",
    why_now: str | None = None,
    rationale: str | None = None,
    counter_case: str | None = None,
    no_action_case: str | None = None,
    valid_until: float | None = None,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO recommendations
           (run_id, ticker, action, action_payload_json, recommendation_score,
            confidence, priority, why_now, rationale, counter_case,
            no_action_case, status, valid_until, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, ticker, action,
         json.dumps(action_payload) if action_payload else None,
         recommendation_score, confidence, priority, why_now, rationale,
         counter_case, no_action_case, "open", valid_until, time.time()),
    )
    rec_id = cur.lastrowid
    conn.commit()
    conn.close()
    return rec_id


def insert_critic_review(
    recommendation_id: int,
    verdict: str,
    strongest_objection: str | None = None,
    missing_evidence: list | None = None,
    confidence_adjustment: int = 0,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO critic_reviews
           (recommendation_id, verdict, strongest_objection,
            missing_evidence_json, confidence_adjustment, created_at)
           VALUES (?,?,?,?,?,?)""",
        (recommendation_id, verdict, strongest_objection,
         json.dumps(missing_evidence) if missing_evidence else None,
         confidence_adjustment, time.time()),
    )
    review_id = cur.lastrowid
    conn.commit()
    conn.close()
    return review_id


def upsert_thesis(
    ticker: str,
    summary: str,
    status: str = "draft",
    version: int = 1,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO investment_theses (ticker, version, summary, status, created_at)
           VALUES (?,?,?,?,?)""",
        (ticker, version, summary, status, time.time()),
    )
    thesis_id = cur.lastrowid
    conn.commit()
    conn.close()
    return thesis_id


def insert_thesis_claim(
    thesis_id: int,
    claim: str,
    claim_type: str,
    metric_key: str | None = None,
    operator: str | None = None,
    threshold: float | None = None,
    persistence_periods: int = 1,
    weight: float = 1.0,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO thesis_claims
           (thesis_id, claim, claim_type, metric_key, operator, threshold,
            persistence_periods, weight, current_status)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (thesis_id, claim, claim_type, metric_key, operator, threshold,
         persistence_periods, weight, "untested"),
    )
    claim_id = cur.lastrowid
    conn.commit()
    conn.close()
    return claim_id


def insert_user_decision(
    recommendation_id: int,
    decision: str,
    reason_code: str = "OTHER",
    notes: str | None = None,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO user_decisions
           (recommendation_id, decision, reason_code, notes, decided_at)
           VALUES (?,?,?,?,?)""",
        (recommendation_id, decision, reason_code, notes, time.time()),
    )
    decision_id = cur.lastrowid
    conn.commit()
    conn.close()
    return decision_id


def insert_outcome(
    recommendation_id: int,
    benchmark_return: float | None = None,
    actual_return: float | None = None,
    recommended_path_return: float | None = None,
    opportunity_cost: float | None = None,
    notes: str | None = None,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO recommendation_outcomes
           (recommendation_id, evaluation_date, benchmark_return, actual_return,
            recommended_path_return, opportunity_cost, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (recommendation_id, time.time(), benchmark_return, actual_return,
         recommended_path_return, opportunity_cost, notes),
    )
    outcome_id = cur.lastrowid
    conn.commit()
    conn.close()
    return outcome_id


# ── Thesis intake helpers ─────────────────────────────────────────────────────

def save_thesis_draft(ticker: str, intake_json: str, draft_json: str) -> int:
    """Insert or replace the DRAFT thesis for ticker. Only one DRAFT per ticker."""
    conn = _connect()
    existing = conn.execute(
        "SELECT id FROM investment_theses WHERE ticker=? AND status='DRAFT' "
        "ORDER BY version DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE investment_theses SET intake_json=?, draft_json=?, summary=? WHERE id=?",
            (intake_json, draft_json, f"Draft thesis for {ticker}", existing["id"]),
        )
        thesis_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO investment_theses
               (ticker, version, summary, status, intake_json, draft_json, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (ticker, 1, f"Draft thesis for {ticker}", "DRAFT",
             intake_json, draft_json, time.time()),
        )
        thesis_id = cur.lastrowid
    conn.commit()
    conn.close()
    return thesis_id


def get_thesis_full(ticker: str) -> dict | None:
    """Return the most recent thesis (any status) with intake_json and draft_json."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM investment_theses WHERE ticker=? ORDER BY version DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    # Parse JSON blobs if present
    for field in ("intake_json", "draft_json"):
        raw = result.get(field)
        if raw:
            try:
                result[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return result


def approve_thesis(ticker: str, final_draft_json: str) -> int:
    """Activate the current DRAFT, superseding any prior ACTIVE thesis."""
    conn = _connect()
    # Supersede old active thesis if one exists
    conn.execute(
        "UPDATE investment_theses SET status='SUPERSEDED', closed_at=? "
        "WHERE ticker=? AND status='ACTIVE'",
        (time.time(), ticker),
    )
    # Find the draft
    draft = conn.execute(
        "SELECT id, version FROM investment_theses WHERE ticker=? AND status='DRAFT' "
        "ORDER BY version DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not draft:
        conn.close()
        raise ValueError(f"No DRAFT thesis found for {ticker}")
    # Compute next version
    max_ver = conn.execute(
        "SELECT MAX(version) FROM investment_theses WHERE ticker=?",
        (ticker,),
    ).fetchone()[0] or 0
    new_version = max_ver  # draft may already be the max; just activate it
    now = time.time()
    conn.execute(
        """UPDATE investment_theses
           SET status='ACTIVE', approved_by='USER', approved_at=?,
               version=?, draft_json=?, summary=?
           WHERE id=?""",
        (now, new_version, final_draft_json,
         f"Active thesis for {ticker} (v{new_version})", draft["id"]),
    )
    conn.commit()
    conn.close()
    return draft["id"]


def create_thesis_change_proposal(
    ticker: str,
    claim_summary: str,
    proposed_change: dict,
    reason: str,
) -> int:
    """Create a THESIS_CHANGE_PROPOSAL recommendation. Agents must call this instead
    of writing directly to thesis_claims for ACTIVE theses."""
    payload = {
        "claim_summary": claim_summary,
        "proposed_change": proposed_change,
        "reason": reason,
    }
    return insert_recommendation(
        ticker=ticker,
        action="THESIS_CHANGE_PROPOSAL",
        action_payload=payload,
        priority="normal",
        why_now=reason,
        rationale=f"Proposed change to claim: {claim_summary}",
    )


def accept_thesis_change_proposal(recommendation_id: int) -> bool:
    """Apply a THESIS_CHANGE_PROPOSAL: update draft_json, increment version, record decision."""
    conn = _connect()
    rec = conn.execute(
        "SELECT * FROM recommendations WHERE id=? AND action='THESIS_CHANGE_PROPOSAL'",
        (recommendation_id,),
    ).fetchone()
    if not rec:
        conn.close()
        return False
    payload = json.loads(rec["action_payload_json"] or "{}")
    ticker = rec["ticker"]

    # Load active thesis
    thesis = conn.execute(
        "SELECT * FROM investment_theses WHERE ticker=? AND status='ACTIVE' "
        "ORDER BY version DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not thesis:
        conn.close()
        return False

    # Apply the change (proposed_change replaces the draft_json with updated claims)
    current_draft = json.loads(thesis["draft_json"] or "{}")
    proposed = payload.get("proposed_change", {})
    if "claims" in proposed:
        current_draft["claims"] = proposed["claims"]
    elif "claim_index" in proposed and "new_claim" in proposed:
        claims = current_draft.get("claims", [])
        idx = proposed["claim_index"]
        if 0 <= idx < len(claims):
            claims[idx] = proposed["new_claim"]
        current_draft["claims"] = claims

    new_version = thesis["version"] + 1
    now = time.time()
    conn.execute(
        """UPDATE investment_theses
           SET draft_json=?, version=?, summary=?
           WHERE id=?""",
        (json.dumps(current_draft), new_version,
         f"Active thesis for {ticker} (v{new_version})", thesis["id"]),
    )
    # Close the recommendation
    conn.execute(
        "UPDATE recommendations SET status='closed' WHERE id=?",
        (recommendation_id,),
    )
    # Record user decision
    conn.execute(
        """INSERT INTO user_decisions
           (recommendation_id, decision, reason_code, notes, decided_at)
           VALUES (?,?,?,?,?)""",
        (recommendation_id, "ACCEPT", "USER_APPROVED_THESIS_CHANGE",
         payload.get("reason"), now),
    )
    conn.commit()
    conn.close()
    return True


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_open_recommendations(ticker: str | None = None) -> list[dict]:
    conn = _connect()
    if ticker:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE status='open' AND ticker=? "
            "ORDER BY created_at DESC",
            (ticker,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE status='open' "
            "ORDER BY recommendation_score DESC, created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_thesis(ticker: str) -> dict | None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM investment_theses WHERE ticker=? "
        "ORDER BY version DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_runs(agent_type: str, ticker: str | None = None, limit: int = 10) -> list[dict]:
    conn = _connect()
    if ticker:
        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE agent_type=? AND ticker=? "
            "ORDER BY started_at DESC LIMIT ?",
            (agent_type, ticker, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE agent_type=? "
            "ORDER BY started_at DESC LIMIT ?",
            (agent_type, limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
