from __future__ import annotations
import json
import math
import sqlite3
from datetime import date
import numpy as np
import pandas as pd
import pytest
import covered_call_v3 as v
import covered_call_ledger as ledger
from strategy_config import CC_V3_CONFIG

CFG=dict(CC_V3_CONFIG,path_count=512)
POLICY=dict(strategy='INCOME',minimum_otm_pct=.03,max_preferred_delta=.30,preferred_dte_min=21,preferred_dte_max=60)


def row(**changes):
    r=dict(expiration='2026-11-12',dte=30,strike=110.,bid=1.8,ask=2.,mid=1.9,exec_premium=1.83,
      impliedVolatility=.25,delta=.15,cc_alpha=1.5,cc_alpha_pct=.015,annualized_ret=22.,
      regret_prob=.0000007,liquidity_score=80,score=75.,opp_score=75.,passes_floor=True,
      has_avoid=False,has_caution=False,risk_events=[],quote_timestamp='2026-10-13T17:00:00+00:00',
      spot=100.,theta=-.025,z_strike=1.)
    r.update(changes);return r


def test_drift_shrinkage_regimes_and_precision():
    estimates=[]
    for daily in (-.01,0,.01):
        ret=np.r_[np.linspace(-.01,.01,192),np.linspace(daily-.01,daily+.01,60)]
        d=v.drift_model(ret);estimates.append(d['mu_center'])
        assert d['mu_low']<d['mu_center']<d['mu_high']
        assert -.25<=d['mu_center']<=.35
        assert d['drift_inputs']['effective_n']==252
        assert abs(d['mu_center'])<.26
        assert d['drift_inputs']['posterior_weight']<=.36
        assert d==v.drift_model(ret)
    assert estimates[0]<estimates[1]<estimates[2]


@pytest.mark.parametrize('change,reason',[
    ({'dte':20},'DTE_BELOW_POLICY'),({'dte':61},'DTE_ABOVE_POLICY'),
    ({'delta':.31},'DELTA_ABOVE_POLICY'),({'strike':102},'OTM_BELOW_POLICY'),
    ({'has_avoid':True},'EVENT_AVOID'),({'bid':0},'INVALID_QUOTE'),
    ({'ask':1.5},'INVALID_QUOTE'),({'liquidity_score':5},'LIQUIDITY_BELOW_POLICY'),
    ({'passes_floor':False},'PROFIT_FLOOR'),({'delta':float('nan')},'INVALID_INPUT_DELTA')])
def test_hard_gates(change,reason):
    assert reason in v.eligibility(row(**change),POLICY,100)


def test_assignment_and_earnings():
    assert 'ASSIGNMENT_FLOOR' in v.eligibility(row(),dict(POLICY,acceptable_assignment_min_price=111),100)
    assert 'ASSIGNMENT_NOT_ALLOWED' in v.eligibility(row(),dict(POLICY,assignment_policy={'allowed':False}),100)
    assert 'ASSIGNMENT_THESIS_DATA_MISSING' in v.eligibility(row(),dict(POLICY,assignment_policy={'preserve_high_conviction':True}),100)
    assert 'EARNINGS_POLICY' in v.eligibility(row(risk_events=[{'event':'earnings','severity':'caution'}]),dict(POLICY,avoid_earnings=True),100)
    assert 'NON_LIVE_QUOTE' in v.eligibility(row(),POLICY,100,'theoretical')


@pytest.mark.parametrize('mu,sigma',[(.08,.2),(-.15,.4),(.3,.25)])
def test_analytic_bridge_matches_mc(mu,sigma):
    analytic=v.touch_probability(100,110,60/365,sigma,mu)
    mc=v.path_oracle(100,110,2,60,sigma,mu,paths=20000)['mc_strike_touch_prob']
    assert abs(analytic-mc)<.02
    assert analytic>=__import__('covered_call_rec').itm_prob_real(100,110,60/365,sigma,mu)


def test_delta_thresholds_and_bounded_management():
    out=v.path_oracle(100,95,2,20,.25,.08,paths=100)
    assert out['delta30_touch_prob']==out['delta50_touch_prob']==1
    out=v.path_metrics(100,row(),v.drift_model([]),paths=100)
    assert 0<=out['management_risk']<=1
    assert out['delta30_touch_prob']>=out['delta50_touch_prob']
    assert v.touch_probability(100,110,1,0,.2)==1
    assert v.touch_probability(100,110,1,0,-.2)==0


@pytest.mark.parametrize('slope',[-.004,0,.004])
def test_surface_distinct_term_skew(slope):
    rows=[]
    for days in (28,56,84):
        for delta in (.2,.25,.3,.5,.6):
            rows.append(row(expiration=f'2026-{days}',dte=days,delta=delta,impliedVolatility=.25+slope*days+.05*(delta-.5)))
    values=v.surface(rows,100,.2)
    assert values[1]['term_richness'] is not None
    if slope==0:assert abs(values[1]['term_richness'])<1e-10
    else:assert values[1]['term_richness']*slope<0
    assert values[1]['skew_richness']<0
    assert values[1]['vrp_estimate'] is not None
    assert values[1]['surface_quality']=='LOCAL'


def test_surface_broken_and_missing():
    rows=[row(bid=0),row(ask=1),row(quote_timestamp='2026-10-01T00:00:00+00:00'),row()]
    out=v.surface(rows,100,.2,now='2026-10-13')
    assert all(not x['surface_point_usable'] for x in out[:3])
    assert all(x['surface_quality']=='INSUFFICIENT' for x in out)
    assert all(x['term_richness'] is None for x in out)


@pytest.mark.parametrize('tax,upside,expected',[(.1,.1,True),(.1,1.8,False),(None,.1,False)])
def test_utility_reconciles_and_hurdle(tax,upside,expected):
    r=row(upside_lost_conservative=upside,management_risk=.2,expected_execution_cost=.05,
          expected_tax_cost=tax,expected_roll_slippage=.1)
    u=v.utility(r,100,CFG)
    if tax is None:assert u['utility_margin'] is None
    else:
        assert u['adjusted_cc_alpha']==u['expected_premium']-u['expected_upside_surrendered']-u['expected_management_cost']-u['expected_execution_cost']-u['expected_tax_cost']
        assert (u['utility_margin']>0)==expected
        assert u['adjusted_cc_alpha_per_day']==u['adjusted_cc_alpha']/30


def test_regime_coverage_and_disable():
    closes=100*np.exp(np.arange(253)*.003)
    strong=v.regime_model(closes,{'conviction':5})
    assert strong['regime_state']=='STRONG_UPTREND'
    neutral=v.regime_model(np.full(253,100),{})
    assert neutral['regime_state']=='NEUTRAL'
    assert v.regime_model(100*np.exp(-np.arange(253)*.003),{})['regime_state']=='DOWNTREND'
    assert v.overwrite(300,POLICY,strong,CFG)['recommended_contracts']==1
    assert v.overwrite(300,POLICY,neutral,CFG)['recommended_contracts']==3
    assert v.overwrite(300,POLICY,strong,dict(CFG,regime_enabled=False))['recommended_contracts']==3
    for shares in (0,50,100,300,450):
        sizing=v.overwrite(shares,dict(POLICY,max_overwrite_fraction=.25),neutral,CFG)
        assert sizing['recommended_contracts']*100<=shares*.25


def test_execution_prior_shrinkage_real_only():
    prior=v.execution(row(),[],CFG)
    assert prior['expected_fill_fraction']==.15
    estimated=[dict(bucket='wide',actual=False,fill_fraction=.5)]*100
    assert v.execution(row(),estimated,CFG)['execution_bucket_n']==0
    bucket=prior['execution_bucket']
    real=[dict(bucket=bucket,actual=True,fill_fraction=.5)]*29
    assert v.execution(row(),real,CFG)['expected_fill_fraction']==.15
    calibrated=v.execution(row(),real*2,CFG)
    assert .15<calibrated['expected_fill_fraction']<.5
    assert calibrated['expected_roll_slippage']>calibrated['expected_entry_slippage']
    assert not v.execution(row(ask=1),[],CFG)['execution_available']


def episode(tmp_path,rows=None,champion=None,challenger=None):
    path=tmp_path/'cc.db'
    c=champion or dict(action='SELL_CC',strike=110.,expiration='2026-11-12',contracts=1,overwrite_fraction=1/3)
    return path,ledger.record_episode('TEST','run1',rows or [row(eligible=True,rejection_reasons=[],management_risk=.1,strike_touch_prob=.1)],c,challenger or dict(action='NO_CALL'),POLICY,CFG,path=path)


def test_immutable_episode_and_rejections(tmp_path):
    path,eid=episode(tmp_path,[row(eligible=False,rejection_reasons=['DTE_ABOVE_POLICY'])])
    db=ledger.connect(path)
    for table in ('cc_decisions','cc_candidates'):
        with pytest.raises(sqlite3.IntegrityError): db.execute(f'DELETE FROM {table}')
    with pytest.raises(sqlite3.IntegrityError):db.execute("UPDATE cc_decisions SET ticker='BAD'")
    db.close()
    data=ledger.report(path)
    assert data['decisions'][0]['candidates'][0]['features']['rejection_reasons']==['DTE_ABOVE_POLICY']
    assert data['decisions'][0]['champion']['overwrite_fraction']==1/3
    assert data['decisions'][0]['git_sha']


def test_path_touch_without_terminal_regret():
    f=row(strike=110,exec_premium=2,expiration='2026-10-16',impliedVolatility=.3)
    bars=[dict(date='2026-10-14',high=116,low=99,close=116,coverage_verified=True),dict(date='2026-10-15',high=112,low=105,close=110,coverage_verified=True),dict(date='2026-10-16',high=109,low=106,close=107,coverage_verified=True)]
    out=ledger.label_path(f,bars,date(2026,10,17))
    assert out['strike_touched'] and out['regret_barrier_touched']
    assert out['expired_otm'] and not out['censored']
    assert out['estimated_expiry_incremental_alpha']==2
    assert out['delta50_event']
    assert out['days_to_first_touch']==1
    assert out['total_option_pnl'] is None
    partial=ledger.label_path(f,bars[:1],date(2026,10,15))
    assert partial['censored']
    nohit=ledger.label_path(f,[dict(date='2026-10-14',high=105,low=99,close=100)],date(2026,10,15))
    assert nohit['strike_touched'] is None


def test_chain_censoring_and_cash_flow():
    f=row(expiration='2026-10-16',shares_potentially_delivered=100)
    bars=[dict(date='2026-10-16',high=105,low=99,close=101,coverage_verified=True)]
    chain=[dict(action='SELL_CC',actual=True,option_cash_flow=200,fees=1,execution_date='2026-10-13')]
    open_label=ledger.label_path(f,bars,date(2026,10,17),chain,'chain1')
    assert open_label['chain_censored']
    chain += [dict(action='BUY_TO_CLOSE',recommendation_action='ROLL_UP',actual=True,option_cash_flow=-300,fees=1,execution_date='2026-10-14'),dict(action='ROLL_UP',actual=True,option_cash_flow=350,fees=1,execution_date='2026-10-14')]
    assert ledger.label_path(f,bars,date(2026,10,17),chain)['chain_censored']
    chain.append(dict(action='EXPIRED',actual=True,option_cash_flow=0,fees=0,execution_date='2026-10-16'))
    out=ledger.label_path(f,bars,date(2026,10,17),chain,'chain1')
    assert out['rolled'] and out['roll_hops']==1 and not out['chain_censored']
    assert out['total_option_pnl']==247 and out['cc_incremental_alpha']==2.47
    assert out['roll_net_credit']==50


def test_actual_fills_and_idempotency(tmp_path):
    path,eid=episode(tmp_path)
    args=('fill1',eid,'TEST:20261112:110',1.9,1.8,2.,'2026-10-13T17:01:00+00:00')
    out=ledger.record_fill(*args,quote_timestamp='2026-10-13T17:00:00+00:00',path=path)
    assert abs(out['fill_fraction']-.5)<1e-10
    with pytest.raises(sqlite3.IntegrityError): ledger.record_fill(*args,quote_timestamp='2026-10-13T17:00:00+00:00',path=path)
    with pytest.raises(ValueError): ledger.record_fill(*args,quote_timestamp='2026-10-13T16:00:00+00:00',path=path)
    assert len(ledger.execution_history(path))==1


def test_labels_separate_dedup_calibration_promotion(tmp_path):
    path,eid=episode(tmp_path)
    cid='TEST:20261112:110'
    labels=dict(censored=False,strike_touched=False,chain_censored=True)
    ledger.append_label(eid,cid,labels,{'test':1},path)
    ledger.append_label(eid,cid,labels,{'test':1},path)
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_labels').fetchone()[0]==1;db.close()
    result=ledger.report(path)
    assert result['calibration']['strike_touch_prob']['n']==1
    assert result['calibration']['strike_touch_prob']['brier']==pytest.approx(.01)
    evidence=ledger.promotion_evidence(CFG,path)
    assert not evidence['eligible'] and evidence['n']==0
    with pytest.raises(ValueError):ledger.transition('v3',CFG,path)
    assert ledger.active_scorer(CFG,path)=='v2'
    ledger.transition('v2',CFG,path)


@pytest.mark.parametrize('a,b,result',[
 ({'action':'NO_CALL'},{'action':'NO_CALL'},'SAME_NO_CALL'),
 ({'action':'SELL_CC'},{'action':'NO_CALL'},'CHAMPION_CALL_CHALLENGER_NO_CALL'),
 ({'action':'NO_CALL'},{'action':'SELL_CC'},'CHALLENGER_CALL_CHAMPION_NO_CALL'),
 ({'action':'SELL_CC','strike':100},{'action':'SELL_CC','strike':105},'DIFFERENT_STRIKE'),
 ({'action':'SELL_CC','contracts':1},{'action':'SELL_CC','contracts':2},'DIFFERENT_COVERAGE'),
 ({'action':'SELL_CC','expiration':'a'},{'action':'SELL_CC','expiration':'b'},'DIFFERENT_EXPIRY')])
def test_divergence(a,b,result):assert v.divergence(a,b)==result


def test_prepare_retains_invalid_universe_and_bad_no_call(monkeypatch):
    monkeypatch.setattr(v,'tax_metrics',lambda *args:dict(expected_tax_cost=0.,tax_data_available=True))
    rows=[row(delta=.31,opp_score=99),row(bid=.05,ask=.06,exec_premium=.051,strike=104,delta=.25),row(dte=65,opp_score=98)]
    result=dict(all_calls=pd.DataFrame(rows),recs=pd.DataFrame(rows[:1]),current_price=100,vol_model=dict(v.drift_model(np.linspace(-.01,.01,252)),hv_forecast=.2),data_mode='live',snapshot_timestamp='2026-10-13T17:00:00+00:00')
    features,challenger=v.prepare('TEST',result,POLICY,300,CFG)
    assert len(features)==3
    assert not features[0]['eligible'] and not features[2]['eligible']
    assert features[1]['v2_rank']==1
    assert challenger['action']=='NO_CALL'
    assert features[1]['regret_prob_conservative']>=features[1]['regret_prob_base']
    assert features[1]['cc_alpha_conservative']<=features[1]['cc_alpha_base']
    assert features[1]['regret_prob']==.0000007


def test_duration_normalized_v2_and_candidate_precision():
    import covered_call_rec as rec
    from agents.covered_call_agent import _build_candidates
    df=pd.DataFrame([row(strike=105,premium_pct=2.,annualized_ret=26.,iv_richness=.2,upside_to_strike=5),
                     row(strike=110,dte=60,premium_pct=3.,annualized_ret=18.,iv_richness=.2,upside_to_strike=5)])
    scored=rec._compute_scores(df)
    assert scored.iloc[0]['score']>scored.iloc[1]['score']
    candidates,_=_build_candidates('TEST',scored)
    assert candidates[0]['regret_prob']==.0000007


def test_entry_zero_valid_no_llm_and_rejected_retained(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import covered_call_rec
    import agent_db
    from agents import covered_call_agent as agent
    path=tmp_path/'agent.db'
    monkeypatch.setattr(agent_db,'DB_PATH',path)
    monkeypatch.setattr(agent_db,'get_active_thesis',lambda t:None)
    monkeypatch.setattr(agent_db,'insert_finding',lambda **kw:None)
    monkeypatch.setattr(agent,'_has_open_cc',lambda t:False)
    monkeypatch.setattr(agent,'_get_cc_policy',lambda t:dict(POLICY))
    monkeypatch.setattr(v,'tax_metrics',lambda *args:dict(expected_tax_cost=0.,tax_data_available=True))
    invalid=row(delta=.45,iv_richness=.2)
    result=dict(recs=pd.DataFrame([invalid]),all_calls=pd.DataFrame([invalid]),current_price=100,
        data_mode='live',vol_model=dict(v.drift_model([]),hv_forecast=.2))
    monkeypatch.setattr(covered_call_rec,'analyze',lambda *args:result)
    monkeypatch.setattr(agent.ollama_client,'generate_structured',lambda **kw:pytest.fail('LLM must not run on invalid candidates'))
    ctx=SimpleNamespace(run_id=1,snapshot=SimpleNamespace(holdings=[SimpleNamespace(ticker='TEST',shares=300,avg_cost=90,current_price=100,layer=1,weight_pct=10)]))
    assert agent._analyze_ticker(ctx,'TEST')==[]
    audit=ledger.report(path)
    assert audit['decisions'][0]['champion']['action']=='NO_CALL'
    assert audit['decisions'][0]['candidates'][0]['features']['rejection_reasons']==['DELTA_ABOVE_POLICY']


def test_entry_filter_before_topn(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import covered_call_rec
    import agent_db
    from agents import covered_call_agent as agent
    path=tmp_path/'agent2.db'
    monkeypatch.setattr(agent_db,'DB_PATH',path)
    monkeypatch.setattr(agent_db,'get_active_thesis',lambda t:None)
    monkeypatch.setattr(agent_db,'insert_finding',lambda **kw:None)
    monkeypatch.setattr(agent,'_has_open_cc',lambda t:False)
    monkeypatch.setattr(agent,'_get_cc_policy',lambda t:dict(POLICY))
    monkeypatch.setattr(v,'tax_metrics',lambda *args:dict(expected_tax_cost=0.,tax_data_available=True))
    invalid=[row(strike=103+i,delta=.45,opp_score=99,iv_richness=.2) for i in range(25)]
    valid=row(strike=135,delta=.10,opp_score=60,iv_richness=.2)
    result=dict(recs=pd.DataFrame(invalid[:20]),all_calls=pd.DataFrame(invalid+[valid]),current_price=100,
        data_mode='live',vol_model=dict(v.drift_model([]),hv_forecast=.2))
    monkeypatch.setattr(covered_call_rec,'analyze',lambda *args:result)
    def llm(**kw):
        assert 'strike=$135.00' in kw['prompt']
        return dict(action='NO_CALL',why='test no call')
    monkeypatch.setattr(agent.ollama_client,'generate_structured',llm)
    ctx=SimpleNamespace(run_id=1,snapshot=SimpleNamespace(holdings=[SimpleNamespace(ticker='TEST',shares=300,avg_cost=90,current_price=100,layer=1,weight_pct=10)]))
    assert agent._analyze_ticker(ctx,'TEST')==[]
    assert len(ledger.report(path)['decisions'][0]['candidates'])==26


def test_liquidity_scale():
    from agents.covered_call_agent import _build_evidence
    assert not _build_evidence(dict(data_mode='live'),[dict(liquidity_score=1)]).option_liquidity_good
    assert _build_evidence(dict(data_mode='live'),[dict(liquidity_score=70)]).option_liquidity_good


def test_tax_reuses_fifo_projected_holding_period(monkeypatch):
    import covered_call_rec as rec
    from types import SimpleNamespace
    captured={}
    def lot(ticker,strike,shares,disposal_date):
        captured.update(ticker=ticker,strike=strike,shares=shares,disposal_date=disposal_date)
        return SimpleNamespace(available=True,lot_schedule=[dict(allocated_shares=100,cost_per_share=90,friction_contribution=20)])
    monkeypatch.setattr(rec,'_lot_tax_friction',lot)
    out=v.tax_metrics('TEST',row(itm_prob_real_conservative=.2),1,POLICY)
    assert captured['disposal_date']==date(2026,11,12)
    assert captured['shares']==100 and captured['strike']==110
    assert out['expected_tax_cost']==pytest.approx(.04)
    assert out['projected_assignment_gain']==2000
    assert out['qualified_covered_call_state']=='UNASSESSED'


def test_label_refresh_verified_sessions_and_idempotence(tmp_path):
    path,eid=episode(tmp_path,[row(expiration='2026-10-16',eligible=True,strike_touch_prob=.1)])
    def fetch(ticker,start,end):
        return [dict(date=f'2026-10-{d}',high=105,low=99,close=100) for d in (14,15,16)]
    result=ledger.refresh_labels(path,date(2026,10,17),fetch)
    assert result['labeled']==1 and not result['errors']
    result=ledger.report(path)
    assert not result['decisions'][0]['candidates'][0]['labels']['censored']
    assert result['decisions'][0]['candidates'][0]['labels']['chain_censored']
    ledger.refresh_labels(path,date(2026,10,17),fetch)
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_labels').fetchone()[0]==1;db.close()


def test_config_activation_mode_does_not_change_cohort_hash():
    assert ledger.config_digest(CFG)==ledger.config_digest(dict(CFG,mode='evidence_gated'))
    assert ledger.config_digest(CFG)!=ledger.config_digest(dict(CFG,utility_hurdle_annual_pct=.10))


def test_event_distorted_surface_explicit_estimate():
    rows=[]
    for days,iv,event in [(21,.2,False),(42,.4,True),(63,.35,True)]:
        for delta in (.2,.25,.3,.5,.6):
            rows.append(row(expiration=f'event-{days}',dte=days,delta=delta,
                impliedVolatility=iv,risk_events=[{'type':'earnings'}] if event else []))
    out=v.surface(rows,100,.2)
    assert out[6]['event_variance_estimate']>0
    assert out[6]['event_premium']>0
    assert out[6]['event_variance_state']=='LOCAL_PRE_EVENT_BASELINE_ESTIMATE'
    assert out[1]['event_premium'] is None


def test_small_drift_perturbation_does_not_flip_ranking(monkeypatch):
    monkeypatch.setattr(v,'tax_metrics',lambda *args:dict(expected_tax_cost=0.,tax_data_available=True))
    candidates=[row(strike=115,bid=1.9,ask=2.,delta=.15),row(strike=110,bid=.2,ask=.3,delta=.25)]
    peers=[row(strike=100,delta=d) for d in (.2,.25,.3,.5,.6)]
    result=dict(recs=pd.DataFrame(candidates),all_calls=pd.DataFrame(candidates),surface_points=peers,
      current_price=100,data_mode='live',snapshot_timestamp='2026-10-13T17:00:00+00:00',vol_model=dict(v.drift_model([]),hv_forecast=.2))
    first=v.prepare('TEST',result,POLICY,300,CFG)[1]
    result['vol_model']['mu_center']+=.001;result['vol_model']['mu_high']+=.001
    second=v.prepare('TEST',result,POLICY,300,CFG)[1]
    assert first==second


def test_explicit_coverage_cap_execution_validation():
    from execution_validation import validate_execution_body
    from datetime import datetime,timezone
    rec=dict(created_at=datetime(2026,10,13,tzinfo=timezone.utc).timestamp(),action_payload_json=json.dumps({'contracts':1}))
    body=dict(execution_date='2026-10-13',contracts=2,strike=110,premium=2,expiration='2026-11-12')
    error=validate_execution_body('SELL_CC',body,rec,date(2026,10,13),server_pos_before=300)
    assert error and 'authorized' in error[1]


def test_reconciled_chain_evidence_requires_matching_origin(tmp_path):
    path,eid=episode(tmp_path)
    decision=ledger.report(path)['decisions'][0]
    chain_id=decision['champion']['trade_chain_id']
    evidence=ledger.record_chain_costs(eid,chain_id,5,2,0,False,100,105,'broker statement + intervention log',path=path)
    assert evidence['cost_source']=='RECONCILED_OBSERVATION'
    with pytest.raises(ValueError):ledger.record_chain_costs(eid,'wrong',5,2,0,False,100,105,'broker',path=path)
    with pytest.raises(ValueError):ledger.record_chain_costs(eid,chain_id,None,2,0,False,100,105,'broker',path=path)
    db=ledger.connect(path)
    with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM cc_chain_costs')
    db.close()


def test_surface_outlier_unusable_and_raw_rejections_retained(monkeypatch):
    points=[row(delta=x) for x in (.2,.25,.3,.5,.6)]+[row(delta=.4,impliedVolatility=2.)]
    assert not v.surface(points,100,.2)[-1]['surface_point_usable']
    monkeypatch.setattr(v,'tax_metrics',lambda *args:dict(expected_tax_cost=0.,tax_data_available=True))
    result=dict(recs=pd.DataFrame([row()]),all_calls=pd.DataFrame([row()]),current_price=100,
        data_mode='live',vol_model=dict(v.drift_model([]),hv_forecast=.2),
        raw_rejected_quotes=[dict(expiration='2026-11-12',strike=105,dte=30,bid=0,ask=1,raw_quote_only=True)])
    features,decision=v.prepare('TEST',result,POLICY,300,CFG)
    assert len(features)==2 and not features[-1]['eligible']
    assert 'INVALID_QUOTE' in features[-1]['rejection_reasons']
