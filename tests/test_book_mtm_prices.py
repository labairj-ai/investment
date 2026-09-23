import json

import pandas as pd
import pytest

from agents.learning import book_mtm
import operational_watchdog as wd


@pytest.mark.parametrize('price,expected', [(4.25,4.25),(0,None),(-1,None),(float('nan'),None),(float('inf'),None)])
def test_provider_contract_and_valid_close(monkeypatch, price, expected):
    import yfinance
    class MockTicker:
        def __init__(self, ticker):
            assert ticker == 'MSGM'
        def history(self, *, start, end, auto_adjust, **kwargs):
            assert start == '2026-09-21' and end == '2026-09-22'
            assert not auto_adjust
            return pd.DataFrame({'Close': [price]}, index=pd.to_datetime(['2026-09-21']))
    monkeypatch.setattr(yfinance, 'Ticker', MockTicker)
    assert book_mtm._get_closing_price('MSGM', '2026-09-21') == expected


def test_no_previous_day_substitution_and_visible_failure(monkeypatch, capsys):
    import yfinance
    class WrongDateTicker:
        def __init__(self, ticker): pass
        def history(self, **kwargs):
            return pd.DataFrame({'Close': [4.2]}, index=pd.to_datetime(['2026-09-18']))
    monkeypatch.setattr(yfinance, 'Ticker', WrongDateTicker)
    assert book_mtm._get_closing_price('MSGM', '2026-09-21') is None
    class BrokenTicker:
        def __init__(self, ticker): pass
        def history(self, **kwargs):
            raise TypeError('provider contract error')
    monkeypatch.setattr(yfinance, 'Ticker', BrokenTicker)
    assert book_mtm._get_closing_price('MSGM', '2026-09-21') is None
    assert 'TypeError: provider contract error' in capsys.readouterr().out


def test_alert_lists_affected_marks_without_portfolio_payload():
    finding=wd.result('mtm_completeness','YELLOW','Missing or incomplete daily marks',missing=[dict(book_id='macro_control',date='2026-09-21',reason='incomplete',private='SECRET')])
    text=wd.alert_summary(dict(component='mtm_completeness',detail=json.dumps(finding),last_success_at=None,last_record_id=None,incident_id='incident'))
    assert 'macro_control / 2026-09-21 (incomplete)' in text
    assert 'None' not in text and 'SECRET' not in text


def test_repair_and_rerun_preserve_returns_and_fills(mem_db, monkeypatch):
    import agent_db
    c=agent_db._connect()
    c.execute("INSERT INTO virtual_books(book_id,starting_cash,current_cash) VALUES ('repair',100,90)")
    c.execute("INSERT INTO virtual_fills(book_id,ticker,action,qty,price,filled_at,created_at) VALUES ('repair','MSGM','BUY',2,5,'2026-09-21T12:00:00',1)")
    for day,nav in [('2026-09-18',100),('2026-09-22',200)]:
        c.execute('INSERT INTO virtual_book_nav(book_id,date,total_nav,is_complete) VALUES (?,?,?,1)',('repair',day,nav))
    c.commit()
    monkeypatch.setattr(book_mtm,'_get_closing_price',lambda ticker,day: 100 if ticker=='SPY' else None)
    assert book_mtm.run_mark_to_market('2026-09-21')['errors']
    assert c.execute("SELECT is_complete FROM virtual_book_nav WHERE book_id='repair' AND date='2026-09-21'").fetchone()[0]==0
    monkeypatch.setattr(book_mtm,'_get_closing_price',lambda ticker,day: 100 if ticker=='SPY' else 6)
    for _ in range(2):
        assert not book_mtm.run_mark_to_market('2026-09-21')['errors']
        row=c.execute("SELECT total_nav,daily_return,is_complete FROM virtual_book_nav WHERE book_id='repair' AND date='2026-09-21'").fetchone()
        assert row['total_nav']==102 and row['is_complete']==1
        assert row['daily_return']==pytest.approx(.02)
    assert c.execute("SELECT COUNT(*) FROM virtual_fills WHERE book_id='repair'").fetchone()[0]==1
    assert c.execute("SELECT current_cash FROM virtual_books WHERE book_id='repair'").fetchone()[0]==90
    c.close()
