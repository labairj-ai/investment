"""Owner connector actions after explicit human Go / No-Go. No background entry point.

Only the authenticated owner-side connector invokes this module. Development
Agent has read-only ingestion, never these write/merge methods or credentials.
"""
from __future__ import annotations
import json
import subprocess
import tempfile
from pathlib import Path
from dev_agent.owner_review import policy,context
from dev_agent.github_owner import HEADER,ingest
from scripts.check_owner_review import check


class OwnerClient:
    def __init__(self,reader):self.reader=reader;self.repository=reader.repository
    def read(self,endpoint):return self.reader.read(endpoint)
    def read_all(self,endpoint):return self.reader.read_all(endpoint)
    def pr_identity(self,number):return self.reader.pr_identity(number)
    def write(self,endpoint,payload,method):
        # No shell, arbitrary paths, git pushes, approvals, ruleset or deployment API.
        payload=dict(payload);number=payload.pop('_pr',None)
        if type(number) is not int or number<=0:raise ValueError('fixed positive PR number required')
        allowed={f'repos/{self.repository}/issues/{number}/comments':'POST'} if method=='POST' and set(payload)=={'body'} else {}
        if method=='PUT' and set(payload)=={'sha','merge_method'}:
            import re
            if payload['merge_method']!='merge' or not re.fullmatch(r'[a-f0-9]{40}',str(payload['sha'])):raise ValueError('exact immediate merge scope required')
            allowed={f'repos/{self.repository}/pulls/{number}/merge':'PUT'}
        if allowed.get(endpoint)!=method:raise ValueError('fixed owner action endpoint required')
        with tempfile.TemporaryDirectory(prefix='owner-action-') as tmp:
            path=Path(tmp)/'request.json';path.write_text(json.dumps(payload));path.chmod(0o600)
            result=subprocess.run(['gh','api','--method',method,endpoint,'--input',str(path)],check=True,capture_output=True,text=True,timeout=30)
        return json.loads(result.stdout)


def owner_actor(client):
    p=policy();actor=client.read('user')
    if actor.get('login')!=p['owner_login'] or actor.get('id')!=p['owner_id'] or actor.get('type')!='User' or client.repository!=p['repository']:raise ValueError('owner-side authenticated connector required')
    return actor


def record_decision(store,client,expected,*,decision,nonce,rationale,financial_ack=False,execution_ack=False):
    owner_actor(client)
    if context(client,expected['pr'],risk=expected['risk'])!=expected:raise ValueError('owner decision context changed; review again')
    if decision not in {'APPROVE','REQUEST_CHANGES','DEFER'}:raise ValueError('explicit owner OK/NO decision required')
    level=int(expected['risk'][1:])
    if decision=='APPROVE' and (level>=3 and not rationale.strip() or level>=4 and financial_ack is not True or level>=5 and execution_ack is not True):raise ValueError('risk acknowledgments required before owner action')
    import re
    if not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9-]{16,128}',nonce):raise ValueError('single-use owner nonce required')
    with store.connect() as db:
        if db.execute('SELECT 1 FROM dev_events WHERE event_id=?',('owner-review:'+nonce,)).fetchone():raise ValueError('owner decision nonce already used')
    payload=dict(repository=client.repository,pr=expected['pr'],head=expected['head'],risk=expected['risk'],decision=decision,nonce=nonce,rationale=rationale,financial_ack=financial_ack,execution_ack=execution_ack)
    obj=client.write(f'repos/{client.repository}/issues/{expected["pr"]}/comments',dict(body=HEADER+json.dumps(payload,sort_keys=True),_pr=expected['pr']),'POST')
    return ingest(store,client,obj['id'])


def merge_after_ok(store,client,number,*,expected_head,explicit_owner_merge=False):
    if explicit_owner_merge is not True:raise ValueError('current owner workflow must explicitly authorize immediate merge')
    owner_actor(client)
    proof=check(store,client,number,expected_head)
    remote=client.pr_identity(number)
    if remote.get('headRefOid')!=expected_head or remote.get('state')!='OPEN' or remote.get('baseRefName')!='main' or remote.get('isDraft'):raise ValueError('exact open reviewed PR head required')
    result=client.write(f'repos/{client.repository}/pulls/{number}/merge',dict(sha=expected_head,merge_method='merge',_pr=number),'PUT')
    import re
    if result.get('merged') is not True or not re.fullmatch(r'[a-f0-9]{40}',result.get('sha','')):raise ValueError('GitHub rejected exact-head owner merge')
    return dict(status='OWNER_MERGED',head=expected_head,merge_sha=result['sha'],owner_review=proof['owner_review'],deployment_authorized=False)


def authorize_deployment(*args,**kwargs):
    raise ValueError('retired: deployment derives from the original owner Go')


def authorize_autonomy_promotion(*args,**kwargs):
    raise ValueError('retired: activation uses the activation PR owner Go')


def go_no_go(store,client,reviewed,answer):
    """Trusted owner connector entry point after ChatGPT's exact-head review.

    `reviewed` is the frozen context already displayed to the owner, including
    elevated risk. Only the authenticated owner connector can invoke this API;
    it must never be exposed to Builder/Reviewer or inferred from model output.
    """
    import uuid
    if answer not in {'Go','No-Go'}:raise ValueError('explicit Go or No-Go required')
    recorded=record_decision(store,client,reviewed,
        decision='APPROVE' if answer=='Go' else 'REQUEST_CHANGES',
        nonce=str(uuid.uuid4()),rationale='Owner '+answer+' after exact-head ChatGPT review ('+reviewed['risk']+')',
        financial_ack=int(reviewed['risk'][1:])>=4,execution_ack=int(reviewed['risk'][1:])>=5)

    if answer=='No-Go':return dict(status='NO_GO',review=recorded)
    try:next_step=advance_approved(store,client,reviewed['pr'])
    except ValueError as error:next_step=dict(status='WAITING_OR_BLOCKED',reason=str(error))
    return dict(status='GO_RECORDED',review=recorded,next_step=next_step)


def advance_approved(store,client,number):
    """Owner-side continuation; the persisted Go authorizes merge once CI passes.

    A timer may retry this fixed action. No user prompt, no agent credential,
    no GitHub auto-merge and no authority to select a different head.
    """
    from dev_agent.owner_review import require
    approved=require(store,client,number)
    head=approved['context']['head']
    remote=client.pr_identity(number)
    if remote.get('state')=='MERGED':return dict(status='MERGED_WAITING_FOR_MAIN_CI',head=head)
    result=merge_after_ok(store,client,number,expected_head=head,explicit_owner_merge=True)
    with store.connect(True) as db:
        from dev_agent.store import digest
        store._append(db,None,'OWNER_MERGE',dict(result,owner_review_hash=digest(approved['review'])),
                      'owner-merge:'+str(number)+':'+head)
    return result


def reconcile_approved(store,client):
    """Fixed owner-connector retry operation; no additional human decision.

    The isolated owner connector calls this periodically after Go. Builder and
    discovery cannot invoke it or access its credential. It selects only existing
    authenticated owner reviews and rechecks current GitHub authority and CI.
    """
    owner_actor(client)
    from dev_agent.owner_review import state
    with store.connect() as db:
        rows=db.execute("SELECT payload FROM dev_events WHERE kind='OWNER_REVIEW' ORDER BY seq DESC LIMIT 100").fetchall()
    numbers=list(dict.fromkeys(json.loads(r[0])['context']['pr'] for r in rows
                             if json.loads(r[0])['context']['repository']==client.repository))
    results=[]
    for number in numbers:
        try:
            if state(store,client,number)['status']!='APPROVE':continue
            results.append(dict(pr=number,result=advance_approved(store,client,number)))
        except ValueError as error:results.append(dict(pr=number,status='WAITING_OR_BLOCKED',reason=str(error)))
    return results
