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
    from .qualification import evaluate
    evidence=evaluate(root,store,now,protections=protections,technical=technical)
    findings.extend(evidence['blockers'])
    history=[]
    if store.path.exists():
        with store.connect() as db:
            history=[dict(kind=r[0],payload=json.loads(r[1])) for r in db.execute("SELECT kind,payload FROM dev_events WHERE kind IN ('PIPELINE','AUTONOMY_PAUSE','DEPLOYMENT','STAGE_OBSERVATION','AUTONOMY_RESUME') ORDER BY seq DESC LIMIT 500")]
    counts={s:len({r['payload'].get('candidate',r['payload'].get('cycle')) for r in history if r['kind']=='STAGE_OBSERVATION' and r['payload'].get('stage')==s and r['payload'].get('harness_hash')==harness_hash(root) and not r['payload'].get('fixture_only')}) for s in STAGES}
    if stage in {'BUILD_ONLY','PR'} and counts['SHADOW']<3:findings.append('three observed shadow cycles required')
    if stage=='PR' and counts['BUILD_ONLY']<3:findings.append('three distinct build-only validations required')
    cap=config.get('daily_implementation_cap',1)
    enabled=config.get('autonomous_implementation') is True
    if enabled and stage!='PR':findings.append('autonomous implementation allowed only at PR stage')
    # Stages are internal evidence, not a sequence of owner approvals.
    from .owner_promotion import activation_authority
    try:owner=activation_authority(root,store,now=now)
    except Exception:
        owner=dict(status='UNAVAILABLE',reason='exact-head activation PR owner Go unavailable')
        findings.append(owner['reason'])
    from .store import digest
    return dict(evidence=evidence,owner_promotion=owner,runtime_policy_hash=digest(config),stage=stage,autonomous_implementation=enabled,eligible=enabled and stage=='PR' and not findings,blockers=list(dict.fromkeys(findings)),stage_counts=counts,daily_cap=cap,hard_maximum=3,grants_merge=False,grants_deployment=False)


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
