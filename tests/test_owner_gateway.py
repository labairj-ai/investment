"""Owner gateway is separate from agent authority; no real comments or merges."""
import json
from datetime import datetime,timezone
import pytest
from test_development_agent_owner_review import setup as owner_setup,scoped_approve
from owner_gateway.core import record_decision,merge_after_ok
from dev_agent.owner_review import context


def test_owner_ok_records_native_object_but_never_implicitly_merges(owner_setup):
    store,client,_=owner_setup;original=client.read;objects={};actions=[]
    client.read=lambda endpoint:dict(login='owner',id=1,type='User') if endpoint=='user' else list(objects.values()) if '/issues/1/comments?' in endpoint else objects[endpoint] if endpoint in objects else original(endpoint)
    def write(endpoint,payload,method):
        actions.append((endpoint,payload,method));assert method=='POST'
        now=datetime.now(timezone.utc).isoformat()
        obj=dict(id=123,user=dict(login='owner',id=1,type='User'),performed_via_github_app=None,body=payload['body'],created_at=now,updated_at=now,issue_url='https://api.github.com/repos/owner/repo/issues/1',html_url='https://github.com/owner/repo/pull/1#issuecomment-123')
        objects['repos/owner/repo/issues/comments/123']=obj;return obj
    client.write=write
    result=record_decision(store,client,context(client,1,risk='L5'),decision='APPROVE',nonce='explicit-owner-ok-0001',rationale='Owner reviewed',action='MERGE_ONLY',financial_ack=True,execution_ack=True)
    assert result['decision']=='APPROVE' and len(actions)==1 and actions[0][2]=='POST'
    with pytest.raises(ValueError):merge_after_ok(store,client,1,expected_head=client.head)
    with pytest.raises(ValueError):record_decision(store,client,context(client,1,risk='L5'),decision='APPROVE',nonce='explicit-owner-ok-0001',rationale='Replay',action='MERGE_ONLY',financial_ack=True,execution_ack=True)
    assert len(actions)==1


def test_gateway_rejects_agent_identity_before_any_write(owner_setup):
    store,client,_=owner_setup;original=client.read
    client.read=lambda endpoint:dict(login='agent',id=2,type='User') if endpoint=='user' else original(endpoint)
    client.write=lambda *a:pytest.fail('agent must never reach owner write')
    with pytest.raises(ValueError):record_decision(store,client,context(client,1,risk='L5'),decision='APPROVE',nonce='explicit-owner-ok-0002',rationale='Not the owner')


def test_owner_merge_uses_atomic_expected_head_and_separate_deployment(owner_setup):
    store,client,_=owner_setup;scoped_approve(owner_setup,action='MERGE_ONLY');original=client.read;original_pr=client.pr_identity;actions=[]
    client.pr_identity=lambda number:dict(original_pr(number),isDraft=False)
    def read(endpoint):
        if endpoint=='user':return dict(login='owner',id=1,type='User')
        if '/check-runs' in endpoint:return dict(total_count=1,check_runs=[dict(id=1,name='test',head_sha=client.head,status='completed',conclusion='success')])
        return original(endpoint)
    client.read=read
    def write(endpoint,payload,method):actions.append((endpoint,payload,method));return dict(merged=True,sha='c'*40)
    client.write=write
    result=merge_after_ok(store,client,1,expected_head=client.head,explicit_owner_merge=True)
    assert result['merge_sha']=='c'*40 and not result['deployment_authorized']
    assert actions[0][1]['sha']==client.head and actions[0][1]['merge_method']=='merge'
    client.head='b'*40
    with pytest.raises(ValueError):merge_after_ok(store,client,1,expected_head='a'*40,explicit_owner_merge=True)
    assert len(actions)==1
