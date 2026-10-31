"""Synthetic epoch reporting; never creates an authoritative live receipt."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from dev_agent import scheduler_health as h
from test_development_agent import store
from test_development_agent_live_rollout import qualifying_payload
from test_pr13_evidence_integrity import scheduled_store,append


@pytest.fixture
def epoch(tmp_path,monkeypatch):
    target='b'*40;directory=tmp_path/'epochs'/target;directory.mkdir(parents=True)
    monkeypatch.setattr(h,'receipt_path',lambda head:directory/'discovery.json')
    actual=Path.lstat
    # Isolated trust boundary: fixture owner stands in for root. Content/schema,
    # source separation and acceptance joining use the actual implementation.
    monkeypatch.setattr(Path,'lstat',lambda p:SimpleNamespace(st_uid=0,st_mode=actual(p).st_mode&~0o022,st_size=actual(p).st_size))
    data=dict(status='COMMITTED',source_head=target,old_head='a'*40,nonce='fresh-deliberate-owner-nonce',history=dict(source_head='a'*40,accepted_slots=['scout:2026-10-29'],accepted_count=1,manifest_sha256='d'*64))
    marker=directory/'transition.json';marker.write_text(json.dumps(data))
    return target,data,marker


def test_epoch_summary_retains_history_without_current_credit(epoch):
    target,data,_=epoch;result=h.qualification_epochs(target)
    assert result['current_source']==target and result['historical']==[data['history']]
    assert result['epoch_transition'] is True


@pytest.mark.parametrize('attack',['uncommitted','wrongsource','sameepoch','wrongarchive','wrongcount','duplicate','malformedslot','missinghistory','extrafield'])
def test_epoch_metadata_fails_closed(epoch,attack):
    target,data,marker=epoch
    if attack=='uncommitted':data['status']='STAGED'
    if attack=='wrongsource':data['source_head']='c'*40
    if attack=='sameepoch':data['history']['source_head']=data['old_head']=target
    if attack=='wrongarchive':data['history']['manifest_sha256']='bad'
    if attack=='wrongcount':data['history']['accepted_count']=2
    if attack=='duplicate':data['history']['accepted_slots']*=2;data['history']['accepted_count']=2
    if attack=='malformedslot':data['history']['accepted_slots']=['manual:today']
    if attack=='missinghistory':del data['history']
    if attack=='extrafield':data['manual_credit']=True
    marker.write_text(json.dumps(data))
    with pytest.raises((ValueError,KeyError)):h.qualification_epochs(target)


@pytest.mark.parametrize('proof',[False,True])
def test_new_epoch_needs_bookended_receipt_even_for_first_credit(store,epoch,monkeypatch,proof):
    target,data,_=epoch;now=1793390418
    scheduled_store(store,now)
    append(store,'SCHEDULE',qualifying_payload(now,head='a'*40,age=1,invocation='a'*32))
    append(store,'SCHEDULE',qualifying_payload(now,head=target,invocation='b'*32))
    calls=[]
    def safety(head,runs,stamp,*,required=3):
        calls.append((head,[p['trigger']['invocation'] for p in runs],required));return proof
    monkeypatch.setattr(h,'host_safety',safety)
    result=h.acceptance(store,target,now)
    assert result['successful_runs']==int(proof)
    assert result['current_epoch_accepted_runs']==int(proof)
    assert result['epochs']['historical'][0]['accepted_count']==1
    assert result['status']=='NOT READY' and result['grants_implementation'] is False
    assert calls==[(target,['b'*32],1)]


def test_missing_committed_epoch_cannot_award_any_credit(store,epoch):
    target,_,marker=epoch;marker.unlink();now=1793390418
    scheduled_store(store,now);append(store,'SCHEDULE',qualifying_payload(now,head=target))
    result=h.acceptance(store,target,now)
    assert result['successful_runs']==0 and result['status']=='NOT READY'
    assert result['epochs']['error']=='epoch authority unavailable'
