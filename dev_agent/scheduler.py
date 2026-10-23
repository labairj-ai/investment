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
from .policy import classify, protected_graph
from .store import digest


def slot(now=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.tzinfo is None: raise ValueError("timezone-aware clock required")
    return now.astimezone(ZoneInfo("America/New_York")).date().isoformat()


def trigger():
    invocation=os.environ.get('INVOCATION_ID','')
    if re.fullmatch(r'[a-f0-9]{32}',invocation):
        try:
            service=subprocess.run(['systemctl','--user','show','development-scout.service','--no-pager','--property=InvocationID,MainPID'],check=True,capture_output=True,text=True,timeout=10)
            values=dict(line.split('=',1) for line in service.stdout.splitlines() if '=' in line)
            timer=subprocess.run(['systemctl','--user','show','development-scout.timer','--value','--property=LastTriggerUSecMonotonic'],check=True,capture_output=True,text=True,timeout=10)
            recent=0<=time.monotonic()-int(timer.stdout.strip())/1_000_000<=180
            if values.get('InvocationID')==invocation and int(values.get('MainPID','0'))==os.getpid() and recent:return dict(source='systemd-observed-timer',invocation=invocation)
        except (OSError,ValueError,subprocess.SubprocessError):pass
    return dict(source='operator',invocation=None)


def discover_daily(root, store, *, now=None, cap=None, backlog_limit=None, signals=()):
    started=time.time();origin=trigger()
    from .discovery import git
    source_head=git(root,'rev-parse','HEAD')
    enabled_sources=[]
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
                found = scout(root, signals, budget, policy.get("architecture_exclusions", {}), suppressed,enabled_sources=enabled_sources); graph = protected_graph(root); ids = []
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
        result.update(trigger=origin,started_at=started,ended_at=time.time(),duration_seconds=time.time()-started,deduplicated=result.get('deduplicated',0),suppressed=result.get('suppressed',0))
        store.event(None, "SCHEDULE", result, key)
        return result
