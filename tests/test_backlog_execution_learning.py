"""Behavioral regressions for the remaining October review backlog."""
import ast
import __future__
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from test_trade_engine import _make_conn,_make_policy,_make_account,_make_intent,_insert_intent
from trade_engine import risk_engine as risk, execution_engine as engine
from trade_engine.models import InstrumentType, Side
from trade_engine.broker_types import BrokerQuote,BrokerOrderAck

ROOT=Path(__file__).resolve().parents[1]


def extract(path, names, namespace):
    tree=ast.parse((ROOT/path).read_text())
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/path),'exec',flags=__future__.annotations.compiler_flag),namespace)


def test_approved_policy_and_dependency_hashes(mem_db,monkeypatch):
    import agent_db
    from agents import covered_call_agent, dependency_checker
    conn=agent_db._connect()
    conn.execute("INSERT INTO investment_theses(ticker,version,summary,status,created_at,cc_policy) VALUES('ABC',1,'test','DRAFT',0,?)",
                 (json.dumps(dict(strategy='NONE',assignment_policy={'allowed':False})),))
    conn.commit();conn.close()
    before=agent_db.get_cc_policy_hash('ABC')
    agent_db.approve_thesis('ABC','{}')
    monkeypatch.setattr(covered_call_agent,'_DB',mem_db)
    assert covered_call_agent._get_cc_policy('ABC')['strategy']=='NONE'
    assert not covered_call_agent._get_cc_policy('ABC')['assignment_policy']['allowed']
    assert dependency_checker._latest_thesis_versions()=={'ABC':1}
    assert agent_db._get_thesis_version_for_hash('ABC')==1
    assert before!=agent_db.get_cc_policy_hash('ABC')
    policy_hash=agent_db.get_cc_policy_hash('ABC')
    conn=agent_db._connect()
    conn.execute("UPDATE investment_theses SET cc_policy=? WHERE ticker='ABC'",
                 (json.dumps(dict(strategy='NONE',assignment_policy={'allowed':True})),))
    conn.commit()
    assert policy_hash!=agent_db.get_cc_policy_hash('ABC')
    conn.execute("INSERT INTO investment_theses(ticker,version,summary,status,created_at) VALUES('ABC',2,'ambiguous','active',0)")
    conn.commit();conn.close()
    assert covered_call_agent._get_cc_policy('ABC')['strategy']=='NONE'
    assert not covered_call_agent._get_cc_policy('ABC')['assignment_policy']['allowed']


def setup_risk():
    conn=_make_conn();stamp=datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO position_snapshots(account_id,symbol,qty,avg_cost,market_price,market_value,price_as_of) VALUES('AGENTIC_SHADOW_01','ANET',100,100,100,10000,?)",(stamp,))
    return conn,stamp


@pytest.mark.parametrize('state',['PENDING_SUBMIT','WORKING','PARTIALLY_FILLED'])
def test_calls_reserve_coverage_and_contract_cap(state):
    conn,stamp=setup_risk()
    conn.execute("INSERT INTO orders(order_id,account_id,symbol,side,quantity,contracts,limit_price,state,fill_qty) VALUES('call','AGENTIC_SHADOW_01','ANET','SELL_TO_OPEN',1,1,2,?,0)",(state,))
    intent=_make_intent(instrument_type=InstrumentType.OPTION,side=Side.SELL_TO_OPEN,quantity=1,contracts=1,strike=110,expiration='2027-01-15',limit_price=2)
    policy=_make_policy({'execution':{'max_daily_notional_pct':100}})
    assert risk.evaluate(intent,policy,_make_account(),conn).decision=='REJECTED'
    preview=risk.preview(intent,policy,_make_account(),conn)
    failures={c['rule'] for c in preview['checks'] if c['result']=='FAIL'}
    assert {'NO_NAKED_OPTIONS','MAX_CONTRACTS_PER_SYMBOL'}<=failures


def test_equity_sales_preserve_filled_call_coverage():
    conn,stamp=setup_risk()
    conn.execute("INSERT INTO orders(order_id,account_id,symbol,side,quantity,contracts,state,fill_qty) VALUES('call','AGENTIC_SHADOW_01','ANET','SELL_TO_OPEN',1,1,'FILLED',1)")
    conn.execute("INSERT INTO fills(fill_id,order_id,account_id,symbol,side,qty,price,filled_at) VALUES('f','call','AGENTIC_SHADOW_01','ANET','SELL_TO_OPEN',1,2,?)",(stamp,))
    policy=_make_policy({'execution':{'max_daily_notional_pct':100}})
    assert risk.preview(_make_intent(side=Side.SELL,quantity=100),policy,_make_account(),conn)['decision']=='REJECTED'
    conn.execute("UPDATE position_snapshots SET qty=150,market_value=15000")
    assert risk.preview(_make_intent(side=Side.SELL,quantity=50),policy,_make_account(),conn)['decision']=='PREVIEW_PASS'
    assert risk.preview(_make_intent(side=Side.SELL,quantity=51),policy,_make_account(),conn)['decision']=='REJECTED'


def test_new_position_reservations_and_own_order_exclusion():
    conn=_make_conn();policy=_make_policy()
    conn.execute("INSERT INTO orders(order_id,account_id,symbol,side,quantity,limit_price,state,fill_qty) VALUES('buy','AGENTIC_SHADOW_01','ANET','BUY',5,100,'WORKING',0)")
    intent=_make_intent(quantity=5)
    assert risk.preview(intent,policy,_make_account(),conn)['decision']=='REJECTED'
    assert risk.evaluate(intent,policy,_make_account(),conn,phase='PRE_FILL',exclude_order_id='buy',remaining_quantity=5).decision=='APPROVED'


def test_temporary_quote_failure_retries_and_submits_once():
    conn=_make_conn();intent=_make_intent(quantity=5);_insert_intent(conn,intent)
    broker=MagicMock();broker.requires_market_timestamp=True;broker.get_quote.return_value=None
    with patch.object(engine,'load_policy',return_value=_make_policy()):
        assert engine.process_new_intents(intent.account_id,conn,broker)[0].decision=='QUOTE_UNAVAILABLE'
        assert conn.execute('SELECT status FROM trade_intents').fetchone()[0]=='PENDING'
        stamp=datetime.now(timezone.utc).isoformat()
        broker.get_quote.return_value=BrokerQuote(99.5,100,'ANET',stamp,stamp)
        broker.submit_order.return_value=BrokerOrderAck('broker-id',stamp,'WORKING')
        broker.poll_order_events.return_value=[]
        engine.process_new_intents(intent.account_id,conn,broker)
        engine.process_new_intents(intent.account_id,conn,broker)
    assert broker.submit_order.call_count==1
    assert conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1


def test_stale_prices_fall_back_and_weekend_uses_exact_session(mem_db,monkeypatch):
    import agent_db
    from agents.learning import outcome_labeler as labeler
    conn=agent_db._connect()
    conn.execute("CREATE TABLE IF NOT EXISTS holding_day(day,ticker,layer,shares,price,value,change_dollars,change_pct,weight_pct)")
    conn.execute("INSERT INTO holding_day(day,ticker,layer,shares,price,value,change_dollars,change_pct,weight_pct) VALUES('2026-01-02','ABC','L',1,100,100,0,0,100)")
    conn.commit();conn.close()
    calls=[];monkeypatch.setattr(labeler,'_yf_price',lambda ticker,day:calls.append(day) or 200)
    assert labeler._get_ticker_price('ABC','2026-10-21')==200
    assert calls==['2026-10-21']
    labeler._get_ticker_price('ABC','2026-10-18')
    assert calls[-1]=='2026-10-16'


def test_missing_outcome_placeholder_can_complete(mem_db):
    import agent_db
    from agents.learning import outcome_labeler as labeler
    conn=agent_db._connect()
    # A real episode FK is required by the production schema.
    from test_outcome_labeler import _insert_episode
    episode=_insert_episode(conn,'ABC',days_old=100)
    labeler._insert_outcome(conn,episode,'1w',None,None,None,None,None)
    assert not labeler._already_labeled(conn,episode,'1w')
    labeler._insert_outcome(conn,episode,'1w',.1,.05,.05,.2,-.01)
    assert labeler._already_labeled(conn,episode,'1w')
    labeler._insert_outcome(conn,episode,'1w',.9,.9,0,.9,0)
    assert conn.execute('SELECT ticker_return FROM episode_outcomes WHERE episode_id=?',(episode,)).fetchone()[0]==.1


def test_newsletter_multilot_and_exchange_calendar(tmp_path,monkeypatch):
    import send_newsletter_main as newsletter
    import sqlite3
    (tmp_path/'out').mkdir()
    (tmp_path/'holdings.csv').write_text('Stock,Shares,AvgCost,Layer\nABC,40,100,3\nABC,60,100,3\n')
    with sqlite3.connect(tmp_path/'out/investment.db') as conn:
        conn.execute('CREATE TABLE cost_lots(ticker,shares)');conn.execute("INSERT INTO cost_lots VALUES('ABC',100)")
    monkeypatch.setattr(newsletter,'PROJECT_DIR',tmp_path);monkeypatch.setattr(newsletter,'HOLDINGS_CSV',tmp_path/'holdings.csv')
    prices=pd.DataFrame({'close_yday':[100.,500.],'close_prev':[100.,500.]},index=['ABC','SPY'])
    monkeypatch.setattr(newsletter,'fetch_last_two_closes',lambda _:prices)
    monkeypatch.setattr(newsletter,'fetch_calendar_events',lambda _:([],[]))
    class Captured(Exception): pass
    captured={}
    def snapshot(day,total,*args):
        captured.update(total=total,holdings=args[-1]);raise Captured()
    monkeypatch.setattr(newsletter,'store_snapshot',snapshot)
    with pytest.raises(Captured): newsletter.main()
    assert captured['total']==10000
    assert len(captured['holdings'])==1
    for day in [date(2026,10,12),date(2026,11,11)]:
        assert not newsletter._is_market_holiday(day)
    assert newsletter._is_market_holiday(date(2026,4,3))


def test_historical_mtm_excludes_future_cash_flows(mem_db,monkeypatch):
    import agent_db
    from agents.learning import book_mtm
    conn=agent_db._connect()
    conn.execute("INSERT INTO virtual_books(book_id,starting_cash,current_cash) VALUES('repair',1000,900)")
    conn.execute("INSERT INTO virtual_fills(book_id,ticker,action,qty,price,fees,filled_at,created_at) VALUES('repair','ABC','BUY',1,100,0,'2026-10-20T17:00:00Z',0)")
    conn.commit()
    monkeypatch.setattr(book_mtm,'_get_closing_price',lambda ticker,day:100 if ticker=='SPY' else 500)
    assert not book_mtm.run_mark_to_market('2026-09-21')['errors']
    assert conn.execute("SELECT total_nav FROM virtual_book_nav WHERE book_id='repair'").fetchone()[0]==1000
    assert conn.execute("SELECT current_cash FROM virtual_books WHERE book_id='repair'").fetchone()[0]==900
    assert conn.execute('SELECT COUNT(*) FROM virtual_fills').fetchone()[0]==1

    assert not book_mtm.run_mark_to_market('2026-09-21')['errors']
    assert conn.execute('SELECT COUNT(*) FROM virtual_fills').fetchone()[0]==1


def test_historical_mtm_uses_eastern_fill_dates(mem_db,monkeypatch):
    import agent_db
    from agents.learning import book_mtm
    conn=agent_db._connect()
    conn.execute("INSERT INTO virtual_books(book_id,starting_cash,current_cash) VALUES('late',1000,900)")
    conn.execute("INSERT INTO virtual_fills(book_id,ticker,action,qty,price,fees,filled_at,created_at) VALUES('late','ABC','BUY',1,100,0,'2026-10-21T01:00:00Z',0)")
    conn.commit()
    monkeypatch.setattr(book_mtm,'_get_closing_price',lambda ticker,day:100 if ticker=='SPY' else 500)
    assert not book_mtm.run_mark_to_market('2026-10-20')['errors']
    assert conn.execute("SELECT total_nav FROM virtual_book_nav WHERE book_id='late'").fetchone()[0]==1400


def test_spy_outcomes_use_explicit_unadjusted_cache(mem_db,monkeypatch):
    import agent_db,yfinance
    from types import SimpleNamespace
    from agents import outcome_evaluator as evaluator
    conn=agent_db._connect()
    conn.execute("INSERT INTO spy_prices(day,price) VALUES('2026-10-21',125)");conn.commit()
    def history(**kw):
        assert kw['auto_adjust'] is False
        return pd.DataFrame({'Close':[100.]},index=pd.to_datetime(['2026-10-21']))
    monkeypatch.setattr(yfinance,'Ticker',lambda _:SimpleNamespace(history=history))
    evaluator._ensure_spy_prices(['2026-10-21'])
    assert evaluator._spy_price_at('2026-10-21')==100
    assert conn.execute("SELECT price FROM spy_prices WHERE day='2026-10-21'").fetchone()[0]==125
