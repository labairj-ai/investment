"""Read-only prospective software promotion report. Never grants activation authority."""
from __future__ import annotations
import os
import re
import time
from .operations import policy,certificates,operational_runs,eligibility
from .certification import harness_hash,technical_current
from .discovery import task_index
from .scheduler_health import health as scheduler_health
from .software_metrics import summary as software_metrics


def report(root,store,now=None):
    now=time.time() if now is None else now
    config=policy(root);bound=harness_hash(root);certs=certificates(store)
    runs=operational_runs(root,store,now);window=eligibility(root,store,now);tasks=task_index(root)
    blockers=[f'TODO {n:04d} operational acceptance incomplete' for n in range(825,831) if tasks.get(f'{n:04d}',{}).get('status') not in {'done','completed','resolved'}]
    blockers+=window['blockers']
    if not technical_current(root,certs,now):blockers.append('current technical certificate not PASS')
    latest=certs[-1] if certs else {};evidence=latest.get('evidence',{})
    for component in ('oracle','deployment_agent'):
        c=evidence.get(component,{})
        if (c.get('status')!='PASS' or c.get('fixture_only') is not False or c.get('harness_hash')!=bound
            or not 0<=now-c.get('created',0)<=86400 or not 0<c.get('expires_at',0)-now<=86400):blockers.append('current real '+component+' certificate not PASS')
    protection=evidence.get('github',{})
    if protection.get('status')!='PASS' or not 0<=now-protection.get('created',0)<=min(300,config.get('github_evidence_max_age_seconds',300)):blockers.append('current effective GitHub protection not PASS')
    if config.get('emergency_stop') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'}:blockers.append('emergency stop active')
    if config.get('auto_merge') or config.get('required_human_merge') is not True:blockers.append('human merge boundary invalid')
    if config.get('autonomous_implementation') is not False:blockers.append('promotion preparation requires autonomy disabled')
    events=[]
    for candidate in store.list(500):events+=candidate['events']
    events+=store.events('AUTONOMY_PAUSE')+store.events('AUTONOMY_RESUME')
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
    return dict(version='software-promotion-report-1',created=now,harness_hash=bound,safety_configuration=config,recommendation='NO-GO' if blockers else 'GO_FOR_OWNER_STAGE_REVIEW',recommended_stage='SHADOW' if blockers else 'BUILD_ONLY',blockers=list(dict.fromkeys(blockers)),qualifying_runs=qualifying,non_qualifying_attempts=[{k:r.get(k) for k in ('candidate','run_id','head','created','reason')} for r in runs['non_qualifying']],failed_attempts=[dict(candidate=e.get('candidate'),created=e['created'],stage=e['payload']['stage']) for e in failures],observation_window=window,scheduler=scheduler_health(store,now),metrics=software_metrics(store),enables_autonomy=False,grants_merge=False,grants_deployment=False,investment_performance_used=False)
