"""Observed user-systemd discovery health; read-only, never installs or starts."""
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
        process=invoke(['systemctl','--user','show','development-scout.timer','--no-pager','--property='+','.join(PROPERTIES)],check=True,capture_output=True,text=True,timeout=10)
        values=dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line)
        if values.get('LoadState')!='loaded':return dict(status='UNAVAILABLE',reason='discovery timer not installed',created=now)
        enabled=values.get('UnitFileState') in {'enabled','enabled-runtime'}
        return dict(status='SCHEDULED' if enabled and values.get('ActiveState')=='active' else 'DISABLED',created=now,enabled=enabled,active=values.get('ActiveState'),next_run=values.get('NextElapseUSecRealtime'),last_trigger=values.get('LastTriggerUSec'),unit='development-scout.timer',implementation_scheduled=False)
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
