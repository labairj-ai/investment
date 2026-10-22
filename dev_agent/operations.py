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
            elif candidate['state'] not in {'DEPLOYED','CLOSED'} or not deployments or deployments[-1]['status']!='HEALTHY': reason='not observed healthy or rolled back'
            elif item.get('created',now+1)>now: reason='future evidence'
            (rejected if reason else accepted).append(dict(item, reason=reason) if reason else item)
    unique={r['run_id']:r for r in accepted}
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
    if config.get('auto_merge') or not config.get('required_human_merge'): raise ValueError('human merge boundary must remain enforced')
    context=[e['payload']['context'] for e in candidate['events'] if e['kind']=='PLAN'][-1]
    approvals=[e['payload'] for e in candidate['events'] if e['kind']=='APPROVAL']
    if context.get('validation_hash')!=digest([e['payload'] for e in candidate['events'] if e['kind']=='PLAN'][-1].get('focused_tests',['tests/test_development_agent.py'])): raise ValueError('validation scope changed after approval')
    if candidate['state']!='APPROVED' or not approvals or not approvals[-1].get('authentication_source') or approvals[-1]['context']!=context or context.get('mode')!=mode:
        raise ValueError('fresh frozen mode/scope/base approval required')
    if not technical_current(root,technical,now): raise ValueError('current technical certification required')
    if protections.get('status')!='PASS' or not 0<=now-protections.get('created',0)<=300: raise ValueError('fresh effective GitHub protection required')
    risk=int(context['risk'][1:])
    if risk>=4: raise ValueError('L4/L5 unavailable to generic Builder')
    if mode=='SUPERVISED':
        if type(human) is not HumanIdentity or not approvals[-1].get('authentication_source'):
            raise ValueError('authenticated approval and explicit human invocation required')
    else:
        if not config.get('autonomous_implementation') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'} or config.get('emergency_stop',False): raise ValueError('autonomous starts disabled')
        if risk>2: raise ValueError('L3 requires human-started supervised mode')
        if not eligibility(root,store,now)['eligible']: raise ValueError('supervised observation requirements not met')
    slot=datetime.fromtimestamp(now,ZoneInfo('America/New_York')).date().isoformat()
    payload=dict(candidate=cid,context=context,mode=mode,harness_hash=harness_hash(root),created=now,slot=slot,**(human.audit() if human else {'actor':'policy-admission','authentication_source':'autonomy-policy','nonce':str(uuid.uuid4())}))
    with store.connect(True) as db:
        if mode=='AUTONOMOUS':
            count=db.execute("SELECT COUNT(*) FROM dev_events WHERE kind='START_AUTHORIZATION' AND json_extract(payload,'$.mode')='AUTONOMOUS' AND json_extract(payload,'$.slot')=?",(slot,)).fetchone()[0]
            if count>=min(3,max(0,config.get('daily_implementation_cap',1))): raise ValueError('daily implementation limit reached')
        store._append(db,cid,'START_AUTHORIZATION',payload,'start:'+payload['nonce'])
    return payload


def record_success(root,store,cid,client,*,human):
    """Human closes a real, independently reviewed, deployed and observed pilot."""
    from .certification import harness_hash
    from .github import verify_remote_pr
    if type(human) is not HumanIdentity: raise ValueError('authenticated human required')
    candidate=store.get(cid);events=candidate['events']
    def latest(kind):
        rows=[e['payload'] for e in events if e['kind']==kind]
        if not rows: raise ValueError('pilot lineage missing: '+kind)
        return rows[-1]
    context=latest('PLAN')['context']; approval=latest('APPROVAL');start=latest('START_AUTHORIZATION');run=[e['payload'] for e in events if e['kind']=='RUN' and e['payload']['role']=='builder'][-1];iteration=latest('ITERATION');proof=latest('RECEIPT')['receipt'];pr=latest('PR');decision=latest('HUMAN_REVIEW');deployment=latest('DEPLOYMENT')
    if start['mode']!='SUPERVISED' or not approval.get('authentication_source') or not start.get('authentication_source') or start['context']!=context or approval['context']!=context:
        raise ValueError('authenticated supervised scope lineage required')
    if start['harness_hash']!=harness_hash(root) or run['data'].get('fixture_only') or run['data'].get('mode')!='SUPERVISED' or run['status']!='PASS' or run['data'].get('provider',{}).get('provider')=='replay': raise ValueError('real supervised builder run required')
    reviews=[e['payload'] for e in events if e['kind']=='RUN' and e['payload']['role']=='reviewer']
    if not reviews or reviews[-1]['status']!='PASS' or reviews[-1]['data'].get('head')!=proof['head'] or reviews[-1]['data'].get('source_hash')!=proof['source_hash'] or not reviews[-1]['data'].get('independent_context'): raise ValueError('exact-head independent reviewer run required')
    if iteration['review']['disposition']!='PASS' or iteration.get('fixture_only') or not proof.get('trusted_validation') or proof.get('status')!='PASS': raise ValueError('trusted complete validation and independent review required')
    records=proof.get('validations',[])
    from .validation import GATES
    if len(records)!=len(GATES) or {r['name'] for r in records}!=set(GATES) or any(r.get('status')!='PASS' or r.get('exit_code')!=0 or r.get('candidate')!=cid or r.get('head')!=proof['head'] for r in records): raise ValueError('complete exact-head trusted gate inventory required')
    if not any(e['kind']=='VALIDATION_BATCH' and e['payload']['batch']==proof.get('batch') and not e['payload'].get('fixture_only') for e in events): raise ValueError('trusted validation batch required')
    if decision.get('stage')!='PR_DISPOSITION' or decision.get('decision')!='accept' or not decision.get('authentication_source') or decision['context'].get('head')!=proof['head']: raise ValueError('authenticated exact-head human PR disposition required')
    if int(context['risk'][1:])>2 or proof['head']!=pr['head'] or proof.get('mode')!='SUPERVISED': raise ValueError('low-risk exact-head pilot required')
    remote=client.pr_identity(pr['result']['number'])
    verify_remote_pr(remote,repository=client.repository,branch=pr['verified']['headRefName'],head=proof['head'])
    if remote.get('reviewDecision')!='APPROVED' or remote.get('state')!='MERGED' or not remote.get('mergeCommit',{}).get('oid'): raise ValueError('independently approved merged PR required')
    if candidate['state'] not in {'DEPLOYED','CLOSED'} or deployment['status']!='HEALTHY' or deployment['deployed_sha']!=remote['mergeCommit']['oid'] or deployment['merge_sha']!=remote['mergeCommit']['oid']: raise ValueError('exact deployed-SHA healthy observation required')
    item=dict(candidate=cid,run_id=run['run_id'],context=context,mode='SUPERVISED',head=proof['head'],receipt=proof['id'],harness_hash=harness_hash(root),created=time.time(),fixture_only=False,**human.audit())
    with store.connect(True) as db:
        old=db.execute("SELECT payload FROM dev_events WHERE event_id=?",('operational-success:'+run['run_id'],)).fetchone()
        if old: return json.loads(old[0])
        store._append(db,cid,'OPERATIONAL_SUCCESS',item,'operational-success:'+run['run_id'])
    return item
