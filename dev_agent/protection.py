"""0805: fresh, attributable, policy-stable protection at every lifecycle boundary."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .store import digest

REQUIRED={'pr','checks','review','stale','last_push','conversation','no_force','no_delete','admin'}
DENIED={'direct_push','bypass_review','bypass_checks','force_push','delete_ref','bypass_conversations','self_approve'}


def require(store, cid, client, stage, *, root=None, observation=None, now=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    maximum = min(300, json.loads((root/'config/development_agent.json').read_text()).get('github_evidence_max_age_seconds',300))
    data = observation if observation is not None else client.protections()
    if not isinstance(data,dict):data={'status':'UNAVAILABLE'}
    now = time.time() if now is None else now
    raw = data.get('evidence')
    details=raw if isinstance(raw,dict) else {}
    account=details.get('identity') if isinstance(details.get('identity'),dict) else {}
    repository=details.get('repository') if isinstance(details.get('repository'),dict) else {}
    identity_id=account.get('id')
    repository_id=repository.get('id')
    normalized = {k:data.get(k) for k in ('effective','required_checks','agent_capabilities')}
    policy_hash = digest(normalized)
    candidate = store.get(cid)
    scope = [e['payload']['context'] for e in candidate['events'] if e['kind']=='PLAN']
    context_hash = digest(scope[-1]) if scope else None
    receipts=[e['payload']['receipt'] for e in candidate['events'] if e['kind']=='RECEIPT']
    head=(scope[-1].get('head') if scope else None) if stage=='start' else (receipts[-1]['head'] if receipts else scope[-1].get('head') if scope else None)
    prior = [e['payload'] for e in candidate['events'] if e['kind']=='PROTECTION' and e['payload'].get('context_hash')==context_hash and e['payload'].get('status')=='PASS']
    failures=[e for e in candidate['events'] if e['kind']=='PROTECTION' and e['payload'].get('context_hash')==context_hash and e['payload'].get('status')!='PASS']
    reason = None
    if (data.get('status')!='PASS' or not isinstance(raw,dict) or digest(raw)!=data.get('evidence_hash') or
        not isinstance(data.get('created'), (int,float)) or not 0<=now-data['created']<=maximum or
        not data.get('identity') or data.get('repository')!=client.repository or
        not isinstance(data.get('effective'),dict) or not REQUIRED<=data['effective'].keys() or not all(v is True for v in data['effective'].values()) or
        not isinstance(data.get('agent_capabilities'),dict) or not DENIED<=data['agent_capabilities'].keys() or not all(v is False for v in data['agent_capabilities'].values()) or
        type(identity_id) is not int or identity_id<=0 or type(repository_id) is not int or repository_id<=0 or
        raw['identity'].get('login')!=data['identity'] or raw['repository'].get('full_name')!=client.repository):
        reason = 'fresh attributable effective-protection PASS required'
    elif failures:
        reason='protection failure requires fresh human scope approval'
    elif prior and any(p['identity']!=data['identity'] or p['identity_id']!=identity_id or p['repository_id']!=repository_id or p['repository']!=client.repository or p['policy_hash']!=policy_hash for p in prior):
        reason = 'effective protection or coding-agent identity changed'
    elif stage!='start' and not any(p['stage']=='start' for p in prior):
        reason = 'start protection lineage missing'
    record = dict(candidate=cid,head=head,stage=stage,created=data.get('created'),observed_at=now,identity=data.get('identity'),identity_id=identity_id,repository_id=repository_id,
                  repository=client.repository,normalized_policy=normalized,policy_hash=policy_hash,
                  raw_evidence_hash=data.get('evidence_hash'),context_hash=context_hash,
                  status='FAIL' if reason else 'PASS',reason=reason)
    with store.connect(True) as db:
        store._append(db,cid,'PROTECTION',record,'protection:'+digest(record))
    if reason:
        if candidate['state'] in {'APPROVED','BUILDING','PR_OPEN','DEPLOYED'}:
            store.transition(cid,'NEEDS_HUMAN',{'reason':reason,'stage':stage})
        raise ValueError(reason)
    return record
