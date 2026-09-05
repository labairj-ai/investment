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

        CREATE TABLE IF NOT EXISTS thesis_pillars (
            id                INTEGER PRIMARY KEY,
            thesis_id         INTEGER NOT NULL REFERENCES investment_theses(id),
            name              TEXT    NOT NULL,
            description       TEXT,
            importance        REAL    NOT NULL,
            critical          INTEGER NOT NULL DEFAULT 0,
            status            TEXT    NOT NULL DEFAULT 'UNKNOWN',
            score             REAL,
            confidence        REAL,
            last_evaluated_at REAL,
            reason            TEXT
        );

        CREATE TABLE IF NOT EXISTS thesis_metrics (
            id                  INTEGER PRIMARY KEY,
            pillar_id           INTEGER NOT NULL REFERENCES thesis_pillars(id),
            metric_key          TEXT    NOT NULL,
            direction           TEXT    NOT NULL,
            healthy_rule_json   TEXT,
            warning_rule_json   TEXT,
            violation_rule_json TEXT,
            persistence_periods INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS thesis_rules (
            id        INTEGER PRIMARY KEY,
            thesis_id INTEGER NOT NULL REFERENCES investment_theses(id),
            rule_type TEXT    NOT NULL,
            rule_json TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_thesis_pillars_thesis
            ON thesis_pillars (thesis_id);

        CREATE INDEX IF NOT EXISTS idx_thesis_metrics_pillar
            ON thesis_metrics (pillar_id);

        CREATE INDEX IF NOT EXISTS idx_thesis_rules_thesis_type
            ON thesis_rules (thesis_id, rule_type);

        CREATE INDEX IF NOT EXISTS idx_decisions_rec
            ON user_decisions (recommendation_id);

        CREATE INDEX IF NOT EXISTS idx_outcomes_rec
            ON recommendation_outcomes (recommendation_id);

        CREATE TABLE IF NOT EXISTS candidate_universe (
            ticker         TEXT PRIMARY KEY,
            source         TEXT NOT NULL DEFAULT 'MANUAL',
            added_at       REAL NOT NULL,
            buffett_score  REAL,
            status         TEXT NOT NULL DEFAULT 'active',
            notes          TEXT,
            last_evaluated REAL
        );
    """)
    conn.commit()

    # Add columns introduced after the initial schema (safe to re-run)
    _new_cols = [
        ("investment_theses", "approved_by",      "TEXT"),
        ("investment_theses", "intake_json",       "TEXT"),
        ("investment_theses", "draft_json",        "TEXT"),
        ("investment_theses", "portfolio_role",    "TEXT"),
        ("investment_theses", "thesis_summary",    "TEXT"),
        ("investment_theses", "holding_period",    "TEXT"),
        ("investment_theses", "conviction",        "INTEGER"),
        ("investment_theses", "target_weight_pct", "REAL"),
        ("investment_theses", "max_weight_pct",    "REAL"),
        ("investment_theses", "closed_reason",     "TEXT"),
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
    """Return the most recent thesis (any status) with parsed JSON fields and DB pillars."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM investment_theses WHERE ticker=? "
        "ORDER BY CASE WHEN status='DRAFT' THEN 1 ELSE 0 END DESC, id DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)
    for field in ("intake_json", "draft_json"):
        raw = result.get(field)
        if raw:
            try:
                result[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    db_pillars = conn.execute(
        "SELECT * FROM thesis_pillars WHERE thesis_id=? ORDER BY importance DESC",
        (row["id"],),
    ).fetchall()
    conn.close()
    result["db_pillars"] = [dict(p) for p in db_pillars]
    return result


def update_thesis_metadata(thesis_id: int, intake: dict) -> None:
    """Write intake-derived columns onto an approved investment_theses row."""
    _ROLE_MAP = {
        "STRUCTURAL_BALLAST": "STRUCTURAL_BALLAST",
        "CASH_FLOW":          "CASH_FLOW",
        "QUALITY_GROWTH":     "QUALITY_GROWTH",
        "ASYMMETRIC":         "ASYMMETRIC",
        "TACTICAL":           "TACTICAL",
        "Core":        "STRUCTURAL_BALLAST",
        "Income":      "CASH_FLOW",
        "Growth":      "QUALITY_GROWTH",
        "Speculative": "ASYMMETRIC",
        "Tactical":    "TACTICAL",
    }
    _PERIOD_MAP = {
        "<1_YEAR":      "<1_YEAR",
        "1_3_YEARS":    "1_3_YEARS",
        "3_5_YEARS":    "3_5_YEARS",
        "5_PLUS_YEARS": "5_PLUS_YEARS",
        "INDEFINITE":   "INDEFINITE",
        "< 1 year":   "<1_YEAR",
        "1–3 years":  "1_3_YEARS",
        "3–5 years":  "3_5_YEARS",
        "5+ years":   "5_PLUS_YEARS",
        "Indefinite": "INDEFINITE",
    }
    conn = _connect()
    conn.execute(
        """UPDATE investment_theses
           SET portfolio_role=?, holding_period=?, conviction=?,
               max_weight_pct=?, thesis_summary=?
           WHERE id=?""",
        (
            _ROLE_MAP.get(intake.get("role", ""), intake.get("role")),
            _PERIOD_MAP.get(intake.get("period", ""), intake.get("period")),
            intake.get("conviction"),
            intake.get("max_pct"),
            intake.get("why"),
            thesis_id,
        ),
    )
    conn.commit()
    conn.close()


def get_thesis_history(ticker: str) -> list[dict]:
    """Return all thesis versions for a ticker, newest first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, version, status, approved_at, closed_at, approved_by, summary "
        "FROM investment_theses WHERE ticker=? ORDER BY version DESC",
        (ticker,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_thesis(ticker: str, final_draft_json: str) -> int:
    """Activate the current DRAFT, superseding any prior ACTIVE thesis."""
    conn = _connect()
    # Record the current max approved version before superseding
    prior_max = conn.execute(
        "SELECT MAX(version) FROM investment_theses WHERE ticker=? AND status='ACTIVE'",
        (ticker,),
    ).fetchone()[0] or 0
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
    new_version = prior_max + 1
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


def insert_thesis_pillar(
    thesis_id: int,
    name: str,
    importance: float,
    *,
    description: str | None = None,
    critical: bool = False,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO thesis_pillars
           (thesis_id, name, description, importance, critical)
           VALUES (?,?,?,?,?)""",
        (thesis_id, name, description, importance, int(critical)),
    )
    conn.commit()
    pillar_id = cur.lastrowid
    conn.close()
    return pillar_id


def insert_thesis_metric(
    pillar_id: int,
    metric_key: str,
    direction: str,
    *,
    healthy_rule_json: str | None = None,
    warning_rule_json: str | None = None,
    violation_rule_json: str | None = None,
    persistence_periods: int = 1,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO thesis_metrics
           (pillar_id, metric_key, direction,
            healthy_rule_json, warning_rule_json, violation_rule_json,
            persistence_periods)
           VALUES (?,?,?,?,?,?,?)""",
        (pillar_id, metric_key, direction,
         healthy_rule_json, warning_rule_json, violation_rule_json,
         persistence_periods),
    )
    conn.commit()
    metric_id = cur.lastrowid
    conn.close()
    return metric_id


def insert_thesis_rule(thesis_id: int, rule_type: str, rule_json: str) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO thesis_rules (thesis_id, rule_type, rule_json) VALUES (?,?,?)",
        (thesis_id, rule_type, rule_json),
    )
    conn.commit()
    rule_id = cur.lastrowid
    conn.close()
    return rule_id


def update_pillar_status(
    pillar_id: int,
    status: str,
    score: float | None,
    confidence: float | None,
    reason: str | None,
) -> None:
    conn = _connect()
    conn.execute(
        """UPDATE thesis_pillars
           SET status=?, score=?, confidence=?, reason=?, last_evaluated_at=?
           WHERE id=?""",
        (status, score, confidence, reason, time.time(), pillar_id),
    )
    conn.commit()
    conn.close()


def get_thesis_pillars(thesis_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM thesis_pillars WHERE thesis_id=? ORDER BY importance DESC",
        (thesis_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_thesis_metrics(pillar_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM thesis_metrics WHERE pillar_id=?",
        (pillar_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_thesis_rules(thesis_id: int, rule_type: str | None = None) -> list[dict]:
    conn = _connect()
    if rule_type:
        rows = conn.execute(
            "SELECT * FROM thesis_rules WHERE thesis_id=? AND rule_type=?",
            (thesis_id, rule_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM thesis_rules WHERE thesis_id=?",
            (thesis_id,),
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
    if not row:
        conn.close()
        return None
    result = dict(row)

    pillars = conn.execute(
        "SELECT * FROM thesis_pillars WHERE thesis_id=? ORDER BY importance DESC",
        (row["id"],),
    ).fetchall()
    conn.close()

    result["pillars"] = [dict(p) for p in pillars]

    scored = [p for p in pillars if p["score"] is not None]
    if scored:
        total_weight = sum(p["importance"] for p in scored)
        if total_weight > 0:
            result["health_score"] = round(
                sum(p["importance"] * p["score"] for p in scored) / total_weight, 1
            )
    result["has_critical_violation"] = any(
        p["critical"] and p["status"] == "VIOLATED" for p in pillars
    )

    return result


def get_active_thesis(ticker: str) -> dict | None:
    """Return the ACTIVE thesis for a ticker with pillars, or None."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM investment_theses WHERE ticker=? AND status='ACTIVE' "
        "ORDER BY version DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)
    pillars = conn.execute(
        "SELECT * FROM thesis_pillars WHERE thesis_id=? ORDER BY importance DESC",
        (row["id"],),
    ).fetchall()
    conn.close()
    result["pillars"] = [dict(p) for p in pillars]
    return result


# ── Candidate universe ────────────────────────────────────────────────────────

def upsert_candidate(
    ticker: str,
    source: str = "MANUAL",
    buffett_score: float | None = None,
    status: str = "active",
    notes: str | None = None,
) -> None:
    """Insert or update a candidate. Never overwrites `rejected` status on BUFFETT upserts."""
    conn = _connect()
    existing = conn.execute(
        "SELECT status FROM candidate_universe WHERE ticker=?", (ticker,)
    ).fetchone()
    if existing:
        current_status = existing[0]
        # BUFFETT upserts: preserve rejected/owned/watch — only refresh score + source
        if source == "BUFFETT":
            conn.execute(
                """UPDATE candidate_universe
                   SET source=?, buffett_score=?, added_at=CASE WHEN added_at IS NULL THEN ? ELSE added_at END
                   WHERE ticker=? AND status NOT IN ('rejected')""",
                (source, buffett_score, time.time(), ticker),
            )
        else:
            # MANUAL re-add: refresh everything, keep existing rejected note if desired
            conn.execute(
                """UPDATE candidate_universe
                   SET source=?, status=?, notes=COALESCE(?, notes), added_at=?
                   WHERE ticker=?""",
                (source, status, notes, time.time(), ticker),
            )
    else:
        conn.execute(
            """INSERT INTO candidate_universe (ticker, source, added_at, buffett_score, status, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticker, source, time.time(), buffett_score, status, notes),
        )
    conn.commit()
    conn.close()


def set_candidate_status(ticker: str, status: str, notes: str | None = None) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE candidate_universe SET status=?, notes=COALESCE(?, notes) WHERE ticker=?",
        (status, notes, ticker),
    )
    conn.commit()
    conn.close()


def get_candidates(include_rejected: bool = False) -> list[dict]:
    """Return candidates ordered by buffett_score DESC, added_at DESC."""
    conn = _connect()
    if include_rejected:
        rows = conn.execute(
            "SELECT * FROM candidate_universe ORDER BY buffett_score DESC NULLS LAST, added_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM candidate_universe WHERE status != 'rejected' "
            "ORDER BY buffett_score DESC NULLS LAST, added_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sync_owned_candidates(holdings_tickers: list[str]) -> None:
    """Set status=owned for held tickers; revert previously-owned-but-sold back to active."""
    held = set(t.upper() for t in holdings_tickers)
    conn = _connect()
    # Mark held tickers as owned
    for ticker in held:
        conn.execute(
            "UPDATE candidate_universe SET status='owned' WHERE ticker=? AND status != 'rejected'",
            (ticker,),
        )
    # Revert previously owned tickers no longer in holdings back to active
    conn.execute(
        f"UPDATE candidate_universe SET status='active' WHERE status='owned' "
        f"AND ticker NOT IN ({','.join('?' for _ in held)})",
        list(held) if held else [],
    )
    conn.commit()
    conn.close()


def mark_candidate_evaluated(ticker: str) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE candidate_universe SET last_evaluated=? WHERE ticker=?",
        (time.time(), ticker),
    )
    conn.commit()
    conn.close()


def list_runs(agent_type: str | None = None, limit: int = 20) -> list[dict]:
    """Return recent agent runs, optionally filtered by agent_type."""
    conn = _connect()
    if agent_type:
        rows = conn.execute(
            "SELECT id, agent_type, scope, ticker, trigger_type, status, "
            "started_at, finished_at, error FROM agent_runs "
            "WHERE agent_type=? ORDER BY started_at DESC LIMIT ?",
            (agent_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, agent_type, scope, ticker, trigger_type, status, "
            "started_at, finished_at, error FROM agent_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run_full(run_id: int) -> dict | None:
    """Return a run row plus all its findings."""
    conn = _connect()
    row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)
    findings = conn.execute(
        "SELECT * FROM agent_findings WHERE run_id=? ORDER BY id",
        (run_id,),
    ).fetchall()
    conn.close()
    result["findings"] = [dict(f) for f in findings]
    return result


def get_recommendation_full(rec_id: int) -> dict | None:
    """Return a recommendation row with its latest critic review attached."""
    conn = _connect()
    row = conn.execute("SELECT * FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)
    critic = conn.execute(
        "SELECT * FROM critic_reviews WHERE recommendation_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (rec_id,),
    ).fetchone()
    result["critic_review"] = dict(critic) if critic else None
    conn.close()
    return result


def list_recommendations(status: str = "open") -> list[dict]:
    """Return recommendations filtered by status, with critic verdict attached."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM recommendations WHERE status=? "
        "ORDER BY recommendation_score DESC, created_at DESC",
        (status,),
    ).fetchall()
    recs = []
    for row in rows:
        rec = dict(row)
        critic = conn.execute(
            "SELECT verdict, confidence_adjustment FROM critic_reviews "
            "WHERE recommendation_id=? ORDER BY created_at DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        rec["critic_verdict"] = critic["verdict"] if critic else None
        rec["critic_confidence_adjustment"] = critic["confidence_adjustment"] if critic else None
        recs.append(rec)
    conn.close()
    return recs


def close_recommendation(rec_id: int, status: str) -> bool:
    """Set recommendation status (e.g. 'accepted', 'rejected', 'deferred').
    Returns False if the recommendation doesn't exist."""
    conn = _connect()
    cur = conn.execute(
        "UPDATE recommendations SET status=? WHERE id=?",
        (status, rec_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


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
