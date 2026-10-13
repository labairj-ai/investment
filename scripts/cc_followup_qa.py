"""Migration isolation and current-chain observer QA on an operator-supplied DB copy."""
from __future__ import annotations
import argparse
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import agent_db
import covered_call_rec as cc
import covered_call_ledger as ledger
import covered_call_virtual as book
from covered_call_evidence import migrate_legacy
from covered_call_validation import run_validation
from covered_call_v3 import prepare
from strategy_config import CC_V3_CONFIG
from time_utils import now_utc

TABLES=('cc_positions','executed_actions','recommendations','holding_day','cost_lots')


def fingerprint(db):
    from covered_call_outcomes import digest
    result={}
    for table in TABLES:
        if db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone():
            rows=[list(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            result[table]=dict(n=len(rows),hash=digest(rows))
    return result


def synthetic_lifecycle(path):
    start=now_utc();timestamp=start.isoformat();expiry=(start+timedelta(days=30)).date().isoformat()
    candidate=dict(strike=110.,expiration=expiry,dte=30,spot=100.,bid=1.8,ask=2.,impliedVolatility=.3,
        quote_timestamp=timestamp,eligible=True,eligible_contracts_max=1,recommended_contracts=1,
        tax_data_available=True,assignment_lot_schedule=[],expected_fill_fraction=.15,mu_center=.08,hv_forecast=.25,
        delta=.15,score=70,opp_score=70,rejection_reasons=[],otm_pct=.1)
    choice=dict(action='SELL_CC',strike=110.,expiration=expiry,contracts=1,overwrite_fraction=1.)
    eid=ledger.record_episode('SYNTHETIC_QA',None,[candidate],{'action':'NO_CALL','contracts':0},choice,
        {'strategy':'INCOME','assignment_policy':{'allowed':True}},CC_V3_CONFIG,timestamp,path,prospective=False,qa_only=True)
    db=ledger.connect(path)
    with db:chain=book.start_from_decision(db,eid,arm='challenger',replay=True)
    at=(start+timedelta(minutes=15)).isoformat()
    snap=dict(ticker='SYNTHETIC_QA',spot=100.,underlying_timestamp=at,captured_at=at,available_at=at,
        options=[dict(strike=110.,expiration=expiry,bid=.2,ask=.25,impliedVolatility=.3,observed_at=at,available_at=at)],
        events=[],coverage_verified=True,quote_timing_verified=True,synthetic_qa=True)
    with db:snapshot_id=book.store_snapshot(db,snap)
    result=book.advance(db,chain,snapshot_id,at,'SYNTHETIC_QA')
    current=book.state(db,chain);db.close()
    expected=183.-25.-1.30-5.
    assert current['status']=='CLOSED_BTC'
    assert abs(current['option_cash_total']-current['fees_total']-current['management_cost_total']-expected)<1e-9
    return dict(episode_id=eid,chain_id=chain,result=result,source='ESTIMATED_COUNTERFACTUAL',cash_reconciled=True)


def run(path,tickers=None,baseline='e0bbb99'):
    agent_db.DB_PATH=Path(path)
    db=ledger.connect(path);before=fingerprint(db);ledger.migrate(db)
    with db:migration=migrate_legacy(db)
    after=fingerprint(db);assert before==after;db.close()
    result=dict(migration=migration,actual_tables_unchanged=True,actual_fingerprints=before,
                promotion_before_market_qa=ledger.promotion_evidence(CC_V3_CONFIG,path),
                synthetic_lifecycle=synthetic_lifecycle(path))
    validation=run_validation(CC_V3_CONFIG,path);result['validation']=validation
    current=[];entered=None
    if tickers:
        raw=subprocess.run(['git','show',baseline+':covered_call_v3.py'],capture_output=True,text=True,check=True).stdout
        with tempfile.TemporaryDirectory(prefix='cc-v3-previous-') as temp:
            old_path=Path(temp)/'covered_call_v3_previous.py';old_path.write_text(raw)
            spec=importlib.util.spec_from_file_location('cc_previous',old_path);previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
            for ticker in tickers:
                try:
                    from portfolio_positions import load_positions
                    holdings=load_positions(Path(__file__).resolve().parent.parent/'holdings.csv')
                    holding=holdings.get(ticker.upper()) or holdings.get(ticker.replace('-','.').upper())
                    if holding is None:raise ValueError('holding data unavailable')
                    row=(holding.shares,holding.avg_cost)
                    analysis=cc.analyze(ticker,float(row[1]),float(row[0]))
                    if analysis is None:raise ValueError('current option data unavailable')
                    from agents import covered_call_agent
                    covered_call_agent._DB=Path(path)
                    policy=covered_call_agent._get_cc_policy(ticker)
                    thesis=agent_db.get_active_thesis(ticker) or {}
                    policy=dict(policy,conviction=thesis.get('conviction'))
                    pillars=[p for p in (thesis.get('pillars') or []) if p.get('score') is not None]
                    weight=sum(p.get('importance',0) for p in pillars)
                    policy['thesis_health']=sum(p.get('importance',0)*p['score'] for p in pillars)/weight if weight else None
                    old_rows,old_decision=previous.prepare(ticker,analysis,policy,float(row[0]),CC_V3_CONFIG)
                    rows,decision=prepare(ticker,analysis,policy,float(row[0]),CC_V3_CONFIG)
                    summary=dict(ticker=ticker,snapshot_timestamp=analysis['snapshot_timestamp'],candidate_n=len(rows),
                        previous_challenger=old_decision,current_challenger=decision,winner_changed=old_decision!=decision,
                        interpolated_n=sum(r.get('surface_expected_iv') is not None for r in rows),
                        flexibility_penalty_n=sum((r.get('flexibility_cost') or 0)>0 for r in rows),
                        event_quality_counts=dict(__import__('collections').Counter(r.get('event_variance_quality','UNSCOREABLE') for r in rows)))
                    current.append(summary)
                    if decision['action']=='SELL_CC' and entered is None:
                        eid=ledger.record_episode(ticker,'deployment-qa',rows,{'action':'NO_CALL','reason':'DEPLOYMENT_QA_ONLY','contracts':0},
                            decision,policy,CC_V3_CONFIG,analysis['snapshot_timestamp'],path,qa_only=True)
                        db=ledger.connect(path);chain=db.execute('SELECT id FROM cc_virtual_chains WHERE episode_id=? AND simulation_kind="PROSPECTIVE"',(eid,)).fetchone();db.close()
                        entered=dict(episode_id=eid,chain_id=chain[0] if chain else None,ticker=ticker,decision=decision)
                except Exception as exc:current.append(dict(ticker=ticker,error=str(exc)))
    result['current_chains']=current;result['real_current_virtual_entry']=entered
    result['market_qa_errors']=sum('error' in c for c in current)
    result['real_entry_state']='CREATED_QA_ONLY' if entered else 'MARKET_QA_INCOMPLETE' if result['market_qa_errors'] else 'NO_CURRENT_QUALIFYING_CHALLENGER_CALL' if tickers else 'NOT_REQUESTED'
    db=ledger.connect(path);final=fingerprint(db);db.close();assert final==before
    result['actual_tables_unchanged_after_all_qa']=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True);parser.add_argument('--tickers',nargs='*');parser.add_argument('--report',required=True)
    args=parser.parse_args();result=run(args.db,args.tickers)
    Path(args.report).write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(actual_tables_unchanged=result['actual_tables_unchanged_after_all_qa'],
        synthetic_lifecycle=result['synthetic_lifecycle']['result'],validation_status=result['validation']['status'],
        validation_n=result['validation']['metrics']['n'],current_chain_n=len(result['current_chains']),market_qa_errors=result['market_qa_errors'],
        real_entry_state=result['real_entry_state']),indent=2))
    if result['market_qa_errors']:sys.exit(1)
