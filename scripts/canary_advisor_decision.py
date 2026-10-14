#!/usr/bin/env python3
"""Network-free, read-only production canary; emits JSON, never persists decisions."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.advisor.context import build_advisor_decision_context
from agents.advisor.service import run_decision


def run_canary(conn):
    names=['holding_day','cost_lots','recommendations','trade_intents','risk_decisions','orders','fills','advisor_decisions']
    def counts():
        result={}
        for name in names:
            try: result[name]=conn.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]
            except sqlite3.OperationalError: result[name]=None
        return result
    before=counts()
    denied={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_CREATE_TRIGGER,sqlite3.SQLITE_DROP_TRIGGER}
    def guard(action,*args): return sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK
    conn.set_authorizer(guard)
    try:
        context=build_advisor_decision_context(conn)
        tickers=sorted(context['holdings'])
        requests=['Get IGV to 100 shares','Buy 17 IGV','Sell 10 STZ and use it to get IGV to 100']
        if tickers:
            requests.extend(['Get '+tickers[0]+' to 100 shares','Sell 1 '+tickers[0]])
        results=[run_decision(conn,raw,persist=False,allow_llm=False) for raw in requests]
        unchanged=before==counts()
        return dict(canary_contract='advisor-canary-v1',health='PASS' if unchanged else 'FAIL',read_only=True,
            network_free=True,production_state_unchanged=unchanged,context_hash=context['context_hash'],
            source_health=context['portfolio_state'].get('brief_health','UNAVAILABLE'),
            outcomes=[dict(request=r['request']['raw_request'],state=r['policy']['decision_state'],reasons=r['policy']['reasons'],
                           trade_deltas=[dict(ticker=l['ticker'],delta=l['delta_shares']) for l in r['impact']['legs']]) for r in results])
    finally:
        conn.set_authorizer(None)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=Path(__file__).resolve().parents[1]/'out'/'investment.db')
    args=parser.parse_args()
    conn=sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try: result=run_canary(conn)
    finally: conn.close()
    print(json.dumps(result,sort_keys=True,indent=2))
    return 0 if result['health']=='PASS' else 1


if __name__=='__main__': raise SystemExit(main())
