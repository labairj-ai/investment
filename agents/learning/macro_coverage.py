"""Candidate collection and supplemental certification under accepted contracts."""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from .macro_provenance import DIMS, accepted_contract, canonical, digest


def migrate(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS macro_candidate_scoring_runs (
      run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at REAL NOT NULL,
      completed_at REAL, expected_n INTEGER NOT NULL, scored_n INTEGER NOT NULL DEFAULT 0,
      failed_n INTEGER NOT NULL DEFAULT 0, scorer_contract_hash TEXT NOT NULL,
      acceptance_id TEXT NOT NULL, universe_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS macro_candidate_scoring_run_items (
      run_id TEXT NOT NULL, ticker TEXT NOT NULL, status TEXT NOT NULL,
      scorer_contract_hash TEXT NOT NULL, completed_at TEXT, error TEXT,
      PRIMARY KEY(run_id,ticker)
    );
    CREATE TABLE IF NOT EXISTS macro_candidate_scores (
      ticker TEXT PRIMARY KEY, scores TEXT NOT NULL, updated_at TEXT NOT NULL,
      run_id TEXT NOT NULL, score_id TEXT NOT NULL, evidence_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS macro_candidate_score_history (
      score_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, scores TEXT NOT NULL,
      scored_at TEXT NOT NULL, run_id TEXT NOT NULL, evidence_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS macro_coverage_certifications (
      certification_id TEXT PRIMARY KEY, acceptance_record_id TEXT NOT NULL,
      scorer_contract_hash TEXT NOT NULL, config_hash TEXT NOT NULL,
      model_identity TEXT NOT NULL, started_at REAL NOT NULL, certified_at REAL NOT NULL,
      status TEXT NOT NULL, artifact_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS macro_coverage_validation (
      certification_id TEXT NOT NULL REFERENCES macro_coverage_certifications(certification_id),
      acceptance_record_id TEXT NOT NULL, ticker TEXT NOT NULL, dimension TEXT NOT NULL,
      stability_class TEXT NOT NULL, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
      n_samples INTEGER NOT NULL, mean_score REAL, stddev REAL,
      scorer_contract_hash TEXT NOT NULL, config_hash TEXT NOT NULL,
      model_identity TEXT NOT NULL, prompt_hash TEXT NOT NULL, evidence_hash TEXT NOT NULL,
      certified_at REAL NOT NULL, PRIMARY KEY(certification_id,ticker,dimension)
    );
    CREATE INDEX IF NOT EXISTS idx_macro_coverage_lookup ON macro_coverage_validation(acceptance_record_id,ticker,dimension,certified_at);
    """)
    for table in ("macro_candidate_score_history", "macro_coverage_certifications", "macro_coverage_validation"):
        for operation in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} "
                         "BEGIN SELECT RAISE(ABORT, 'immutable macro coverage record'); END")
    conn.commit()


def coverage_row(conn, acceptance, ticker, dim, at):
    """Supplemental eligibility never falls back to mutable runtime stability."""
    try:
        return conn.execute("""SELECT v.eligible,v.config_hash,v.scorer_contract_hash,v.n_samples,
                    v.model_identity,v.certification_id,v.certified_at
             FROM macro_coverage_validation v JOIN macro_coverage_certifications c USING(certification_id)
             WHERE v.acceptance_record_id=? AND v.ticker=? AND v.dimension=?
               AND v.certified_at<=? AND c.certified_at<=? AND c.status='COMPLETE'
               AND v.scorer_contract_hash=? AND v.config_hash=? AND v.model_identity=?
               AND c.acceptance_record_id=v.acceptance_record_id
               AND c.scorer_contract_hash=v.scorer_contract_hash AND c.config_hash=v.config_hash
               AND c.model_identity=v.model_identity
             ORDER BY v.certified_at DESC,v.certification_id DESC LIMIT 1""",
             (acceptance["record_id"], ticker, dim, at, at, acceptance["scorer_contract_hash"],
              acceptance["config_hash"], acceptance["model_identity"])).fetchone()
    except sqlite3.OperationalError:
        return None


def _current(conn, expected):
    current = accepted_contract(conn, time.time())
    if current != expected:
        raise ValueError("accepted scorer changed during collection/certification")


def score_candidates(conn, tickers):
    """Crash-safe separate collection ledger; no acceptance or eligibility writes."""
    import portfolio_ai as pai
    from scripts.validate_macro_scorer import _freeze_validation_evidence, _score_one_ticker
    acceptance = accepted_contract(conn, time.time())
    if not acceptance:
        raise ValueError("no current accepted scorer")
    tickers = sorted(set(tickers))
    if not tickers or any(pai.is_fund(t) for t in tickers):
        raise ValueError("candidate collection requires company tickers")
    run_id = str(uuid.uuid4())
    conn.execute("INSERT INTO macro_candidate_scoring_runs VALUES (?,?,?,NULL,?,0,0,?,?,?)",
                 (run_id, "STARTED", time.time(), len(tickers), acceptance["scorer_contract_hash"], acceptance["record_id"], canonical(tickers)))
    conn.executemany("INSERT INTO macro_candidate_scoring_run_items VALUES (?,?, 'PENDING',?,NULL,NULL)",
                     [(run_id, t, acceptance["scorer_contract_hash"]) for t in tickers])
    conn.commit()
    try:
        for ticker in tickers:
            try:
                frozen = _freeze_validation_evidence([ticker], conn)[ticker]
                score = _score_one_ticker(ticker, frozen["evidence"], frozen["betas"])
                if score is None:
                    raise ValueError("canonical scorer returned no valid response")
                _current(conn, acceptance)
                completed = datetime.now(timezone.utc).isoformat()
                score.update({k: v for k, v in frozen["evidence"].items() if k.startswith("evidence_quality")})
                score.update(scorer_contract_hash=acceptance["scorer_contract_hash"],
                             model_version=acceptance["model_identity"], prompt_hash=frozen["prompt_hash"],
                             evidence_hash=frozen["evidence_hash"], evidence_schema_version=pai.MACRO_EVIDENCE_SCHEMA_VERSION,
                             run_id=run_id, scored_at=completed)
                payload, evidence = canonical(score), canonical(frozen)
                sid = str(uuid.uuid4())
                with conn:
                    conn.execute("INSERT INTO macro_candidate_score_history VALUES (?,?,?,?,?,?)", (sid, ticker, payload, completed, run_id, evidence))
                    conn.execute("INSERT INTO macro_candidate_scores VALUES (?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
                                 "scores=excluded.scores,updated_at=excluded.updated_at,run_id=excluded.run_id,score_id=excluded.score_id,evidence_json=excluded.evidence_json",
                                 (ticker, payload, completed, run_id, sid, evidence))
                    conn.execute("UPDATE macro_candidate_scoring_run_items SET status='SUPPORTED',completed_at=? WHERE run_id=? AND ticker=?", (completed, run_id, ticker))
                    conn.execute("UPDATE macro_candidate_scoring_runs SET scored_n=scored_n+1 WHERE run_id=?", (run_id,))
            except Exception as exc:
                with conn:
                    conn.execute("UPDATE macro_candidate_scoring_run_items SET status='FAILED',completed_at=?,error=? WHERE run_id=? AND ticker=?",
                                 (datetime.now(timezone.utc).isoformat(), str(exc), run_id, ticker))
                    conn.execute("UPDATE macro_candidate_scoring_runs SET failed_n=failed_n+1 WHERE run_id=?", (run_id,))
    finally:
        with conn:
            # Interrupted pending items are failures, never silently successful.
            pending = conn.execute("SELECT COUNT(*) FROM macro_candidate_scoring_run_items WHERE run_id=? AND status='PENDING'", (run_id,)).fetchone()[0]
            conn.execute("UPDATE macro_candidate_scoring_run_items SET status='FAILED',completed_at=?,error='collection interrupted' WHERE run_id=? AND status='PENDING'",
                         (datetime.now(timezone.utc).isoformat(), run_id))
            conn.execute("UPDATE macro_candidate_scoring_runs SET failed_n=failed_n+?,completed_at=?,status=CASE WHEN failed_n+?=0 THEN 'COMPLETE' ELSE 'FAILED' END WHERE run_id=?",
                         (pending, time.time(), pending, run_id))
    return run_id


def reconcile_runs(conn, before):
    """Explicit stale-run recovery after process loss; callers must hold collector lock."""
    for row in conn.execute("SELECT run_id FROM macro_candidate_scoring_runs WHERE status='STARTED' AND started_at<?", (before,)).fetchall():
        run_id = row[0]
        conn.execute("UPDATE macro_candidate_scoring_run_items SET status='FAILED',completed_at=?,error='process lost' WHERE run_id=? AND status='PENDING'",
                     (datetime.now(timezone.utc).isoformat(), run_id))
        failed = conn.execute("SELECT COUNT(*) FROM macro_candidate_scoring_run_items WHERE run_id=? AND status='FAILED'", (run_id,)).fetchone()[0]
        scored = conn.execute("SELECT COUNT(*) FROM macro_candidate_scoring_run_items WHERE run_id=? AND status='SUPPORTED'", (run_id,)).fetchone()[0]
        conn.execute("UPDATE macro_candidate_scoring_runs SET status='FAILED',failed_n=?,scored_n=?,completed_at=? WHERE run_id=?", (failed, scored, time.time(), run_id))
    conn.commit()


def certify(conn, tickers):
    """Use accepted frozen-input N=20 machinery without activating acceptance."""
    import portfolio_ai as pai
    from scripts.validate_macro_scorer import _freeze_validation_evidence, run_repeatability
    acceptance = accepted_contract(conn, time.time())
    if not acceptance:
        raise ValueError("no current accepted scorer")
    artifact = json.loads(conn.execute("SELECT artifact_json FROM macro_validation_runs WHERE record_id=?", (acceptance["record_id"],)).fetchone()[0])
    config = artifact["config_used"]
    if config["n_repeats"] != 20:
        raise ValueError("coverage requires formal N=20 policy")
    tickers = sorted(set(tickers))
    if not tickers or any(pai.is_fund(t) for t in tickers):
        raise ValueError("coverage requires company tickers")
    cid, started = str(uuid.uuid4()), time.time()
    frozen = _freeze_validation_evidence(tickers, conn)
    results = run_repeatability(tickers, {}, n=20, evidence_snapshot=frozen,
                               same_input_score_max_range=config["thresholds"]["same_input_score_max_range"],
                               stability_policy=config["stability_policy"])
    _current(conn, acceptance)
    complete = all(results[t][d]["n"] == 20 for t in tickers for d in DIMS)
    completed = time.time()
    record = {"certification_id": cid, "acceptance": acceptance, "frozen": frozen,
              "results": results, "config": config, "evidence_schema_version": pai.MACRO_EVIDENCE_SCHEMA_VERSION}
    with conn:
        conn.execute("INSERT INTO macro_coverage_certifications VALUES (?,?,?,?,?,?,?,?,?)",
                     (cid, acceptance["record_id"], acceptance["scorer_contract_hash"], acceptance["config_hash"],
                      acceptance["model_identity"], started, completed, "COMPLETE" if complete else "FAILED", canonical(record)))
        for ticker in tickers:
            for dim in DIMS:
                r = results[ticker][dim]
                state = pai._dimension_validation_state(r, config)
                conn.execute("INSERT INTO macro_coverage_validation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, acceptance["record_id"], ticker, dim, state["stability_class"],
                              int(complete and state["eligible"]), r["n"], r["mean"], r["stdev"],
                              acceptance["scorer_contract_hash"], acceptance["config_hash"], acceptance["model_identity"],
                              frozen[ticker]["prompt_hash"], frozen[ticker]["evidence_hash"], completed))
    return cid


def preparation_targets():
    """Read current opportunity inputs without capturing episodes or recommendations."""
    from agents import opportunity_agent as oa
    from agents.opportunity_config import MIN_COMPOSITE
    from .macro_experiment import load_protocol
    winners = oa._get_buffett_winners()
    names = {w["ticker"] for w in winners}
    winners += [w for w in oa._get_manual_candidates() if w["ticker"] not in names]
    held, weights = oa._get_current_tickers(), oa._get_layer_weights()
    sectors = oa._get_holding_sectors(held)
    scored = []
    for w in winners:
        if w["ticker"] in held:
            continue
        fit, _ = oa._score_portfolio_fit(w, held, weights, sectors)
        base = oa._composite(oa._score_quality(w), oa._score_valuation(w), fit, oa._score_catalyst(w), oa._score_evidence(w))
        if base >= MIN_COMPOSITE:
            scored.append({"ticker": w["ticker"], "base_score": base})
    maximum = max((r["base_score"] for r in scored), default=None)
    cap = load_protocol()["adjustment_cap"]
    envelope = [r for r in scored if r["base_score"] >= maximum - 2 * cap]
    return {"prepared_at": time.time(), "base_max": maximum, "cap": cap, "eligible_n": len(scored), "envelope": envelope}
