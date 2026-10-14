"""Dated short-call daily P&L: no network or production database access."""
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import covered_call_daily_pnl as pnl

NOW=datetime(2026,10,13,20,5,tzinfo=timezone.utc)
POSITION=dict(id=1,ticker='BRK-B',strike=525.0,expiry='2026-12-18',contracts=1,
              premium_per_contract=10.005,opened_date='2026-10-12',status='open')


def record(**changes):
    r=dict(position_id=1,session='2026-10-13',previous_session='2026-10-12',previous_close=11.41,
           observed_at=NOW.isoformat(),position_identity=pnl.position_identity(POSITION),
           quote_json=json.dumps(dict(mark=12.925,last_trade_at='2026-10-13T19:58:03+00:00',source=pnl.SOURCE)))
    r.update(changes)
    return r


def test_short_call_loss_uses_prior_close_not_entry_premium():
    result=pnl.position_daily_pnl(POSITION,record(),NOW)
    assert result['pnl_day']==-151.50
    assert result['pnl_day_status']=='ESTIMATED'
    assert result['pnl_day_previous_session']=='2026-10-12'


@pytest.mark.parametrize('change,status',[
    ({'previous_close':None},'PREVIOUS_CLOSE_UNAVAILABLE'),
    ({'previous_session':'2026-10-09'},'WRONG_PREVIOUS_SESSION'),
    ({'session':'2026-10-12'},'STALE_SESSION'),
    ({'observed_at':'2026-10-13T13:30:00Z'},'STALE_OPTION_OBSERVATION'),
    ({'observed_at':'2026-10-14T20:05:00Z'},'STALE_OPTION_OBSERVATION'),
])
def test_invalid_baselines_and_observations_never_become_zero(change,status):
    result=pnl.position_daily_pnl(POSITION,record(**change),NOW)
    assert result['pnl_day'] is None
    assert result['pnl_day_status']==status


@pytest.mark.parametrize('quote,status',[
    ({'last_trade_at':'2026-10-13T14:00:00Z'},'STALE_OPTION_QUOTE'),
    ({'last_trade_at':'2026-10-12T19:58:00Z'},'STALE_OPTION_QUOTE'),
    ({'last_trade_at':'2026-10-14T19:58:00Z'},'STALE_OPTION_QUOTE'),
    ({'mark':None},'INVALID_OPTION_QUOTE'),
    ({'mark':float('nan')},'INVALID_OPTION_QUOTE'),
    ({'source':'unverified'},'INVALID_OPTION_QUOTE'),
    ({'error':'QUOTE_FETCH_FAILED'},'QUOTE_FETCH_FAILED'),
])
def test_invalid_quotes_are_unavailable(quote,status):
    r=record(); q=json.loads(r['quote_json']);q.update(quote);r['quote_json']=json.dumps(q)
    result=pnl.position_daily_pnl(POSITION,r,NOW)
    assert result['pnl_day'] is None
    assert result['pnl_day_status']==status


def test_legacy_and_same_day_entry_are_not_fabricated_daily_pnl():
    assert pnl.position_daily_pnl(POSITION,None,NOW)['pnl_day'] is None
    p=dict(POSITION,opened_date='2026-10-13')
    result=pnl.position_daily_pnl(p,record(position_identity=pnl.position_identity(p)),NOW)
    assert result['pnl_day'] is None
    assert result['pnl_day_status']=='OPENED_THIS_SESSION'
    assert pnl.position_daily_pnl(dict(POSITION,contracts=2),record(),NOW)['pnl_day_status']=='POSITION_CHANGED'


@pytest.mark.parametrize('timestamp,session,previous',[
    ('2026-10-14T02:00:00+00:00','2026-10-13','2026-10-12'),
    ('2026-10-14T12:00:00+00:00','2026-10-13','2026-10-12'),
    ('2026-10-14T14:00:00+00:00','2026-10-14','2026-10-13'),
    ('2026-10-17T15:00:00+00:00','2026-10-16','2026-10-15'),
    ('2026-11-27T18:05:00+00:00','2026-11-27','2026-11-25'),
])
def test_session_calendar(timestamp,session,previous):
    assert pnl.reporting_session(datetime.fromisoformat(timestamp))==session
    assert pnl.nth_trading_session_before(session,1)==previous


def db(tmp_path):
    path=tmp_path/'marks.sqlite3'
    c=sqlite3.connect(path);c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE cc_positions (id INTEGER, ticker TEXT, strike REAL, expiry TEXT, contracts INTEGER, premium_per_contract REAL, opened_date TEXT, status TEXT, current_mark REAL, prev_mark REAL)')
    c.execute('INSERT INTO cc_positions VALUES (1,?,?,?,?,?,?,?,12.925,12.925)',tuple(POSITION[k] for k in ('ticker','strike','expiry','contracts','premium_per_contract','opened_date','status')))
    pnl.migrate(c);c.commit()
    return path,c


def test_baseline_is_immutable_across_repeated_refreshes(tmp_path):
    path,c=db(tmp_path)
    q=json.loads(record()['quote_json'])
    pnl.save_quote(c,POSITION,'2026-10-13',q,11.41,NOW.isoformat())
    pnl.save_quote(c,POSITION,'2026-10-13',dict(q,mark=13.0),None,NOW.isoformat())
    r=dict(c.execute('SELECT * FROM cc_daily_pnl_marks').fetchone())
    assert r['previous_close']==11.41
    assert pnl.position_daily_pnl(POSITION,r,NOW)['pnl_day']==-159.0
    pnl.save_quote(c,POSITION,'2026-10-13',q,12.925,NOW.isoformat())
    r=dict(c.execute('SELECT * FROM cc_daily_pnl_marks').fetchone())
    assert r['previous_close']==11.41
    assert pnl.position_daily_pnl(POSITION,r,NOW)['pnl_day_status']=='BASELINE_CONFLICT'
    c.close()


def test_report_does_not_treat_missing_call_or_intraday_close_as_complete(tmp_path):
    path,c=db(tmp_path)
    pnl.save_quote(c,POSITION,'2026-10-13',json.loads(record()['quote_json']),11.41,NOW.isoformat())
    positions=[dict(POSITION),dict(POSITION,id=2)]
    report=pnl.annotate_positions(c,positions,NOW)
    assert report['priced_count']==1 and report['open_count']==2
    assert report['options_pnl'] is None
    assert report['partial_options_pnl']==-151.5
    report=pnl.annotate_positions(c,[dict(POSITION),dict(POSITION,id=3,status='closed',closed_date='2026-10-13')],NOW)
    assert report['closed_this_session']==1
    assert not report['complete']
    assert report['reconciled_to_broker'] is False
    assert pnl.annotate_positions(c,[],NOW)['options_pnl']==0
    c.close()


def test_refresh_uses_exact_dated_history_and_never_rolls_prev_mark(tmp_path):
    path,c=db(tmp_path)
    history_calls=[]
    frame=pd.DataFrame([dict(strike=525.0,contractSymbol='BRKB261218C00525000',bid=12.65,ask=13.2,lastTradeDate=pd.Timestamp('2026-10-13T19:58:03Z'))])
    class Ticker:
        def __init__(self,symbol): self.symbol=symbol
        def option_chain(self,expiry): return SimpleNamespace(calls=frame)
        def history(self,**kwargs):
            history_calls.append(kwargs)
            return pd.DataFrame([dict(Close=11.41,Volume=77)],index=[pd.Timestamp('2026-10-12',tz='America/New_York')])
    pnl.refresh_marks(path,ticker_factory=Ticker,clock=lambda:NOW)
    pnl.refresh_marks(path,ticker_factory=Ticker,clock=lambda:NOW)
    assert len(history_calls)==1
    assert history_calls[0]['start']=='2026-10-12'
    assert history_calls[0]['end']=='2026-10-13'
    assert history_calls[0]['auto_adjust'] is False
    assert c.execute('SELECT prev_mark FROM cc_positions').fetchone()[0]==12.925
    positions=[dict(c.execute('SELECT * FROM cc_positions').fetchone())]
    assert pnl.annotate_positions(c,positions,NOW)['options_pnl']==-151.5
    c.close()


def test_quote_fetch_failure_and_absent_table_are_fail_closed(tmp_path):
    path,c=db(tmp_path)
    c.execute('DROP TABLE cc_daily_pnl_marks');c.commit()
    assert pnl.annotate_positions(c,[dict(POSITION)],NOW)['options_pnl'] is None
    def fail(symbol): raise RuntimeError('no network')
    pnl.refresh_marks(path,ticker_factory=fail,clock=lambda:NOW)
    report=pnl.annotate_positions(c,[dict(POSITION)],NOW)
    assert report['statuses']=={'QUOTE_FETCH_FAILED':1}
    assert report['options_pnl'] is None
    c.close()


def test_older_refresh_cannot_replace_a_newer_quote(tmp_path):
    path,c=db(tmp_path)
    quote=json.loads(record()['quote_json'])
    assert pnl.save_quote(c,POSITION,'2026-10-13',quote,11.41,NOW.isoformat())
    assert not pnl.save_quote(c,POSITION,'2026-10-13',dict(quote,mark=1),11.41,'2026-10-13T19:59:00Z')
    saved=dict(c.execute('SELECT * FROM cc_daily_pnl_marks').fetchone())
    assert json.loads(saved['quote_json'])['mark']==12.925
    c.close()


def test_network_fetch_does_not_hold_a_database_write_lock(tmp_path):
    path,c=db(tmp_path)
    frame=pd.DataFrame([dict(strike=525.0,contractSymbol='BRKB261218C00525000',bid=12.65,ask=13.2,lastTradeDate=pd.Timestamp('2026-10-13T19:58:03Z'))])
    c.execute("INSERT INTO cc_positions SELECT 2,'BP',strike,expiry,contracts,premium_per_contract,opened_date,status,current_mark,prev_mark FROM cc_positions")
    c.commit()
    class Ticker:
        def __init__(self,symbol): self.symbol=symbol
        def option_chain(self,expiry):
            # Another writer must remain able to acquire its transaction while
            # remote quote work is in progress.
            other=sqlite3.connect(path,timeout=.1)
            other.execute('BEGIN IMMEDIATE');other.rollback();other.close()
            return SimpleNamespace(calls=frame)
        def history(self,**kwargs):
            return pd.DataFrame([dict(Close=11.41,Volume=77)],index=[pd.Timestamp('2026-10-12',tz='America/New_York')])
    report=pnl.refresh_marks(path,ticker_factory=Ticker,clock=lambda:NOW)
    assert report['fetch_results']=={'FETCHED':2}
    c.close()
