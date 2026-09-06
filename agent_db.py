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

# ── Canonical candidate_universe status values ────────────────────────────────
CAND_ACTIVE   = "active"
CAND_WATCH    = "watch"
CAND_OWNED    = "owned"
CAND_REJECTED = "rejected"
CAND_OPPORTUNITY_STATUSES = (CAND_ACTIVE, CAND_WATCH)  # statuses counted as alternatives


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

        CREATE TABLE IF NOT EXISTS spy_prices (
            day   TEXT PRIMARY KEY,
            price REAL NOT NULL
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

        CREATE TABLE IF NOT EXISTS candidate_decisions (
            id          INTEGER PRIMARY KEY,
            ticker      TEXT    NOT NULL,
            old_status  TEXT,
            new_status  TEXT    NOT NULL,
            actor       TEXT    NOT NULL DEFAULT 'user',
            reason      TEXT,
            notes       TEXT,
            decided_at  REAL    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_decisions_ticker
            ON candidate_decisions (ticker, decided_at DESC);

        CREATE TABLE IF NOT EXISTS recommendation_dependencies (
            id                  INTEGER PRIMARY KEY,
            recommendation_id   INTEGER NOT NULL REFERENCES recommendations(id),
            dependency_type     TEXT    NOT NULL,
            dependency_key      TEXT    NOT NULL,
            original_value      TEXT,
            tolerance           REAL,
            invalidating_event  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_rec_deps_rec
            ON recommendation_dependencies (recommendation_id);

        CREATE TABLE IF NOT EXISTS learned_preferences (
            id              INTEGER PRIMARY KEY,
            preference_key  TEXT    NOT NULL UNIQUE,
            scope           TEXT    NOT NULL DEFAULT 'global',
            value           REAL    NOT NULL,
            confidence      REAL    NOT NULL DEFAULT 0,
            sample_size     INTEGER NOT NULL DEFAULT 0,
            first_observed  TEXT    NOT NULL,
            last_updated    TEXT    NOT NULL,
            evidence_json   TEXT
        );

        CREATE TABLE IF NOT EXISTS preference_feedback (
            id              INTEGER PRIMARY KEY,
            preference_id   INTEGER NOT NULL REFERENCES learned_preferences(id),
            outcome         TEXT,
            suppressed      INTEGER NOT NULL DEFAULT 0,
            feedback_at     TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notification_events (
            id                INTEGER PRIMARY KEY,
            recommendation_id INTEGER NOT NULL REFERENCES recommendations(id),
            level             TEXT    NOT NULL,
            sent_at           REAL    NOT NULL,
            outcome           TEXT,
            time_to_action    REAL
        );

        CREATE INDEX IF NOT EXISTS idx_notif_events_rec
            ON notification_events (recommendation_id);
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
        # 0024 — NO_ACTION deduplication
        ("recommendations",   "input_hash",        "TEXT"),
        ("recommendations",   "updated_at",        "REAL"),
        # 0025 — dependency engine
        ("recommendations",   "superseded_reason", "TEXT"),
        # 0019 — sell/trim rationale class
        ("recommendations",   "rationale_class",   "TEXT"),
        # 0029 — recommendation lineage
        ("recommendations",          "supersedes_id",          "INTEGER"),
        ("recommendations",          "lineage_root_id",         "INTEGER"),
        # 0026 — counterfactual benchmarking
        ("recommendation_outcomes",  "horizon",                 "TEXT"),
        ("recommendation_outcomes",  "hold_return",             "REAL"),
        # 0028 — investor model
        ("learned_preferences",      "suppressed",              "INTEGER"),
        # 0023 — notification system
        ("recommendations",          "urgency_level",           "TEXT"),
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


def compute_urgency_level(
    action: str,
    recommendation_score: int = 50,
    valid_until: float | None = None,
) -> str:
    """Return URGENT / ATTENTION / INFORMATIONAL using the deterministic urgency formula.

    Urgency = TimeSensitivity × (score/100) × DecisionSeverity
    Thresholds and severity weights come from strategy_config (strategy.json).
    """
    if action == "NO_ACTION":
        return "INFORMATIONAL"
    try:
        from strategy_config import (
            URGENCY_URGENT_THRESHOLD,
            URGENCY_ATTENTION_THRESHOLD,
            URGENCY_SEVERITY,
        )
    except Exception:
        return "INFORMATIONAL"

    sev = URGENCY_SEVERITY.get(action, 0.3)

    if valid_until:
        days_left = (valid_until - time.time()) / 86400.0
        if days_left <= 1:
            ts = 1.0
        elif days_left <= 3:
            ts = 0.7
        elif days_left <= 7:
            ts = 0.4
        else:
            ts = 0.2
    else:
        ts = 0.2

    mat = min(1.0, max(0.0, (recommendation_score or 50) / 100.0))
    urgency = ts * mat * sev

    if urgency >= URGENCY_URGENT_THRESHOLD:
        return "URGENT"
    elif urgency >= URGENCY_ATTENTION_THRESHOLD:
        return "ATTENTION"
    return "INFORMATIONAL"


def record_notification_event(
    rec_id: int,
    level: str,
    outcome: str | None = None,
    time_to_action: float | None = None,
) -> None:
    conn = _connect()
    conn.execute(
        """INSERT INTO notification_events (recommendation_id, level, sent_at, outcome, time_to_action)
           VALUES (?, ?, ?, ?, ?)""",
        (rec_id, level, time.time(), outcome, time_to_action),
    )
    conn.commit()
    conn.close()


def close_notification_event(rec_id: int, outcome: str, decided_at: float) -> None:
    """Mark the most recent pending notification event for a rec as acted_on."""
    conn = _connect()
    row = conn.execute(
        """SELECT id, sent_at FROM notification_events
           WHERE recommendation_id=? AND outcome IS NULL
           ORDER BY sent_at DESC LIMIT 1""",
        (rec_id,),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE notification_events SET outcome=?, time_to_action=? WHERE id=?",
            (outcome, decided_at - row["sent_at"], row["id"]),
        )
        conn.commit()
    conn.close()


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
    input_hash: str | None = None,
    rationale_class: str | None = None,
) -> int:
    now = time.time()
    urgency = compute_urgency_level(action, recommendation_score, valid_until)
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO recommendations
           (run_id, ticker, action, action_payload_json, recommendation_score,
            confidence, priority, why_now, rationale, counter_case,
            no_action_case, status, valid_until, input_hash, updated_at,
            created_at, rationale_class, urgency_level)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, ticker, action,
         json.dumps(action_payload) if action_payload else None,
         recommendation_score, confidence, priority, why_now, rationale,
         counter_case, no_action_case, "open", valid_until,
         input_hash, now, now, rationale_class, urgency),
    )
    rec_id = cur.lastrowid
    conn.commit()
    if action != "NO_ACTION" and run_id is not None:
        _link_lineage(conn, rec_id, ticker, run_id)
        conn.commit()
    conn.close()
    return rec_id


def _link_lineage(conn: "sqlite3.Connection", rec_id: int, ticker: str, run_id: int) -> None:
    """Set supersedes_id/lineage_root_id on rec_id and mark the prior rec superseded."""
    run_row = conn.execute(
        "SELECT agent_type FROM agent_runs WHERE id=?", (run_id,)
    ).fetchone()
    if not run_row:
        return
    agent_type = run_row["agent_type"]
    prior = conn.execute(
        """SELECT r.id, r.lineage_root_id, r.status
           FROM recommendations r
           JOIN agent_runs ar ON ar.id = r.run_id
           WHERE r.ticker=? AND ar.agent_type=? AND r.action != 'NO_ACTION'
             AND r.id != ?
           ORDER BY r.created_at DESC LIMIT 1""",
        (ticker, agent_type, rec_id),
    ).fetchone()
    if not prior:
        return
    root_id = prior["lineage_root_id"] or prior["id"]
    conn.execute(
        "UPDATE recommendations SET supersedes_id=?, lineage_root_id=? WHERE id=?",
        (prior["id"], root_id, rec_id),
    )
    if prior["status"] == "open":
        conn.execute(
            "UPDATE recommendations SET status='superseded', updated_at=? WHERE id=?",
            (time.time(), prior["id"]),
        )


def compute_input_hash(
    ticker: str,
    agent_type: str,
    price: float,
    thesis_version: int,
    latest_quarter: str,
) -> str:
    """Deterministic 16-char hash of the evaluation state for deduplication.

    Price is bucketed in ~2% bands (log1p spacing) so minor tick movements
    don't invalidate the hash. Thesis version and earnings quarter changes
    always produce a new hash regardless of the 24h window.
    """
    import hashlib, math
    bucket = round(math.log(max(price, 0.001)) / math.log(1.02)) if price > 0 else 0
    raw = f"{ticker}|{agent_type}|{bucket}|{thesis_version}|{latest_quarter}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_thesis_version_for_hash(ticker: str) -> int:
    conn = _connect()
    row = conn.execute(
        "SELECT version FROM investment_theses WHERE ticker=? AND status='active' "
        "ORDER BY id DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _get_latest_quarter_for_hash(ticker: str) -> str:
    conn = _connect()
    row = conn.execute(
        "SELECT MAX(day) FROM holding_day WHERE ticker=?", (ticker,)
    ).fetchone()
    conn.close()
    return str(row[0]) if row and row[0] else ""


def upsert_no_action(
    ticker: str,
    agent_type: str,
    run_id: int,
    input_hash: str,
    why_now: str | None = None,
) -> int:
    """Insert a NO_ACTION recommendation, or update updated_at if identical state
    was already recorded within the last 24 hours.

    Returns the recommendation id (new or existing).
    """
    conn = _connect()
    now = time.time()
    cutoff = now - 86400  # 24 h window

    row = conn.execute(
        """SELECT id FROM recommendations
           WHERE ticker=? AND action='NO_ACTION' AND input_hash=?
             AND COALESCE(updated_at, created_at) > ?
           ORDER BY created_at DESC LIMIT 1""",
        (ticker, input_hash, cutoff),
    ).fetchone()

    if row:
        conn.execute(
            "UPDATE recommendations SET updated_at=? WHERE id=?", (now, row[0])
        )
        conn.commit()
        conn.close()
        return row[0]

    # New distinct-state record
    cur = conn.execute(
        """INSERT INTO recommendations
           (run_id, ticker, action, recommendation_score, confidence, priority,
            why_now, rationale, status, input_hash, updated_at, created_at)
           VALUES (?,?,'NO_ACTION',50,70,'low',?,?,'no_action',?,?,?)""",
        (
            run_id, ticker,
            why_now or f"Evaluated by {agent_type} — no action required.",
            f"{agent_type}: all checks passed.",
            input_hash, now, now,
        ),
    )
    rec_id = cur.lastrowid
    conn.commit()
    conn.close()
    return rec_id


def get_coverage() -> dict:
    """Per-ticker, per-agent-type last evaluation status.

    Returns:
        tickers: list of {ticker, agent_type, last_eval_ts, last_action,
                          days_since_eval, coverage_gap}
        no_action_count_24h: distinct tickers with a NO_ACTION in the last 24h
        coverage_gap_count:  tickers with no evaluation in > 7 days
    """
    conn = _connect()
    conn.row_factory = sqlite3.Row
    now = time.time()

    rows = conn.execute(
        """SELECT r.ticker,
                  ar.agent_type,
                  MAX(COALESCE(r.updated_at, r.created_at)) AS last_eval_ts,
                  r.action AS last_action
           FROM recommendations r
           JOIN agent_runs ar ON r.run_id = ar.id
           GROUP BY r.ticker, ar.agent_type
           ORDER BY r.ticker, ar.agent_type""",
    ).fetchall()

    no_action_24h = conn.execute(
        """SELECT COUNT(DISTINCT ticker) AS cnt
           FROM recommendations
           WHERE action='NO_ACTION'
             AND COALESCE(updated_at, created_at) > ?""",
        (now - 86400,),
    ).fetchone()["cnt"]

    conn.close()

    tickers = []
    gap_count = 0
    for r in rows:
        days = (now - r["last_eval_ts"]) / 86400 if r["last_eval_ts"] else None
        gap = days is not None and days > 7
        if gap:
            gap_count += 1
        tickers.append({
            "ticker":         r["ticker"],
            "agent_type":     r["agent_type"],
            "last_eval_ts":   r["last_eval_ts"],
            "last_action":    r["last_action"],
            "days_since_eval": round(days, 1) if days is not None else None,
            "coverage_gap":   gap,
        })

    return {
        "tickers":             tickers,
        "no_action_count_24h": no_action_24h,
        "coverage_gap_count":  gap_count,
    }


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
    horizon: str | None = None,
    hold_return: float | None = None,
) -> int:
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO recommendation_outcomes
           (recommendation_id, evaluation_date, benchmark_return, actual_return,
            recommended_path_return, opportunity_cost, notes, horizon, hold_return)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (recommendation_id, time.time(), benchmark_return, actual_return,
         recommended_path_return, opportunity_cost, notes, horizon, hold_return),
    )
    outcome_id = cur.lastrowid
    conn.commit()
    conn.close()
    return outcome_id


def upsert_spy_price(day: str, price: float) -> None:
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO spy_prices (day, price) VALUES (?,?)",
        (day, price),
    )
    conn.commit()
    conn.close()


def get_spy_prices(days: list[str]) -> dict[str, float]:
    """Return {date_str: price} for the requested dates that are stored."""
    if not days:
        return {}
    conn = _connect()
    placeholders = ",".join("?" * len(days))
    rows = conn.execute(
        f"SELECT day, price FROM spy_prices WHERE day IN ({placeholders})", days
    ).fetchall()
    conn.close()
    return {r["day"]: r["price"] for r in rows}


def get_outcome_alpha_stats() -> dict:
    """Aggregate agent alpha statistics across all matured outcome rows.

    Returns per-agent-type means for:
      agent_alpha_vs_hold  = recommended_path_return - hold_return   (B - C)
      agent_alpha_vs_spy   = recommended_path_return - benchmark_return (B - D)
      user_override_alpha  = actual_return - recommended_path_return  (A - B)

    Only rows where all three component returns are non-null are included.
    Groups: overall + per agent_type. Requires ≥ 1 matured horizon row.
    """
    conn = _connect()
    rows = conn.execute(
        """SELECT ar.agent_type, r.rationale_class,
                  ro.actual_return          AS a,
                  ro.recommended_path_return AS b,
                  ro.hold_return             AS c,
                  ro.benchmark_return        AS d
           FROM recommendation_outcomes ro
           JOIN recommendations r  ON r.id  = ro.recommendation_id
           LEFT JOIN agent_runs ar ON ar.id = r.run_id
           WHERE ro.horizon IS NOT NULL
             AND ro.recommended_path_return IS NOT NULL
             AND ro.hold_return             IS NOT NULL
             AND ro.benchmark_return        IS NOT NULL""",
    ).fetchall()
    conn.close()

    def _mean(vals):
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 4) if clean else None

    by_agent: dict[str, dict] = {}
    all_vs_hold, all_vs_spy, all_override = [], [], []

    for r in rows:
        b, c, d, a = r["b"], r["c"], r["d"], r["a"]
        vs_hold  = b - c if b is not None and c is not None else None
        vs_spy   = b - d if b is not None and d is not None else None
        override = a - b if a is not None and b is not None else None
        agent    = r["agent_type"] or "unknown"
        entry    = by_agent.setdefault(agent, {"vs_hold": [], "vs_spy": [], "override": [], "n": 0})
        entry["n"] += 1
        if vs_hold  is not None: entry["vs_hold"].append(vs_hold);   all_vs_hold.append(vs_hold)
        if vs_spy   is not None: entry["vs_spy"].append(vs_spy);     all_vs_spy.append(vs_spy)
        if override is not None: entry["override"].append(override); all_override.append(override)

    by_agent_out = {
        agent: {
            "n":                   v["n"],
            "agent_alpha_vs_hold": _mean(v["vs_hold"]),
            "agent_alpha_vs_spy":  _mean(v["vs_spy"]),
            "user_override_alpha": _mean(v["override"]),
        }
        for agent, v in by_agent.items()
    }

    return {
        "total_rows":          len(rows),
        "agent_alpha_vs_hold": _mean(all_vs_hold),
        "agent_alpha_vs_spy":  _mean(all_vs_spy),
        "user_override_alpha": _mean(all_override),
        "by_agent_type":       by_agent_out,
    }


def journal_summary() -> dict:
    """Aggregate counts by recommendation status + outcome alpha stats."""
    conn = _connect()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM recommendations GROUP BY status"
    ).fetchall()
    counts = {r["status"]: r["cnt"] for r in rows}
    total = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]

    opp = conn.execute(
        """SELECT COUNT(*) as n,
                  AVG(opportunity_cost) as avg_opp,
                  SUM(opportunity_cost) as total_opp
           FROM recommendation_outcomes
           WHERE opportunity_cost IS NOT NULL"""
    ).fetchone()
    matured_n = conn.execute(
        "SELECT COUNT(*) FROM recommendation_outcomes WHERE horizon IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    alpha_stats = get_outcome_alpha_stats() if matured_n >= 5 else None

    return {
        "total_generated":      total,
        "by_status":            counts,
        "outcomes_evaluated":   opp["n"] or 0,
        "avg_opportunity_cost": opp["avg_opp"],
        "total_opportunity_cost": opp["total_opp"],
        "matured_horizon_rows": matured_n,
        "alpha_stats":          alpha_stats,
    }


def update_journal_entry(rec_id: int, notes: str | None, reason_code: str | None) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT id FROM user_decisions WHERE recommendation_id=?", (rec_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    updates, vals = [], []
    if notes is not None:
        updates.append("notes=?"); vals.append(notes or None)
    if reason_code is not None:
        updates.append("reason_code=?"); vals.append(reason_code)
    if updates:
        vals.append(rec_id)
        conn.execute(
            f"UPDATE user_decisions SET {', '.join(updates)} WHERE recommendation_id=?",
            vals,
        )
        conn.commit()
    conn.close()
    return True


def list_journal_entries(limit: int = 200) -> list[dict]:
    """Return closed recommendations joined with user_decisions and outcomes."""
    conn = _connect()
    rows = conn.execute(
        """SELECT
               r.id, r.ticker, r.action, r.status, r.created_at,
               r.recommendation_score, r.confidence, r.why_now,
               r.action_payload_json, r.superseded_reason,
               ud.decision, ud.reason_code, ud.notes as decision_notes, ud.decided_at,
               ro.actual_return, ro.recommended_path_return, ro.opportunity_cost,
               ro.notes as outcome_notes
           FROM recommendations r
           LEFT JOIN user_decisions ud ON ud.recommendation_id = r.id
           LEFT JOIN recommendation_outcomes ro ON ro.recommendation_id = r.id
           WHERE r.status IN ('accepted','rejected','deferred','vetoed','superseded')
           ORDER BY COALESCE(ud.decided_at, r.created_at) DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Dependency engine ─────────────────────────────────────────────────────────

def write_dependencies(rec_id: int, deps: list[dict]) -> None:
    if not deps:
        return
    conn = _connect()
    for d in deps:
        conn.execute(
            """INSERT INTO recommendation_dependencies
               (recommendation_id, dependency_type, dependency_key,
                original_value, tolerance, invalidating_event)
               VALUES (?,?,?,?,?,?)""",
            (rec_id,
             d["dependency_type"],
             d["dependency_key"],
             str(d["original_value"]) if d.get("original_value") is not None else None,
             d.get("tolerance"),
             d.get("invalidating_event")),
        )
    conn.commit()
    conn.close()


def supersede_recommendation(rec_id: int, reason: str) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE recommendations SET status='superseded', superseded_reason=?, updated_at=? WHERE id=?",
        (reason, time.time(), rec_id),
    )
    conn.commit()
    conn.close()


def get_open_recs_with_deps() -> list[dict]:
    """Return open recommendations that have at least one dependency row."""
    conn = _connect()
    rows = conn.execute(
        """SELECT
               r.id, r.ticker, r.action, r.created_at,
               ar.agent_type,
               d.id as dep_id, d.dependency_type, d.dependency_key,
               d.original_value, d.tolerance, d.invalidating_event
           FROM recommendations r
           JOIN recommendation_dependencies d ON d.recommendation_id = r.id
           LEFT JOIN agent_runs ar ON ar.id = r.run_id
           WHERE r.status = 'open'
           ORDER BY r.id, d.id""",
    ).fetchall()
    conn.close()
    # Group by rec_id
    recs: dict[int, dict] = {}
    for row in rows:
        rid = row["id"]
        if rid not in recs:
            recs[rid] = {
                "id": rid,
                "ticker": row["ticker"],
                "action": row["action"],
                "created_at": row["created_at"],
                "agent_type": row["agent_type"],
                "deps": [],
            }
        recs[rid]["deps"].append({
            "dep_id": row["dep_id"],
            "dependency_type": row["dependency_type"],
            "dependency_key": row["dependency_key"],
            "original_value": row["original_value"],
            "tolerance": row["tolerance"],
            "invalidating_event": row["invalidating_event"],
        })
    return list(recs.values())


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

def log_candidate_decision(
    ticker: str,
    new_status: str,
    old_status: str | None = None,
    actor: str = "user",
    reason: str | None = None,
    notes: str | None = None,
) -> None:
    conn = _connect()
    conn.execute(
        """INSERT INTO candidate_decisions
               (ticker, old_status, new_status, actor, reason, notes, decided_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (ticker, old_status, new_status, actor, reason, notes, time.time()),
    )
    conn.commit()
    conn.close()


def get_candidate_history(ticker: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT id, ticker, old_status, new_status, actor, reason, notes, decided_at
           FROM candidate_decisions WHERE ticker=? ORDER BY decided_at DESC""",
        (ticker,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_candidate(
    ticker: str,
    source: str = "MANUAL",
    buffett_score: float | None = None,
    status: str = "active",
    notes: str | None = None,
    actor: str = "agent",
    reason: str | None = None,
) -> None:
    """Insert or update a candidate. Never overwrites `rejected` status on BUFFETT upserts."""
    conn = _connect()
    existing = conn.execute(
        "SELECT status FROM candidate_universe WHERE ticker=?", (ticker,)
    ).fetchone()
    old_status = existing[0] if existing else None
    if existing:
        if source == "BUFFETT":
            conn.execute(
                """UPDATE candidate_universe
                   SET source=?, buffett_score=?, added_at=CASE WHEN added_at IS NULL THEN ? ELSE added_at END
                   WHERE ticker=? AND status NOT IN ('rejected')""",
                (source, buffett_score, time.time(), ticker),
            )
        else:
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
    effective_status = status if (not existing or source != "BUFFETT") else old_status
    if old_status != effective_status or old_status is None:
        log_candidate_decision(
            ticker=ticker, new_status=effective_status, old_status=old_status,
            actor=actor, reason=reason or source, notes=notes,
        )


def set_candidate_status(
    ticker: str,
    status: str,
    notes: str | None = None,
    actor: str = "user",
    reason: str | None = None,
) -> None:
    conn = _connect()
    row = conn.execute(
        "SELECT status FROM candidate_universe WHERE ticker=?", (ticker,)
    ).fetchone()
    old_status = row[0] if row else None
    conn.execute(
        "UPDATE candidate_universe SET status=?, notes=COALESCE(?, notes) WHERE ticker=?",
        (status, notes, ticker),
    )
    conn.commit()
    conn.close()
    log_candidate_decision(
        ticker=ticker, new_status=status, old_status=old_status,
        actor=actor, reason=reason, notes=notes,
    )


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


_ACTION_SEVERITY: dict[str, int] = {
    "NO_ACTION": 0, "HOLD": 1, "REVIEW": 2,
    "TRIM": 3, "EXIT": 4, "ALLOCATE": 1,
    "REBALANCE": 2, "SELL_CC": 2,
    "TAX_HARVEST": 2, "TAX_SELL": 3,
}


def _compute_trend_note(conn: "sqlite3.Connection", ticker: str, agent_type: str) -> str | None:
    """Return an escalating-trend note if the last ≥3 recs show strictly increasing severity."""
    rows = conn.execute(
        """SELECT r.action FROM recommendations r
           JOIN agent_runs ar ON ar.id = r.run_id
           WHERE r.ticker=? AND ar.agent_type=? AND r.action != 'NO_ACTION'
           ORDER BY r.created_at DESC LIMIT 4""",
        (ticker, agent_type),
    ).fetchall()
    if len(rows) < 3:
        return None
    # rows are newest-first; reverse to get chronological order for the last 3+
    actions_asc = [r["action"] for r in reversed(rows)]
    severities = [_ACTION_SEVERITY.get(a, 0) for a in actions_asc]
    # Find longest trailing strictly-increasing run
    run = 1
    for i in range(len(severities) - 1, 0, -1):
        if severities[i] > severities[i - 1]:
            run += 1
        else:
            break
    if run < 3:
        return None
    chain = " → ".join(actions_asc[-run:])
    return f"Concern escalating over {run} assessments: {chain}"


def list_recommendations(status: str = "open") -> list[dict]:
    """Return recommendations filtered by status, with critic verdict, trend note, and preference fit."""
    conn = _connect()
    rows = conn.execute(
        """SELECT r.*, ar.agent_type
           FROM recommendations r
           LEFT JOIN agent_runs ar ON ar.id = r.run_id
           WHERE r.status=?
           ORDER BY r.recommendation_score DESC, r.created_at DESC""",
        (status,),
    ).fetchall()

    # Load preferences once for the whole batch
    pref_rows = conn.execute("SELECT * FROM learned_preferences WHERE COALESCE(suppressed, 0) = 0").fetchall()
    prefs = {r["preference_key"]: dict(r) for r in pref_rows}

    recs = []
    for row in rows:
        rec = dict(row)
        critic = conn.execute(
            "SELECT verdict, confidence_adjustment, strongest_objection FROM critic_reviews "
            "WHERE recommendation_id=? ORDER BY created_at DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        rec["critic_verdict"] = critic["verdict"] if critic else None
        rec["critic_confidence_adjustment"] = critic["confidence_adjustment"] if critic else None
        rec["critic_objection"] = critic["strongest_objection"] if critic else None
        if status == "open" and rec.get("agent_type"):
            rec["trend_note"] = _compute_trend_note(conn, row["ticker"], rec["agent_type"])
        else:
            rec["trend_note"] = None
        fit, pref_note = _compute_preference_fit(rec, prefs)
        rec["preference_fit"] = fit
        rec["preference_note"] = pref_note
        recs.append(rec)
    conn.close()
    return recs


def get_lineage(ticker: str) -> dict:
    """Return the full recommendation history for a ticker, grouped by agent_type.

    Each chain is sorted oldest-first and includes user decisions and critic verdicts.
    A trend_note is attached when ≥3 consecutive assessments show escalating severity.
    """
    conn = _connect()
    rows = conn.execute(
        """SELECT r.id, r.action, r.recommendation_score, r.confidence,
                  r.why_now, r.rationale, r.rationale_class, r.status,
                  r.supersedes_id, r.lineage_root_id, r.created_at,
                  ar.agent_type,
                  ud.decision, ud.decided_at, ud.notes AS decision_notes,
                  cr.verdict AS critic_verdict
           FROM recommendations r
           LEFT JOIN agent_runs ar ON ar.id = r.run_id
           LEFT JOIN user_decisions ud ON ud.recommendation_id = r.id
           LEFT JOIN critic_reviews cr ON cr.recommendation_id = r.id
           WHERE r.ticker=? AND r.action != 'NO_ACTION'
           ORDER BY r.created_at ASC""",
        (ticker,),
    ).fetchall()

    by_agent: dict[str, list[dict]] = {}
    for row in rows:
        agent = row["agent_type"] or "unknown"
        by_agent.setdefault(agent, []).append({
            "id":             row["id"],
            "action":         row["action"],
            "score":          row["recommendation_score"],
            "confidence":     row["confidence"],
            "why_now":        row["why_now"],
            "rationale":      row["rationale"],
            "rationale_class": row["rationale_class"],
            "status":         row["status"],
            "supersedes_id":  row["supersedes_id"],
            "created_at":     row["created_at"],
            "user_decision":  row["decision"],
            "decided_at":     row["decided_at"],
            "decision_notes": row["decision_notes"],
            "critic_verdict": row["critic_verdict"],
        })

    chains = []
    for agent_type, entries in by_agent.items():
        trend_note = _compute_trend_note(conn, ticker, agent_type)
        chains.append({
            "agent_type": agent_type,
            "entries":    entries,
            "trend_note": trend_note,
        })
    chains.sort(key=lambda c: c["entries"][-1]["created_at"] if c["entries"] else 0, reverse=True)
    conn.close()
    return {"ticker": ticker, "chains": chains}


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


# ── Preference learner DB helpers ─────────────────────────────────────────────

_MIN_PREF_SAMPLE = 5


def upsert_learned_preference(
    key: str,
    value: float,
    scope: str = "global",
    sample_size: int = 0,
    evidence: dict | None = None,
) -> None:
    """Insert or update a learned preference row."""
    import json as _json
    from datetime import date as _date
    today = _date.today().isoformat()
    confidence = 100.0 * sample_size / (sample_size + 10)
    evidence_json = _json.dumps(evidence) if evidence else None
    conn = _connect()
    conn.execute(
        """INSERT INTO learned_preferences
               (preference_key, scope, value, confidence, sample_size,
                first_observed, last_updated, evidence_json)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(preference_key) DO UPDATE SET
               scope=excluded.scope,
               value=excluded.value,
               confidence=excluded.confidence,
               sample_size=excluded.sample_size,
               last_updated=excluded.last_updated,
               evidence_json=excluded.evidence_json""",
        (key, scope, value, confidence, sample_size, today, today, evidence_json),
    )
    conn.commit()
    conn.close()


def get_learned_preferences() -> list[dict]:
    """Return all learned preference rows as dicts (including suppressed, for the UI)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM learned_preferences ORDER BY confidence DESC, preference_key"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_preference_feedback(
    pref_id: int,
    outcome: str | None,
    suppressed: bool = False,
) -> None:
    """Write a feedback row and optionally set suppressed on the preference."""
    from datetime import datetime as _dt
    conn = _connect()
    conn.execute(
        """INSERT INTO preference_feedback (preference_id, outcome, suppressed, feedback_at)
           VALUES (?, ?, ?, ?)""",
        (pref_id, outcome, 1 if suppressed else 0, _dt.utcnow().isoformat()),
    )
    if suppressed:
        conn.execute(
            "UPDATE learned_preferences SET suppressed = 1 WHERE id = ?",
            (pref_id,),
        )
    conn.commit()
    conn.close()


def _compute_preference_fit(
    rec: dict,
    prefs: dict[str, dict],
) -> tuple[int | None, str | None]:
    """Return (fit_score 0-100, note) given a rec and learned preferences dict.

    Returns (None, None) when the action has fewer than _MIN_PREF_SAMPLE decisions —
    no preference shown until we have enough data.
    Fit does NOT modify recommendation_score, confidence, or any evidence column.
    """
    import json as _json
    action = rec.get("action")
    rate_key = f"action_acceptance_rate.{action}"
    rate_pref = prefs.get(rate_key)
    if rate_pref is None or rate_pref["sample_size"] < _MIN_PREF_SAMPLE:
        return None, None

    base_fit = int(float(rate_pref["value"]) * 100)
    fit = base_fit

    if action == "SELL_CC":
        try:
            pl = _json.loads(rec.get("action_payload_json") or "{}") or {}
            adjustments: list[int] = []
            delta_pref = prefs.get("cc.preferred_delta")
            if (delta_pref and pl.get("delta") is not None
                    and delta_pref["sample_size"] >= _MIN_PREF_SAMPLE):
                dev = abs(float(pl["delta"]) - float(delta_pref["value"])) / max(abs(float(delta_pref["value"])), 0.01)
                adjustments.append(max(0, 100 - int(dev * 200)))
            dte_pref = prefs.get("cc.preferred_dte")
            if (dte_pref and pl.get("dte") is not None
                    and dte_pref["sample_size"] >= _MIN_PREF_SAMPLE):
                dev = abs(float(pl["dte"]) - float(dte_pref["value"])) / max(abs(float(dte_pref["value"])), 1.0)
                adjustments.append(max(0, 100 - int(dev * 100)))
            if adjustments:
                spec_fit = int(sum(adjustments) / len(adjustments))
                fit = int(0.5 * base_fit + 0.5 * spec_fit)
        except Exception:
            pass
    elif action in ("TRIM", "EXIT"):
        threshold_pref = prefs.get("sell.score_threshold")
        if threshold_pref and threshold_pref["sample_size"] >= _MIN_PREF_SAMPLE:
            score = rec.get("recommendation_score") or 50
            sell_fit = 80 if float(score) >= float(threshold_pref["value"]) else 30
            fit = int(0.5 * base_fit + 0.5 * sell_fit)

    fit = max(0, min(100, fit))

    note: str | None = None
    if fit < 40:
        action_label = action.replace("_", " ").title()
        note = (
            f"Low preference fit ({fit}) — you've historically accepted "
            f"{base_fit}% of {action_label} recommendations"
        )
    elif fit >= 75:
        note = f"Preference fit {fit} — consistent with your decision history"

    return fit, note


def update_recommendation(
    rec_id: int,
    confidence: int | None = None,
    status: str | None = None,
) -> None:
    """Patch confidence and/or status on an existing recommendation (used by Critic)."""
    if confidence is None and status is None:
        return
    conn = _connect()
    if confidence is not None and status is not None:
        conn.execute(
            "UPDATE recommendations SET confidence=?, status=? WHERE id=?",
            (confidence, status, rec_id),
        )
    elif confidence is not None:
        conn.execute(
            "UPDATE recommendations SET confidence=? WHERE id=?",
            (confidence, rec_id),
        )
    else:
        conn.execute(
            "UPDATE recommendations SET status=? WHERE id=?",
            (status, rec_id),
        )
    conn.commit()
    conn.close()


def list_open_unreviewed_recommendations() -> list[dict]:
    """Return open recommendations that have not yet received a critic review."""
    conn = _connect()
    rows = conn.execute(
        """SELECT r.* FROM recommendations r
           LEFT JOIN critic_reviews cr ON cr.recommendation_id = r.id
           WHERE r.status = 'open' AND cr.id IS NULL
           ORDER BY r.created_at ASC""",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_todays_findings() -> dict:
    """Return today's agent findings and all open recommendations for briefing synthesis.

    Returns:
        {
          "findings": {agent_type: [{"ticker", "finding_type", "severity",
                                     "confidence", "summary", "why_now"}, ...]},
          "recommendations": [{"ticker", "action", "score", "confidence",
                                "priority", "agent_type", "why_now", "rationale",
                                "counter_case", "critic_verdict",
                                "critic_objection", "critic_confidence_adj"}, ...]
        }
    """
    import time as _time
    from datetime import date as _date
    today_start = _time.mktime(_date.today().timetuple())
    today_end = today_start + 86400

    conn = _connect()

    finding_rows = conn.execute(
        """SELECT af.ticker, af.finding_type, af.severity, af.confidence,
                  af.summary, af.why_now, ar.agent_type
           FROM agent_findings af
           JOIN agent_runs ar ON ar.id = af.run_id
           WHERE af.created_at >= ? AND af.created_at < ?
           ORDER BY af.severity DESC, af.created_at DESC""",
        (today_start, today_end),
    ).fetchall()

    findings: dict = {}
    for r in finding_rows:
        agent = r["agent_type"] or "unknown"
        findings.setdefault(agent, []).append({
            "ticker": r["ticker"],
            "finding_type": r["finding_type"],
            "severity": r["severity"],
            "confidence": r["confidence"],
            "summary": r["summary"],
            "why_now": r["why_now"],
        })

    rec_rows = conn.execute(
        """SELECT r.ticker, r.action, r.recommendation_score, r.confidence,
                  r.priority, r.why_now, r.rationale, r.counter_case,
                  ar.agent_type,
                  cr.verdict, cr.confidence_adjustment, cr.strongest_objection
           FROM recommendations r
           LEFT JOIN agent_runs ar ON ar.id = r.run_id
           LEFT JOIN critic_reviews cr ON cr.recommendation_id = r.id
           WHERE r.status = 'open'
           ORDER BY r.recommendation_score DESC, r.created_at DESC""",
    ).fetchall()
    conn.close()

    recs = []
    for r in rec_rows:
        recs.append({
            "ticker": r["ticker"],
            "action": r["action"],
            "score": r["recommendation_score"],
            "confidence": r["confidence"],
            "priority": r["priority"],
            "agent_type": r["agent_type"],
            "why_now": r["why_now"],
            "rationale": r["rationale"],
            "counter_case": r["counter_case"],
            "critic_verdict": r["verdict"],
            "critic_objection": r["strongest_objection"],
            "critic_confidence_adj": r["confidence_adjustment"],
        })

    return {"findings": findings, "recommendations": recs}


def has_recent_user_decision(ticker: str, action: str, cooldown_days: int = 5) -> bool:
    """Return True if the user acted on a recommendation for this ticker+action
    within the last cooldown_days days, regardless of which agent produced it.
    Used to suppress re-recommendations when the user already decided and market
    conditions haven't materially changed (dependency invalidation handles that).
    """
    conn = _connect()
    cutoff = time.time() - cooldown_days * 86400
    row = conn.execute(
        """SELECT ud.id
           FROM user_decisions ud
           JOIN recommendations r ON r.id = ud.recommendation_id
           WHERE r.ticker = ? AND r.action = ? AND ud.decided_at >= ?
           LIMIT 1""",
        (ticker, action, cutoff),
    ).fetchone()
    conn.close()
    return row is not None


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
