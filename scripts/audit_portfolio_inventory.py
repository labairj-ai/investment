#!/usr/bin/env python3
"""Read-only inventory/projection/stranded-intent audit. Never migrates or repairs data."""
import argparse
import csv
import json
import math
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio_positions import _normalize


def audit(root):
    root=Path(root)
    findings=[]
    with (root/'holdings.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    csv_positions={}
    for row in rows:
        ticker=_normalize(row['Stock'])
        qty=float(row['Shares']);cost=float(row['AvgCost'])
        old=csv_positions.setdefault(ticker,dict(qty=0,basis=0,rows=0))
        old['qty']+=qty;old['basis']+=qty*cost;old['rows']+=1
    conn=sqlite3.connect((root/'out/investment.db').resolve().as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    try:
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        lots={}
        if 'cost_lots' in tables:
            for row in conn.execute('SELECT * FROM cost_lots'):
                ticker=_normalize(row['ticker'])
                if not all(isinstance(row[k],(int,float)) and math.isfinite(row[k]) and row[k]>=0 for k in ('shares','cost_per_share')):
                    findings.append(dict(kind='INVALID_LOT',ticker=ticker,lot_id=row['id']));continue
                old=lots.setdefault(ticker,dict(qty=0,basis=0))
                old['qty']+=row['shares'];old['basis']+=row['shares']*row['cost_per_share']
            for ticker in sorted(set(lots)|set(csv_positions)):
                csv_pos=csv_positions.get(ticker,dict(qty=0,basis=0,rows=0));ledger=lots.get(ticker,dict(qty=0,basis=0))
                if csv_pos['rows']>1:
                    findings.append(dict(kind='DUPLICATE_CSV_POSITION',ticker=ticker))
                if abs(csv_pos['qty']-ledger['qty'])>1e-6 or abs(csv_pos['basis']-ledger['basis'])>0.02:
                    findings.append(dict(kind='CSV_LEDGER_MISMATCH',ticker=ticker,csv=csv_pos,ledger=ledger))
        if {'holding_day','portfolio_day'}<=tables:
            for row in conn.execute('''SELECT p.day,p.total_value,COALESCE(SUM(h.value),0) AS holdings_value
                FROM portfolio_day p LEFT JOIN holding_day h ON h.day=p.day GROUP BY p.day
                HAVING ABS(p.total_value-COALESCE(SUM(h.value),0))>0.02'''):
                findings.append(dict(kind='SNAPSHOT_TOTAL_MISMATCH',**dict(row)))
        if {'orders','trade_intents'}<=tables:
            for row in conn.execute("SELECT intent_id,account_id,valid_until FROM trade_intents i WHERE status='APPROVED' AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.intent_id=i.intent_id)"):
                findings.append(dict(kind='APPROVED_WITHOUT_ORDER',**dict(row)))
        if 'investment_theses' in tables:
            for row in conn.execute("SELECT ticker,COUNT(*) AS count FROM investment_theses WHERE UPPER(status)='ACTIVE' GROUP BY ticker HAVING COUNT(*)>1"):
                findings.append(dict(kind='AMBIGUOUS_ACTIVE_THESIS',**dict(row)))
        if 'portfolio_mutation_receipts' in tables:
            for row in conn.execute('SELECT id FROM portfolio_mutation_receipts WHERE projected=0'):
                findings.append(dict(kind='PENDING_CSV_PROJECTION',mutation_id=row[0]))
        if {'episode_outcomes','decision_episodes','holding_day'}<=tables:
            for row in conn.execute('''SELECT DISTINCT e.episode_id,e.ticker,MAX(h.day) AS last_cached_session
                FROM decision_episodes e JOIN episode_outcomes o ON o.episode_id=e.episode_id
                LEFT JOIN holding_day h ON h.ticker=e.ticker
                WHERE o.ticker_return IS NOT NULL GROUP BY e.episode_id
                HAVING last_cached_session IS NULL OR last_cached_session<DATE(e.captured_at,'unixepoch','+7 days')'''):
                findings.append(dict(kind='OUTCOME_PRICE_PROVENANCE_REVIEW',**dict(row)))
        if {'virtual_book_nav','virtual_books','virtual_fills'}<=tables:
            from time_utils import parse_timestamp,TZ_EASTERN
            for book in conn.execute('SELECT book_id,starting_cash FROM virtual_books').fetchall():
                fills=conn.execute('SELECT * FROM virtual_fills WHERE book_id=? ORDER BY filled_at',(book['book_id'],)).fetchall()
                for nav in conn.execute('SELECT date,cash,positions_json FROM virtual_book_nav WHERE book_id=?',(book['book_id'],)).fetchall():
                    cash=book['starting_cash'];positions={}
                    for fill in fills:
                        if parse_timestamp(fill['filled_at'],legacy_utc=True).astimezone(TZ_EASTERN).date().isoformat()>nav['date']:continue
                        sign=1 if fill['action']=='BUY' else -1
                        positions[fill['ticker']]=positions.get(fill['ticker'],0)+sign*fill['qty']
                        cash-=sign*fill['qty']*fill['price']+(fill['fees'] or 0)
                    stored=json.loads(nav['positions_json'] or '{}')
                    mismatched=any(abs(positions.get(ticker,0)-stored.get(ticker,{}).get('qty',0))>1e-6 for ticker in set(positions)|set(stored))
                    if mismatched or abs(cash-nav['cash'])>.02:
                        findings.append(dict(kind='VIRTUAL_NAV_ASOF_MISMATCH',book_id=book['book_id'],date=nav['date']))
    finally:
        conn.close()
    return dict(read_only=True,findings=findings,count=len(findings),
        outcome_note='Price-cache gaps identify candidates for review, not proof of bad outcomes; provider fallback may have supplied valid prices.',
        repair_policy='Take a consistent backup, freeze an affected-row manifest, rebuild in a copy, and reconcile before any production repair. Valid historical outcome labels must be versioned rather than overwritten.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    print(json.dumps(audit(args.project),indent=2,allow_nan=False))
