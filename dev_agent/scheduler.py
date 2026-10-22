"""Daily Eastern discovery only; never invokes builder/reviewer/PR/deploy."""
from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .discovery import scout, score
from .policy import classify, protected_graph
from .store import digest


def slot(now=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.tzinfo is None: raise ValueError("timezone-aware clock required")
    return now.astimezone(ZoneInfo("America/New_York")).date().isoformat()


def discover_daily(root, store, *, now=None, cap=None, backlog_limit=None, signals=()):
    policy_path = Path(root) / "config/development_agent.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    cap = policy.get("daily_candidate_cap", 5) if cap is None else cap
    backlog_limit = policy.get("active_backlog_limit", 50) if backlog_limit is None else backlog_limit
    if not 0 <= cap <= 10 or not 1 <= backlog_limit <= 500: raise ValueError("bounded discovery policy required")
    key = "scout:" + slot(now)
    store.migrate()
    with store.path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with store.connect() as db:
            prior = db.execute("SELECT payload FROM dev_events WHERE event_id=?", (key,)).fetchone()
        if prior: return dict(status="DUPLICATE", slot=key)
        existing = store.list(500)
        active = len([c for c in existing if c["state"] not in {"CLOSED", "REJECTED"}])
        suppressed = {digest({k:c[k] for k in ("source", "problem", "files", "evidence")}) for c in existing}
        with store.connect() as db:
            attempts = db.execute("SELECT count(*) FROM dev_events WHERE event_id LIKE ?", (key+":attempt:%",)).fetchone()[0]
        if attempts >= 2: return dict(status="NEEDS_HUMAN", reason="daily retry budget exhausted", slot=key)
        attempt = attempts+1
        store.event(None, "SCHEDULE_ATTEMPT", dict(slot=key, attempt=attempt, status="STARTED"), key+":attempt:"+str(attempt))
        budget = max(0, min(10, cap, backlog_limit-active))
        if not budget:
            result = dict(status="BACKLOG_FULL", slot=key, created=0)
        else:
            try:
                found = scout(root, signals, budget, policy.get("architecture_exclusions", {}), suppressed); graph = protected_graph(root); ids = []
                previous = {c["id"] for c in existing}
                for proposal in found["proposals"]:
                    cid = store.discover(proposal); ids.append(cid)
                    store.event(cid, "SCORE", score(proposal, classify(proposal["files"], graphs=[graph])))
                result = dict(status="COLLECTED", slot=key, candidates=ids, created=len(set(ids)-previous), head=found["head"], unavailable=found["unavailable"])
            except Exception as error:
                result = dict(status="FAILED", slot=key, attempt=attempt, reason=type(error).__name__)
                store.event(None, "SCHEDULE_FAILURE", result, key+":failure:"+str(attempt))
                return result
        store.event(None, "SCHEDULE", result, key)
        return result
