"""Execution admission and prospective supervised pilot evidence. No merge/deploy tools."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime

from .identity import HumanIdentity
from .store import digest

MODES={'SUPERVISED','AUTONOMOUS'}


def policy(root):
    return json.loads((Path(root)/'config/development_agent.json').read_text())


def certificates(store):
    if not store.path.exists(): return []
    with store.connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM dev_events WHERE kind='TECHNICAL_CERTIFICATION' ORDER BY seq")]


def operational_runs(root,store,now=None):
    from .certification import harness_hash
    bound=harness_hash(root); now=time.time() if now is None else now
    accepted=[]; rejected=[]
    for candidate in store.list(500):
        successes=[e['payload'] for e in candidate['events'] if e['kind']=='OPERATIONAL_SUCCESS']
        for item in successes:
            events=candidate['events']
            receipt=[e['payload']['receipt'] for e in events if e['kind']=='RECEIPT' and e['payload']['receipt']['id']==item.get('receipt')]
            deployments=[e['payload'] for e in events if e['kind']=='DEPLOYMENT']
            latest_plan=[e['payload']['context'] for e in events if e['kind']=='PLAN']
            reason=None
            if item.get('harness_hash')!=bound: reason='stale harness/config/contracts'
            elif item.get('fixture_only') or item.get('mode')!='SUPERVISED': reason='fixture or wrong mode'
            elif not receipt or receipt[-1].get('head')!=item.get('head'): reason='receipt missing'
            elif not latest_plan or latest_plan[-1]!=item.get('context'): reason='scope changed'
            elif any(e['kind']=='PROTECTION' and e['payload'].get('context_hash')==digest(item.get('context')) and e['payload'].get('status')!='PASS' for e in events): reason='protection drift recorded; fresh human scope required'
            elif candidate['state'] not in {'DEPLOYED','CLOSED'} or not deployments or deployments[-1]['status']!='HEALTHY': reason='not observed healthy or rolled back'
            elif item.get('created',now+1)>now: reason='future evidence'
            if reason is None:
                try:
                    from .deployment_evidence import qualifying
                    d=deployments[-1];p=next(e['payload'] for e in reversed(events) if e['kind']=='PR')
                    qualifying(d.get('deployment_evidence'),repository=d['deployment_evidence']['receipt']['repository'],pr=p['result']['number'],head=item['head'],merge_sha=d['merge_sha'],expected_sha256=item.get('deployment_evidence_sha256',''))
                except (ValueError,KeyError,TypeError,StopIteration):reason='missing or invalid deployment receipt'
            (rejected if reason else accepted).append(dict(item, reason=reason) if reason else item)
    unique={};releases=set()
    for item in accepted:
        candidate=store.get(item['candidate'])
        deployment=next(e['payload'] for e in reversed(candidate['events']) if e['kind']=='DEPLOYMENT')
        r=deployment['deployment_evidence']['receipt'];release=(r['repository'],r['pr'],r['merge_sha'])
        if release in releases or item['run_id'] in unique:rejected.append(dict(item,reason='duplicate operational run or PR release'))
        else:unique[item['run_id']]=item;releases.add(release)
    return dict(qualifying=list(unique.values()),non_qualifying=rejected)


def eligibility(root,store,now=None):
    now=time.time() if now is None else now
    config=policy(root); runs=operational_runs(root,store,now)['qualifying']
    times=sorted(r['created'] for r in runs)
    # Calendar days in the established application timezone, including DST.
    days=(datetime.fromtimestamp(times[-1],ZoneInfo('America/New_York')).date()-datetime.fromtimestamp(times[0],ZoneInfo('America/New_York')).date()).days if times else 0
    blockers=[]
    if config.get('minimum_supervised_successes',0)<3 or config.get('minimum_observation_days',0)<7: blockers.append('policy certification minima weakened')
    if len(runs)<max(3,config.get('minimum_supervised_successes',3)): blockers.append('insufficient qualifying supervised runs')
    if days<max(7,config.get('minimum_observation_days',7)): blockers.append('seven-day prospective observation incomplete')
    return dict(eligible=not blockers,blockers=blockers,completed=len(runs),required=max(3,config.get('minimum_supervised_successes',3)),observation_days=days,required_days=max(7,config.get('minimum_observation_days',7)),first=times[0] if times else None,last=times[-1] if times else None)


def authorize_start(root,store,cid,mode,technical,protections,*,human=None,now=None):
    from .certification import technical_current, harness_hash
    if mode not in MODES: raise ValueError('explicit execution mode required')
    now=time.time() if now is None else now
    config=policy(root); candidate=store.get(cid)
    if config.get('emergency_stop') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'}:raise ValueError('starts disabled: emergency stop active')
    if config.get('auto_merge') or not config.get('required_human_merge'): raise ValueError('human merge boundary must remain enforced')
    context=[e['payload']['context'] for e in candidate['events'] if e['kind']=='PLAN'][-1]
    approvals=[e['payload'] for e in candidate['events'] if e['kind'] in {'APPROVAL','POLICY_ADMISSION'}]
    if context.get('validation_hash')!=digest([e['payload'] for e in candidate['events'] if e['kind']=='PLAN'][-1].get('focused_tests',['tests/test_development_agent.py'])): raise ValueError('validation scope changed after approval')
    if candidate['state']!='APPROVED' or not approvals or not approvals[-1].get('authentication_source') or approvals[-1]['context']!=context or context.get('mode')!=mode:
        raise ValueError('fresh frozen mode/scope/base approval required')
    if not technical_current(root,technical,now): raise ValueError('current technical certification required')
    if not technical:raise ValueError('current technical certification and snapshot evidence required')
    snapshot=technical[-1].get('evidence',{}).get('snapshot',{})
    if snapshot.get('status')!='PASS' or not 0<=now-snapshot.get('backup_timestamp',0)<=min(24,config.get('snapshot_max_age_hours',24))*3600:raise ValueError('fresh authenticated snapshot required before build')
    from .protection import require
    from types import SimpleNamespace
    authority=require(store,cid,SimpleNamespace(repository=protections.get('repository')),'start',root=root,observation=protections,now=now)
    risk=int(context['risk'][1:])
    if risk>=4: raise ValueError('L4/L5 unavailable to generic Builder')
    if mode=='SUPERVISED':
        delegated=approvals[-1].get('authentication_source')=='owner-build-policy'
        if delegated:
            from .build_policy import current as current_build_policy
            if risk>2 or digest(current_build_policy(root,store))!=approvals[-1].get('policy_hash'):raise ValueError('delegated build policy stale or exceeded')
        elif type(human) is not HumanIdentity or not approvals[-1].get('authentication_source'):
            raise ValueError('authenticated approval and explicit human invocation required')
    else:
        if not config.get('autonomous_implementation') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'} or config.get('emergency_stop',False): raise ValueError('autonomous starts disabled')
        if risk>2: raise ValueError('L3 requires human-started supervised mode')
        if not eligibility(root,store,now)['eligible']: raise ValueError('supervised observation requirements not met')
        from .stage_control import require as require_stage
        require_stage(root,store,protections=protections,technical=technical)
    slot=datetime.fromtimestamp(now,ZoneInfo('America/New_York')).date().isoformat()
    payload=dict(candidate=cid,context=context,mode=mode,harness_hash=harness_hash(root),created=now,slot=slot,protection_policy=authority['policy_hash'],protection_identity=authority['identity'],**(human.audit() if human else {'actor':'owner-delegated-supervised-policy' if mode=='SUPERVISED' else 'policy-admission','authentication_source':'owner-build-policy' if mode=='SUPERVISED' else 'autonomy-policy','nonce':str(uuid.uuid4())}))
    with store.connect(True) as db:
        if mode=='AUTONOMOUS' or approvals[-1].get('authentication_source')=='owner-build-policy':
            count=db.execute("SELECT COUNT(*) FROM dev_events WHERE kind='START_AUTHORIZATION' AND json_extract(payload,'$.slot')=?",(slot,)).fetchone()[0]
            if count>=min(3,max(0,config.get('daily_implementation_cap',1))): raise ValueError('daily implementation limit reached')
        store._append(db,cid,'START_AUTHORIZATION',payload,'start:'+payload['nonce'])
    return payload


def record_success(root,store,cid,client,*,human):
    """Human closes a real, independently reviewed, deployed and observed pilot."""
    from .certification import harness_hash
    from .github import verify_remote_pr
    if type(human) is not HumanIdentity: raise ValueError('authenticated human required')
    from .protection import require
    authority=require(store,cid,client,'pilot_success',root=root)
    candidate=store.get(cid);events=candidate['events']
    def latest(kind):
        rows=[e['payload'] for e in events if e['kind']==kind]
        if not rows: raise ValueError('pilot lineage missing: '+kind)
        return rows[-1]
    context=latest('PLAN')['context']; approvals=[e['payload'] for e in events if e['kind'] in {'APPROVAL','POLICY_ADMISSION'}];approval=approvals[-1] if approvals else {};start=latest('START_AUTHORIZATION');run=[e['payload'] for e in events if e['kind']=='RUN' and e['payload']['role']=='builder'][-1];iteration=latest('ITERATION');proof=latest('RECEIPT')['receipt'];pr=latest('PR');decisions=[e['payload'] for e in events if e['kind']=='HUMAN_REVIEW'];decision=decisions[-1] if decisions else None;deployment=latest('DEPLOYMENT')
    if start['mode']!='SUPERVISED' or not approval.get('authentication_source') or not start.get('authentication_source') or start['context']!=context or approval['context']!=context:
        raise ValueError('authenticated supervised scope lineage required')
    if approval.get('authentication_source')=='owner-build-policy':
        from .owner_review import policy as owner_policy
        policies=[e['payload'] for e in store.events('BUILD_POLICY')]
        parent=next((p for p in policies if digest(p)==approval.get('policy_hash')),None)
        owner=owner_policy()
        if parent is None:
            from .build_policy import current as source_build_policy
            proposed=source_build_policy(root,store)
            if proposed.get('source')=='reviewed-supervised-scope' and digest(proposed)==approval.get('policy_hash'):parent=proposed
        if not parent or parent['owner_policy_hash']!=digest(owner) or parent['harness_hash']!=harness_hash(root) or not parent['created']<=start['created']<parent['expires_at']:raise ValueError('authenticated delegated owner build lineage required')
    if start['harness_hash']!=harness_hash(root) or run['data'].get('fixture_only') or run['data'].get('mode')!='SUPERVISED' or run['status']!='PASS' or run['data'].get('provider',{}).get('provider')=='replay': raise ValueError('real supervised builder run required')
    reviews=[e['payload'] for e in events if e['kind']=='RUN' and e['payload']['role']=='reviewer']
    if not reviews or reviews[-1]['status']!='PASS' or reviews[-1]['data'].get('head')!=proof['head'] or reviews[-1]['data'].get('source_hash')!=proof['source_hash'] or not reviews[-1]['data'].get('independent_context'): raise ValueError('exact-head independent reviewer run required')
    if iteration['review']['disposition']!='PASS' or iteration.get('fixture_only') or not proof.get('trusted_validation') or proof.get('status')!='PASS': raise ValueError('trusted complete validation and independent review required')
    records=proof.get('validations',[])
    from .validation import GATES
    if len(records)!=len(GATES) or {r['name'] for r in records}!=set(GATES) or any(r.get('status')!='PASS' or r.get('exit_code')!=0 or r.get('candidate')!=cid or r.get('head')!=proof['head'] for r in records): raise ValueError('complete exact-head trusted gate inventory required')
    if not any(e['kind']=='VALIDATION_BATCH' and e['payload']['batch']==proof.get('batch') and not e['payload'].get('fixture_only') for e in events): raise ValueError('trusted validation batch required')
    if decision is not None and (decision.get('stage')!='PR_DISPOSITION' or decision.get('decision')!='accept' or not decision.get('authentication_source') or decision['context'].get('head')!=proof['head']): raise ValueError('authenticated exact-head human PR disposition required')
    observations=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='PROTECTION' and e['payload'].get('context_hash')==digest(context)]
    required_stages={'start','publish','pr_handoff','pr_disposition','merge','deployment_observation','pilot_success'}
    if (required_stages-{o['stage'] for o in observations} or
        any(o['status']!='PASS' or o['identity']!=authority['identity'] or o['policy_hash']!=authority['policy_hash'] or
            (o['stage']!='start' and o.get('head')!=proof['head']) for o in observations)):
        raise ValueError('complete stable exact-head protection lifecycle required')
    merged=latest('MERGE')
    if merged.get('source')!='github-verified-merge' or merged.get('head')!=proof['head'] or merged.get('protection_policy')!=authority['policy_hash']:
        raise ValueError('fresh protection-bound verified merge required')
    if int(context['risk'][1:])>2 or proof['head']!=pr['head'] or proof.get('mode')!='SUPERVISED': raise ValueError('low-risk exact-head pilot required')
    remote=client.pr_identity(pr['result']['number'])
    verify_remote_pr(remote,repository=client.repository,branch=pr['verified']['headRefName'],head=proof['head'])
    from .owner_review import require as require_owner,verify_merge_actor
    owner_approval=require_owner(store,client,remote['number'])
    verify_merge_actor(client,remote['number'],proof['head'],remote.get('mergeCommit',{}).get('oid'))
    if remote.get('state')!='MERGED' or not remote.get('mergeCommit',{}).get('oid'): raise ValueError('exact-head owner-approved merged PR required')
    if candidate['state'] not in {'DEPLOYED','CLOSED'} or deployment['status']!='HEALTHY' or deployment['deployed_sha']!=remote['mergeCommit']['oid'] or deployment['merge_sha']!=remote['mergeCommit']['oid']: raise ValueError('exact deployed-SHA healthy observation required')
    if merged['merge_sha']!=remote['mergeCommit']['oid']:raise ValueError('merge identity changed')
    from .deployment_evidence import qualifying
    deployment_proof=deployment.get('deployment_evidence')
    qualifying(deployment_proof,repository=client.repository,pr=remote['number'],head=proof['head'],merge_sha=remote['mergeCommit']['oid'])
    item=dict(deployment_evidence_sha256=deployment_proof['sha256'],candidate=cid,run_id=run['run_id'],context=context,mode='SUPERVISED',head=proof['head'],receipt=proof['id'],owner_review_hash=digest(owner_approval['review']),owner_review_origin=owner_approval['review'].get('origin'),harness_hash=harness_hash(root),created=time.time(),fixture_only=False,protection_policy=authority['policy_hash'],protection_identity=authority['identity'],**human.audit())
    with store.connect(True) as db:
        old=db.execute("SELECT payload FROM dev_events WHERE event_id=?",('operational-success:'+run['run_id'],)).fetchone()
        if old: return json.loads(old[0])
        store._append(db,cid,'OPERATIONAL_SUCCESS',item,'operational-success:'+run['run_id'])
    return item
