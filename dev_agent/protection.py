"""0805: fresh, attributable, policy-stable protection at every lifecycle boundary."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .store import digest


def require(store, cid, client, stage, *, root=None, observation=None, now=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    maximum = min(300, json.loads((root/'config/development_agent.json').read_text()).get('github_evidence_max_age_seconds',300))
    data = observation if observation is not None else client.protections()
    now = time.time() if now is None else now
    raw = data.get('evidence')
    normalized = {k:data.get(k) for k in ('effective','required_checks','agent_capabilities')}
    policy_hash = digest(normalized)
    candidate = store.get(cid)
    scope = [e['payload']['context'] for e in candidate['events'] if e['kind']=='PLAN']
    context_hash = digest(scope[-1]) if scope else None
    receipts=[e['payload']['receipt'] for e in candidate['events'] if e['kind']=='RECEIPT']
    head=(scope[-1].get('head') if scope else None) if stage=='start' else (receipts[-1]['head'] if receipts else scope[-1].get('head') if scope else None)
    prior = [e['payload'] for e in candidate['events'] if e['kind']=='PROTECTION' and e['payload'].get('context_hash')==context_hash and e['payload'].get('status')=='PASS']
    reason = None
    if (data.get('status')!='PASS' or not isinstance(raw,dict) or digest(raw)!=data.get('evidence_hash') or
        not isinstance(data.get('created'), (int,float)) or not 0<=now-data['created']<=maximum or
        not data.get('identity') or data.get('repository')!=client.repository or
        not isinstance(data.get('effective'),dict) or not data['effective'] or not all(data['effective'].values())):
        reason = 'fresh attributable effective-protection PASS required'
    elif prior and any(p['identity']!=data['identity'] or p['repository']!=client.repository or p['policy_hash']!=policy_hash for p in prior):
        reason = 'effective protection or coding-agent identity changed'
    elif stage!='start' and not any(p['stage']=='start' for p in prior):
        reason = 'start protection lineage missing'
    record = dict(candidate=cid,head=head,stage=stage,created=data.get('created'),observed_at=now,identity=data.get('identity'),
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
