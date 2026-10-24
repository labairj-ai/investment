"""Owner-authentication adversaries; synthetic GitHub objects are never live evidence."""
import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import pytest
from dev_agent import owner_promotion as op, promotion_github as pg
from dev_agent.store import Store


@pytest.fixture
def setup(tmp_path,monkeypatch):
    now=float(int(time.time()))
    ctx=dict(repository='owner/repo',harness_hash='a'*64,activation_pr=21,head='b'*40,
             stage='PR',maximum_risk='L2',daily_cap=1,owner_login='owner',owner_id=10)
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={},allowed_github_apps=[dict(id=1144995,slug='chatgpt-codex-connector')])))
    monkeypatch.setenv('DEV_AGENT_PROMOTION_PR','21')
    monkeypatch.setattr(pg,'context',lambda *a,**k:copy.deepcopy(ctx))
    stamp=datetime.fromtimestamp(now,timezone.utc).isoformat().replace('+00:00','Z')
    payload=dict(ctx,protocol=op.PROTOCOL,created=now,nonce='owner-promotion-unique-0001',rationale='Owner reviewed bounded next stage',decision='APPROVE')
    obj=dict(id=901,user=dict(id=10,login='owner',type='User'),performed_via_github_app=dict(id=1144995,slug='chatgpt-codex-connector'),created_at=stamp,updated_at=stamp,body=pg.HEADER+json.dumps(payload),issue_url='https://api.github.com/repos/owner/repo/issues/21',html_url='https://github.com/owner/repo/pull/21#issuecomment-901')
    class Client:
        repository='owner/repo'
        def read_all(self,path):return copy.deepcopy(self.rows)
        def read(self,path):return copy.deepcopy(next(o for o in self.rows if o['id']==int(path.rsplit('/',1)[-1])))
    client=Client();client.rows=[obj]
    monkeypatch.setattr(pg,'GitHub',lambda *a:client)
    store=Store(tmp_path/'development-control.sqlite3');store.migrate()
    return ctx,payload,obj,client,store,now


def test_ingest_and_independently_reverify(setup):
    ctx,payload,obj,client,store,now=setup
    result=pg.ingest('.',store,21,client=client,now=now)
    assert result['status']=='INGESTED' and result['enables_autonomy'] is False
    assert pg.ingest('.',store,21,client=client,now=now)==result
    auth=op.authorization('.',store,now=now)
    assert auth['authenticated'] is True and auth['fixture_only'] is False
    assert op.require_runtime_binding('.',store,auth,now=now)
    assert auth['grants_authority'] is False


@pytest.mark.parametrize('attack',['fixture','harness','head','stage','risk','cap','stale','future','revoked','connector','slug','no_app','bot','wrong_owner','wrong_login','edited','wrong_pr','wrong_repo','wrong_protocol','nonce','timestamp','duplicate_key'])
def test_attacks_fail_closed(setup,attack):
    ctx,payload,obj,client,store,now=setup
    pg.ingest('.',store,21,client=client,now=now)
    if attack=='fixture':payload['fixture_only']=True
    elif attack=='harness':payload['harness_hash']='c'*64
    elif attack=='head':payload['head']='c'*40
    elif attack=='stage':payload['stage']='BUILD_ONLY'
    elif attack=='risk':payload['maximum_risk']='L3'
    elif attack=='cap':payload['daily_cap']=2
    elif attack=='stale':payload['created']=now-86401
    elif attack=='future':payload['created']=now+100
    elif attack=='revoked':payload['decision']='REVOKE'
    elif attack=='connector':obj['performed_via_github_app']['id']=7
    elif attack=='slug':obj['performed_via_github_app']['slug']='other'
    elif attack=='no_app':obj['performed_via_github_app']=None
    elif attack=='bot':obj['user']['type']='Bot'
    elif attack=='wrong_owner':obj['user']['id']=20
    elif attack=='wrong_login':obj['user']['login']='other'
    elif attack=='edited':obj['updated_at']='2020-01-01T00:00:00Z'
    elif attack=='wrong_pr':obj['issue_url']=obj['issue_url'].replace('/21','/22')
    elif attack=='wrong_repo':payload['repository']='other/repo'
    elif attack=='wrong_protocol':payload['protocol']='future'
    elif attack=='nonce':payload['nonce']='new-uningested-nonce-0001'
    elif attack=='timestamp':payload['created']=now-61
    obj['body']=pg.HEADER+json.dumps(payload)
    if attack=='duplicate_key':obj['body']=obj['body'][:-1]+',"decision":"APPROVE"}'
    assert op.authorization('.',store,now=now)['status']=='UNAVAILABLE'


def test_forged_ledger_does_not_authenticate(setup):
    ctx,payload,obj,client,store,now=setup
    with store.connect(True) as db:
        store._append(db,None,'OWNER_AUTONOMY_PROMOTION',dict(binding=payload,authenticated=True),'owner-promotion:'+payload['nonce'])
    assert op.authorization('.',store,now=now)['status']=='UNAVAILABLE'


def test_replay_nonce_new_object_denied(setup):
    ctx,payload,obj,client,store,now=setup
    pg.ingest('.',store,21,client=client,now=now)
    obj['id']=902;obj['html_url']=obj['html_url'].replace('901','902')
    with pytest.raises(ValueError,match='replay'):pg.ingest('.',store,21,client=client,now=now)
    assert op.authorization('.',store,now=now)['status']=='UNAVAILABLE'


@pytest.mark.parametrize('field,value',[('status','FAIL'),('authenticated',False),('fixture_only',True),('protocol','other'),('revocation_checked',False),('replay_checked',False)])
def test_runtime_rechecks_adapter_proof(setup,field,value):
    ctx,payload,obj,client,store,now=setup
    pg.ingest('.',store,21,client=client,now=now)
    result=op.authorization('.',store,now=now);result[field]=value
    with pytest.raises(ValueError):op.require_runtime_binding('.',store,result,now=now)


@pytest.mark.parametrize('field,value',[('repository','other/repo'),('harness_hash','c'*64),('activation_pr',22),('head','c'*40),('stage','BUILD_ONLY'),('maximum_risk','L3'),('daily_cap',2),('owner_login','other'),('owner_id',20)])
def test_runtime_rechecks_every_context_field(setup,field,value):
    ctx,payload,obj,client,store,now=setup
    pg.ingest('.',store,21,client=client,now=now)
    result=op.authorization('.',store,now=now);result['binding'][field]=value
    with pytest.raises(ValueError):op.require_runtime_binding('.',store,result,now=now)


def test_generic_pass_is_insufficient(setup):
    *_,store,now=setup
    with pytest.raises(ValueError):op.require_runtime_binding('.',store,dict(status='PASS',authenticated=True),now=now)


def test_runtime_reverifies_origin_instead_of_trusting_full_adapter_json(setup):
    ctx,payload,obj,client,store,now=setup
    pg.ingest('.',store,21,client=client,now=now)
    result=op.authorization('.',store,now=now);result['origin']['id']=999
    with pytest.raises(ValueError,match='provenance'):op.require_runtime_binding('.',store,result,now=now)


def test_newer_revocation_blocks_older_ingestion(setup):
    ctx,payload,obj,client,store,now=setup
    pg.ingest('.',store,21,client=client,now=now)
    rev=copy.deepcopy(obj);rev['id']=902;rev['html_url']=rev['html_url'].replace('901','902')
    payload.update(decision='REVOKE',nonce='owner-promotion-revoke-0002')
    rev['body']=pg.HEADER+json.dumps(payload);client.rows.append(rev)
    assert op.authorization('.',store,now=now)['status']=='UNAVAILABLE'
    assert pg.ingest('.',store,21,client=client,now=now)['decision']=='REVOKE'
    assert op.authorization('.',store,now=now)['status']=='UNAVAILABLE'


def test_real_context_checks_repository_pr_and_exact_runtime_source(tmp_path,monkeypatch):
    from dev_agent import git_exec,certification,operations
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={})))
    class Client:
        repository='owner/repo'
        repo=dict(full_name='owner/repo',owner=dict(type='User',login='owner',id=10))
        pr=dict(number=21,baseRefName='main',state='OPEN',headRepository=dict(nameWithOwner='owner/repo'),headRefOid='b'*40)
        def read(self,path):return self.repo
        def pr_identity(self,number):return self.pr
    c=Client()
    monkeypatch.setattr(git_exec,'output',lambda *a:'b'*40)
    monkeypatch.setattr(certification,'harness_hash',lambda root:'a'*64)
    monkeypatch.setattr(operations,'policy',lambda root:dict(autonomy_stage='PR',autonomous_max_risk='L2',daily_implementation_cap=1))
    assert pg.context(tmp_path,21,c)['head']=='b'*40
    for field,value in [('state','CLOSED'),('baseRefName','other'),('number',22),('headRefOid','c'*40),('headRepository',dict(nameWithOwner='evil/repo'))]:
        old=c.pr[field];c.pr[field]=value
        with pytest.raises(ValueError):pg.context(tmp_path,21,c)
        c.pr[field]=old
    c.repo['owner']['type']='Bot'
    with pytest.raises(ValueError):pg.context(tmp_path,21,c)


def test_owner_side_issuer_requires_separate_action_and_never_enables(setup):
    from owner_gateway.core import authorize_autonomy_promotion
    ctx,payload,obj,client,store,now=setup
    original=client.read;actions=[];client.rows=[]
    client.read=lambda path:dict(login='owner',id=10,type='User') if path=='user' else original(path)
    def write(path,data,method):
        actions.append((path,data,method))
        emitted=copy.deepcopy(obj);emitted['body']=data['body']
        client.rows.append(emitted)
        return emitted
    client.write=write
    args=dict(decision='APPROVE',nonce='issuer-owner-promotion-0001',rationale='Deliberate reviewed next stage')
    with pytest.raises(ValueError):authorize_autonomy_promotion('.',store,client,ctx,**args)
    assert actions==[]
    # Superseded issuer cannot manufacture a second authority path.
    with pytest.raises(ValueError,match='retired'):
        authorize_autonomy_promotion('.',store,client,ctx,explicit_owner_promotion=True,**args)
    assert actions==[]


def test_issuer_rejects_nonowner_before_any_write(setup):
    from owner_gateway.core import authorize_autonomy_promotion
    ctx,payload,obj,client,store,now=setup
    client.read=lambda path:dict(login='agent',id=20,type='User')
    client.write=lambda *a:pytest.fail('no write before deliberate owner authentication')
    with pytest.raises(ValueError):authorize_autonomy_promotion('.',store,client,ctx,decision='APPROVE',nonce='issuer-owner-promotion-0001',rationale='No authority',explicit_owner_promotion=True)
