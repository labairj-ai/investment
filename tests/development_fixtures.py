"""Explicit test-only authenticated adapters; no operational identity is inferred."""
import time
from types import SimpleNamespace
from dev_agent.store import digest
from dev_agent.identity import HumanIdentity, _PROOF


def human(actor='alice@example.test'):
    return HumanIdentity(actor,'fixture-only',_PROOF)


def protection_observation(repository='owner/repo',identity='agent',created=None,**changes):
    raw={'identity':{'login':identity,'id':100},'repository':{'full_name':repository,'id':2},'fixture_only':True}
    return dict(dict(status='PASS',created=time.time() if created is None else created,repository=repository,identity=identity,evidence=raw,evidence_hash=digest(raw),effective={k:True for k in ('pr','checks','review','stale','last_push','conversation','no_force','no_delete','admin')},required_checks=['test'],agent_capabilities={k:False for k in ('direct_push','bypass_review','bypass_checks','force_push','delete_ref','bypass_conversations','self_approve')}),**changes)


def client():
    return SimpleNamespace(repository='owner/repo',protections=protection_observation)


def start_protection(store,cid,adapter=None,root=None):
    from dev_agent.protection import require
    return require(store,cid,adapter or client(),'start',root=root)


def deployment_evidence(repository='owner/repo',pr=1,head='a'*40,merge='c'*40):
    """Synthetic isolated ledger adapter; never persisted to operational paths."""
    from dev_agent.deployment_evidence import seal
    def ci(sha,run):return dict(head=sha,run_id=run,status='PASS',url=f'https://github.com/{repository}/actions/runs/{run}')
    return seal(dict(repository=repository,pr=pr,head=head,merge_sha=merge,deployed_sha=merge,prior_sha='b'*40,main_sha=merge,deployed_at='2020-01-01T00:00:00+00:00',actor='deployment-agent',fixture_only=False,head_ci=ci(head,1),merge_ci=ci(merge,2),health=dict(service_active=True,dashboard_http=200,development_dashboard_http=200,authenticated_api_http=200,unauthorized_api_http=403,advisor_functional='PASS',advisor_mutation_safety='PASS'),backup=dict(exists=True,integrity='ok',sha256='f'*64),activation=dict(autonomous_implementation=False,supervised_loop_enabled=False,supervised_publish_pr=False,auto_merge=False),state_safety=dict(holdings_unchanged=True,investment_state_unchanged=True,development_ledger_unchanged=True)))


def isolated_runtime_admission(monkeypatch):
    """Trusted adapter for legacy pipeline/budget unit scope only.

    Shared gate/owner refusal are exercised without this adapter in the exhaustive
    0833 parity tests. No fixture record is written to operational storage.
    """
    from dev_agent import qualification,owner_promotion
    monkeypatch.setattr(qualification,'evaluate',lambda *a,**k:dict(status='PASS',blockers=[],fixture_only=True,grants_authority=False))
    monkeypatch.setattr(owner_promotion,'authorization',lambda *a,**k:dict(status='PASS',authenticated=True,fixture_only=True,grants_authority=False))
