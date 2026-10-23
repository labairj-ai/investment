"""Shared read-only safety evidence; independent of activation/preparation mode."""
from __future__ import annotations
import os
import math
import json
import re
import time
from .operations import policy,certificates,operational_runs,eligibility
from .certification import harness_hash,technical_current
from .discovery import task_index
from .scheduler_health import health as scheduler_health
from .software_metrics import summary as software_metrics


def evaluate(root,store,now=None,*,protections=None,technical=None):
    now=time.time() if now is None else now
    config=policy(root);bound=harness_hash(root);certs=certificates(store) if technical is None else technical
    runs=operational_runs(root,store,now);window=eligibility(root,store,now)
    inventory_blockers=[]
    try:tasks=task_index(root)
    except ValueError:tasks={};inventory_blockers.append('TODO dependency inventory is untrusted')
    def fresh(stamp,ttl):return type(stamp) in (int,float) and math.isfinite(stamp) and 0<=now-stamp<=ttl
    blockers=[f'TODO {n:04d} operational acceptance incomplete' for n in [*range(816,824),*range(825,831)] if tasks.get(f'{n:04d}',{}).get('status') not in {'done','completed','resolved'}]
    blockers+=inventory_blockers+window['blockers']
    if not technical_current(root,certs,now):blockers.append('current technical certificate not PASS')
    latest=certs[-1] if certs else {};evidence=latest.get('evidence',{})
    for component in ('oracle','deployment_agent'):
        c=evidence.get(component,{})
        if (c.get('status')!='PASS' or c.get('fixture_only') is not False or c.get('harness_hash')!=bound
            or not fresh(c.get('created'),86400) or not (type(c.get('expires_at')) in (int,float) and math.isfinite(c['expires_at']) and 0<c['expires_at']-now<=86400)):blockers.append('current real '+component+' certificate not PASS')
    protection=evidence.get('github',{}) if protections is None else protections
    if protection.get('status')!='PASS' or not fresh(protection.get('created'),min(300,config.get('github_evidence_max_age_seconds',300))):blockers.append('current effective GitHub protection not PASS')
    if config.get('emergency_stop') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'}:blockers.append('emergency stop active')
    if config.get('auto_merge') is not False or config.get('required_human_merge') is not True:blockers.append('human merge boundary invalid')
    if config.get('autonomous_max_risk')!='L2':blockers.append('risk ceiling must remain L2')
    cap=config.get('daily_implementation_cap',1)
    if type(cap) is not int or not 0<=cap<=3:blockers.append('daily cap malformed or exceeds hard maximum three')
    snapshot=evidence.get('snapshot',{})
    if snapshot.get('status')!='PASS' or snapshot.get('provenance_status')!='PASS' or snapshot.get('source_environment')!='optiplex/investment/out/investment.db' or snapshot.get('fixture_only') is True or not fresh(snapshot.get('backup_timestamp'),min(24,config.get('snapshot_max_age_hours',24))*3600):blockers.append('current authenticated snapshot evidence required')
    scheduler=scheduler_health(store,now)
    if scheduler.get('status')!='SCHEDULED' or scheduler.get('enabled') is not True or scheduler.get('active')!='active' or scheduler.get('inventory_complete') is not True or type(scheduler.get('successful_runs')) is not int or scheduler.get('successful_runs',0)<3:blockers.append('healthy scheduler with three genuine scheduled runs required')
    events=[]
    if store.path.exists():
        with store.connect() as db:
            rows=db.execute("SELECT kind,created,payload,candidate FROM dev_events WHERE kind IN ('PIPELINE','AUTONOMY_PAUSE','AUTONOMY_RESUME','DEPLOYMENT') ORDER BY seq DESC LIMIT 1001").fetchall()
        if len(rows)>1000:blockers.append('incident evidence inventory incomplete')
        events=[dict(kind=r[0],created=r[1],payload=json.loads(r[2]),candidate=r[3]) for r in rows]
    resume=max([e['payload'].get('created',0) for e in events if e['kind']=='AUTONOMY_RESUME']+[0])
    if any(e['kind']=='AUTONOMY_PAUSE' and e['payload'].get('created',0)>=resume for e in events):blockers.append('unresolved autonomy pause')
    if any(e['kind']=='DEPLOYMENT' and e['payload'].get('status') in {'DEGRADED','ROLLED_BACK'} and e['payload'].get('observed_at',0)>=resume for e in events):blockers.append('abnormal deployment observation')
    failures=sorted([e for e in events if e['kind']=='PIPELINE' and e['payload'].get('stage') in {'FAILED','NEEDS_HUMAN'}],key=lambda e:e['created'],reverse=True)
    if len([e for e in failures[:3] if e['created']>=resume])>=3:blockers.append('repeated failure condition')
    qualifying=[]
    for run in runs['qualifying']:
        c=store.get(run['candidate']);deploy=[e['payload'] for e in c['events'] if e['kind']=='DEPLOYMENT'][-1];r=deploy['deployment_evidence']
        metrics=deploy.get('metrics',{})
        if metrics.get('defect_recurrence_checked') is not True:blockers.append('post-fix recurrence observation unavailable: '+run['run_id'])
        elif metrics.get('defect_recurred') is not False:blockers.append('post-fix defect recurrence requires owner assessment: '+run['run_id'])
        qualifying.append(dict(run_id=run['run_id'],candidate=run['candidate'],created=run['created'],risk=run['context']['risk'],pr=r['receipt']['pr'],head=r['receipt']['head'],merge_sha=r['receipt']['merge_sha'],deployed_sha=r['receipt']['deployed_sha'],deployment_receipt_sha256=r['sha256'],observed_at=deploy.get('observed_at'),evidence=deploy.get('evidence',[])))
    return dict(status='FAIL' if blockers else 'PASS',created=now,harness_hash=bound,safety_configuration=config,blockers=list(dict.fromkeys(blockers)),qualifying_runs=qualifying,non_qualifying_attempts=[{k:r.get(k) for k in ('candidate','run_id','head','created','reason')} for r in runs['non_qualifying']],failed_attempts=[dict(candidate=e.get('candidate'),created=e['created'],stage=e['payload']['stage']) for e in failures],observation_window=window,scheduler=scheduler,metrics=software_metrics(store),grants_authority=False)
