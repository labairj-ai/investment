"""Daily Eastern discovery only; never invokes builder/reviewer/PR/deploy."""
from __future__ import annotations

import fcntl
import json
import time
import os
import subprocess
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .discovery import scout, score
from .policy import classify
from .reviewed_source import reviewed_sources
from .store import digest


def slot(now=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.tzinfo is None: raise ValueError("timezone-aware clock required")
    return now.astimezone(ZoneInfo("America/New_York")).date().isoformat()


def trigger():
    # The root standalone copy and this reviewed-source copy execute the same
    # contract independently in Pre and Main. Environment is only a hint to
    # compare against manager-owned identity; it grants no authority.
    from ops.discovery import observer as authority
    invocation=os.environ.get('INVOCATION_ID','')
    try:
        if not re.fullmatch(r'[a-f0-9]{32}',invocation):raise ValueError('invocation required')
        authority.protected(authority.CONFIG)
        config=authority.loads(authority.CONFIG.read_bytes())
        authority.protected(authority.SOURCE)
        if authority.file_hash(authority.SOURCE)!=config['observer_digest']:raise ValueError('installed identity mismatch')
        from .discovery import git
        if config['head']!=git(authority.ROOT,'rev-parse','HEAD'):raise ValueError('exact source required')
        authority.epoch_ready(config)
        observed=authority.systemd(config,os.getpid(),'scout')
        if observed['invocation']!=invocation:raise ValueError('invocation changed')
        if authority.loads(authority.CONFIG.read_bytes())!=config:raise ValueError('pin changed')
        return dict(source='systemd-observed-timer',invocation=invocation)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        return dict(source='operator',invocation=None)


def discover_daily(root, store, *, now=None, cap=None, backlog_limit=None, signals=()):
    started=time.time();origin=trigger()
    from .discovery import git
    source_head=git(root,'rev-parse','HEAD')
    enabled_sources=[]
    reviewed=reviewed_sources(root,source_head)
    policy=reviewed.configuration()
    cap = policy.get("daily_candidate_cap", 5) if cap is None else cap
    backlog_limit = policy.get("active_backlog_limit", 50) if backlog_limit is None else backlog_limit
    if not 0 <= cap <= 10 or not 1 <= backlog_limit <= 500: raise ValueError("bounded discovery policy required")
    key = "scout:" + slot(now)
    store.migrate()
    with store.path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with store.connect() as db:
            prior = db.execute("SELECT payload FROM dev_events WHERE event_id=?", (key,)).fetchone()
        if prior:
            duplicate=dict(status='DUPLICATE',slot=key,head=source_head,created=0,candidates=[],deduplicated=0,suppressed=0,unavailable=[],trigger=origin,started_at=started,ended_at=time.time(),duration_seconds=time.time()-started)
            if origin['source']=='systemd-observed-timer':store.event(None,'SCHEDULE_DUPLICATE',duplicate,key+':duplicate:'+origin['invocation'])
            return duplicate
        existing = store.list(500)
        active = len([c for c in existing if c["state"] not in {"CLOSED", "REJECTED"}])
        suppressed = {digest({k:c[k] for k in ("source", "problem", "files", "evidence")}) for c in existing}
        with store.connect() as db:
            attempts = db.execute("SELECT count(*) FROM dev_events WHERE event_id LIKE ?", (key+":attempt:%",)).fetchone()[0]
        if attempts >= 2: return dict(status="NEEDS_HUMAN", reason="daily retry budget exhausted", slot=key)
        attempt = attempts+1
        store.event(None, "SCHEDULE_ATTEMPT", dict(slot=key,head=source_head,trigger=origin,started_at=started,attempt=attempt,status="STARTED"), key+":attempt:"+str(attempt))
        budget = max(0, min(10, cap, backlog_limit-active))
        if not budget:
            result = dict(status="BACKLOG_FULL",slot=key,head=source_head,created=0,candidates=[],unavailable=[])
        else:
            try:
                if os.environ.get('DEVELOPMENT_SIGNAL_SPOOL'):
                    from .signals import load_spool
                    loaded,enabled_sources=load_spool(os.environ['DEVELOPMENT_SIGNAL_SPOOL'])
                    signals=[*signals,*loaded]
                deduplicated=0;signal_suppressed=0
                found = scout(root, signals, budget, policy.get("architecture_exclusions", {}), suppressed,enabled_sources=enabled_sources,reviewed=reviewed); graph = reviewed.graph(root); ids = []
                previous = {c["id"] for c in existing}
                for proposal in found["proposals"]:
                    if proposal.get('signal_id'):
                        from .signals import ingest
                        signal_result=ingest(store,[proposal]);deduplicated+=signal_result['deduplicated'];signal_suppressed+=signal_result['suppressed']
                        if not signal_result['candidates']:continue
                        cid=signal_result['candidates'][0]
                    else:cid=store.discover(proposal)
                    ids.append(cid)
                    store.event(cid, "SCORE", score(proposal, classify(proposal["files"], graphs=[graph])))
                result = dict(status="COLLECTED", slot=key, candidates=ids, created=len(set(ids)-previous), head=found["head"], unavailable=found["unavailable"],deduplicated=deduplicated,suppressed=signal_suppressed)
            except Exception as error:
                result = dict(status="FAILED",slot=key,head=source_head,trigger=origin,started_at=started,ended_at=time.time(),duration_seconds=time.time()-started,candidates=[],created=0,deduplicated=0,suppressed=0,unavailable=[],availability_status="UNKNOWN_DUE_TO_RUN_FAILURE",attempt=attempt,reason=type(error).__name__)
                store.event(None, "SCHEDULE_FAILURE", result, key+":failure:"+str(attempt))
                return result
        result.update(trigger=origin,started_at=started,ended_at=time.time(),duration_seconds=time.time()-started,deduplicated=result.get('deduplicated',0),suppressed=result.get('suppressed',0),enabled_sources=enabled_sources,signal_count=len(signals),proposal_count=len(found['proposals']) if budget else 0)
        store.event(None, "SCHEDULE", result, key)
        return result
