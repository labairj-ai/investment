"""Observed system Scout / user collector discovery health; read-only, never installs or starts."""
from __future__ import annotations
import json
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import subprocess
import time

PROPERTIES=('LoadState','UnitFileState','ActiveState','NextElapseUSecRealtime','LastTriggerUSec')


def observe(*,invoke=subprocess.run,now=None):
    now=time.time() if now is None else now
    try:
        process=invoke(['/usr/bin/systemctl','--system','show','development-scout.timer','--no-pager','--property='+','.join(PROPERTIES)],check=True,capture_output=True,text=True,timeout=10,env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'})
        values=dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line)
        if values.get('LoadState')!='loaded':return dict(status='UNAVAILABLE',reason='discovery timer not installed',created=now)
        enabled=values.get('UnitFileState') in {'enabled','enabled-runtime'}
        return dict(status='SCHEDULED' if enabled and values.get('ActiveState')=='active' else 'DISABLED',created=now,enabled=enabled,active=values.get('ActiveState'),next_run=values.get('NextElapseUSecRealtime'),last_trigger=values.get('LastTriggerUSec'),unit='development-scout.timer',manager='system',collector_manager='user',scheduler_observer_manager='user',implementation_scheduled=False)
    except (OSError,ValueError,subprocess.SubprocessError):return dict(status='UNAVAILABLE',reason='systemd discovery observation unavailable',created=now)


def record(store,observation):
    # Only trusted operator code calls this adapter. No payload endpoint exposes it.
    with store.connect(True) as db:store._append(db,None,'SCHEDULER_OBSERVATION',observation,'scheduler-observation:'+str(time.time_ns()))
    return observation


def timer_invocation(payload):
    trigger=payload.get('trigger',{})
    invocation=trigger.get('invocation')
    return invocation if trigger.get('source')=='systemd-observed-timer' and isinstance(invocation,str) and re.fullmatch(r'[a-f0-9]{32}',invocation) else None


def successful_execution(row,failed,now):
    p=row['payload'];invocation=timer_invocation(p)
    if row['kind']!='SCHEDULE' or p.get('status') not in {'COLLECTED','BACKLOG_FULL'} or not invocation or invocation in failed:return False
    if not isinstance(p.get('head'),str) or not re.fullmatch(r'[a-f0-9]{40}',p['head']):return False
    if not isinstance(p.get('slot'),str) or not re.fullmatch(r'scout:\d{4}-\d{2}-\d{2}',p['slot']):return False
    start=p.get('started_at');end=p.get('ended_at');duration=p.get('duration_seconds')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end,duration)):return False
    if start<0 or end<start or end>now+60 or duration<0 or abs(end-start-duration)>1:return False
    try:return datetime.fromtimestamp(start,ZoneInfo('America/New_York')).date().isoformat()==p['slot'][6:]
    except (ValueError,OverflowError,OSError):return False


def health(store,now=None):
    now=time.time() if now is None else now
    counts=dict(timer_fires=0,successful_runs=0,duplicate_runs=0,failed_runs=0,successful_slots=[])
    if not store.path.exists():return dict(status='UNAVAILABLE',reason='scheduler evidence missing',**counts)
    with store.connect() as db:
        rows=[dict(kind=r[0],created=r[1],payload=json.loads(r[2])) for r in db.execute("SELECT kind,created,payload FROM dev_events WHERE kind IN ('SCHEDULER_OBSERVATION','SCHEDULE','SCHEDULE_FAILURE','SCHEDULE_ATTEMPT','SCHEDULE_DUPLICATE') ORDER BY seq DESC LIMIT 1001")]
        first=db.execute("SELECT min(created) FROM dev_events WHERE kind='SCHEDULER_OBSERVATION'").fetchone()[0]
    if len(rows)>1000:return dict(status='UNAVAILABLE',reason='scheduler evidence inventory incomplete',inventory_complete=False,**counts)
    failed={timer_invocation(r['payload']) for r in rows if r['kind']=='SCHEDULE_FAILURE'}-{None}
    success=[r for r in rows if successful_execution(r,failed,now)]
    counts.update(timer_fires=len({timer_invocation(r['payload']) for r in rows if r['kind']!='SCHEDULER_OBSERVATION'}-{None}),duplicate_runs=len({timer_invocation(r['payload']) for r in rows if r['kind']=='SCHEDULE_DUPLICATE'}-{None}),failed_runs=len(failed),successful_slots=sorted({r['payload']['slot'] for r in success}))
    counts['successful_runs']=len(counts['successful_slots'])
    observations=[r['payload'] for r in rows if r['kind']=='SCHEDULER_OBSERVATION']
    if not observations:return dict(status='UNAVAILABLE',reason='scheduler installation is not observed',**counts)
    last_success=max([r['payload']['ended_at'] for r in success],default=None)
    result=dict(observations[0],last_attempt=next((r['created'] for r in rows if r['kind']=='SCHEDULE_ATTEMPT'),None),last_success=last_success,recent_failure=next((r['payload'] for r in rows if r['kind']=='SCHEDULE_FAILURE'),None),inventory_complete=True,**counts)
    if not 0<=now-result.get('created',0)<=3600:result.update(status='STALE',reason='systemd observation expired')
    elif result['status']=='SCHEDULED' and not success:result.update(status='AWAITING_FIRST_RUN' if first and 0<=now-first<=36*3600 else 'STALE',reason='no observed scheduled scout success yet')
    elif result['status']=='SCHEDULED' and not 0<=now-last_success<=36*3600:result.update(status='STALE',reason='no successful daily discovery within 36 hours')
    return result


def accepted_runs(store,source_head,now=None):
    """Read-only exact-source acceptance; no manual, duplicate or fixture credit.

    Return records, not a new authority object. The installed observer and
    scheduler remain the producers; generic JSON supplied by a caller is not read.
    """
    if not isinstance(source_head,str) or not re.fullmatch(r'[a-f0-9]{40}',source_head):raise ValueError('exact discovery source required')
    now=time.time() if now is None else now
    if not store.path.exists():return []
    with store.connect() as db:
        rows=[dict(kind=r[0],created=r[1],payload=json.loads(r[2])) for r in db.execute("SELECT kind,created,payload FROM dev_events WHERE kind IN ('SCHEDULE','SCHEDULE_FAILURE') ORDER BY seq DESC LIMIT 1001")]
    if len(rows)>1000:raise ValueError('discovery acceptance inventory incomplete')
    failed={timer_invocation(r['payload']) for r in rows if r['kind']=='SCHEDULE_FAILURE'}-{None}
    seen_slots=set();seen_invocations=set();accepted=[]
    for row in rows:
        p=row['payload'];invocation=timer_invocation(p)
        if not successful_execution(row,failed,now) or p.get('head')!=source_head or p.get('fixture_only') is True:continue
        if p.get('status')!='COLLECTED' or not isinstance(p.get('unavailable'),list):continue
        if set(p['unavailable']) & {'CI','telemetry','performance'} or p.get('availability_status')=='UNKNOWN_DUE_TO_RUN_FAILURE':continue
        if not isinstance(p.get('enabled_sources'),list) or not {'ci','telemetry','performance'}<=set(p['enabled_sources']):continue
        if not isinstance(p.get('candidates'),list) or any(not isinstance(c,str) or not c for c in p['candidates']):continue
        if any(type(p.get(k)) is not int or p[k]<0 for k in ('created','deduplicated','suppressed','signal_count','proposal_count')):continue
        if invocation in seen_invocations or p['slot'] in seen_slots:continue
        seen_invocations.add(invocation);seen_slots.add(p['slot']);accepted.append(p)
    return sorted(accepted,key=lambda p:p['started_at'])


def receipt_path(source_head):
    from pathlib import Path
    import stat
    base=Path('/var/lib/investment-development-acceptance')
    config=Path('/etc/investment-discovery-observer/config.json')
    if not config.exists() and not config.is_symlink():return base/'discovery.json'
    from .structured_json import loads
    for p in (config,*config.parents):
        info=p.lstat()
        if p.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('protected epoch selector required')
    if not stat.S_ISREG(config.stat().st_mode) or config.stat().st_size>2_000_000:raise ValueError('bounded epoch selector required')
    raw=config.read_bytes();data=loads(raw)
    if config.read_bytes()!=raw or data.get('head')!=source_head:raise ValueError('current source selector required')
    epoch=data.get('acceptance_epoch')
    if epoch is None:return base/'discovery.json'
    if epoch!=source_head or not re.fullmatch('[a-f0-9]{40}',epoch):raise ValueError('exact qualification epoch required')
    return base/'epochs'/epoch/'discovery.json'


def host_safety(source_head,runs,now):
    """Operator-owned OS/state observations outside discovery's writable state.

    This reads actual host acceptance only. It does not issue a certificate,
    invent safety measurements, or accept request JSON from the model/owner UI.
    """
    from pathlib import Path
    import os,stat
    try:
        path=receipt_path(source_head)
        info=path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>64000:return False
        for parent in path.parents:
            if parent.is_symlink() or parent.stat().st_uid!=0 or parent.stat().st_mode&0o022:return False
        from .structured_json import loads
        data=loads(path.read_bytes())
        if data.get('source_head')!=source_head or data.get('fixture_only') is not False or data.get('os_boundary_verified') is not True:return False
        stamp=data.get('observed_at')
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=now-stamp<=86400:return False
        accepted={timer_invocation(p):p for p in runs};seen=set()
        checks={'no_builder','no_worktree','no_source_mutation','no_pr','no_deploy','no_financial_execution'}
        for r in data.get('runs',[]):
            invocation=r.get('invocation');run=accepted.get(invocation)
            if not run or invocation in seen or r.get('slot')!=run['slot'] or stamp<run['ended_at']:return False
            if any(r.get(k) is not True for k in checks):return False
            for kind in ('holdings','investment'):
                before=r.get(kind+'_before');after=r.get(kind+'_after')
                if not isinstance(before,str) or not re.fullmatch('[a-f0-9]{64}',before) or before!=after:return False
            seen.add(invocation)
        return len(seen)>=3
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return False


def acceptance(store,source_head,now=None):
    now=time.time() if now is None else now
    runs=accepted_runs(store,source_head,now)
    observed=health(store,now)
    current=(observed.get('status')=='SCHEDULED' and observed.get('inventory_complete') is True
             and observed.get('enabled') is True and observed.get('active')=='active')
    safe=host_safety(source_head,runs,now) if len(runs)>=3 else False
    ready=current and len(runs)>=3 and safe
    reason='three genuine scheduled runs and host safety accepted' if ready else 'discovery host safety acceptance is incomplete' if current and len(runs)>=3 else 'discovery service has not completed three current scheduled runs'
    return dict(status='READY' if ready else 'NOT READY',reason=reason,
                source_head=source_head,successful_runs=len(runs),required_runs=3,runs=runs,host_safety_accepted=safe,scheduled_discovery=observed,grants_implementation=False)


def require_candidate(store,candidate_id,source_head,now=None):
    """A pilot must originate in actual scheduled discovery, never a replay seed."""
    accepted=acceptance(store,source_head,now)
    if accepted['status']!='READY':raise ValueError('genuine discovery and host safety acceptance required')
    runs=accepted['runs']
    match=next((p for p in reversed(runs) if candidate_id in p['candidates']),None)
    if match is None:raise ValueError('candidate lacks genuine scheduled discovery provenance')
    candidate=store.get(candidate_id)
    if candidate.get('synthetic') is True or candidate.get('fixture_only') is True:raise ValueError('synthetic candidate cannot qualify for the real pilot')
    observations=[e['payload'] for e in candidate['events'] if e['kind']=='SIGNAL_OBSERVATION']
    if any(p.get('synthetic') is True or p.get('fixture_only') is True for p in observations):raise ValueError('synthetic discovery cannot qualify for the real pilot')
    return dict(source_head=source_head,slot=match['slot'],invocation=timer_invocation(match),candidate=candidate_id)
