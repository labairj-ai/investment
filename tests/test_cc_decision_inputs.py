"""0806: invalid decision inputs stop before calculations and challenger selection."""
import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace, ModuleType

import numpy as np
import pandas as pd
import pytest

from agents import covered_call_agent as agent
from test_covered_call_v3 import row, POLICY


@pytest.fixture
def environment(monkeypatch):
    import agent_db
    import covered_call_rec
    import covered_call_v3
    import covered_call_ledger
    findings=[]
    raw=row(iv_richness=.2)
    result=dict(recs=pd.DataFrame([raw]),all_calls=pd.DataFrame([raw]),current_price=100.,data_mode='live',vol_model=dict(hv_forecast=.2))
    ctx=SimpleNamespace(run_id=1,snapshot=SimpleNamespace(holdings=[SimpleNamespace(ticker='TEST',shares=300.,avg_cost=90.,current_price=100.,layer=1,weight_pct=10.)],macro_scores={}))
    monkeypatch.setattr(agent_db,'get_active_thesis',lambda *a:None)
    monkeypatch.setattr(agent_db,'insert_finding',lambda **kw:findings.append(kw))
    monkeypatch.setattr(agent_db,'get_open_cc_for_ticker',lambda *a:None)
    monkeypatch.setattr(agent_db,'upsert_option_quote_snapshot',lambda **kw:1)
    monkeypatch.setattr(agent_db,'get_latest_earnings_date',lambda *a:None)
    monkeypatch.setattr(agent_db,'get_latest_financial_snapshot_hash',lambda *a:None)
    monkeypatch.setattr(agent_db,'_get_thesis_version_for_hash',lambda *a:1)
    monkeypatch.setattr(covered_call_rec,'analyze',lambda *a:result)
    monkeypatch.setattr(covered_call_ledger,'execution_history',lambda *a:[])
    monkeypatch.setattr(covered_call_ledger,'surface_history',lambda *a:[])
    monkeypatch.setattr(covered_call_ledger,'record_episode',lambda *a:1)
    monkeypatch.setattr(covered_call_ledger,'active_scorer',lambda *a:'v2')
    def configure(module):
        monkeypatch.setattr(module,'_has_open_cc',lambda *a:False)
        monkeypatch.setattr(module,'_get_cc_policy',lambda *a:dict(POLICY))
    configure(agent)
    monkeypatch.setattr(covered_call_v3,'prepare',lambda *a:([dict(raw,eligible=True)],{'action':'NO_CALL','contracts':0}))
    monkeypatch.setattr(agent.ollama_client,'generate_structured',lambda **kw:dict(action='SELL_CC',contract_id=agent._make_contract_id('TEST',raw['expiration'],raw['strike']),why='finite fixture',main_tradeoff='finite fixture',no_call_case='finite fixture'))
    return ctx,result,raw,findings,configure


@pytest.mark.parametrize('field,value,reason',[
    ('cc_alpha',float('nan'),'NON_FINITE_DECISION_INPUT_CC_ALPHA'),
    ('exec_premium',float('inf'),'NON_FINITE_DECISION_INPUT_EXEC_PREMIUM'),
    ('regret_prob',float('nan'),'NON_FINITE_DECISION_INPUT_REGRET_PROB'),
    ('delta',np.float64('nan'),'NON_FINITE_DECISION_INPUT_DELTA'),
    ('dte',float('inf'),'NON_FINITE_DECISION_INPUT_DTE'),
    ('impliedVolatility',float('inf'),'NON_FINITE_DECISION_INPUT_IMPLIEDVOLATILITY'),
    ('liquidity_score',float('nan'),'NON_FINITE_DECISION_INPUT_LIQUIDITY_SCORE'),
])
def test_raw_invalid_inputs_do_not_reach_prepare_or_recommendation(environment,monkeypatch,field,value,reason):
    import covered_call_v3
    ctx,result,raw,findings,_=environment
    result['all_calls'][field]=result['all_calls'][field].astype(float)
    result['all_calls'].loc[0,field]=value
    monkeypatch.setattr(covered_call_v3,'prepare',lambda *a:pytest.fail('invalid input reached challenger math'))
    assert agent._analyze_ticker(ctx,'TEST')==[]
    assert reason in findings[-1]['summary'] and findings[-1]['finding_type']=='cc_insufficient_data'


def test_invalid_spot_stops_before_financial_summary(environment,monkeypatch):
    import covered_call_rec
    ctx,_,_,findings,_=environment;ctx.snapshot.holdings[0].current_price=np.float64('nan')
    monkeypatch.setattr(covered_call_rec,'analyze',lambda *a:pytest.fail('invalid spot reached recommendation math'))
    assert agent._analyze_ticker(ctx,'TEST')==[]
    assert 'NON_FINITE_DECISION_INPUT_CURRENT_PRICE' in findings[-1]['summary']


def test_invalid_prepared_required_metric_cannot_reach_comparison(environment,monkeypatch):
    import covered_call_v3
    ctx,_,raw,findings,_=environment
    monkeypatch.setattr(covered_call_v3,'prepare',lambda *a:([dict(raw,eligible=True,cc_alpha=float('nan'))],{'action':'NO_CALL'}))
    monkeypatch.setattr(agent,'_build_candidates',lambda *a:pytest.fail('invalid comparison input'))
    assert agent._analyze_ticker(ctx,'TEST')==[]
    assert 'NON_FINITE_DECISION_INPUT_CC_ALPHA' in findings[-1]['summary']


def test_valid_finite_recommendation_matches_actual_cc_v34_source(environment):
    ctx,_,_,_,configure=environment
    # Read the immutable deployed baseline, remove registration side effects, and
    # run both implementations on the same isolated inputs and adapters.
    root=Path(__file__).resolve().parents[1]
    source=subprocess.check_output(['git','-C',str(root),'show','0c775008ad9ec0fa8ed32cc61a1d9c3215ce80ce:agents/covered_call_agent.py'],text=True)
    tree=ast.parse(source);tree.body=[n for n in tree.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='register_agent')]
    baseline=ModuleType('agents.cc_v34_fixture');baseline.__package__='agents';baseline.__file__=agent.__file__
    exec(compile(tree,'cc-v3.4-fixture','exec'),baseline.__dict__)
    configure(baseline)
    expected=baseline._analyze_ticker(ctx,'TEST');actual=agent._analyze_ticker(ctx,'TEST')
    assert actual and expected
    assert actual[0]==expected[0]
    json.dumps(actual[0].action_payload,allow_nan=False)


def test_numpy_scalars_are_json_safe_without_changing_finite_values():
    payload={'nan':np.float32('nan'),'inf':np.float64('inf'),'integer':np.int64(17),'finite':np.float32(.125),'missing':pd.NA,'flag':np.bool_(False)}
    encoded=json.loads(json.dumps(agent._sanitize_payload(payload),allow_nan=False))
    assert encoded=={'nan':None,'inf':None,'integer':17,'finite':.125,'missing':None,'flag':False}


def test_required_missing_values_are_not_zero():
    assert agent._decision_inputs({'cc_alpha':None})==['MISSING_DECISION_INPUT_CC_ALPHA']
    assert agent._decision_inputs({'cc_alpha':0.,'delta':0.})==[]


def test_management_rejects_invalid_contract_before_price_math(environment,monkeypatch):
    import covered_call_rec
    ctx,_,_,findings,_=environment
    monkeypatch.setattr(covered_call_rec,'evaluate_open_position',lambda **kw:pytest.fail('invalid management metric reached math'))
    position=dict(strike=110.,expiry='2026-11-12',premium_per_contract=float('inf'),contracts=3)
    assert agent._analyze_roll(ctx,'TEST',position)==[]
    assert 'NON_FINITE_DECISION_INPUT_PREMIUM' in findings[-1]['summary']


def test_nonfinite_volatility_model_stops_before_challenger_math(environment,monkeypatch):
    import covered_call_v3
    ctx,result,_,findings,_=environment
    result['vol_model']['hv_forecast']=np.float64('nan')
    monkeypatch.setattr(covered_call_v3,'prepare',lambda *a:pytest.fail('invalid forecast reached math'))
    assert agent._analyze_ticker(ctx,'TEST')==[]
    assert 'NON_FINITE_DECISION_INPUT_HV_FORECAST' in findings[-1]['summary']


def test_unrepresentable_decision_values_fail_closed_but_json_integers_remain_exact():
    value=10**400
    assert agent._decision_inputs({'shares':value})==['UNREPRESENTABLE_DECISION_INPUT_SHARES']
    assert agent._safe_float(value) is None
    assert json.loads(json.dumps(agent._sanitize_payload({'evidence_integer':value})))['evidence_integer']==value
