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
