"""User-requested midpoint fallback and dated historical projection contracts."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

import covered_call_daily_pnl as pnl
from portfolio_valuation import value_portfolio
from portfolio_value_history import historical_values
from portfolio_quote_refresh import slot, refresh, run

NOW=datetime(2026,11,5,16,0,tzinfo=timezone.utc)
P=dict(id=1,ticker='TEST',contracts=2,strike=100.,expiry='2026-12-18',opened_date='2026-11-02',
       status='open',closed_date=None,current_mark=None)


def book():
    c=sqlite3.connect(':memory:')
    c.execute('CREATE TABLE cc_positions(id,ticker,contracts,strike,expiry,opened_date,status,closed_date,current_mark)')
    c.execute('INSERT INTO cc_positions VALUES(?,?,?,?,?,?,?,?,?)',tuple(P.values()))
    pnl.migrate(c)
    return c


def quote(**changes):
    return dict(dict(mark=4.5,bid=4.,ask=5.,mark_basis='BID_ASK_MIDPOINT',
                     last_trade_at='2026-11-02T19:00:00Z',source=pnl.SOURCE),**changes)


def save(c,q=None,observed=NOW,previous=4.):
    pnl.save_quote(c,P,'2026-11-05',q or quote(),previous,observed.isoformat())


def test_midpoint_is_valued_despite_old_last_trade_and_is_read_only():
    c=book();save(c)
    before=c.total_changes
    assert value_portfolio(c,10000.,'2026-11-05',NOW)['net_value']==9100.
    assert c.total_changes==before
    assert value_portfolio(c,10000.,'2026-11-05',NOW+timedelta(minutes=31))['net_value'] is None


def test_actual_reported_mark_has_priority_over_fresh_midpoint():
    c=book();save(c,quote(mark=4.8,mark_basis='PROVIDER_MARK'))
    save(c,quote(mark=5.5,bid=5.,ask=6.),NOW+timedelta(minutes=1))
    assert value_portfolio(c,10000.,'2026-11-05',NOW+timedelta(minutes=1))['net_value']==9040.


def test_failure_cannot_erase_last_good_quote_or_its_historical_value():
    c=book();save(c)
    before=c.execute('SELECT * FROM cc_display_quote_observations').fetchall()
    save(c,dict(error='QUOTE_FETCH_FAILED',source=pnl.SOURCE),NOW+timedelta(minutes=1))
    assert value_portfolio(c,10000.,'2026-11-05',NOW+timedelta(minutes=2))['net_value']==9100.
    after=c.execute('SELECT * FROM cc_display_quote_observations').fetchall()
    assert all(r in after for r in before)
    assert len(after)==len(before)+1
    pnl.migrate(c)
    assert c.execute('SELECT count(*) FROM cc_display_quote_observations').fetchone()[0]==len(after)


@pytest.mark.parametrize('bid,ask',[(5.,4.),(0.,0.),(None,4.),(-1.,4.)])
def test_invalid_spreads_do_not_qualify_without_an_actual_mark(bid,ask):
    c=book();save(c,quote(bid=bid,ask=ask))
    assert value_portfolio(c,10000.,'2026-11-05',NOW)['net_value'] is None


def test_fetch_stores_bid_ask_and_uses_midpoint_when_provider_mark_missing():
    frame=pd.DataFrame([dict(strike=100.,bid=4.,ask=5.,lastPrice=9.,contractSymbol='TEST261218C00100000',
                             lastTradeDate=pd.Timestamp('2026-10-20T15:00:00Z'))])
    factory=lambda _:SimpleNamespace(option_chain=lambda expiry:SimpleNamespace(calls=frame))
    q,prior=pnl.fetch_quote(P,'2026-11-05',4.,factory,lambda s:s)
    assert q['mark']==4.5 and q['bid']==4. and q['ask']==5.
    assert q['mark_basis']=='BID_ASK_MIDPOINT'
    assert prior==4.
    frame['mark']=4.8
    q,_=pnl.fetch_quote(P,'2026-11-05',4.,factory,lambda s:s)
    assert q['mark']==4.8 and q['mark_basis']=='PROVIDER_MARK'


def test_historical_days_use_dated_evidence_and_never_todays_quote_for_the_past():
    c=book();save(c)
    series=[dict(day=d,total_value=10000.) for d in ['2026-10-30','2026-11-03','2026-11-04','2026-11-05']]
    before=c.total_changes
    values=historical_values(c,series)
    assert [r['net_value'] for r in values]==[10000.,None,9200.,9100.]
    assert values[2]['marks'][0]['basis']=='CONTRACT_DAILY_CLOSE'
    assert values[3]['marks'][0]['basis']=='BID_ASK_MIDPOINT'
    assert c.total_changes==before
    assert series[2]['total_value']==10000.


def test_historical_position_lifetimes_exclude_closed_calls_at_end_of_day():
    c=book();save(c)
    c.execute("UPDATE cc_positions SET status='closed',closed_date='2026-11-05'")
    assert historical_values(c,[dict(day='2026-11-05',total_value=10000.)])[0]['net_value']==10000.


def test_historical_option_snapshots_match_exact_contract_and_do_not_require_a_trade():
    c=book()
    c.execute('CREATE TABLE option_quote_snapshots(id,ticker,strike,expiration,bid,ask,captured_at)')
    c.execute('INSERT INTO option_quote_snapshots VALUES(1,?,?,?,?,?,?)',('TEST',100.,P['expiry'],4.,5.,NOW.timestamp()))
    c.execute('INSERT INTO option_quote_snapshots VALUES(2,?,?,?,?,?,?)',('TEST',101.,P['expiry'],90.,100.,NOW.timestamp()))
    value=historical_values(c,[dict(day='2026-11-05',total_value=10000.)])[0]
    assert value['net_value']==9100.
    assert value['marks'][0]['reference']=='option_quote_snapshots:1'


@pytest.mark.parametrize('stamp,expected',[
    ('2026-11-05T14:29:59Z',None),('2026-11-05T14:30:00Z','2026-11-05T09:2'),
    ('2026-11-05T21:15:00Z','2026-11-05T16:1'),('2026-11-05T21:16:00Z',None),
    ('2026-11-07T16:00:00Z',None),('2026-11-26T16:00:00Z',None),
    ('2026-11-27T18:15:00Z','2026-11-27T13:1'),('2026-11-27T18:16:00Z',None),
])
def test_quote_schedule_market_calendar_and_early_close(stamp,expected):
    assert slot(datetime.fromisoformat(stamp.replace('Z','+00:00')))==expected


def test_refresh_path_runs_only_quote_collection_and_dashboard_no_email_models_or_broker(tmp_path):
    (tmp_path/'out').mkdir()
    calls=[]
    def invoke(args,**kwargs):
        calls.append(args);return SimpleNamespace(returncode=0)
    assert refresh(tmp_path,invoke)['status']=='REFRESHED'
    assert len(calls)==2
    assert 'fetch_cc_mtm' in calls[0][-1]
    assert calls[1][-1].endswith('generate_dashboard.py')
    assert not any('send_email' in str(c) or 'agent_pipeline' in str(c) for c in calls)


def test_backfill_is_completed_sessions_only_idempotent_and_preserves_source_tables():
    from cc_history_backfill import collect,apply
    c=book()
    c.execute('CREATE TABLE portfolio_day(day,total_value)')
    c.execute("INSERT INTO portfolio_day VALUES('2026-11-03',10000.)")
    c.commit()
    frame=pd.DataFrame([dict(Close=3.,Volume=10),dict(Close=4.,Volume=0),dict(Close=5.,Volume=10)],
                       index=[pd.Timestamp(d,tz='America/New_York') for d in ['2026-11-03','2026-11-04','2026-11-05']])
    symbols=[]
    def factory(symbol):
        symbols.append(symbol)
        return SimpleNamespace(history=lambda **kwargs:frame)
    before=c.total_changes
    report=collect(c,factory,NOW)
    assert c.total_changes==before
    assert report['completed_session']=='2026-11-04'
    assert [r['session'] for r in report['observations']]==['2026-11-03']
    assert symbols==['TEST261218C00100000']
    original=c.execute('SELECT * FROM portfolio_day').fetchall()
    assert apply(c,report['observations'])==1
    assert apply(c,report['observations'])==0
    assert c.execute('SELECT * FROM portfolio_day').fetchall()==original
    value=historical_values(c,[dict(day='2026-11-03',total_value=10000.)])[0]
    assert value['net_value']==9400.
    assert value['marks'][0]['basis']=='CONTRACT_DAILY_CLOSE'


def test_backfill_does_not_write_in_read_only_dry_run(tmp_path):
    from cc_history_backfill import collect
    path=tmp_path/'source.sqlite3'
    c=book();c.execute('CREATE TABLE portfolio_day(day,total_value)');c.execute("INSERT INTO portfolio_day VALUES('2026-11-03',10000.)");c.commit()
    with sqlite3.connect(path) as disk:c.backup(disk)
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as ro:
        report=collect(ro,lambda _:SimpleNamespace(history=lambda **kw:pd.DataFrame()),NOW)
        assert report['observations']==[]
        assert ro.execute("SELECT 1 FROM sqlite_master WHERE name='cc_display_historical_marks'").fetchone() is None


def test_worker_waits_for_next_slot_and_never_repeats_a_slot(monkeypatch,tmp_path):
    import portfolio_quote_refresh as worker
    instants=iter([NOW,NOW+timedelta(minutes=1),NOW+timedelta(minutes=15),NOW+timedelta(minutes=15,seconds=15)])
    calls=[]
    monkeypatch.setattr(worker,'refresh',lambda root:calls.append(root))
    with pytest.raises(StopIteration):
        worker.run(tmp_path,clock=lambda:next(instants),sleep=lambda _:None)
    assert calls==[tmp_path]


def test_worker_lock_skips_a_concurrent_refresh(tmp_path):
    import fcntl
    (tmp_path/'out').mkdir()
    with (tmp_path/'out'/'display-quote-refresh.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert refresh(tmp_path,lambda *a,**kw:pytest.fail('concurrent refresh'))['status']=='BUSY'


def test_expired_and_closed_contract_backfill_bounds_do_not_include_later_bars():
    from cc_history_backfill import collect
    c=book();c.execute('CREATE TABLE portfolio_day(day,total_value)');c.execute("INSERT INTO portfolio_day VALUES('2026-11-03',10000.)")
    c.execute("UPDATE cc_positions SET status='closed',closed_date='2026-11-04'")
    bounds=[]
    frame=pd.DataFrame([dict(Close=3.,Volume=10),dict(Close=4.,Volume=10)],
                       index=[pd.Timestamp(d,tz='America/New_York') for d in ['2026-11-03','2026-11-04']])
    def fetch(**kw):bounds.append(kw);return frame
    report=collect(c,lambda _:SimpleNamespace(history=fetch),NOW)
    assert bounds[0]['end']=='2026-11-04'
    assert [r['session'] for r in report['observations']]==['2026-11-03']


def test_historical_invalid_spread_does_not_complete_the_day():
    c=book();save(c,quote(bid=5.,ask=4.),previous=None)
    assert historical_values(c,[dict(day='2026-11-05',total_value=10000.)])[0]['net_value'] is None


def test_live_value_rejects_nonfinite_result_even_for_finite_inputs():
    c=book();save(c,quote(mark=1.e308,mark_basis='PROVIDER_MARK'))
    assert value_portfolio(c,10000.,'2026-11-05',NOW)['net_value'] is None
