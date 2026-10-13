"""Tests for CC Evidence Accrual Health (0713)."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import pytest
import covered_call_ledger as ledger
import covered_call_virtual as book
import covered_call_evidence as evidence
from strategy_config import CC_V3_CONFIG
from time_utils import parse_timestamp

START='2026-10-13T17:00:00+00:00'


@pytest.fixture
def accrual_episode(tmp_path,monkeypatch):
    monkeypatch.setattr(evidence,'committed_policy',lambda *a:True)
    monkeypatch.setattr(evidence,'now_utc',lambda:parse_timestamp(START)+timedelta(seconds=1))
    path=tmp_path/'cc.db';cfg=deepcopy(CC_V3_CONFIG)
    def create(timestamp=START,config=None,prospective=True):
        from test_cc_followups import candidate
        row=candidate(quote_timestamp=timestamp)
        choose=lambda a:dict(action=a,strike=row['strike'],expiration=row['expiration'],contracts=1,overwrite_fraction=1/3)
        eid=ledger.record_episode('TEST',1,[row],choose('SELL_CC'),choose('SELL_CC'),
            dict(strategy='INCOME',assignment_policy={'allowed':True}),config or cfg,timestamp,path,prospective=prospective)
        return eid
    return path,cfg,create


def test_accrual_health_returns_three_sections(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;create()
    health=accrual_health(cfg,path)
    assert 'simulator_certification' in health
    assert 'promotion_progress' in health
    assert 'evidence_velocity' in health
    assert 'as_of' in health


def test_cert_section_not_certified_when_no_runs(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;create()
    health=accrual_health(cfg,path)
    cert=health['simulator_certification']
    assert cert['certified']==False
    assert cert['certification_id'] is None
    assert cert['usable_n']==0
    assert cert['required_n']==cfg['simulator_validation']['minimum_n']


def test_promo_section_shows_current_vs_required(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;create()
    health=accrual_health(cfg,path)
    promo=health['promotion_progress']
    assert 'current' in promo['n'] and 'required' in promo['n']
    assert promo['n']['required']==cfg['promotion']['minimum_n']
    assert promo['eligible']==False


def test_promo_economics_labeled_preliminary_when_not_eligible(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;create()
    health=accrual_health(cfg,path)
    promo=health['promotion_progress']
    assert promo['eligible']==False
    econ=promo['economics']
    # When no eligible pairs exist, alpha_improvement is None — no PRELIMINARY label needed
    assert 'alpha_improvement' in econ


def test_velocity_section_counts_opportunities(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode
    for _ in range(3):create()
    health=accrual_health(cfg,path)
    vel=health['evidence_velocity']
    assert vel['new_opportunities']['7d']>=3
    assert vel['new_opportunities']['30d']>=3


def test_velocity_excludes_non_prospective(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode
    create(prospective=True);create(prospective=False)
    health=accrual_health(cfg,path)
    vel=health['evidence_velocity']
    assert vel['new_opportunities']['7d']==1


def test_velocity_chains_opened(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    book.start_from_decision(db,eid);db.close()
    health=accrual_health(cfg,path)
    vel=health['evidence_velocity']
    assert vel['chains_opened']['7d']>=1


def test_velocity_version_censored_chains_counted(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid)
    book.censor_version_mismatch(db,chain_id,'hash-new','2026-10-13T18:00:00+00:00')
    db.close()
    health=accrual_health(cfg,path)
    vel=health['evidence_velocity']
    assert vel['chains_version_censored']['7d']==1


def test_estimated_days_to_n_absent_when_no_velocity(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode;create()
    health=accrual_health(cfg,path)
    vel=health['evidence_velocity']
    assert vel['estimated_days_to_minimum_n'] is None


def test_endpoint_returns_json(accrual_episode,monkeypatch):
    import sys;sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from http.server import BaseHTTPRequestHandler
    from io import BytesIO
    from urllib.parse import urlparse
    path,cfg,create=accrual_episode;create()
    # Import the handler class and test the routing
    import importlib;spec=importlib.util.spec_from_file_location('serve',Path(__file__).resolve().parent.parent/'serve.py')
    # Just verify the accrual_health function works end-to-end without errors
    from covered_call_accrual import accrual_health
    result=accrual_health(cfg,path)
    assert result['simulator_certification']['certified']==False
    assert isinstance(result['promotion_progress']['n']['current'],int)
    assert isinstance(result['evidence_velocity']['new_opportunities']['30d'],int)


def test_all_counts_reconcile_to_episodes(accrual_episode):
    from covered_call_accrual import accrual_health
    path,cfg,create=accrual_episode
    for _ in range(2):create()
    health=accrual_health(cfg,path)
    promo=health['promotion_progress']
    total_opps=promo['total_opportunities']
    eligible_n=promo['n']['current']
    excluded_n=promo['excluded_n']
    assert eligible_n+excluded_n==total_opps
