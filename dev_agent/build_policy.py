"""Authenticated owner delegation of bounded supervised build scope, not PR approval."""
from __future__ import annotations
import fnmatch
import json
import time
import uuid
from .certification import harness_hash
from .identity import HumanIdentity
from .owner_review import policy as owner_policy
from .policy import classify,protected_graph,GOVERNANCE,matches
from .store import digest


def approve(root,store,patterns,*,human,nonce,rationale,expires_at):
    owner=owner_policy();now=time.time()
    if type(human) is not HumanIdentity or human.actor not in owner['operators'].get(human.source,[]):raise ValueError('authenticated owner policy action required')
    if not patterns or len(patterns)>20 or any(not isinstance(p,str) or p.startswith('/') or '..' in p.split('/') for p in patterns):raise ValueError('bounded relative patterns required')
    if not rationale.strip() or not nonce or not now<expires_at<=now+7*86400:raise ValueError('explicit expiring owner delegation required')
    payload=dict(patterns=patterns,max_risk='L2',harness_hash=harness_hash(root),created=now,expires_at=expires_at,rationale=rationale,decision_nonce=nonce,owner_policy_hash=digest(owner),**human.audit())
    with store.connect(True) as db:
        key='build-policy:'+nonce
        if db.execute('SELECT 1 FROM dev_events WHERE event_id=?',(key,)).fetchone():raise ValueError('policy replay')
        store._append(db,None,'BUILD_POLICY',payload,key)
    return payload


def current(root,store):
    with store.connect() as db:row=db.execute("SELECT payload FROM dev_events WHERE kind='BUILD_POLICY' ORDER BY seq DESC LIMIT 1").fetchone()
    if not row:
        # The reviewed source defines the initial supervised scope. No recurring
        # owner delegation ceremony is needed before preparing an L0 PR.
        return dict(patterns=['docs/help/*.md','docs/help/*.txt'],max_risk='L0',
                    source='reviewed-supervised-scope',harness_hash=harness_hash(root),
                    owner_policy_hash=digest(owner_policy()),created=0,expires_at=253402300799)

    p=json.loads(row[0]);owner=owner_policy()
    if not p['created']<=time.time()<p['expires_at'] or p['harness_hash']!=harness_hash(root) or p['owner_policy_hash']!=digest(owner) or p.get('actor') not in owner['operators'].get(p.get('authentication_source'),[]):raise ValueError('owner build policy stale')
    return p


def admit(root,store,cid):
    p=current(root,store);candidate=store.get(cid)
    plan=[e['payload'] for e in candidate['events'] if e['kind']=='PLAN'][-1];context=plan['context']
    risk=classify(candidate['files'],graphs=[protected_graph(root)])
    if int(risk['risk'][1:])>min(2,int(p['max_risk'][1:])) or int(context['risk'][1:])>min(2,int(p['max_risk'][1:])) or any(matches(name,GOVERNANCE) or not any(fnmatch.fnmatchcase(name,pattern) for pattern in p['patterns']) for name in candidate['files']):raise ValueError('candidate exceeds delegated owner policy')
    if candidate['state']!='PLANNED' or context.get('mode')!='SUPERVISED':raise ValueError('frozen supervised plan required')
    payload=dict(context=context,policy_hash=digest(p),actor='owner-delegated-build-policy',authentication_source='owner-build-policy',created=time.time(),nonce=str(uuid.uuid4()),grants_merge=False,grants_deployment=False)
    with store.connect(True) as db:
        store._append(db,cid,'POLICY_ADMISSION',payload,'policy-admission:'+payload['nonce'])
        store._append(db,cid,'STATE',dict(state='APPROVED'),'policy-state:'+payload['nonce'])
    return payload
