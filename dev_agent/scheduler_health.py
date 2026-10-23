"""Observed user-systemd discovery health; read-only, never installs or starts."""
from __future__ import annotations
import json
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


def health(store,now=None):
    now=time.time() if now is None else now
    if not store.path.exists():return dict(status='UNAVAILABLE',reason='scheduler evidence missing')
    with store.connect() as db:
        rows=[dict(kind=r[0],created=r[1],payload=json.loads(r[2])) for r in db.execute("SELECT kind,created,payload FROM dev_events WHERE kind IN ('SCHEDULER_OBSERVATION','SCHEDULE','SCHEDULE_FAILURE','SCHEDULE_ATTEMPT','SCHEDULE_DUPLICATE') ORDER BY seq DESC LIMIT 100")]
    observations=[r['payload'] for r in rows if r['kind']=='SCHEDULER_OBSERVATION'];success=[r for r in rows if r['kind'] in {'SCHEDULE','SCHEDULE_DUPLICATE'} and r['payload'].get('status') in {'COLLECTED','BACKLOG_FULL','DUPLICATE'} and r['payload'].get('trigger',{}).get('source')=='systemd-observed-timer']
    if not observations:return dict(status='UNAVAILABLE',reason='scheduler installation is not observed')
    result=dict(observations[0],last_attempt=next((r['created'] for r in rows if r['kind']=='SCHEDULE_ATTEMPT'),None),last_success=success[0]['created'] if success else None,successful_runs=len({r['payload'].get('slot') for r in success}),recent_failure=next((r['payload'] for r in rows if r['kind']=='SCHEDULE_FAILURE'),None))
    if not 0<=now-result.get('created',0)<=3600:result.update(status='STALE',reason='systemd observation expired')
    elif result['status']=='SCHEDULED' and not success:
        with store.connect() as db:first=db.execute("SELECT min(created) FROM dev_events WHERE kind='SCHEDULER_OBSERVATION'").fetchone()[0]
        result.update(status='AWAITING_FIRST_RUN' if first and now-first<=36*3600 else 'STALE',reason='no observed scheduled scout success yet')
    elif result['status']=='SCHEDULED' and (not success or not 0<=now-success[0]['created']<=36*3600):result.update(status='STALE',reason='no successful daily discovery within 36 hours')
    return result
