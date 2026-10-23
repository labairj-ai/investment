"""Solo-owner authority: explicit authenticated human acts, never model output.

The trusted operator mapping is deployment configuration, not candidate JSON.
The agent service must not possess the owner's authentication credentials.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from .identity import HumanIdentity, _PROOF
from .store import digest

MODEL = 'solo-owner-1'
SOURCES = {'os-interactive-cli', 'tailscale-serve'}


def policy():
    raw=os.environ.get('DEV_AGENT_OWNER_BINDINGS','')
    try:
        data=json.loads(raw)
        if set(data)!={'repository','owner_login','owner_id','operators'}: raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',data['repository']): raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9-]+',data['owner_login']) or type(data['owner_id']) is not int or data['owner_id']<=0: raise ValueError()
        if not isinstance(data['operators'],dict) : raise ValueError()
        for source,actors in data['operators'].items():
            if source not in SOURCES or not isinstance(actors,list) or not actors or any(not isinstance(a,str) or not a.strip() for a in actors): raise ValueError()
        return data
    except (ValueError,TypeError,KeyError): raise ValueError('operator-controlled owner bindings unavailable') from None


def owner_identity(handler=None):
    if handler is None:
        from .identity import cli_identity
        human=cli_identity()
    else:
        from .identity import dashboard_identity
        verified=dashboard_identity(handler)
        human=HumanIdentity(verified.actor,'tailscale-serve',_PROOF)
    p=policy()
    if human.actor not in p['operators'].get(human.source,[]): raise ValueError('authenticated operator is not repository owner')
    return human


def context(client,number,*,risk):
    """Bind the deliberate review to GitHub's current PR identity, never authorship."""
    if type(number) is not int or number<=0 or not re.fullmatch(r'L[0-5]',risk): raise ValueError('PR/risk required')
    p=policy()
    if p['repository']!=client.repository: raise ValueError('owner repository mismatch')
    repo=client.read('repos/'+client.repository)
    owner=repo.get('owner',{})
    if owner.get('type')!='User' or owner.get('id')!=p['owner_id'] or owner.get('login')!=p['owner_login'] or repo.get('full_name')!=client.repository: raise ValueError('personal repository owner mismatch')
    pr=client.pr_identity(number)
    if pr.get('number')!=number or pr.get('baseRefName')!='main' or pr.get('state') not in {'OPEN','MERGED'}: raise ValueError('current main PR required')
    if not re.fullmatch(r'[a-f0-9]{40}',pr.get('headRefOid','')): raise ValueError('exact head required')
    if pr.get('headRepository',{}).get('nameWithOwner')!=client.repository: raise ValueError('same repository PR required')
    # GitHub supplies the complete file inventory; callers may raise, never lower,
    # deterministic risk. Unknown/executable application surfaces stay protected.
    from .policy import classify
    files=client.read_all(f'repos/{client.repository}/pulls/{number}/files')
    if not files or len(files)>=3000: raise ValueError('complete PR file inventory required')
    names=[f['filename'] for f in files]
    floor=int(classify(names,diff='\n'.join(f.get('patch','') for f in files))['risk'][1:])
    if any(n.endswith('.py') and not n.startswith('tests/') for n in names):floor=max(floor,3)
    if any(n.rsplit('/',1)[-1] in {'conftest.py','pytest.ini','pyproject.toml','setup.cfg','sitecustomize.py','usercustomize.py'} for n in names):floor=max(floor,3)
    # Documentation/CSS/tests are the only low-risk surfaces; ambiguous content
    # requires explicit owner rationale even when a model labels it presentation.
    if any(not (n.endswith('.md') or n.endswith('.css') or n.startswith('tests/') and n.endswith('.py')) for n in names):floor=max(floor,3)
    if client.pr_identity(number).get('headRefOid')!=pr['headRefOid']: raise ValueError('PR changed during owner context inspection')
    if int(risk[1:])<floor: raise ValueError('owner review understates deterministic risk')
    return dict(model=MODEL,repository=client.repository,pr=number,head=pr['headRefOid'],risk=risk,owner_login=p['owner_login'],owner_id=p['owner_id'],policy_hash=digest(p))


def attest(store,client,expected,decision,nonce,rationale,*,human,financial_ack=False,execution_ack=False):
    if type(human) is not HumanIdentity: raise ValueError('authenticated owner required')
    p=policy()
    if human.source not in SOURCES or human.actor not in p['operators'].get(human.source,[]): raise ValueError('owner identity required')
    if decision not in {'APPROVE','REQUEST_CHANGES','DEFER'} or not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9-]{16,128}',nonce): raise ValueError('explicit decision and nonce required')
    if context(client,expected['pr'],risk=expected['risk'])!=expected: raise ValueError('stale owner review context')
    level=int(expected['risk'][1:])
    if decision=='APPROVE' and (level>=3 and not rationale.strip() or level>=4 and financial_ack is not True or level>=5 and execution_ack is not True): raise ValueError('risk-specific rationale and acknowledgments required')
    payload=dict(context=expected,decision=decision,rationale=rationale,financial_ack=financial_ack is True,execution_ack=execution_ack is True,created=time.time(),decision_nonce=nonce,**human.audit())
    with store.connect(True) as db:
        if db.execute('SELECT 1 FROM dev_events WHERE event_id=?',('owner-review:'+nonce,)).fetchone(): raise ValueError('replayed owner review nonce')
        store._append(db,None,'OWNER_REVIEW',payload,'owner-review:'+nonce)
    return payload


def state(store,client,number):
    p=policy()
    with store.connect() as db:
        rows=db.execute("SELECT payload FROM dev_events WHERE kind='OWNER_REVIEW' ORDER BY seq DESC").fetchall()
    rows=[json.loads(r[0]) for r in rows]
    item=next((r for r in rows if r['context']['repository']==client.repository and r['context']['pr']==number),None)
    current=context(client,number,risk=item['context']['risk'] if item else 'L5')
    if not item:return dict(status='MISSING',context=current)
    if item['context']!=current:return dict(status='STALE',context=current,review=item)
    if item.get('authentication_source')!='github-owner-object':
        from datetime import datetime,timezone
        from .github_owner import latest_object
        since=datetime.fromtimestamp(int(item['created']),tz=timezone.utc).isoformat()
        try:
            if latest_object(client,number,current['head'],since,required=False) is not None:return dict(status='STALE',context=current,review=item,reason='new GitHub owner decision must be ingested')
        except Exception:return dict(status='UNAVAILABLE',context=current,review=item)
    if item.get('authentication_source')=='github-owner-object':
        from .github_owner import still_valid
        if not still_valid(item,client):return dict(status='STALE',context=current,review=item)
        return dict(status=item['decision'],context=current,review=item)
    if item['decision']!='APPROVE':return dict(status=item['decision'],context=current,review=item)
    if item.get('authentication_source') not in SOURCES or item.get('actor') not in p['operators'].get(item.get('authentication_source'),[]) or int(current['risk'][1:])>=4 and not item.get('financial_ack') or int(current['risk'][1:])>=5 and not item.get('execution_ack'):
        return dict(status='INVALID',context=current,review=item)
    return dict(status=item['decision'],context=current,review=item)


def require(store,client,number):
    result=state(store,client,number)
    if result['status']!='APPROVE':raise ValueError('fresh exact-head authenticated owner approval required')
    return result


def verify_merge_actor(client,number,head,merge_sha):
    """GitHub's actual merge must belong to the owner, with auto-merge absent."""
    p=policy()
    remote=client.read(f'repos/{client.repository}/pulls/{number}')
    actor=remote.get('merged_by') or {}
    if (client.repository!=p['repository'] or remote.get('merged') is not True
        or (remote.get('head') or {}).get('sha')!=head or remote.get('merge_commit_sha')!=merge_sha
        or remote.get('auto_merge') is not None or actor.get('type')!='User'
        or actor.get('id')!=p['owner_id'] or actor.get('login')!=p['owner_login']):
        raise ValueError('exact-head owner-performed non-automated GitHub merge required')
    return dict(id=actor['id'],login=actor['login'],source='github-merged-by')
