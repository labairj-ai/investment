"""Real receipt validation plus disposable operational-boundary regressions."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import pytest
from dev_agent.deployment_evidence import validate,seal,qualifying,load
from development_fixtures import deployment_evidence
from test_development_agent import store,repo
from scripts.check_deployment_receipt import check

ROOT=Path(__file__).resolve().parents[1]


def test_authentic_pr10_receipt_is_sanitized_hashed_and_not_pilot():
    path=ROOT/'docs/evidence/continuous-improvement-20261023/deployment-pr10.json'
    result=check(path);envelope=load(path);r=envelope['receipt']
    assert r['deployed_sha']==r['main_sha']=='15df8960b7c376da8b15fd80dad1bfb19aaede9b'
    assert r['merge_ci']['run_id']==39997737221 and r['merge_ci']['status']=='PASS'
    assert r['actor']=='manual-owner-authorized' and r['fixture_only'] is False
    assert result['authority']=='NONE'
    raw=path.read_text()
    for private in ['/home/','/Users/','backup_directory','DEV_AGENT_API_TOKEN','authorization_nonce','holdings.csv']:assert private not in raw
    with pytest.raises(ValueError,match='deployment-agent'):qualifying(envelope,repository=r['repository'],pr=r['pr'],head=r['head'],merge_sha=r['merge_sha'])


@pytest.mark.parametrize('field',['head','deployed_sha','merge_ci','health','backup','activation','state_safety'])
def test_edited_or_incomplete_receipts_never_qualify(field):
    envelope=deployment_evidence();envelope['receipt'].pop(field)
    with pytest.raises(ValueError):validate(envelope)
    with pytest.raises(ValueError):seal(envelope['receipt'])


@pytest.mark.parametrize('field,value',[('deployed_sha','b'*40),('main_sha','b'*40),('backup',dict(exists=False,integrity='ok',sha256='a'*64)),('fixture_only','false'),('deployed_at','2026-10-23'),('credentials','secret-value')])
def test_even_rehashed_invalid_observations_are_rejected(field,value):
    receipt=deployment_evidence()['receipt'];receipt[field]=value
    with pytest.raises(ValueError):seal(receipt)


def test_file_digest_and_ledger_digest_both_detect_substitution(tmp_path):
    e=deployment_evidence();path=tmp_path/'receipt.json';path.write_text(json.dumps(e))
    path.with_suffix('.json.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'  receipt.json\n')
    assert check(path)['status']=='PASS'
    prior=e['sha256'];e['receipt']['pr']=2;e=seal(e['receipt']);path.write_text(json.dumps(e))
    with pytest.raises(ValueError):check(path)
    with pytest.raises(ValueError):qualifying(e,repository='owner/repo',pr=2,head='a'*40,merge_sha='c'*40,expected_sha256=prior)


def test_receipt_identity_cannot_be_reused_or_fixture_qualified():
    e=deployment_evidence()
    assert qualifying(e,repository='owner/repo',pr=1,head='a'*40,merge_sha='c'*40)
    with pytest.raises(ValueError):qualifying(e,repository='other/repo',pr=1,head='a'*40,merge_sha='c'*40)
    e['receipt']['fixture_only']=True;e=seal(e['receipt'])
    with pytest.raises(ValueError):qualifying(e,repository='owner/repo',pr=1,head='a'*40,merge_sha='c'*40)


def test_missing_oracle_and_pilots_cannot_produce_promotion(store):
    from dev_agent.promotion import report
    before=store.path.read_bytes();config=(ROOT/'config/development_agent.json').read_bytes()
    result=report(ROOT,store)
    assert result['recommendation']=='NO-GO' and result['recommended_stage']=='SHADOW'
    assert result['qualifying_runs']==[] and result['observation_window']['observation_days']==0
    assert any('oracle' in b for b in result['blockers'])
    assert any('seven-day' in b for b in result['blockers'])
    assert not result['enables_autonomy'] and not result['grants_merge'] and not result['grants_deployment']
    assert (ROOT/'config/development_agent.json').read_bytes()==config
    assert store.path.read_bytes()==before


def test_malformed_deployment_blocks_operational_success(store,monkeypatch):
    from test_development_agent_hardening import seed_completed_pilot,fixture_human
    from dev_agent.operations import record_success
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={'os-interactive-cli':['fixture-owner']})))
    cid,client=seed_completed_pilot(store)
    with store.connect(True) as db:
        db.execute('DROP TRIGGER dev_events_update')
        row=db.execute("SELECT seq,payload FROM dev_events WHERE candidate=? AND kind='DEPLOYMENT'",(cid,)).fetchone()
        data=json.loads(row[1]);data['deployment_evidence']['receipt']['backup']['exists']=False
        db.execute('UPDATE dev_events SET payload=? WHERE seq=?',(json.dumps(data),row[0]))
    with pytest.raises(ValueError):record_success(ROOT,store,cid,client,human=fixture_human())
    assert not any(e['kind']=='OPERATIONAL_SUCCESS' for e in store.get(cid)['events'])


def test_collector_uses_actual_loopback_port_and_records_http_failures(monkeypatch):
    from scripts.collect_development_signals import collect
    from dev_agent.github import GitHub
    monkeypatch.setattr(GitHub,'read',lambda *a:dict(workflow_runs=[]))
    urls=[]
    def fail(url,**kwargs):
        urls.append(url);raise urllib.error.HTTPError(url,503,'unavailable',{},None)
    result=collect('owner/repo',invoke=lambda *a,**k:SimpleNamespace(stdout='ActiveState=active\nNRestarts=0'),open_url=fail)
    assert urls==['http://127.0.0.1:5001/development-agent']
    assert any(o['kind']=='http_failure' and o['synthetic'] is False for o in result['observations'])
    assert result['health']['http_status']==503


def test_deployment_executor_detects_financial_content_mutation(tmp_path):
    import sqlite3
    from deployment_agent.executor import Executor
    from dev_agent.store import Store
    root=tmp_path/'source';(root/'out').mkdir(parents=True);(root/'holdings.csv').write_text('fixture')
    path=root/'out/investment.db'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE positions(value)');db.execute('INSERT INTO positions VALUES(1)')
    ledger=Store(tmp_path/'authority/development-control.sqlite3');ledger.migrate()
    executor=Executor(root,tmp_path/'receipts',ledger.path);before=executor.protected()
    with sqlite3.connect(path) as db:db.execute('UPDATE positions SET value=2')
    assert not executor.protected_unchanged(before,executor.protected())


def test_failed_and_duplicate_discovery_keep_complete_run_identity(repo,store,monkeypatch):
    from dev_agent import scheduler
    monkeypatch.setattr(scheduler,'scout',lambda *a,**k:(_ for _ in ()).throw(ValueError('bounded failure')))
    result=scheduler.discover_daily(repo,store)
    assert result['status']=='FAILED' and len(result['head'])==40
    assert result['ended_at']>=result['started_at'] and result['duration_seconds']>=0
    assert result['trigger']['source']=='operator' and result['candidates']==[]


def test_missing_schema_cannot_create_signed_healthy_observation(tmp_path):
    from test_deployment_agent import FakeExecutor,authorization
    from deployment_agent.observer import observe
    from deployment_agent.service import deploy
    executor=FakeExecutor(tmp_path);auth=authorization()
    raw=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    raw.pop('deployment_evidence')
    with pytest.raises(ValueError):observe(executor,raw,key=b'fixture-observer-key-that-is-long-enough',now=raw['finished']+301)


def test_same_pr_release_cannot_manufacture_multiple_successes(store,monkeypatch):
    from test_development_agent_hardening import seed_completed_pilot,fixture_human
    from dev_agent import operations
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={'os-interactive-cli':['fixture-owner']})))
    cid,client=seed_completed_pilot(store);first=operations.record_success(ROOT,store,cid,client,human=fixture_human())
    with store.connect(True) as db:store._append(db,cid,'OPERATIONAL_SUCCESS',dict(first,run_id='duplicate-fixture-run'),'duplicate-fixture-release')
    result=operations.operational_runs(ROOT,store)
    assert len(result['qualifying'])==1
    assert any('duplicate' in r['reason'] for r in result['non_qualifying'])


def test_promotion_can_only_recommend_stage_after_real_shape_window(store,monkeypatch,complete_evidence):
    from dev_agent import promotion
    result=promotion.report(ROOT,store,complete_evidence['now'])
    assert result['recommendation']=='GO_FOR_OWNER_STAGE_REVIEW'
    assert result['recommended_stage']=='BUILD_ONLY' and len(result['qualifying_runs'])==3
    assert not result['enables_autonomy'] and result['safety_configuration']['autonomous_implementation'] is False
    assert result['observation_window']['observation_days']>=7


def test_missing_post_fix_measurement_is_not_inferred_from_health(store,monkeypatch):
    from test_development_agent_hardening import seed_completed_pilot,fixture_human
    from dev_agent import operations,promotion
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={'os-interactive-cli':['fixture-owner']})))
    cid,client=seed_completed_pilot(store);operations.record_success(ROOT,store,cid,client,human=fixture_human())
    with store.connect(True) as db:
        db.execute('DROP TRIGGER dev_events_update')
        seq,payload=db.execute("SELECT seq,payload FROM dev_events WHERE candidate=? AND kind='DEPLOYMENT'",(cid,)).fetchone()
        value=json.loads(payload);value.pop('metrics');db.execute('UPDATE dev_events SET payload=? WHERE seq=?',(json.dumps(value),seq))
    result=promotion.report(ROOT,store)
    assert any('recurrence observation unavailable' in reason for reason in result['blockers'])

from test_pr13_evidence_integrity import complete_evidence


# Imported deployment transaction fixtures require explicit isolated scoped policy.
from test_deployment_agent import scoped_transaction_policy
