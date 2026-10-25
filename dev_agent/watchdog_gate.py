"""Read-only independent watchdog prerequisite. Health never grants authority."""
import json
import os
from pathlib import Path
import sqlite3
import time
from .discovery_watchdog import VERSION,COMPONENTS,reviewed_phase,timer_valid,finite,valid_hex,HEX32
from .discovery_watchdog_reader import source_binding,ReadOnlySystemd,pinned_unit,read_bytes,read_json


def coverage_path(root):
    # Never consume a candidate checkout's caller-writable projection.
    return Path('/home/optiplex/investment/out/watchdog.db')


def require_coverage(root,*,now=None):
    now=time.time() if now is None else now
    try:
        binding=source_binding(root)
        if reviewed_phase(binding['reviewed_config'])!='supervised':raise ValueError('reviewed supervised phase required')
        timer=ReadOnlySystemd(os.getuid()).show('macro-health-watchdog.timer')
        timer['pinned']=pinned_unit(root,'macro-health-watchdog.timer',timer,os.getuid())
        if not timer_valid(timer):raise ValueError('independent watchdog timer inactive')
        path=coverage_path(root)
        if any(path.with_name(path.name+s).exists() for s in ('-journal','-wal')):raise ValueError('watchdog snapshot transaction in progress')
        data=read_bytes(path,128_000_000,uid=os.getuid())
        with sqlite3.connect(':memory:') as db:
            db.deserialize(data);db.execute('PRAGMA query_only=ON')
            rows=db.execute("SELECT component,status,checked_at,detail,incident_id FROM system_watchdog_state WHERE component LIKE 'development_discovery%' LIMIT 101").fetchall()
            for row in rows:
                if row[4]:
                    event=db.execute('SELECT severity,transition FROM watchdog_events WHERE incident_id=? ORDER BY detected_at DESC,rowid DESC LIMIT 1',(row[4],)).fetchone()
                    if event and event[0]=='RED' and event[1]!='RESOLVED':raise ValueError('unresolved watchdog RED incident')
        expected={'development_discovery',*('development_discovery_'+s for s in COMPONENTS)}
        if len(rows)>100 or not expected<=set(r[0] for r in rows):raise ValueError('complete watchdog coverage missing')
        if any(r[1] not in {'INFO','YELLOW'} or type(r[2]) not in (int,float) or not 0<=now-r[2]<=2100 for r in rows):raise ValueError('watchdog coverage stale or RED')
        row=next(r for r in rows if r[0]=='development_discovery');e=json.loads(row[3])['evidence']
        failure=path.parent/'watchdog_failure.json'
        if failure.exists() or failure.is_symlink():
            marker=read_json(failure,limit=64000,uid=os.getuid())
            if not finite(marker.get('checked_at')) or marker['checked_at']>=row[2]:raise ValueError('watchdog execution failed after its last inspection')
        if (e.get('version')!=VERSION or e.get('source_head')!=binding['head'] or e.get('observer_head')!=binding['head'] or e.get('code_identity')!=binding['code_identity']
            or e.get('inspected') is not True or e.get('producer_verified') is not True or e.get('grants_implementation') is not False
            or not finite(e.get('observed_at')) or not 0<=now-e['observed_at']<=2100 or abs(e['observed_at']-row[2])>180
            or not valid_hex(e.get('producer_invocation'),HEX32) or type(e.get('producer_pid')) is not int or e['producer_pid']<=0
            or e.get('phase')!='supervised' or e.get('builder')!='SUPERVISED' or e.get('acceptance')!='READY 3/3' or e.get('host_safety_accepted') is not True
            or type(e.get('accepted_runs')) is not int or e['accepted_runs']<3):raise ValueError('current independent watchdog inspection not proven')
        return dict(status='PASS',source_head=binding['head'],checked_at=row[2],grants_implementation=False)
    except Exception as exc:
        raise ValueError('Development Agent watchdog coverage is unavailable, stale or RED') from exc
