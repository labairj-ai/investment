"""Prospective paired macro ranking experiment. No recommendation/execution writes."""
from __future__ import annotations

import inspect
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .macro_provenance import DIMS, ET, accepted_contract, canonical, digest

PROTOCOL_PATH = Path(__file__).resolve().parents[2] / "config" / "macro_experiment_v1.json"


def migrate(conn):
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS macro_experiment_epochs (
        epoch_id TEXT PRIMARY KEY, registered_at REAL NOT NULL,
        acceptance_id TEXT NOT NULL, scorer_contract_hash TEXT NOT NULL,
        macro_config_version TEXT NOT NULL, macro_config_hash TEXT NOT NULL,
        protocol_hash TEXT NOT NULL, protocol_json TEXT NOT NULL,
        base_contract_hash TEXT NOT NULL, acceptance_json TEXT NOT NULL,
        code_commit_sha TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS macro_experiment_cohorts (
        cohort_id TEXT PRIMARY KEY, epoch_id TEXT NOT NULL REFERENCES macro_experiment_epochs(epoch_id),
        agent_run_id TEXT NOT NULL, captured_at REAL NOT NULL, decision_date TEXT NOT NULL,
        universe_hash TEXT NOT NULL, candidate_n INTEGER NOT NULL, eligible_n INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('OBSERVED','EXCLUDED')), exclusion_reason TEXT,
        control_episode_id TEXT REFERENCES decision_episodes(episode_id),
        macro_episode_id TEXT REFERENCES decision_episodes(episode_id),
        control_ticker TEXT, macro_ticker TEXT, control_score REAL, macro_score REAL,
        diverged INTEGER NOT NULL CHECK(diverged IN (0,1)),
        dimensions_json TEXT NOT NULL, regime TEXT NOT NULL, regime_json TEXT NOT NULL,
        book_status TEXT NOT NULL, created_at REAL NOT NULL,
        UNIQUE(epoch_id,agent_run_id)
      );
      CREATE TABLE IF NOT EXISTS macro_experiment_candidates (
        cohort_id TEXT NOT NULL REFERENCES macro_experiment_cohorts(cohort_id),
        episode_id TEXT NOT NULL REFERENCES decision_episodes(episode_id), ticker TEXT NOT NULL,
        base_score REAL NOT NULL, macro_score REAL NOT NULL, adjustment REAL NOT NULL,
        risk_eligible INTEGER NOT NULL, evidence_json TEXT NOT NULL, evidence_hash TEXT NOT NULL,
        macro_snapshot TEXT NOT NULL, sector TEXT, price REAL,
        PRIMARY KEY(cohort_id,ticker), UNIQUE(cohort_id,episode_id)
      );
      CREATE TABLE IF NOT EXISTS macro_experiment_labels (
        cohort_id TEXT NOT NULL REFERENCES macro_experiment_cohorts(cohort_id),
        horizon TEXT NOT NULL, horizon_version TEXT NOT NULL, matured_at REAL NOT NULL,
        control_outcome_id INTEGER NOT NULL, macro_outcome_id INTEGER NOT NULL,
        delta_alpha REAL NOT NULL, delta_mfe REAL, delta_mae REAL,
        control_alpha REAL NOT NULL, macro_alpha REAL NOT NULL,
        control_mae REAL, macro_mae REAL,
        PRIMARY KEY(cohort_id,horizon,horizon_version)
      );
      CREATE INDEX IF NOT EXISTS idx_macro_cohorts_epoch_date ON macro_experiment_cohorts(epoch_id,decision_date);
    """)
    for table in ("macro_experiment_epochs", "macro_experiment_cohorts", "macro_experiment_candidates", "macro_experiment_labels"):
        for operation in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} "
                         f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable macro experiment record'); END")
    # Existing capture attaches the snapshot once, in the insert transaction.
    conn.executescript("""
      CREATE TRIGGER IF NOT EXISTS immutable_episode_macro
      BEFORE UPDATE OF macro_snapshot,macro_acceptance_record_id,macro_scorer_contract_hash,
          macro_config_version,macro_score_timestamp,macro_prompt_hash,macro_evidence_hash,
          macro_usable_dimensions,macro_coverage_state,macro_epoch ON decision_episodes
      WHEN OLD.macro_snapshot IS NOT NULL AND OLD.macro_epoch IS NOT NULL
      BEGIN SELECT RAISE(ABORT, 'immutable episode macro snapshot'); END;
    """)
    conn.commit()


def load_protocol():
    p = json.loads(PROTOCOL_PATH.read_text())
    if p["mode"] != "observe_only" or p["horizon_version"] != "sessions_v2":
        raise ValueError("macro experiment requires observe-only/session-based protocol")
    if not 0 < p["adjustment_cap"] <= 5 or set(p["dimension_weights"]) != set(DIMS):
        raise ValueError("invalid macro adjustment policy")
    return p


def base_contract():
    from agents import opportunity_agent as oa
    from . import book_simulator as books
    from agents.opportunity_config import COMPOSITE_WEIGHTS, MIN_COMPOSITE
    from . import macro_provenance, book_mtm
    functions = (oa._score_quality, oa._score_valuation, oa._score_portfolio_fit,
                 oa._score_catalyst, oa._score_evidence, oa._composite, books._record_one_book)
    return digest({"source": [inspect.getsource(f) for f in functions],
                   "weights": COMPOSITE_WEIGHTS, "min_composite": MIN_COMPOSITE,
                   "slippage": books._DEFAULT_SLIPPAGE_PCT, "position_cap": books._MAX_POSITION_PCT,
                   "ticker_cap": books._MAX_TICKER_EXPOSURE_PCT,
                   "experiment_source": [inspect.getsource(f) for f in
                       (adjustment, observe_cohort, macro_provenance.snapshot, _mature, _outcome)],
                   "book_horizon_sessions": book_mtm.BOOK_HOLD_SESSIONS})


def register_epoch(conn, now=None):
    """Register before collecting episodes. Never enroll historical episodes."""
    from agent_db import CODE_COMMIT_SHA
    now = time.time() if now is None else now
    acc = accepted_contract(conn, now)
    if not acc:
        return None
    protocol = load_protocol()
    protocol_hash = digest(protocol)
    base_hash = base_contract()
    epoch_id = digest({"acceptance": acc, "protocol": protocol_hash, "base": base_hash})
    conn.execute("INSERT OR IGNORE INTO macro_experiment_epochs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (epoch_id, now, acc["record_id"], acc["scorer_contract_hash"], acc["config_version"],
                  acc["config_hash"], protocol_hash, canonical(protocol), base_hash, canonical(acc), CODE_COMMIT_SHA))
    conn.commit()
    return epoch_id


def adjustment(snap, protocol, dimensions=None):
    allowed = set(dimensions if dimensions is not None else DIMS) & set(snap.get("usable_dimensions", []))
    if snap.get("coverage_state") != "company_supported":
        return 0.0
    value = 0.0
    for dim in allowed:
        score = snap[dim]["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 1 <= score <= 10:
            raise ValueError("invalid frozen macro score")
        value += protocol["dimension_weights"][dim] * (score - 5.5) / 4.5
    cap = protocol["adjustment_cap"]
    return max(-cap, min(cap, cap * value))


def stage_adjustment(base, proposed, stage=0, *, evidence_positive=False, approved=False, near_tie_gap=None, protocol=None):
    """Pure future-stage policy. Production has no caller and remains stage zero."""
    policy = protocol or load_protocol()
    if str(stage) not in policy["stages"] or not all(math.isfinite(x) for x in (base, proposed)):
        raise ValueError("invalid stage or score")
    if stage == 0:
        return base
    if not evidence_positive or not approved:
        raise ValueError("positive prospective evidence and explicit promotion required")
    cap = policy["stages"][str(stage)]["cap"]
    if stage == 1 and (near_tie_gap is None or abs(near_tie_gap) > cap):
        return base
    return base + max(-cap, min(cap, proposed))


def _regime(conn, captured_at):
    # Only stored snapshots known before the shared decision timestamp; no fetch.
    from .macro_provenance import timestamp
    try:
        rows = conn.execute("SELECT regime_json,created_at FROM macro_regime_snapshots ORDER BY created_at DESC").fetchall()
        for row in rows:
            ts = timestamp(row[1], local=True)
            if ts is not None and 0 <= captured_at - ts <= 86400:
                from portfolio_ai import compute_regime_stress
                raw = json.loads(row[0])
                stress = compute_regime_stress(raw)
                value = stress.get("rate_stress")
                return ("unknown" if value is None else "rising_rates" if value > .1 else "falling_rates" if value < -.1 else "neutral_rates"), {"observed_at": ts, "regime": raw}
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return "unknown", {}


def _book_ids(epoch_id):
    return f"MACRO_CONTROL_{epoch_id}", f"MACRO_CHALLENGER_{epoch_id}"


def _books(conn, epoch, control, macro, date):
    from .book_simulator import _record_one_book
    from agents.opportunity_config import VIRTUAL_BOOK_STARTING_CASH
    if not all(isinstance(c["price"], (float, int)) and math.isfinite(c["price"]) and c["price"] > 0 for c in (control, macro)):
        return "NO_PAIRED_PRICES"
    for book_id, c in zip(_book_ids(epoch), (control, macro)):
        conn.execute("INSERT OR IGNORE INTO virtual_books(book_id,label,starting_cash,current_cash,as_of) VALUES (?,?,?,?,?)",
                     (book_id, book_id, VIRTUAL_BOOK_STARTING_CASH, VIRTUAL_BOOK_STARTING_CASH, date))
        _record_one_book(conn, book_id, c["ticker"], c["price"], c["episode_id"], "BUY", "MACRO_OBSERVE")
        # The shared helper writes cost-basis placeholders. Only nightly MTM may
        # designate a macro NAV row complete, never a trade-time placeholder.
        conn.execute("UPDATE virtual_book_nav SET is_complete=0 WHERE book_id=? AND date=?", (book_id, datetime.now(timezone.utc).date().isoformat()))
    return "RECORDED"


def observe_cohort(conn, epoch_id, cohort_id, agent_run_id, candidates, captured_at):
    """Persist all candidates and both selections atomically, from captured episodes."""
    epoch_row = conn.execute("SELECT * FROM macro_experiment_epochs WHERE epoch_id=?", (epoch_id,)).fetchone()
    if not epoch_row:
        raise ValueError("unregistered experiment epoch")
    epoch = dict(epoch_row)
    protocol = json.loads(epoch["protocol_json"])
    if epoch["registered_at"] > captured_at or not 0 <= time.time() - captured_at <= 300:
        raise ValueError("historical cohort enrollment prohibited")
    acc = accepted_contract(conn, captured_at)
    if not acc or acc["record_id"] != epoch["acceptance_id"] or acc["scorer_contract_hash"] != epoch["scorer_contract_hash"]:
        raise ValueError("acceptance changed during decision")
    if epoch["base_contract_hash"] != base_contract() or epoch["protocol_hash"] != digest(load_protocol()):
        raise ValueError("ranking or protocol changed during decision")
    from agents.opportunity_config import MIN_COMPOSITE
    if not candidates or len({c["ticker"] for c in candidates}) != len(candidates):
        raise ValueError("missing or duplicate opportunity universe")
    frozen = []
    for c in candidates:
        from .macro_provenance import timestamp
        if c.get("scanned_at"):
            available_at = timestamp(c["scanned_at"], local=True)
            if available_at is None or available_at > captured_at:
                raise ValueError("financial evidence timestamp is invalid or future")
        row = conn.execute("SELECT * FROM decision_episodes WHERE episode_id=?", (c.get("_episode_id"),)).fetchone()
        if not row or row["ticker"] != c["ticker"] or str(row["run_id"]) != str(agent_run_id):
            raise ValueError("candidate episode lineage mismatch")
        if row["macro_epoch"] != epoch_id or row["captured_at"] != captured_at:
            raise ValueError("candidate timestamp or epoch mismatch")
        base = row["base_score"]
        if not isinstance(base, (int, float)) or not math.isfinite(base) or base != c["_composite"]:
            raise ValueError("candidate base score mismatch")
        snap = json.loads(row["macro_snapshot"] or "{}")
        if snap.get("usable_dimensions"):
            if (snap.get("macro_acceptance_record_id") != epoch["acceptance_id"]
                    or snap.get("scorer_contract_hash") != epoch["scorer_contract_hash"]
                    or snap.get("macro_config_hash") != epoch["macro_config_hash"]
                    or not snap.get("prompt_hash") or not snap.get("evidence_hash")
                    or snap.get("macro_score_timestamp", float("inf")) > captured_at):
                raise ValueError("unusable accepted macro provenance")
        adj = adjustment(snap, protocol)
        # One shared immutable candidate payload; arm-specific fields are excluded.
        evidence = {k: v for k, v in c.items() if not k.startswith("_challenger") and not k.startswith("_composite_challenger")}
        frozen.append({"episode_id": row["episode_id"], "ticker": row["ticker"], "base_score": base,
                       "macro_score": base + adj, "adjustment": adj, "risk_eligible": int(base >= MIN_COMPOSITE),
                       "evidence_json": canonical(evidence), "evidence_hash": digest(evidence),
                       "macro_snapshot": canonical(snap), "sector": row["sector"], "price": c.get("price")})
    universe_hash = digest(sorted((c["ticker"], c["episode_id"], c["evidence_hash"], c["macro_snapshot"]) for c in frozen))
    prior = conn.execute("SELECT cohort_id,universe_hash FROM macro_experiment_cohorts WHERE epoch_id=? AND agent_run_id=?", (epoch_id, str(agent_run_id))).fetchone()
    if prior:
        if prior[1] != universe_hash:
            raise ValueError("cohort retry changed its frozen universe")
        return prior[0]
    eligible = [c for c in frozen if c["risk_eligible"]]
    control = min(eligible, key=lambda c: (-c["base_score"], c["ticker"])) if eligible else None
    macro = min(eligible, key=lambda c: (-c["macro_score"], c["ticker"])) if eligible else None
    dims = sorted({d for c in eligible for d in json.loads(c["macro_snapshot"]).get("usable_dimensions", [])})
    reason = "no_base_eligible_candidates" if not eligible else "no_usable_macro_dimensions" if not dims else None
    date = datetime.fromtimestamp(captured_at, ET).date().isoformat()
    regime, regime_json = _regime(conn, captured_at)
    conn.execute("SAVEPOINT macro_cohort")
    try:
        book_status = _books(conn, epoch_id, control, macro, date) if not reason else "EXCLUDED"
        conn.execute("INSERT INTO macro_experiment_cohorts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (cohort_id, epoch_id, str(agent_run_id), captured_at, date, universe_hash, len(frozen), len(eligible),
                      "EXCLUDED" if reason else "OBSERVED", reason,
                      control["episode_id"] if control else None, macro["episode_id"] if macro else None,
                      control["ticker"] if control else None, macro["ticker"] if macro else None,
                      control["base_score"] if control else None, macro["macro_score"] if macro else None,
                      int(bool(control and control["ticker"] != macro["ticker"])), canonical(dims), regime,
                      canonical(regime_json), book_status, time.time()))
        conn.executemany("INSERT INTO macro_experiment_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(cohort_id, c["episode_id"], c["ticker"], c["base_score"], c["macro_score"], c["adjustment"],
                           c["risk_eligible"], c["evidence_json"], c["evidence_hash"], c["macro_snapshot"], c["sector"], c["price"]) for c in frozen])
        conn.execute("RELEASE macro_cohort")
    except BaseException:
        conn.execute("ROLLBACK TO macro_cohort")
        conn.execute("RELEASE macro_cohort")
        raise
    return cohort_id


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mature(captured_at, horizon, now):
    from trade_engine.market_calendar import maturity_date
    from .outcome_labeler import _entry_date
    # Require the horizon's market close, not merely midnight on that date.
    day = maturity_date(_entry_date(captured_at), "sessions_v2", horizon)
    return now >= datetime.fromisoformat(str(day) + "T16:00:00").replace(tzinfo=ET).timestamp()


def _outcome(conn, episode_id, horizon, now):
    from .macro_provenance import timestamp
    row = conn.execute("SELECT * FROM episode_outcomes WHERE episode_id=? AND horizon=? "
                       "AND horizon_definition_version='sessions_v2'", (episode_id, horizon)).fetchone()
    if not row or not all(_finite(row[k]) for k in ("alpha", "ticker_return", "spy_return")):
        return None
    labeled = timestamp(row["labeled_at"])
    if labeled is None or labeled > now or abs(row["alpha"] - (row["ticker_return"] - row["spy_return"])) > 1e-8:
        return None
    return row


def sync_labels(conn, now=None):
    """Freeze paired labels once both original episodes have valid mature outcomes."""
    now = time.time() if now is None else now
    written = 0
    for cohort in conn.execute("SELECT * FROM macro_experiment_cohorts WHERE status='OBSERVED'").fetchall():
        for horizon in ("1w", "1m", "3m"):
            if not _mature(cohort["captured_at"], horizon, now):
                continue
            control = _outcome(conn, cohort["control_episode_id"], horizon, now)
            macro = _outcome(conn, cohort["macro_episode_id"], horizon, now)
            if control is None or macro is None:
                continue
            if abs(control["spy_return"] - macro["spy_return"]) > 1e-8:
                continue
            delta = lambda key: macro[key] - control[key] if _finite(macro[key]) and _finite(control[key]) else None
            cur = conn.execute("INSERT OR IGNORE INTO macro_experiment_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (cohort["cohort_id"], horizon, "sessions_v2", now, control["id"], macro["id"],
                                delta("alpha"), delta("mfe"), delta("mae"), control["alpha"], macro["alpha"],
                                control["mae"] if _finite(control["mae"]) else None,
                                macro["mae"] if _finite(macro["mae"]) else None))
            written += cur.rowcount
    return written


def summarize(pairs, protocol):
    """Cohort-weighted effect; resample whole dates to preserve dependence."""
    import random
    import statistics
    from collections import defaultdict
    values = [value for _, value in pairs]
    result = {"n": len(values), "mean": statistics.mean(values) if values else None,
              "median": statistics.median(values) if values else None,
              "mean_ci": None, "median_ci": None,
              "macro_wins": sum(v > protocol["tie_tolerance"] for v in values),
              "control_wins": sum(v < -protocol["tie_tolerance"] for v in values),
              "ties": sum(abs(v) <= protocol["tie_tolerance"] for v in values)}
    clusters = defaultdict(list)
    for day, value in pairs:
        clusters[day].append(value)
    result["decision_dates"] = len(clusters)
    if len(clusters) < 2:
        return result
    groups = [clusters[d] for d in sorted(clusters)]
    rng = random.Random(protocol["bootstrap"]["seed"])
    means, medians = [], []
    for _ in range(protocol["bootstrap"]["replicates"]):
        sample = [v for _ in groups for v in rng.choice(groups)]
        means.append(statistics.mean(sample))
        medians.append(statistics.median(sample))
    tail = (1 - protocol["bootstrap"]["confidence"]) / 2
    for name, samples in (("mean_ci", means), ("median_ci", medians)):
        samples.sort()
        result[name] = [samples[int(tail * (len(samples) - 1))], samples[int((1 - tail) * (len(samples) - 1))]]
    return result


def _book_report(conn, book_id):
    import statistics
    rows = conn.execute("SELECT * FROM virtual_book_nav WHERE book_id=? AND is_complete=1 ORDER BY date", (book_id,)).fetchall()
    book = conn.execute("SELECT starting_cash FROM virtual_books WHERE book_id=?", (book_id,)).fetchone()
    if not rows or not book:
        return {"complete_days": 0, "cumulative_return": None, "max_drawdown": None, "volatility": None}
    navs = [r["total_nav"] for r in rows]
    peak = book[0]
    drawdown = 0.0
    for nav in navs:
        peak = max(peak, nav)
        drawdown = max(drawdown, 1 - nav / peak)
    # Avoid treating missing MTM dates as one-day returns.
    from trade_engine.market_calendar import trading_sessions_between
    returns = [(b["total_nav"] / a["total_nav"]) - 1 for a, b in zip(rows, rows[1:])
               if a["total_nav"] > 0 and trading_sessions_between(a["date"], b["date"]) == 1]
    turnover = conn.execute("SELECT COALESCE(SUM(ABS(price*qty)),0) FROM virtual_fills WHERE book_id=?", (book_id,)).fetchone()[0] / book[0]
    return {"complete_days": len(rows), "as_of": rows[-1]["date"], "dates_hash": digest([r["date"] for r in rows]), "turnover": turnover,
            "cumulative_return": navs[-1] / book[0] - 1, "max_drawdown": drawdown,
            "volatility": statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else None}


def evaluate(conn, now=None, epoch_id=None):
    """Read-only report; never enroll, label, pool epochs or promote a model."""
    import statistics
    from collections import Counter
    now = time.time() if now is None else now
    current = accepted_contract(conn, now)
    epochs = [dict(r) for r in conn.execute("SELECT * FROM macro_experiment_epochs ORDER BY registered_at DESC")]
    epoch = next((e for e in epochs if e["epoch_id"] == epoch_id), None) if epoch_id else next(
        (e for e in epochs if current and e["acceptance_id"] == current["record_id"]
         and e["scorer_contract_hash"] == current["scorer_contract_hash"]
         and e["protocol_hash"] == digest(load_protocol()) and e["base_contract_hash"] == base_contract()), None)
    report = {"observe_only": True, "stage": 0, "evidence_state": "INSUFFICIENT",
              "acceptance": current, "epoch_id": epoch["epoch_id"] if epoch else None,
              "epochs": [{k: e[k] for k in ("epoch_id", "registered_at", "acceptance_id")} for e in epochs],
              "prospective_cohorts": 0, "divergent_cohorts": 0, "matured_divergent": 0,
              "excluded_cohorts": 0, "mean_selection_delta": None, "median_selection_delta": None,
              "mean_ci": None, "macro_wins": 0, "control_wins": 0, "ties": 0,
              "graduation_ready": False, "blockers": ["No prospective epoch registered"],
              "primary_metric": "63-session SPY-relative selection alpha on divergent cohorts"}
    if not epoch:
        return report
    p = json.loads(epoch["protocol_json"])
    epoch_current = bool(current and epoch["acceptance_id"] == current["record_id"]
                         and epoch["scorer_contract_hash"] == current["scorer_contract_hash"]
                         and epoch["base_contract_hash"] == base_contract()
                         and epoch["protocol_hash"] == digest(load_protocol()))
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM macro_experiment_cohorts WHERE epoch_id=? AND captured_at<=? ORDER BY captured_at,cohort_id", (epoch["epoch_id"], now))]
    rows = [r for r in all_rows if r["status"] == "OBSERVED"]
    divergent = [r for r in rows if r["diverged"]]
    labels = {(r["cohort_id"], r["horizon"]): dict(r) for r in conn.execute(
        "SELECT l.* FROM macro_experiment_labels l JOIN macro_experiment_cohorts c USING(cohort_id) "
        "WHERE c.epoch_id=? AND l.matured_at<=? AND l.horizon_version='sessions_v2'", (epoch["epoch_id"], now))}
    secondary = {}
    for h in p["horizons"]:
        valid = [(r, labels[(r["cohort_id"], h)]) for r in divergent if (r["cohort_id"], h) in labels]
        stats = summarize([(r["decision_date"], l["delta_alpha"]) for r, l in valid], p)
        for key in ("delta_mfe", "delta_mae"):
            vals = [l[key] for _, l in valid if _finite(l[key])]
            stats[key] = statistics.mean(vals) if vals else None
            stats[key + "_n"] = len(vals)
        secondary[h] = stats
    primary = secondary["3m"]
    matured = [r for r in divergent if (r["cohort_id"], "3m") in labels]
    candidates = [dict(r) for r in conn.execute("SELECT m.* FROM macro_experiment_candidates m JOIN macro_experiment_cohorts c USING(cohort_id) WHERE c.epoch_id=?", (epoch["epoch_id"],))]
    sectors = {c["episode_id"]: c["sector"] for c in candidates}
    diversity = {"decision_dates": len({r["decision_date"] for r in matured}),
                 "tickers": len({r[k] for r in matured for k in ("control_ticker", "macro_ticker")}),
                 "sectors": len({sectors.get(r[k]) for r in matured for k in ("control_episode_id", "macro_episode_id")} - {None, "", "Unknown", "unknown"}),
                 "regimes": len({r["regime"] for r in matured} - {"unknown"})}
    concentration, churn = {}, {}
    for arm in ("control", "macro"):
        tickers = [r[arm + "_ticker"] for r in rows]
        sec = [sectors.get(r[arm + "_episode_id"]) for r in rows]
        concentration[arm] = {"ticker": max(Counter(tickers).values()) / len(tickers) if tickers else None,
                              "sector": max(Counter(sec).values()) / len(sec) if sec and all(sec) else None}
        churn[arm] = sum(a != b for a, b in zip(tickers, tickers[1:])) / (len(tickers) - 1) if len(tickers) > 1 else None
    books = {arm: _book_report(conn, bid) for arm, bid in zip(("control", "macro"), _book_ids(epoch["epoch_id"]))}
    blockers = [f"Insufficient {key}: {diversity[key]}/{minimum}" for key, minimum in p["diversity"].items() if diversity[key] < minimum]
    fraction = len(divergent) / len(rows) if rows else 0
    if fraction < p["minimum_divergence_fraction"]:
        blockers.append("Insufficient selection divergence")
    ci = primary["mean_ci"]
    if ci is None or (ci[1] - ci[0]) / 2 > p["max_mean_ci_half_width"]:
        blockers.append("Insufficient statistical precision")
    state = "INSUFFICIENT" if blockers else "POSITIVE" if ci[0] > p["minimum_effect"] else "NEGATIVE" if ci[1] < -p["minimum_effect"] else "INCONCLUSIVE"
    risk = []
    if not epoch_current:
        risk.append("Archived epoch cannot graduate into the current production contract")
    if primary["delta_mae_n"] != primary["n"] or primary["delta_mae"] is None:
        risk.append("Incomplete primary MAE evidence")
    elif primary["delta_mae"] < -p["max_mae_worsening"]:
        risk.append("Macro MAE exceeds risk tolerance")
    cb, mb = books["control"], books["macro"]
    if (min(cb["complete_days"], mb["complete_days"]) < 63
            or cb.get("dates_hash") != mb.get("dates_hash")):
        risk.append("Paired mark-to-market history unavailable")
    elif mb["max_drawdown"] - cb["max_drawdown"] > p["max_drawdown_worsening"]:
        risk.append("Macro drawdown exceeds risk tolerance")
    for key in ("ticker", "sector"):
        c, m = concentration["control"][key], concentration["macro"][key]
        if c is None or m is None:
            risk.append(f"Incomplete {key} concentration evidence")
        elif m - c > p["max_concentration_increase"]:
            risk.append(f"Macro {key} concentration exceeds tolerance")
    if any(r["book_status"] != "RECORDED" for r in rows):
        risk.append("Some cohorts lack paired virtual-book prices")
    report.update(prospective_cohorts=len(rows), divergent_cohorts=len(divergent), matured_divergent=primary["n"],
                  excluded_cohorts=len(all_rows)-len(rows), exclusions=dict(Counter(r["exclusion_reason"] for r in all_rows if r["status"] == "EXCLUDED")),
                  unevaluable_matured=sum(_mature(r["captured_at"], "3m", now) and (r["cohort_id"], "3m") not in labels for r in divergent),
                  mean_selection_delta=primary["mean"], median_selection_delta=primary["median"], mean_ci=ci,
                  median_ci=primary["median_ci"], macro_wins=primary["macro_wins"], control_wins=primary["control_wins"], ties=primary["ties"],
                  evidence_state=state, diversity=diversity, divergence_fraction=fraction, secondary=secondary,
                  books=books, concentration=concentration, recommendation_churn=churn,
                  blockers=blockers, risk_blockers=risk, graduation_ready=state == "POSITIVE" and not risk,
                  protocol=p, epoch_acceptance_id=epoch["acceptance_id"],
                  epoch_current=epoch_current,
                  regime_breakdown={regime: summarize([(r["decision_date"], labels[(r["cohort_id"], "3m")]["delta_alpha"])
                                                       for r in matured if r["regime"] == regime], p)
                                    for regime in sorted({r["regime"] for r in matured})},
                  dimension_ablations=_ablations(conn, rows, candidates, p, now))
    return report


def _ablations(conn, rows, candidates, protocol, now):
    """Exploratory dimension subsets, using only the original frozen evidence."""
    results = {}
    for name, dims in protocol["dimension_ablations"].items():
        pairs, maes = [], []
        for cohort in rows:
            universe = [c for c in candidates if c["cohort_id"] == cohort["cohort_id"] and c["risk_eligible"]]
            if not universe or not _mature(cohort["captured_at"], "3m", now):
                continue
            selected = min(universe, key=lambda c: (-(c["base_score"] + adjustment(json.loads(c["macro_snapshot"]), protocol, dims)), c["ticker"]))
            if selected["episode_id"] == cohort["control_episode_id"]:
                continue
            c = _outcome(conn, cohort["control_episode_id"], "3m", now)
            m = _outcome(conn, selected["episode_id"], "3m", now)
            if c is not None and m is not None:
                pairs.append((cohort["decision_date"], m["alpha"] - c["alpha"]))
                if _finite(m["mae"]) and _finite(c["mae"]):
                    maes.append(m["mae"] - c["mae"])
        result = summarize(pairs, protocol)
        result.update(exploratory=True, delta_mae=sum(maes) / len(maes) if maes else None)
        results[name] = result
    return results
