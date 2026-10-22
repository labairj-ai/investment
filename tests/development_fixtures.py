"""Explicit test-only authenticated adapters; no operational identity is inferred."""
import time
from types import SimpleNamespace
from dev_agent.store import digest
from dev_agent.identity import HumanIdentity, _PROOF


def human(actor='alice@example.test'):
    return HumanIdentity(actor,'fixture-only',_PROOF)


def protection_observation(repository='owner/repo',identity='agent',created=None,**changes):
    raw={'identity':{'login':identity},'repository':{'full_name':repository},'fixture_only':True}
    return dict(dict(status='PASS',created=time.time() if created is None else created,repository=repository,identity=identity,evidence=raw,evidence_hash=digest(raw),effective={'pr':True,'checks':True,'review':True,'no_bypass':True},required_checks=['test'],agent_capabilities={'direct_push':False}),**changes)


def client():
    return SimpleNamespace(repository='owner/repo',protections=protection_observation)


def start_protection(store,cid,adapter=None,root=None):
    from dev_agent.protection import require
    return require(store,cid,adapter or client(),'start',root=root)
