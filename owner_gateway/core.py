"""Owner connector actions after explicit human OK/NO. No background entry point.

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


def authorize_deployment(store,client,number,*,head,merge_sha,nonce,rationale,execution_ack=False,explicit_owner_deployment=False,expires_at=None):
    """A separate owner action after merge CI; does not execute deployment."""
    import re,time
    owner_actor(client)
    if explicit_owner_deployment is not True or execution_ack is not True or not rationale.strip() or not re.fullmatch(r'[A-Za-z0-9-]{16,128}',str(nonce)):raise ValueError('separate explicit owner deployment authorization required')
    check(store,client,number,head)
    remote=client.pr_identity(number)
    if remote.get('state')!='MERGED' or remote.get('headRefOid')!=head or (remote.get('mergeCommit') or {}).get('oid')!=merge_sha:raise ValueError('exact observed owner merge required')
    from dev_agent.owner_review import verify_merge_actor
    verify_merge_actor(client,number,head,merge_sha)
    runs=client.read(f'repos/{client.repository}/commits/{merge_sha}/check-runs?per_page=100')
    tests=[r for r in runs.get('check_runs',[]) if r.get('name')=='test' and r.get('head_sha')==merge_sha]
    if runs.get('total_count',0)>100 or not tests or max(tests,key=lambda r:r['id']).get('conclusion')!='success':raise ValueError('wait for exact merged main CI before authorizing deployment')
    expires_at=time.time()+3600 if expires_at is None else expires_at
    if not time.time()<expires_at<=time.time()+86400:raise ValueError('bounded deployment expiration required')
    payload=dict(repository=client.repository,pr=number,head=head,merge_sha=merge_sha,nonce=nonce,expires_at=expires_at,rationale=rationale,execution_ack=True)
    obj=client.write(f'repos/{client.repository}/issues/{number}/comments',dict(body='OWNER-DEPLOY deployment-1\n'+json.dumps(payload,sort_keys=True),_pr=number),'POST')
    return dict(status='OWNER_DEPLOYMENT_AUTHORIZED',authorization_id=obj['id'],merge_sha=merge_sha,executed=False)


def authorize_autonomy_promotion(root,store,client,expected,*,decision,nonce,rationale,explicit_owner_promotion=False):
    """Owner-side issuer only, after a deliberate separate human stage decision.

    This function is never called by Scout/Builder/runtime. It issues and ingests
    an owner object; it does not edit configuration, start services or grant merge.
    """
    import time
    from dev_agent import owner_promotion,promotion_github
    owner_actor(client)
    if explicit_owner_promotion is not True or decision not in {'APPROVE','REVOKE'}:
        raise ValueError('separate deliberate owner promotion decision required')
    number=expected.get('activation_pr')
    if promotion_github.context(root,number,client)!=expected:
        raise ValueError('owner promotion context changed; review again')
    p=policy()
    if not any(a['id']==1144995 and a['slug']=='chatgpt-codex-connector' for a in p.get('allowed_github_apps',[])):
        raise ValueError('explicit owner connector allowlist required')
    binding=dict(expected,protocol=owner_promotion.PROTOCOL,created=time.time(),nonce=nonce,rationale=rationale)
    owner_promotion.validate_binding(binding,expected)
    with store.connect() as db:
        if db.execute('SELECT 1 FROM dev_events WHERE event_id=?',('owner-promotion:'+nonce,)).fetchone():
            raise ValueError('owner promotion nonce already used')
    # Current remote inventory also prevents replay when a prior POST succeeded
    # but local ingestion was interrupted. Fail closed on malformed own objects.
    from dev_agent.structured_json import loads
    for obj in client.read_all(f'repos/{client.repository}/issues/{number}/comments'):
        actor=obj.get('user') or {};body=obj.get('body','')
        if actor.get('id')==p['owner_id'] and isinstance(body,str) and body.startswith(promotion_github.HEADER):
            if len(body.encode())>16000:raise ValueError('oversized owner promotion object')
            data=loads(body[len(promotion_github.HEADER):])
            if not isinstance(data,dict) or data.get('nonce')==nonce:
                raise ValueError('owner promotion nonce already issued or inventory malformed')
    if promotion_github.context(root,number,client)!=expected:
        raise ValueError('owner promotion context changed before issuance')
    obj=client.write(f'repos/{client.repository}/issues/{number}/comments',dict(body=promotion_github.HEADER+json.dumps(dict(binding,decision=decision),sort_keys=True),_pr=number),'POST')
    accepted=promotion_github.ingest(root,store,number,client=client)
    if accepted['origin']['id']!=obj.get('id'):
        raise ValueError('issued owner promotion was superseded')
    return dict(status='OWNER_PROMOTION_RECORDED',decision=decision,origin=accepted['origin'],enables_autonomy=False)
