"""Offline reproductions. Extract handlers with AST to avoid serve.py startup/DB writes."""
import ast
import __future__
import csv
import io
import json
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = Path(tempfile.mkdtemp(prefix='investment-deep-review-'))
print('Temporary reproduction evidence:', EVIDENCE_DIR)
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
RESULTS = {}


def extract(file, names, globals):
    tree = ast.parse((ROOT / file).read_text())
    selected = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / file), 'exec', flags=__future__.annotations.compiler_flag), globals)


def fixture():
    root = Path(tempfile.mkdtemp(prefix='case-', dir=EVIDENCE_DIR))
    (root / 'out').mkdir()
    db = root / 'out/investment.db'
    conn = sqlite3.connect(db)
    conn.executescript('''
      CREATE TABLE cost_lots(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker,shares,cost_per_share,purchase_date,notes);
      CREATE TABLE sell_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker,shares_sold,sell_price,sell_date,realized_gain,st_gain,lt_gain,fifo_detail,notes);
      CREATE TABLE holding_day(day,ticker,layer,shares,price,value,change_dollars,change_pct,weight_pct,PRIMARY KEY(day,ticker));
    ''')
    conn.execute("INSERT INTO cost_lots VALUES(1,'ABC',100,100,'2025-01-01','')")
    conn.execute("INSERT INTO holding_day VALUES('2026-10-21','ABC','Layer 3',100,150,15000,0,0,100)")
    conn.commit()
    (root / 'holdings.csv').write_text('Stock,Shares,AvgCost,Layer\nABC,100,100,3\n')
    g = dict(PROJECT_DIR=root, sqlite3=sqlite3, _csv_mod=csv, today_eastern=lambda:date(2026,10,21))
    extract('serve.py', {'_fifo_allocate','_handle_sell_add','_handle_sell_undo','_handle_lot_delete','_handle_lot_add'}, g)
    output = []
    obj = SimpleNamespace(_json=lambda data: output.append(data), _json_error=lambda code,error:output.append(dict(code=code,error=error)))
    def sell(qty, day='2026-10-21'):
        body=json.dumps(dict(ticker='ABC',shares_sold=qty,sell_price=150,sell_date=day)).encode()
        obj.headers={'Content-Length':str(len(body))};obj.rfile=io.BytesIO(body)
        g['_handle_sell_add'](obj)
        assert output[-1].get('ok'), output[-1]
        return output[-1]['id']
    return root, conn, g, obj, output, sell


root, conn, g, obj, output, sell = fixture()
first = sell(40); sell(60)
g['_handle_sell_undo'](obj, first)
restored = conn.execute('SELECT SUM(shares) FROM cost_lots').fetchone()[0]
assert restored == 100
RESULTS['undo_earlier_sale'] = dict(expected_shares=40, actual_shares=restored, csv=(root/'holdings.csv').read_text())

root, conn, g, obj, output, sell = fixture()
sid = sell(100)
snapshot = conn.execute('SELECT shares,value FROM holding_day').fetchone()
assert snapshot == (100,15000)
RESULTS['full_sale_snapshot'] = dict(expected_shares=0,actual_shares=snapshot[0],actual_value=snapshot[1])
g['_handle_sell_undo'](obj,sid)
assert list(csv.DictReader(io.StringIO((root/'holdings.csv').read_text()))) == []
RESULTS['undo_csv'] = dict(lot_shares=conn.execute('SELECT SUM(shares) FROM cost_lots').fetchone()[0], csv_rows=0)

root, conn, g, obj, output, sell = fixture()
conn.execute("UPDATE cost_lots SET shares=50,cost_per_share=100")
conn.execute("INSERT INTO cost_lots VALUES(2,'ABC',50,200,'2025-02-01','')");conn.commit()
(root/'holdings.csv').write_text('Stock,Shares,AvgCost,Layer\nABC,100,150,3\n')
sell(50)
row=list(csv.DictReader(io.StringIO((root/'holdings.csv').read_text())))[0]
assert float(row['AvgCost']) == 150
RESULTS['fifo_average_cost'] = dict(expected_avg_cost=200,actual_avg_cost=float(row['AvgCost']))

root, conn, g, obj, output, sell = fixture()
sell(20, '2026-10-20')
assert conn.execute('SELECT COUNT(*) FROM holding_day').fetchone()[0] == 0
RESULTS['backdated_sale_history'] = dict(expected_today_shares=80,actual_today_rows=0)

root, conn, g, obj, output, sell = fixture()
g['_handle_lot_delete'](obj,1)
RESULTS['delete_lot_csv'] = dict(lot_count=conn.execute('SELECT COUNT(*) FROM cost_lots').fetchone()[0],csv=(root/'holdings.csv').read_text())

# Cached outcome prices never expire and bypass the market-data fallback.
db = Path(tempfile.mkdtemp(dir=EVIDENCE_DIR)) / 'prices.db'
c=sqlite3.connect(db);c.execute('CREATE TABLE holding_day(ticker,day,price)');c.execute("INSERT INTO holding_day VALUES('ABC','2026-01-02',100)");c.commit();c.close()
def connect():
    c=sqlite3.connect(db);c.row_factory=sqlite3.Row;return c
fallback=[]
g=dict(agent_db=SimpleNamespace(_connect=connect),_yf_price=lambda *a:fallback.append(a) or 200)
extract('agents/learning/outcome_labeler.py',{'_get_ticker_price'},g)
actual=g['_get_ticker_price']('ABC','2026-10-21')
assert actual == 100 and not fallback
RESULTS['stale_outcome_price']=dict(target_date='2026-10-21',cached_date='2026-01-02',actual_price=actual,available_fallback_price=200,fallback_called=False)

# Risk tests use the repository's existing in-memory schema and policy factories.
from test_trade_engine import _make_conn,_make_policy,_make_account,_make_intent
from trade_engine import risk_engine as risk
from trade_engine.models import InstrumentType,Side
def evaluate(*args):
    return risk.evaluate(*args).to_dict()
c=_make_conn();policy=_make_policy()
c.execute("INSERT INTO orders(order_id,account_id,symbol,side,quantity,limit_price,state,fill_qty) VALUES('buy1','AGENTIC_SHADOW_01','ANET','BUY',5,100,'WORKING',0)")
d=evaluate(_make_intent(quantity=5,limit_price=100),policy,_make_account(),c)
assert d['decision'] != 'REJECTED'
RESULTS['new_position_reservations']=dict(decision=d['decision'],limit_pct=5,actual_committed_pct=10)

c=_make_conn();now=datetime.now(timezone.utc).isoformat()
c.execute("INSERT INTO position_snapshots(account_id,symbol,qty,avg_cost,market_price,market_value,price_as_of) VALUES('AGENTIC_SHADOW_01','ANET',100,100,100,10000,?)",(now,))
policy=_make_policy({'execution':{'max_daily_notional_pct':100}})
c.execute("INSERT INTO orders(order_id,account_id,symbol,side,quantity,contracts,limit_price,state,fill_qty) VALUES('call1','AGENTIC_SHADOW_01','ANET','SELL_TO_OPEN',1,1,2,'WORKING',0)")
intent=_make_intent(instrument_type=InstrumentType.OPTION,side=Side.SELL_TO_OPEN,quantity=1,contracts=1,strike=110,expiration='2026-12-18',limit_price=2)
d=evaluate(intent,policy,_make_account(),c)
assert d['decision'] != 'REJECTED'
RESULTS['option_coverage_reservations']=dict(decision=d['decision'],shares_owned=100,shares_required_for_both=200)
c.execute("UPDATE orders SET state='FILLED',fill_qty=1 WHERE order_id='call1'")
c.execute("INSERT INTO fills(fill_id,order_id,account_id,symbol,side,qty,price,filled_at) VALUES('f1','call1','AGENTIC_SHADOW_01','ANET','SELL_TO_OPEN',1,2,?)",(now,))
d=evaluate(_make_intent(side=Side.SELL,quantity=100),policy,_make_account(),c)
assert d['decision'] != 'REJECTED'
RESULTS['sell_covered_underlying']=dict(decision=d['decision'],shares_after=0,open_calls=1)

# Newsletter: each CSV lot gets replaced with the ticker's entire lot quantity.
import pandas as pd
root,conn,g0,obj,output,sell=fixture()
(root/'holdings.csv').write_text('Stock,Shares,AvgCost,Layer\nABC,40,100,3\nABC,60,100,3\n')
closes=pd.DataFrame({'close_yday':[100.,500.],'close_prev':[100.,500.]},index=['ABC','SPY'])
class Captured(Exception): pass
captured={}
def snapshot(day,total,*args):
    captured.update(total=total,shares=args[-1]['Shares'].tolist())
    raise Captured()
from concurrent.futures import ThreadPoolExecutor
g=dict(HOLDINGS_CSV=root/'holdings.csv',PROJECT_DIR=root,pd=pd,normalize_ticker=lambda t:t,
       LAYER_NAMES={n:str(n) for n in range(1,6)},BENCHMARK='SPY',ThreadPoolExecutor=ThreadPoolExecutor,
       fetch_last_two_closes=lambda ts:closes,fetch_calendar_events=lambda ts:([],[]),
       compute_drift=lambda _:[],datetime=datetime,TZ=timezone.utc,_is_market_holiday=lambda _:False,
       store_snapshot=snapshot)
extract('send_newsletter_main.py',{'main'},g)
try:g['main']()
except Captured:pass
assert captured['total']==20000
RESULTS['newsletter_multiple_lots']=dict(expected_value=10000,actual_value=captured['total'],actual_csv_row_shares=captured['shares'])

# Both newsletter and dashboard disagree with the project's canonical market calendar.
from pandas.tseries.holiday import USFederalHolidayCalendar
from trade_engine.market_calendar import is_trading_day
g=dict(USFederalHolidayCalendar=USFederalHolidayCalendar,today_eastern=lambda:date(2026,10,21),date=date)
extract('send_newsletter_main.py',{'_good_friday','_is_market_holiday'},g)
assert g['_is_market_holiday'](date(2026,10,12)) and is_trading_day(date(2026,10,12))
RESULTS['market_holiday_disagreement']=dict(day='2026-10-12',newsletter_closed=True,canonical_market_open=True)

# A transient quote miss marks the intent APPROVED before creating any order.
from trade_engine import execution_engine as engine
from test_trade_engine import _insert_intent
c=_make_conn();intent=_make_intent(quantity=5);_insert_intent(c,intent)
broker=MagicMock();broker.get_quote.return_value=None
with patch.object(engine,'load_policy',return_value=_make_policy()):
    first=engine.process_intent(intent.intent_id,c,broker)
    retry=engine.process_new_intents(intent.account_id,c,broker)
assert first.decision=='QUOTE_UNAVAILABLE' and retry==[]
RESULTS['quote_retry_stranded']=dict(first_result=first.decision,status=c.execute('SELECT status FROM trade_intents').fetchone()[0],next_cycle_processed=len(retry),orders=c.execute('SELECT COUNT(*) FROM orders').fetchone()[0])

# Lot-add accepts negative share quantities.
root,conn,g,obj,output,sell=fixture()
obj._read_body=lambda:dict(ticker='ABC',shares=-20,cost_per_share=100,purchase_date='2026-10-21')
g['_handle_lot_add'](obj)
assert output[-1].get('ok')
RESULTS['negative_lot_accepted']=dict(response=output[-1],negative_lots=conn.execute('SELECT COUNT(*) FROM cost_lots WHERE shares<0').fetchone()[0])

# Concurrent sell requests allocate from the same pre-transaction inventory.
from concurrent.futures import ThreadPoolExecutor
import threading
root,conn,g,obj,output,sell=fixture()
barrier=threading.Barrier(2);original=g['_fifo_allocate']
def allocate(*args):
    result=original(*args);barrier.wait(timeout=10);return result
g['_fifo_allocate']=allocate
def request_sell():
    body=json.dumps(dict(ticker='ABC',shares_sold=70,sell_price=150,sell_date='2026-10-21')).encode()
    response=[]
    request=SimpleNamespace(headers={'Content-Length':str(len(body))},rfile=io.BytesIO(body),_json=lambda d:response.append(d),_json_error=lambda code,error:response.append(dict(error=error)))
    g['_handle_sell_add'](request)
    return response
with ThreadPoolExecutor(max_workers=2) as pool:
    replies=list(pool.map(lambda _:request_sell(),range(2)))
sold=conn.execute('SELECT SUM(shares_sold) FROM sell_transactions').fetchone()[0]
assert sold==140
RESULTS['concurrent_oversell']=dict(starting_shares=100,sold_shares=sold,remaining_shares=conn.execute('SELECT SUM(shares) FROM cost_lots').fetchone()[0],responses=replies)

# Approval writes uppercase ACTIVE, while the CC policy loader filters lowercase active.
root=Path(tempfile.mkdtemp(dir=EVIDENCE_DIR));db=root/'thesis.db'
c=sqlite3.connect(db)
c.execute('CREATE TABLE investment_theses(id INTEGER PRIMARY KEY,ticker,version,status,closed_at,approved_by,approved_at,draft_json,summary,cc_policy)')
c.execute("INSERT INTO investment_theses(id,ticker,version,status,cc_policy) VALUES(1,'ABC',1,'DRAFT',?)",(json.dumps(dict(strategy='NONE',assignment_policy={'allowed':False})),));c.commit();c.close()
def thesis_conn():
    c=sqlite3.connect(db);c.row_factory=sqlite3.Row;return c
import time
g=dict(_connect=thesis_conn,time=time)
extract('agent_db.py',{'approve_thesis'},g)
g['approve_thesis']('ABC','{}')
tree=ast.parse((ROOT/'agents/covered_call_agent.py').read_text())
defaults=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.AnnAssign) and getattr(n.target,'id',None)=='_CC_POLICY_DEFAULTS')
g=dict(_DB=db,sqlite3=sqlite3,_CC_POLICY_DEFAULTS=defaults,agent_db=SimpleNamespace(_connect=thesis_conn))
extract('agents/covered_call_agent.py',{'_get_cc_policy'},g)
extract('agents/dependency_checker.py',{'_latest_thesis_versions'},g)
policy=g['_get_cc_policy']('ABC');versions=g['_latest_thesis_versions']()
assert policy['strategy']=='INCOME' and policy['assignment_policy']['allowed'] and versions=={}
RESULTS['approved_thesis_ignored']=dict(stored_strategy='NONE',actual_strategy=policy['strategy'],stored_assignment_allowed=False,actual_assignment_allowed=policy['assignment_policy']['allowed'],dependency_versions=versions)

# A historical MTM repair includes purchases that have not occurred as of that date.
from agents.learning import book_mtm
db=Path(tempfile.mkdtemp(dir=EVIDENCE_DIR))/'book.db'
c=sqlite3.connect(db)
c.executescript("CREATE TABLE virtual_books(book_id,starting_cash,current_cash,as_of); CREATE TABLE virtual_fills(book_id,episode_id,ticker,action,price,qty,fees,filled_at,decision_origin,created_at); CREATE TABLE virtual_book_nav(book_id,date,cash,positions_json,total_nav,spy_nav,daily_return,is_complete,created_at,PRIMARY KEY(book_id,date));")
c.execute("INSERT INTO virtual_books VALUES('TEST',1000,900,'2026-10-20')")
c.execute("INSERT INTO virtual_fills VALUES('TEST',NULL,'ABC','BUY',100,1,0,'2026-10-20T17:00:00Z','CHAMPION',0)");c.commit();c.close()
def book_conn():
    c=sqlite3.connect(db);c.row_factory=sqlite3.Row;return c
with patch.object(book_mtm.agent_db,'_connect',book_conn),patch.object(book_mtm,'_get_closing_price',side_effect=lambda ticker,day:100 if ticker=='SPY' else 500):
    result=book_mtm.run_mark_to_market('2026-09-21')
    assert result['errors']==[]
c=book_conn();row=c.execute('SELECT * FROM virtual_book_nav').fetchone()
assert row['total_nav']==1400 and row['is_complete']==1
RESULTS['mtm_future_fill_leakage']=dict(target_date=row['date'],purchase_date='2026-10-20',expected_nav=1000,actual_nav=row['total_nav'],is_complete=row['is_complete'])

(EVIDENCE_DIR / 'results.json').write_text(json.dumps(RESULTS,indent=2))
print(json.dumps(RESULTS,indent=2))
