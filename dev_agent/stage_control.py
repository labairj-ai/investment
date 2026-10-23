"""Shadow → build-only → PR stage admission. Never edits autonomy configuration."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from .certification import harness_hash,technical_current
from .operations import certificates,eligibility
from .discovery import task_index

STAGES=('SHADOW','BUILD_ONLY','PR')


def report(root,store,now=None,*,protections=None,technical=None):
    now=time.time() if now is None else now
    from .operations import policy as control_policy
    config=control_policy(root);stage=config.get('autonomy_stage','SHADOW');findings=[]
    if stage not in STAGES:findings.append('unknown autonomy stage')
    if config.get('auto_merge') or config.get('required_human_merge') is not True:findings.append('human merge boundary invalid')
    if config.get('autonomous_max_risk')!='L2':findings.append('risk ceiling must remain L2')
    cap=config.get('daily_implementation_cap',1)
    if type(cap) is not int or not 0<=cap<=3:findings.append('daily cap malformed or exceeds hard maximum three')
    if config.get('emergency_stop') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'}:findings.append('emergency stop or environment kill switch')
    certs=certificates(store) if technical is None else technical;current=technical_current(root,certs,now)
    if not current:findings.append('current complete technical certificate required')
    deployment=(certs[-1].get('evidence',{}).get('deployment_agent',{}) if certs else {})
    if deployment.get('status')!='PASS' or deployment.get('harness_hash')!=harness_hash(root) or not 0<=now-deployment.get('created',0)<=86400:findings.append('current deployment-agent certification required')
    snapshot=(certs[-1].get('evidence',{}).get('snapshot',{}) if certs else {})
    if snapshot.get('status')!='PASS' or not 0<=now-snapshot.get('backup_timestamp',0)<=min(24,config.get('snapshot_max_age_hours',24))*3600:findings.append('current authenticated snapshot evidence required')
    github=protections if protections is not None else (certs[-1].get('evidence',{}).get('github',{}) if certs else {})
    if github.get('status')!='PASS' or not 0<=now-github.get('created',0)<=min(300,config.get('github_evidence_max_age_seconds',300)):findings.append('fresh GitHub protection evidence required')
    try:tasks=task_index(root)
    except ValueError:
        tasks={};findings.append('TODO dependency inventory is untrusted')
    if any(tasks.get(f'{n:04d}',{}).get('status') not in {'done','completed','resolved'} for n in range(816,824)):findings.append('TODOs 0816-0823 require complete operational acceptance')
    progress=eligibility(root,store,now)
    if not progress['eligible']:findings.extend(progress['blockers'])
    history=[]
    if store.path.exists():
        with store.connect() as db:
            history=[dict(kind=r[0],payload=json.loads(r[1])) for r in db.execute("SELECT kind,payload FROM dev_events WHERE kind IN ('PIPELINE','AUTONOMY_PAUSE','DEPLOYMENT','STAGE_OBSERVATION','AUTONOMY_RESUME') ORDER BY seq DESC LIMIT 500")]
    resumed=max([r['payload'].get('created',0) for r in history if r['kind']=='AUTONOMY_RESUME']+[0])
    history=[r for r in history if r['kind'] in {'STAGE_OBSERVATION','AUTONOMY_RESUME'} or r['payload'].get('created',r['payload'].get('observed_at',0))>=resumed]
    failures=[r for r in history if r['kind']=='PIPELINE' and r['payload'].get('stage') in {'FAILED','NEEDS_HUMAN'}][:3]
    if len(failures)>=3:findings.append('repeated improvement failures require owner review')
    if any(r['kind']=='AUTONOMY_PAUSE' for r in history):findings.append('explicit autonomy pause remains active')
    if any(r['kind']=='DEPLOYMENT' and r['payload'].get('status') in {'DEGRADED','ROLLED_BACK'} for r in history):findings.append('abnormal deployment outcome requires owner review')
    counts={s:len({r['payload'].get('candidate',r['payload'].get('cycle')) for r in history if r['kind']=='STAGE_OBSERVATION' and r['payload'].get('stage')==s and r['payload'].get('harness_hash')==harness_hash(root) and not r['payload'].get('fixture_only')}) for s in STAGES}
    if stage in {'BUILD_ONLY','PR'} and counts['SHADOW']<3:findings.append('three observed shadow cycles required')
    if stage=='PR' and counts['BUILD_ONLY']<3:findings.append('three distinct build-only validations required')
    enabled=config.get('autonomous_implementation') is True
    if enabled and stage!='PR':findings.append('autonomous implementation allowed only at PR stage')
    from .store import digest
    return dict(runtime_policy_hash=digest(config),stage=stage,autonomous_implementation=enabled,eligible=enabled and stage=='PR' and not findings,blockers=list(dict.fromkeys(findings)),stage_counts=counts,daily_cap=cap,hard_maximum=3,grants_merge=False,grants_deployment=False)


def require(root,store,*,protections=None,technical=None):
    result=report(root,store,protections=protections,technical=technical)
    if not result['eligible']:raise ValueError('bounded autonomy stage/evidence admission failed: '+', '.join(result['blockers']))
    return result


def observe(store,stage,*,candidate,head,harness,receipt,fixture=False):
    # Trusted orchestration supplies verified source/receipt linkage; not request JSON.
    if stage not in STAGES or not candidate or not head or not receipt:raise ValueError('bound stage observation required')
    payload=dict(stage=stage,candidate=candidate,head=head,harness_hash=harness,receipt=receipt,created=time.time(),fixture_only=fixture)
    with store.connect(True) as db:store._append(db,candidate,'STAGE_OBSERVATION',payload,'stage-observation:'+stage+':'+candidate+':'+head)
    return payload


def resume(root,store,*,human,rationale,nonce):
    from .identity import HumanIdentity
    from .owner_review import policy
    owner=policy()
    if type(human) is not HumanIdentity or human.actor not in owner['operators'].get(human.source,[]) or not rationale.strip() or not nonce:raise ValueError('explicit authenticated owner pause review required')
    payload=dict(created=time.time(),rationale=rationale,harness_hash=harness_hash(root),decision_nonce=nonce,**human.audit())
    with store.connect(True) as db:
        key='autonomy-resume:'+nonce
        if db.execute('SELECT 1 FROM dev_events WHERE event_id=?',(key,)).fetchone():raise ValueError('resume replay')
        store._append(db,None,'AUTONOMY_RESUME',payload,key)
    return dict(status='REVIEW_RECORDED',enables_autonomy=False)
