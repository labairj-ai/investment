from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timedelta,timezone,date
import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest
import covered_call_ledger as ledger
import covered_call_evidence as evidence
import covered_call_outcomes as outcomes
import covered_call_virtual as book
import covered_call_validation as validation
from covered_call_surface import surface_v2,duration_adjust
from strategy_config import CC_V3_CONFIG
from time_utils import parse_timestamp

START='2026-10-13T17:00:00+00:00'


def candidate(**kw):
    data=dict(strike=110.,expiration='2026-11-12',dte=30,spot=100.,bid=1.8,ask=2.,impliedVolatility=.3,
        delta=.15,quote_timestamp=START,eligible=True,eligible_contracts_max=3,recommended_contracts=1,
        origin_holding_shares=300.,tax_data_available=True,assignment_lot_schedule=[dict(purchase_date='2025-01-01',allocated_shares=100,cost_per_share=90)],
        expected_fill_fraction=.15,mu_center=.08,hv_forecast=.25,score=70,opp_score=70,regret_prob=.02,
        strike_touch_prob=.1,management_risk=.1,rejection_reasons=[],otm_pct=.1)
    data.update(kw);return data


@pytest.fixture
def episode(tmp_path,monkeypatch):
    monkeypatch.setattr(evidence,'committed_policy',lambda *a:True)
    monkeypatch.setattr(evidence,'now_utc',lambda:parse_timestamp(START)+timedelta(seconds=1))
    path=tmp_path/'cc.db';cfg=deepcopy(CC_V3_CONFIG)
    def create(champion='SELL_CC',challenger='SELL_CC',ticker='TEST',timestamp=START,config=None,prospective=True):
        row=candidate(quote_timestamp=timestamp)
        choose=lambda a:dict(action=a,strike=row['strike'],expiration=row['expiration'],contracts=1,overwrite_fraction=1/3) if a=='SELL_CC' else dict(action='NO_CALL',contracts=0)
        eid=ledger.record_episode(ticker,1,[row],choose(champion),choose(challenger),dict(strategy='INCOME',assignment_policy={'allowed':True}),config or cfg,timestamp,path,prospective=prospective)
        return eid
    return path,cfg,create


def snapshot(at='2026-10-13T17:15:00+00:00',spot=100,current_iv=.3,bid=1.,ask=1.2,options=None,events=None,settlement=None):
    options=options or [dict(strike=110.,expiration='2026-11-12',bid=bid,ask=ask,impliedVolatility=current_iv,observed_at=at,available_at=at)]
    return dict(ticker='TEST',spot=spot,captured_at=at,available_at=at,underlying_timestamp=at,options=options,events=events or [],
                coverage_verified=True,quote_timing_verified=True,settlement=settlement)


def advance(path,eid,snap,cycle=None):
    db=ledger.connect(path);ledger.migrate(db)
    chain=db.execute('SELECT id FROM cc_virtual_chains WHERE episode_id=? AND simulation_kind="PROSPECTIVE"',(eid,)).fetchone()[0]
    with db:sid=book.store_snapshot(db,snap)
    result=book.advance(db,chain,sid,snap['available_at'],cycle)
    current=book.state(db,chain);db.close()
    return result,current,chain


def test_virtual_entry_idempotent_isolated(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path)
    first=book.start_from_decision(db,eid);again=book.start_from_decision(db,eid)
    assert first==again and first.startswith('virtual-cc-')
    assert db.execute('SELECT count(*) FROM cc_virtual_chains').fetchone()[0]==1
    current=book.state(db,first)
    assert current['leg_entry_premium']==pytest.approx(1.83)
    assert current['option_cash_total']==pytest.approx(183.) and current['fees_total']==.65
    assert 'executed_actions' not in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.close()
    create(challenger='NO_CALL')
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_virtual_chains').fetchone()[0]==1;db.close()


def test_retroactive_creation_not_prospective(episode):
    path,cfg,create=episode;eid=create(prospective=False)
    db=ledger.connect(path);assert book.start_from_decision(db,eid) is None
    with db:chain=book.start_from_decision(db,eid,arm='champion',replay=True)
    assert chain is not None
    assert json.loads(db.execute('SELECT origin_json FROM cc_virtual_chains').fetchone()[0])['prospective'] is False
    db.close()


def test_hold_and_eighty_percent_btc(episode):
    path,cfg,create=episode;eid=create()
    result,current,_=advance(path,eid,snapshot())
    assert result['action']=='HOLD_CALL' and current['status']=='OPEN'
    result,current,chain=advance(path,eid,snapshot(at='2026-10-13T17:45:00+00:00',bid=.2,ask=.25))
    assert result['action']=='BUY_TO_CLOSE' and current['status']=='CLOSED_BTC'
    db=ledger.connect(path);out=outcomes.latest(db,eid,'challenger');db.close()
    assert out['outcome_source']=='PROSPECTIVE_VIRTUAL' and not out['broker_reconciled']
    assert out['cc_incremental_alpha']==pytest.approx((183.-25.-1.30-5.)/100)
    assert out['realized_execution_cost']==pytest.approx((7.+2.5+1.3)/100)
    assert out['chain_identifier']==chain


@pytest.mark.parametrize('action,spot,iv,events,target',[
 ('ROLL_UP',100.,.75,[],dict(strike=115.,expiration='2026-11-12',bid=3.,ask=3.2,impliedVolatility=.55)),
 ('ROLL_OUT',100.,.3,[dict(type='earnings',severity='avoid',label='earnings',date='2026-11-01',known_at='2026-10-13T17:10:00+00:00')],dict(strike=110.,expiration='2026-12-10',bid=3.,ask=3.2,impliedVolatility=.3)),
 ('ROLL_UP_AND_OUT',111.,.3,[],dict(strike=120.,expiration='2026-12-10',bid=3.,ask=3.2,impliedVolatility=.25))])
def test_shared_policy_roll_invariants(episode,action,spot,iv,events,target):
    from covered_call_rec import evaluate_cc_management_state
    path,cfg,create=episode;eid=create();at='2026-10-13T17:15:00+00:00'
    snap=snapshot(spot=spot,current_iv=iv,bid=3.5,ask=4.,events=events)
    snap['options'].append(dict(target,observed_at=at,available_at=at))
    db=ledger.connect(path);origin=json.loads(db.execute('SELECT origin_json FROM cc_virtual_chains').fetchone()[0]);current=book.state(db,db.execute('SELECT id FROM cc_virtual_chains').fetchone()[0])
    context,_=book.context_for(origin,current,book.enforce_asof(snap,at),at)
    assert evaluate_cc_management_state(context)[0]==action;db.close()
    result,current,chain=advance(path,eid,snap)
    assert result['action']==action and current['roll_hops']==1
    if action!='ROLL_OUT':assert current['strike']>110
    if action!='ROLL_UP':assert current['expiration']>'2026-11-12'
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_virtual_fills WHERE chain_id=?',(chain,)).fetchone()[0]==3;db.close()


@pytest.mark.parametrize('price,status,alpha',[(105.,'EXPIRED_OTM',1.8235),(115.,'ASSIGNED',-3.1765)])
def test_terminal_economics(episode,price,status,alpha):
    path,cfg,create=episode;eid=create()
    at='2026-11-12T21:15:00+00:00'
    settle=dict(expiration='2026-11-12',price=price,timestamp='2026-11-12T21:00:00+00:00',available_at=at,coverage_verified=True)
    result,current,_=advance(path,eid,snapshot(at=at,spot=price,settlement=settle))
    assert current['status']==status
    db=ledger.connect(path);out=outcomes.latest(db,eid,'challenger');db.close()
    assert out['cc_incremental_alpha']==pytest.approx(alpha)
    assert out['total_option_pnl']==pytest.approx(182.35)
    assert out['units']=='USD_PER_SHARE' and out['complete']


def test_unavailable_quote_no_action_and_retry_idempotency(episode):
    path,cfg,create=episode;eid=create()
    bad=snapshot();bad['options']=[]
    result,current,chain=advance(path,eid,bad)
    assert result['unavailable'] and current['status']=='OPEN'
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_virtual_actions').fetchone()[0]==1;db.close()
    good=snapshot(at='2026-10-13T17:16:00+00:00')
    result,current,_=advance(path,eid,good,cycle='cycle1')
    again,_,_=advance(path,eid,snapshot(at='2026-10-13T17:17:00+00:00'),cycle='cycle1')
    assert again['duplicate']
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_virtual_actions').fetchone()[0]==2;db.close()


def test_no_lookahead_future_bars_events_options(episode):
    path,cfg,create=episode;eid=create();at='2026-10-13T17:15:00+00:00'
    now=snapshot(at=at)
    future=dict(strike=115.,expiration='2026-11-12',bid=100,ask=101,impliedVolatility=.9,observed_at='2026-10-14T17:00:00+00:00',available_at='2026-10-14T17:00:00+00:00',actual_action='ROLL_UP')
    now['options'].append(future)
    now['events'].append(dict(type='earnings',severity='avoid',date='2026-11-01',known_at='2026-10-14T00:00:00+00:00'))
    now['actual_action']='BUY_TO_CLOSE'
    clean=book.enforce_asof(now,at)
    assert len(clean['options'])==1 and clean['events']==[] and 'actual_action' not in clean
    result,_,_=advance(path,eid,now);assert result['action']=='HOLD_CALL'
    with pytest.raises(book.DataUnavailable):book.enforce_asof(snapshot(at='2026-10-14T00:00:00+00:00'),at)


def typed(episode,source='PROSPECTIVE_VIRTUAL',**kw):
    row=outcomes.base(episode,source,START,'2026-11-12T21:15:00+00:00','lineage',{'test':1})
    row.update(chain_identifier='virtual-chain' if source=='PROSPECTIVE_VIRTUAL' else 'actual-chain',simulator_version=book.SIMULATOR_VERSION,
        config_hash='cfg',execution_source='VIRTUAL_MODEL' if source=='PROSPECTIVE_VIRTUAL' else 'ACTUAL',execution_ids=[1] if source=='ACTUAL_EXECUTION' else [],
        execution_reconciled=source=='ACTUAL_EXECUTION',prospective=source=='PROSPECTIVE_VIRTUAL',complete=True,censored=False,
        market_data_coverage_verified=True,economic_share_basis='COVERED_SHARES',covered_shares=100.,origin_holding_shares=300.,chain_censored=False,data_quality_unresolved=False,cc_incremental_alpha=1.,realized_management_cost=.1,realized_execution_cost=.02,
        assignment_policy_violation=False,rolled=False,roll_hops=0)
    row.update(kw);return row


@pytest.mark.parametrize('source,changes',[
 ('PROSPECTIVE_VIRTUAL',{'broker_reconciled':True}),('ACTUAL_EXECUTION',{'execution_ids':[]}),
 ('MARKET_PATH_ONLY',{'realized_execution_cost':1}),('ESTIMATED_COUNTERFACTUAL',{'prospective':True}),
 ('UNKNOWN',{})])
def test_invalid_provenance(source,changes):
    with pytest.raises(ValueError):outcomes.validate(typed('test',source,**changes))


def test_provenance_revision_cannot_upgrade(episode):
    path,cfg,create=episode;eid=create();db=ledger.connect(path)
    with db:outcomes.persist(db,eid,'candidate','challenger',typed(eid))
    with pytest.raises(ValueError):outcomes.persist(db,eid,'candidate','challenger',typed(eid,'ACTUAL_EXECUTION'))
    with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM cc_outcomes')
    db.close()


def seed_pair(path,cfg,eid,champion=True,challenger=True,**changes):
    db=ledger.connect(path);meta=outcomes.contract(db,eid)
    h=ledger.config_digest(cfg)
    for arm,source,write in [('champion','ACTUAL_EXECUTION',champion),('challenger','PROSPECTIVE_VIRTUAL',challenger)]:
        if not write:continue
        record=typed(eid,source,market_snapshot_lineage=meta['market_snapshot_lineage'],config_hash=h,**changes)
        if source=='ACTUAL_EXECUTION':
            actual_chain=json.loads(db.execute('SELECT champion_json FROM cc_decisions WHERE id=?',(eid,)).fetchone()[0])['trade_chain_id']
            db.execute('CREATE TABLE IF NOT EXISTS recommendations(id INTEGER PRIMARY KEY,trade_chain_id TEXT,action TEXT,action_payload_json TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS executed_actions(id INTEGER PRIMARY KEY,recommendation_id INTEGER)')
            rec_id=db.execute('INSERT INTO recommendations(trade_chain_id,action,action_payload_json) VALUES(?,?,?)',(actual_chain,'SELL_CC',json.dumps({'cc_episode_id':eid}))).lastrowid
            execution_id=db.execute('INSERT INTO executed_actions(recommendation_id) VALUES(?)',(rec_id,)).lastrowid
            record.update(chain_identifier=actual_chain,execution_ids=[execution_id])

        with db:outcomes.persist(db,eid,'TEST:20261112:110',arm,record)
    db.close()


def test_paired_actual_virtual_eligibility_no_auto_promotion(episode,monkeypatch):
    path,cfg,create=episode;eid=create();seed_pair(path,cfg,eid)
    monkeypatch.setattr(validation,'certification',lambda *a,**kw:{'id':'cert'})
    report=evidence.promotion_report(cfg,path,as_of=parse_timestamp('2026-12-01T00:00:00Z'))
    assert report['n']==1 and report['source_composition']=={'champion:ACTUAL_EXECUTION':1,'challenger:PROSPECTIVE_VIRTUAL':1}
    assert not report['eligible'] and 'MINIMUM_N' in report['failures']
    assert ledger.active_scorer(cfg,path)=='v2'


@pytest.mark.parametrize('champ,chall',[('NO_CALL','SELL_CC'),('SELL_CC','NO_CALL'),('NO_CALL','NO_CALL')])
def test_no_call_pairs(episode,monkeypatch,champ,chall):
    path,cfg,create=episode;eid=create(champion=champ,challenger=chall)
    seed_pair(path,cfg,eid,champion=champ=='SELL_CC',challenger=chall=='SELL_CC')
    monkeypatch.setattr(validation,'certification',lambda *a,**kw:{'id':'cert'})
    report=evidence.promotion_report(cfg,path,as_of=parse_timestamp('2026-12-01T00:00:00Z'))
    assert report['n']==1
    assert report['divergent_n']==(0 if champ==chall else 1)
    expected=1 if champ=='NO_CALL' and chall=='SELL_CC' else -1 if chall=='NO_CALL' and champ=='SELL_CC' else 0
    assert report['alpha_improvement']==pytest.approx(expected/3)


def test_uncertified_duplicate_and_wrong_source_exclusions(episode,monkeypatch):
    path,cfg,create=episode;eid=create();seed_pair(path,cfg,eid)
    second=create();seed_pair(path,cfg,second)
    report=evidence.promotion_report(cfg,path,as_of=parse_timestamp('2026-12-01T00:00:00Z'))
    assert report['n']==0
    assert report['exclusions']['SIMULATOR_UNCERTIFIED']==1 and report['exclusions']['DUPLICATE_TICKER_SESSION']==1
    monkeypatch.setattr(validation,'certification',lambda *a,**kw:{'id':'cert'})
    assert evidence.promotion_report(dict(cfg,config_version='new'),path)['exclusions']['CONFIG_MISMATCH']==2


def test_validation_metrics_gates_and_human_override():
    actual=dict(fills=[dict(price=2,bid=1.8,ask=2.2,fees_total=.65)],actions=[dict(action='HOLD',session_index=0),dict(action='ROLL_UP',session_index=1,strike=115,expiration='2026-11-12')],
        incremental_alpha=1,total_option_pnl=100,execution_cost=.02,management_cost=.05)
    virtual=deepcopy(actual);virtual['actions'][0]['action']='NO_ACTION';virtual['actions'][1]['session_index']=2
    case=validation.compare(actual,virtual)
    assert case['action_agreement']==1 and case['intervention_timing_error']==1
    policy=deepcopy(CC_V3_CONFIG['simulator_validation'])
    assert validation.acceptance([case]*20,policy)['eligible']
    case['lookahead_violations']=1;assert 'LOOKAHEAD' in validation.acceptance([case]*20,policy)['failures']
    case['lookahead_violations']=0;case['alpha_absolute_error']=10
    assert 'ECONOMIC_ERROR' in validation.acceptance([case]*20,policy)['failures']
    assert validation.acceptance([],policy)['status']=='INSUFFICIENT_EVIDENCE'
    actual['actions'][1]['source']='HUMAN_OVERRIDE';assert validation.compare(actual,virtual)['human_overrides']


def test_surface_delta_and_total_variance():
    rows=[]
    for dte,iv in [(20,.2),(40,.3),(60,.4)]:
        for i,delta in enumerate((.1,.2,.3,.4,.5,.6)):
            rows.append(candidate(expiration=f'exp-{dte}',dte=dte,strike=100+i,delta=delta,impliedVolatility=iv+.05*(delta-.3)))
    result=surface_v2(rows,100,START)
    middle=result[8]
    expected=((.2**2*(20/365)+.4**2*(60/365))/2/(40/365))**.5
    assert middle['surface_expected_iv']==pytest.approx(expected)
    assert middle['surface_interpolation_quality']=='BRACKETED_TOTAL_VARIANCE'
    assert result[0]['surface_expected_iv'] is None
    flat=[candidate(strike=100+i,delta=d,impliedVolatility=.25) for i,d in enumerate((.1,.2,.3,.4,.5))]
    assert abs(surface_v2(flat,100,START)[2]['candidate_surface_residual'])<1e-10


def test_event_total_variance_missing_date_and_stale():
    rows=[]
    for dte,iv in [(14,.2),(21,.22),(42,.4)]:
        for i,delta in enumerate((.1,.2,.3,.4,.5,.6)):
            rows.append(candidate(expiration=f'exp-{dte}',dte=dte,strike=100+i,delta=delta,impliedVolatility=iv,
                risk_events=[dict(type='earnings',date='2026-11-10')] if dte==42 else []))
    result=surface_v2(rows,100,START)
    item=result[14];inputs=item['event_variance_reference_inputs']
    assert item['event_variance_estimate_v2']>0
    assert inputs['before']['total_variance']==pytest.approx(.22**2*21/365)
    assert inputs['after']['total_variance']==pytest.approx(.4**2*42/365)
    rows[14]['risk_events']=[dict(type='earnings')]
    assert surface_v2(rows,100,START)[14]['event_variance_estimate_v2'] is None
    rows[14]['quote_timestamp']='2026-10-12T00:00:00Z'
    assert surface_v2(rows,100,START)[14]['surface_expected_iv'] is None


def duration_row(days,alpha,**kw):
    return dict(dte=days,adjusted_cc_alpha=alpha,utility_hurdle=.1,eligible=True,v3_rejection_reasons=[],strike=110,expiration=f'exp-{days}',**kw)


def test_duration_accounting_and_long_can_win():
    cfg=deepcopy(CC_V3_CONFIG)
    rows=[duration_row(30,2),duration_row(60,1)]
    duration_adjust(rows,cfg)
    assert rows[1]['flexibility_cost']==.75 and rows[1]['duration_adjusted_alpha']==.25
    assert rows[0]['benchmark_available'] is False and rows[0]['flexibility_cost']==0
    proportional=[duration_row(30,1),duration_row(60,2)]
    duration_adjust(proportional,cfg);assert proportional[1]['flexibility_cost']==0
    dominant=[duration_row(30,1),duration_row(60,5)]
    duration_adjust(dominant,cfg)
    assert dominant[1]['duration_adjusted_utility_margin']/60>dominant[0]['duration_adjusted_utility_margin']/30
    blocked=[duration_row(30,20),duration_row(60,2)];blocked[0]['v3_rejection_reasons']=['EVENT_AVOID']
    duration_adjust(blocked,cfg);assert not blocked[1]['benchmark_available']


def test_exact_release_inventory_contract(tmp_path):
    spec=importlib.util.spec_from_file_location('gate',str(Path(__file__).resolve().parent.parent/'scripts/check_release_baseline.py'))
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    inventory=gate.load_inventory(Path(__file__).resolve().parent.parent/'config/release_baseline_failures.json')
    historical=deepcopy(inventory)
    for item in historical['failures']:item['status']='active';item['permitted_in_release']=True
    historical_results={f['node_id']:dict(signature=f['signature']) for f in historical['failures']}
    assert len(gate.compare(historical_results,historical,date(2026,10,13))['known_debt'])==4
    current={f['node_id']:dict(signature=f['signature']) for f in inventory['failures'] if f.get('status')!='resolved'}
    assert gate.compare(current,inventory,date(2026,10,13))['passed']
    current['newtest']=dict(signature='new');assert not gate.compare(current,inventory,date(2026,10,13))['passed'];current.pop('newtest')
    key=next(iter(current));current[key]['signature']='changed';assert gate.compare(current,inventory,date(2026,10,13))['changed_failures']
    current.pop(key);assert gate.compare(current,inventory,date(2026,10,13))['resolved_stale_inventory']
    assert gate.compare(current,inventory,date(2027,1,1))['expired_waivers']
    path=tmp_path/'bad.json';inventory['failures'].append(inventory['failures'][0]);path.write_text(json.dumps(inventory))
    with pytest.raises(ValueError):gate.load_inventory(path)


def test_atomic_virtual_cycle_failure_can_retry(episode,monkeypatch):
    path,cfg,create=episode;eid=create();snap=snapshot(bid=.2,ask=.25)
    original=book.write_state
    monkeypatch.setattr(book,'write_state',lambda *a:(_ for _ in ()).throw(RuntimeError('injected mid-cycle failure')))
    with pytest.raises(RuntimeError):advance(path,eid,snap)
    db=ledger.connect(path)
    assert db.execute('SELECT count(*) FROM cc_virtual_actions').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM cc_virtual_fills').fetchone()[0]==1
    db.close()
    monkeypatch.setattr(book,'write_state',original)
    result,current,_=advance(path,eid,snap)
    assert current['status']=='CLOSED_BTC'
    db=ledger.connect(path);assert db.execute('SELECT count(*) FROM cc_virtual_fills').fetchone()[0]==2;db.close()


def test_actual_records_untouched_by_virtual_lifecycle(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path)
    db.execute('CREATE TABLE executed_actions(id INTEGER PRIMARY KEY, notes TEXT)')
    db.execute('CREATE TABLE cc_positions(id INTEGER PRIMARY KEY,status TEXT)')
    db.execute("INSERT INTO executed_actions VALUES(1,'sentinel actual fill')")
    db.execute("INSERT INTO cc_positions VALUES(1,'open')");db.commit();db.close()
    advance(path,eid,snapshot(bid=.2,ask=.25))
    db=ledger.connect(path)
    assert tuple(db.execute('SELECT * FROM executed_actions').fetchone())==(1,'sentinel actual fill')
    assert tuple(db.execute('SELECT * FROM cc_positions').fetchone())==(1,'open');db.close()


def test_shared_policy_assignment_permission_waits_for_expiry(episode):
    path,cfg,create=episode;eid=create()
    result,current,_=advance(path,eid,snapshot(spot=130.,current_iv=.25,bid=20.1,ask=20.2))
    assert result['action']=='ALLOW_ASSIGNMENT' and current['status']=='AWAIT_ASSIGNMENT'
    db=ledger.connect(path);assert outcomes.latest(db,eid,'challenger') is None;db.close()


def test_multi_hop_cash_reconciles_once(episode):
    path,cfg,create=episode;eid=create();at='2026-10-13T17:15:00+00:00'
    snap=snapshot(spot=111.,bid=3.5,ask=4.)
    snap['options'].append(dict(strike=120.,expiration='2026-12-10',bid=3.,ask=3.2,impliedVolatility=.25,observed_at=at,available_at=at))
    _,current,chain=advance(path,eid,snap)
    at2='2026-10-13T17:45:00+00:00'
    current_quote=dict(strike=120.,expiration='2026-12-10',bid=4.,ask=4.2,impliedVolatility=.3,observed_at=at2,available_at=at2)
    next_quote=dict(strike=130.,expiration='2027-01-08',bid=5.,ask=5.2,impliedVolatility=.25,observed_at=at2,available_at=at2)
    result,current,_=advance(path,eid,snapshot(at=at2,spot=121.,options=[current_quote,next_quote]))
    assert result['action']=='ROLL_UP_AND_OUT' and current['roll_hops']==2
    at3='2026-10-13T18:15:00+00:00'
    close_quote=dict(next_quote,bid=.2,ask=.25,observed_at=at3,available_at=at3)
    result,current,_=advance(path,eid,snapshot(at=at3,spot=100.,options=[close_quote]))
    assert current['status']=='CLOSED_BTC'
    db=ledger.connect(path)
    fills=[json.loads(r[0]) for r in db.execute('SELECT fill_json FROM cc_virtual_fills WHERE chain_id=?',(chain,))]
    outcome=outcomes.latest(db,eid,'challenger');db.close()
    cash=sum(f['cash_flow_total'] for f in fills);fees=sum(f['fees_total'] for f in fills)
    assert len(fills)==6
    assert current['option_cash_total']==pytest.approx(cash)
    assert outcome['cc_incremental_alpha']==pytest.approx((cash-fees-15.)/100)


def test_missed_intervals_remain_censored(episode):
    path,cfg,create=episode;eid=create()
    result,current,_=advance(path,eid,snapshot(at='2026-10-14T18:00:00+00:00',bid=.2,ask=.25))
    db=ledger.connect(path);out=outcomes.latest(db,eid,'challenger')
    assert out['censored'] and db.execute('SELECT count(*) FROM cc_virtual_intervals').fetchone()[0]>0;db.close()


def test_replay_deterministic_actual_actions_not_policy_inputs(episode):
    path,cfg,create=episode;eid=create();db=ledger.connect(path)
    origin=json.loads(db.execute('SELECT origin_json FROM cc_virtual_chains').fetchone()[0])
    initial=book.state(db,db.execute('SELECT id FROM cc_virtual_chains').fetchone()[0]);db.close()
    data=[dict(evaluation_timestamp='2026-10-13T17:15:00+00:00',snapshot=snapshot(bid=.2,ask=.25),actual_action='ROLL_OUT')]
    first=validation.replay(origin,initial,data)
    data[0]['actual_action']='ASSIGNED'
    second=validation.replay(origin,initial,data)
    assert first==second and first['actions'][0]['action']=='BUY_TO_CLOSE'
    assert first['total_option_pnl']==pytest.approx(183.-25.-1.3)
    assert first['outcome_source']=='ESTIMATED_COUNTERFACTUAL' and first['prospective'] is False


def test_validation_zero_spread_and_roll_disagreement():
    actual=dict(fills=[dict(price=2,bid=2,ask=2,fees_total=.65)],actions=[dict(action='ROLL_OUT',session_index=0)],incremental_alpha=1,total_option_pnl=100,execution_cost=0,management_cost=0)
    simulated=deepcopy(actual);simulated['actions'][0]['action']='ROLL_UP'
    result=validation.compare(actual,simulated)
    assert result['entry_fill_spread_error']==0 and result['roll_type_agreement']==0
    simulated['fills'][0]['price']=3
    assert validation.compare(actual,simulated)['entry_fill_spread_error'] is None


def test_certification_immutable_and_version_invalidation(episode):
    path,cfg,create=episode;create();db=ledger.connect(path)
    case=dict(entry_fill_spread_error=.1,action_agreement=1,intervention_timing_error=0,roll_type_agreement=1,
        alpha_absolute_error=.01,actual_alpha_absolute=1,lookahead_violations=0,state_contamination=0)
    result=validation.acceptance([case]*20,cfg['simulator_validation'])
    result.update(cases=[case]*20,out_of_sample=True,simulator_version=book.SIMULATOR_VERSION,config_hash=ledger.config_digest(cfg),
        management_contract=book.management_contract(),git_sha=validation.current_git_sha(),cohort_ids=[str(i) for i in range(20)])
    with db:db.execute('INSERT INTO cc_simulator_validation_runs VALUES(?,?,?,?,?,?)',('valid-run',START,book.SIMULATOR_VERSION,ledger.config_digest(cfg),validation.current_git_sha(),json.dumps(result)))
    db.close()
    certificate=validation.certify('valid-run',cfg,path)
    assert validation.certification(cfg,path)['id']==certificate['id']
    assert validation.certification(dict(cfg,config_version='new'),path) is None
    db=ledger.connect(path)
    with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM cc_simulator_certifications')
    db.close()


def test_simulator_contract_hash_properties(episode):
    """0711: simulator_contract_hash decouples cert validity from repo git SHA."""
    _,cfg,_=episode
    h1=validation.simulator_contract_hash(cfg)
    # Same config → same hash (deterministic).
    assert validation.simulator_contract_hash(cfg)==h1
    # Changing a non-simulator config key must not change the hash.
    cfg_copy=dict(cfg,config_version='unrelated_dashboard_change')
    assert validation.simulator_contract_hash(cfg_copy)==h1
    # Changing a simulator-relevant config value must change the hash.
    import copy
    cfg_changed=copy.deepcopy(cfg)
    cfg_changed.setdefault('cc_v3',{})['management_cost_per_contract']=99999
    assert validation.simulator_contract_hash(cfg_changed)!=h1


def test_cert_valid_across_git_sha(episode,monkeypatch):
    """0711: a cert is valid when contract hash matches even if git SHA differs."""
    path,cfg,create=episode;create();db=ledger.connect(path)
    case=dict(entry_fill_spread_error=.1,action_agreement=1,intervention_timing_error=0,roll_type_agreement=1,
        alpha_absolute_error=.01,actual_alpha_absolute=1,lookahead_violations=0,state_contamination=0)
    result=validation.acceptance([case]*20,cfg['simulator_validation'])
    result.update(cases=[case]*20,out_of_sample=True,simulator_version=book.SIMULATOR_VERSION,config_hash=ledger.config_digest(cfg),
        management_contract=book.management_contract(),git_sha='old-sha-before-unrelated-commit',cohort_ids=[str(i) for i in range(20)])
    with db:db.execute('INSERT INTO cc_simulator_validation_runs VALUES(?,?,?,?,?,?)',('valid-run2',START,book.SIMULATOR_VERSION,ledger.config_digest(cfg),'old-sha-before-unrelated-commit',json.dumps(result)))
    db.close()
    certificate=validation.certify('valid-run2',cfg,path)
    # Simulate an unrelated commit by monkeypatching git SHA.
    monkeypatch.setattr(validation,'current_git_sha',lambda:'new-unrelated-sha')
    found=validation.certification(cfg,path)
    assert found is not None and found['id']==certificate['id']
    assert found['certified_at_git_sha']=='old-sha-before-unrelated-commit'
    assert found['current_git_sha']=='new-unrelated-sha'


def test_cert_invalidated_by_contract_change(episode,monkeypatch):
    """0711: cert becomes invalid when simulator_contract_hash changes."""
    path,cfg,create=episode;create();db=ledger.connect(path)
    case=dict(entry_fill_spread_error=.1,action_agreement=1,intervention_timing_error=0,roll_type_agreement=1,
        alpha_absolute_error=.01,actual_alpha_absolute=1,lookahead_violations=0,state_contamination=0)
    result=validation.acceptance([case]*20,cfg['simulator_validation'])
    result.update(cases=[case]*20,out_of_sample=True,simulator_version=book.SIMULATOR_VERSION,config_hash=ledger.config_digest(cfg),
        management_contract=book.management_contract(),git_sha=validation.current_git_sha(),cohort_ids=[str(i) for i in range(20)])
    with db:db.execute('INSERT INTO cc_simulator_validation_runs VALUES(?,?,?,?,?,?)',('valid-run3',START,book.SIMULATOR_VERSION,ledger.config_digest(cfg),validation.current_git_sha(),json.dumps(result)))
    db.close()
    certificate=validation.certify('valid-run3',cfg,path)
    assert certificate['simulator_contract_hash']==validation.simulator_contract_hash(cfg)
    # Simulate a simulator-relevant code change by returning a different contract hash.
    monkeypatch.setattr(validation,'simulator_contract_hash',lambda *a:'changed-hash')
    assert validation.certification(cfg,path) is None


def test_missing_contract_metadata_fails_closed(episode):
    """0711: a cert without simulator_contract_hash with wrong git SHA is rejected."""
    path,cfg,create=episode;create();db=ledger.connect(path)
    # Insert a legacy cert with an old git SHA and no simulator_contract_hash.
    legacy_cert=dict(validation_run_id='legacy-run',simulator_version=book.SIMULATOR_VERSION,
        config_hash=ledger.config_digest(cfg),management_contract=book.management_contract(),
        validation_policy_version=cfg['simulator_validation']['version'],
        cohort_ids=[],metrics={},git_sha='old-git-sha-no-longer-current')
    from covered_call_outcomes import digest as od
    cert_id=od(legacy_cert)
    with db:
        db.execute('INSERT INTO cc_simulator_validation_runs VALUES(?,?,?,?,?,?)',
            ('legacy-run',START,book.SIMULATOR_VERSION,ledger.config_digest(cfg),'old-git-sha-no-longer-current','{}'))
        db.execute('INSERT INTO cc_simulator_certifications VALUES(?,?,?,?)',
            (cert_id,'legacy-run',START,json.dumps(legacy_cert,sort_keys=True)))
    db.close()
    # No simulator_contract_hash → falls back to git_sha; old SHA ≠ current → rejected.
    assert validation.certification(cfg,path) is None


def test_actual_virtual_metrics_separated_in_report(episode):
    path,cfg,create=episode;eid=create();seed_pair(path,cfg,eid)
    report=ledger.report(path)
    assert report['outcome_source_counts']=={'ACTUAL_EXECUTION':1,'PROSPECTIVE_VIRTUAL':1}
    assert all(c['outcome_source']=='ACTUAL_EXECUTION' for c in report['cohorts'])
    assert all(c['incremental_alpha']==1 for c in report['cohorts'])
    assert report['virtual_book']['open_chains']==1


def test_explicit_promotion_snapshot_and_rollback(episode,monkeypatch):
    path,cfg,create=episode
    cfg['mode']='evidence_gated'
    cfg['promotion'].update(minimum_n=1,minimum_divergent_n=1,minimum_days=0,max_management_cost_increase=.2,max_execution_cost_increase=.2)
    eid=create(champion='NO_CALL',config=cfg);seed_pair(path,cfg,eid,champion=False)
    ledger.append_label(eid,'TEST:20261112:110',dict(censored=False,path_complete=True,path_coverage_verified=True,strike_touched=False),{'test':'verified path'},path)
    monkeypatch.setattr(validation,'certification',lambda *a,**kw:{'id':'cert'})
    monkeypatch.setattr(evidence,'now_utc',lambda:parse_timestamp('2026-12-01T00:00:00Z'))
    report=evidence.promotion_report(cfg,path)
    assert report['eligible'] and ledger.active_scorer(cfg,path)=='v2'
    snapshot=ledger.transition('v3',cfg,path)
    assert snapshot['cohort_ids']==[eid] and snapshot['simulator_certification_id']=='cert'
    assert ledger.active_scorer(cfg,path)=='v3'
    assert ledger.active_scorer(dict(cfg,config_version='changed'),path)=='v2'
    ledger.transition('v2',cfg,path);assert ledger.active_scorer(cfg,path)=='v2'
    db=ledger.connect(path)
    with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM cc_promotions')
    assert db.execute('SELECT count(*) FROM cc_promotions').fetchone()[0]==2;db.close()


@pytest.mark.parametrize('field,value,failure',[
 ('minimum_n',2,'MINIMUM_N'),('minimum_divergent_n',2,'DIVERGENT_N'),('minimum_days',1,'PROSPECTIVE_DURATION'),
 ('minimum_alpha_improvement',1.,'ALPHA_IMPROVEMENT'),('max_management_cost_increase',0.,'MANAGEMENT_COST_REGRESSION'),
 ('max_execution_cost_increase',0.,'EXECUTION_COST_REGRESSION'),('max_brier',.001,'CALIBRATION')])
def test_each_promotion_gate_blocks(episode,monkeypatch,field,value,failure):
    path,cfg,create=episode
    cfg['promotion'].update(minimum_n=1,minimum_divergent_n=1,minimum_days=0,max_management_cost_increase=.2,max_execution_cost_increase=.2)
    cfg['promotion'][field]=value
    eid=create(champion='NO_CALL',config=cfg);seed_pair(path,cfg,eid,champion=False)
    ledger.append_label(eid,'TEST:20261112:110',dict(censored=False,path_complete=True,path_coverage_verified=True,strike_touched=False),{'test':'verified path'},path)
    monkeypatch.setattr(validation,'certification',lambda *a,**kw:{'id':'cert'})
    report=evidence.promotion_report(cfg,path,as_of=parse_timestamp('2026-12-01T00:00:00Z'))
    assert not report['eligible'] and failure in report['failures']


@pytest.mark.parametrize('source',['MARKET_PATH_ONLY','ESTIMATED_COUNTERFACTUAL'])
def test_path_and_estimated_challenger_never_qualify(episode,monkeypatch,source):
    path,cfg,create=episode;eid=create(champion='NO_CALL');db=ledger.connect(path)
    meta=outcomes.contract(db,eid)
    outcome=outcomes.base(eid,source,START,'2026-11-12T21:15:00Z',meta['market_snapshot_lineage'],{'path':1})
    outcome.update(complete=True,censored=False,market_data_coverage_verified=True)
    with db:outcomes.persist(db,eid,'TEST:20261112:110','challenger',outcome)
    db.close();monkeypatch.setattr(validation,'certification',lambda *a,**kw:{'id':'cert'})
    report=evidence.promotion_report(cfg,path,as_of=parse_timestamp('2026-12-01T00:00:00Z'))
    assert report['n']==0 and report['exclusions']['WRONG_CHALLENGER_SOURCE']==1


def test_actual_provenance_requires_database_receipt(episode):
    path,cfg,create=episode;eid=create();db=ledger.connect(path)
    with pytest.raises(ValueError):outcomes.persist(db,eid,'TEST:20261112:110','champion',typed(eid,'ACTUAL_EXECUTION'))
    db.close()


def test_zero_bid_buyback_is_valid(episode):
    path,cfg,create=episode;eid=create()
    result,current,_=advance(path,eid,snapshot(bid=0.,ask=.10))
    assert result['action']=='BUY_TO_CLOSE' and current['status']=='CLOSED_BTC'


def test_scheduler_duplicate_runs_and_restart(episode):
    from scripts.cc_virtual_job import run
    path,cfg,create=episode;eid=create();at=parse_timestamp('2026-10-13T17:15:00Z')
    first=run(path,capture=lambda ticker,current:snapshot(),clock=lambda:at)
    second=run(path,capture=lambda *a:pytest.fail('duplicate must not refetch'),clock=lambda:at)
    assert first['open_chains']==1 and second['results'][0]['duplicate']
    db=ledger.connect(path);ledger.migrate(db)
    assert book.metrics(db)['open_chains']==1;db.close()


def test_version_censored_closes_chain(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid)
    current=book.state(db,chain_id)
    assert current['status']=='OPEN'
    evaluation='2026-10-13T18:00:00+00:00'
    result=book.censor_version_mismatch(db,chain_id,'different-hash-abc',evaluation)
    assert result['action']=='VERSION_CENSORED'
    after=book.state(db,chain_id)
    assert after['status']=='VERSION_CENSORED'
    db.close()


def test_version_censored_terminal_outcome(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid)
    evaluation='2026-10-13T18:00:00+00:00'
    book.censor_version_mismatch(db,chain_id,'hash-b',evaluation)
    from covered_call_outcomes import latest
    outcome=latest(db,eid,'challenger')
    assert outcome is not None
    assert outcome['version_censored']==True
    assert outcome['promotion_eligible']==False
    assert outcome['censor_source']=='SIMULATOR_CONTRACT_CHANGE'
    assert outcome['complete']==True
    db.close()


def test_version_censored_idempotent(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid)
    evaluation='2026-10-13T18:00:00+00:00'
    book.censor_version_mismatch(db,chain_id,'hash-b',evaluation)
    result2=book.censor_version_mismatch(db,chain_id,'hash-b',evaluation)
    assert result2['terminal']==True
    actions=db.execute('SELECT count(*) FROM cc_virtual_actions WHERE chain_id=? AND action="VERSION_CENSORED"',(chain_id,)).fetchone()[0]
    assert actions==1
    db.close()


def test_version_censored_blocks_further_advance(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid)
    evaluation='2026-10-13T18:00:00+00:00'
    book.censor_version_mismatch(db,chain_id,'hash-b',evaluation)
    snap=snapshot(at='2026-10-13T19:00:00+00:00')
    with db:sid=book.store_snapshot(db,snap)
    result=book.advance(db,chain_id,sid,snap['available_at'])
    assert result.get('terminal')==True
    db.close()


def test_scheduler_routes_contract_mismatch_to_censor(episode,monkeypatch):
    import scripts.cc_virtual_job as vjob
    from scripts.cc_virtual_job import run
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid);db.close()
    monkeypatch.setattr(vjob,'simulator_contract_hash',lambda config:'new-contract-xyz')
    at=parse_timestamp('2026-10-13T17:15:00Z')
    result=run(path,capture=lambda ticker,current:snapshot(),clock=lambda:at)
    assert result['results'][0]['action']=='VERSION_CENSORED'
    assert result['version_censored_chains']==1
    assert result['open_chains']==0


def test_scheduler_no_censor_when_contract_matches(episode,monkeypatch):
    from scripts.cc_virtual_job import run
    path,cfg,create=episode;eid=create()
    original_hash=book.simulator_contract_hash(cfg)
    at=parse_timestamp('2026-10-13T17:15:00Z')
    result=run(path,capture=lambda ticker,current:snapshot(),clock=lambda:at)
    assert 'action' not in result['results'][0] or result['results'][0].get('action')!='VERSION_CENSORED'
    assert result['version_censored_chains']==0
    assert result['open_chains']==1


def test_metrics_version_censored_count(episode):
    path,cfg,create=episode;eid=create()
    db=ledger.connect(path);ledger.migrate(db)
    chain_id=book.start_from_decision(db,eid)
    m_before=book.metrics(db)
    assert m_before['version_censored_chains']==0
    book.censor_version_mismatch(db,chain_id,'hash-new','2026-10-13T18:00:00+00:00')
    m_after=book.metrics(db)
    assert m_after['version_censored_chains']==1
    assert m_after['open_chains']==0
    assert m_after['virtual_economics']['version_censored_n']==1
    db.close()
