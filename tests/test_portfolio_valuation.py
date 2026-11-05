"""Synthetic reconciliation and failed-feed regressions; never touch live state."""
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import covered_call_daily_pnl as pnl
from portfolio_valuation import value_portfolio

NOW = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
SESSION = '2026-11-05'
POSITION = dict(id=1, ticker='TEST', contracts=2, strike=100., expiry='2026-12-18',
                opened_date='2026-11-02', status='open', current_mark=999.)


def fixture():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE cc_positions (id, ticker, contracts, strike, expiry, opened_date, status, current_mark)')
    conn.execute('INSERT INTO cc_positions VALUES (?,?,?,?,?,?,?,?)', tuple(POSITION.values()))
    pnl.migrate(conn)
    quote = dict(mark=4.5, last_trade_at=NOW.isoformat(), source=pnl.SOURCE)
    pnl.save_quote(conn, POSITION, SESSION, quote, None, NOW.isoformat())
    conn.commit()
    return conn


def test_reconciles_contract_multiplier_ignores_legacy_marks_and_needs_no_prior_close():
    conn = fixture()
    before = conn.total_changes
    result = value_portfolio(conn, 10000., SESSION, NOW)
    assert result['complete']
    assert result['call_liability'] == 900.
    assert result['net_value'] == 9100.
    assert result['priced_count'] == 1
    assert conn.total_changes == before
    assert not result['reconciled_to_broker']


@pytest.mark.parametrize('mutation,reason', [
    ("DELETE FROM cc_daily_pnl_marks", 'MISSING_QUOTE'),
    ("UPDATE cc_daily_pnl_marks SET session='2026-11-04'", 'MISSING_QUOTE'),
    ("UPDATE cc_daily_pnl_marks SET observed_at='2026-11-05T14:00:00Z'", 'STALE_OPTION_QUOTE'),
    ("UPDATE cc_positions SET contracts=3", 'POSITION_CHANGED'),
    ("UPDATE cc_daily_pnl_marks SET quote_json='{}'", 'INVALID_OPTION_QUOTE'),
    ("UPDATE cc_daily_pnl_marks SET quote_json='invalid json'", 'Expecting value'),
])
def test_missing_failed_or_stale_quotes_cannot_become_zero_liabilities(mutation, reason):
    conn = fixture()
    conn.execute(mutation)
    result = value_portfolio(conn, 10000., SESSION, NOW)
    assert not result['complete']
    assert result['net_value'] is None
    assert result['call_liability'] is None
    assert reason in ' '.join(result['issues'])


def test_one_missing_call_invalidates_entire_net_not_just_missing_contract():
    conn = fixture()
    conn.execute("INSERT INTO cc_positions VALUES (2,'NFLX',1,73,'2026-12-18','2026-11-04','open',NULL)")
    result = value_portfolio(conn, 10000., SESSION, NOW)
    assert result['priced_count'] == 1
    assert result['open_count'] == 2
    assert result['net_value'] is None


def test_stock_session_and_missing_schema_fail_closed_but_empty_book_is_valid():
    conn = fixture()
    assert value_portfolio(conn, 10000., '2026-11-04', NOW)['net_value'] is None
    conn.execute('DELETE FROM cc_positions')
    assert value_portfolio(conn, 10000., SESSION, NOW)['net_value'] == 10000.
    conn.execute('DROP TABLE cc_positions')
    assert value_portfolio(conn, 10000., SESSION, NOW)['net_value'] is None


def test_history_outage_preserves_current_quote_without_fabricating_daily_pnl():
    frame = pd.DataFrame([dict(strike=100., contractSymbol='TEST261218C00100000',
                               bid=4., ask=5., lastTradeDate=pd.Timestamp(NOW))])
    class Ticker:
        def option_chain(self, expiry):
            return SimpleNamespace(calls=frame)
        def history(self, **kwargs):
            raise RuntimeError('history unavailable')
    quote, previous = pnl.fetch_quote(POSITION, SESSION, None, lambda _: Ticker(), lambda x:x)
    assert quote['mark'] == 4.5
    assert previous is None
    assert quote['error'] == 'PREVIOUS_CLOSE_UNAVAILABLE'
    conn = fixture()
    pnl.save_quote(conn, POSITION, SESSION, quote, None, NOW.isoformat())
    assert value_portfolio(conn, 10000., SESSION, NOW)['net_value'] == 9100.
    conn.row_factory = sqlite3.Row
    rec = dict(conn.execute('SELECT * FROM cc_daily_pnl_marks').fetchone())
    assert pnl.position_daily_pnl(POSITION, rec, NOW)['pnl_day'] is None


def test_client_expires_headline_and_shared_goal_value():
    source = (Path(__file__).resolve().parents[1] / 'static/portfolio_valuation.js').read_text()
    js = source + '''
const nodes = {'kpi-net-value':{}, 'kpi-net-status':{}};
global.document = {getElementById:id=>nodes[id]};
const d = {totalValue:9100,valuation:{complete:true,net_value:9100,valid_until:'2026-11-05T16:30:00Z'}};
if (expirePortfolioValuation(d, Date.parse('2026-11-05T16:29:59Z'))) throw Error('early expiry');
if (!expirePortfolioValuation(d, Date.parse('2026-11-05T16:30:00Z'))) throw Error('stale accepted');
if (d.totalValue !== null || d.valuation.net_value !== null || nodes['kpi-net-value'].textContent !== 'Unavailable') throw Error('stale total retained');
'''
    subprocess.run(['node', '-e', js], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("complete", [False, True])
def test_dashboard_fixture_uses_shared_nullable_net_and_emits_valid_javascript(tmp_path, monkeypatch, mem_db, complete):
    import re
    import generate_dashboard as dashboard
    holdings_csv = tmp_path / 'holdings.csv'
    holdings_csv.write_text('ticker,shares,layer\n')
    monkeypatch.setattr(dashboard, 'DB_PATH', mem_db)
    monkeypatch.setattr(dashboard, 'HOLDINGS_CSV', holdings_csv)
    monkeypatch.setattr(dashboard, 'load_csv_holdings', lambda: [])
    monkeypatch.setattr(dashboard, 'rebuild_today_holdings', lambda *args: ([], [], 10000.))
    if complete:
        import portfolio_valuation
        monkeypatch.setattr(portfolio_valuation, 'now_utc', lambda: NOW)
        source_conn = fixture()
        with sqlite3.connect(mem_db) as target:
            target.executescript('\n'.join(source_conn.iterdump()))
    page = dashboard.build_dashboard([dict(day=SESSION, total_value=10000., total_change_dollars=0., total_change_pct=0., spy_change_pct=0.)], [], [])
    assert ('id="kpi-net-value">$9,100.00' if complete else 'id="kpi-net-value">Unavailable') in page
    assert ('"totalValue": 9100.0' if complete else '"totalValue": null') in page
    assert '"grossStockValue": 10000.0' in page
    assert 'Stocks vs SPY' in page
    scripts = re.findall(r'<script(?![^>]*\bsrc\b)[^>]*>(.*?)</script>', page, re.S | re.I)
    for index, script in enumerate(scripts):
        path = tmp_path / f'fixture-{index}.js'
        path.write_text(script)
        checked = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize('quote_change,reason', [
    ({'mark':None}, 'INVALID_OPTION_QUOTE'),
    ({'mark':float('nan')}, 'INVALID_OPTION_QUOTE'),
    ({'mark':-1.}, 'INVALID_OPTION_QUOTE'),
    ({'source':'legacy'}, 'INVALID_OPTION_QUOTE'),
    ({'last_trade_at':'2026-11-05T14:00:00Z'}, 'STALE_OPTION_QUOTE'),
    ({'last_trade_at':'2026-11-05T16:05:00Z'}, 'STALE_OPTION_QUOTE'),
    ({'error':'QUOTE_FETCH_FAILED'}, 'QUOTE_FETCH_FAILED'),
])
def test_bad_quotes_fail_closed(quote_change, reason):
    conn = fixture()
    rec = conn.execute('SELECT quote_json FROM cc_daily_pnl_marks').fetchone()[0]
    quote = dict(json.loads(rec), **quote_change)
    conn.execute('UPDATE cc_daily_pnl_marks SET quote_json=?', (json.dumps(quote),))
    result = value_portfolio(conn, 10000., SESSION, NOW)
    assert result['net_value'] is None
    assert reason in ' '.join(result['issues'])


def test_refresh_reports_zero_bid_ask_without_overwriting_legacy_marks(tmp_path):
    path = tmp_path / 'marks.sqlite3'
    conn = fixture()
    with sqlite3.connect(path) as disk:
        conn.backup(disk)
    frame = pd.DataFrame([dict(strike=100., contractSymbol='TEST261218C00100000',
                               bid=0., ask=0., lastTradeDate=pd.Timestamp(NOW))])
    ticker = SimpleNamespace(option_chain=lambda expiry: SimpleNamespace(calls=frame))
    report = pnl.refresh_marks(path, ticker_factory=lambda _: ticker, clock=lambda: NOW)
    assert report['fetch_results'] == {'INVALID_OPTION_QUOTE':1}
    with sqlite3.connect(path) as disk:
        assert disk.execute('SELECT current_mark FROM cc_positions').fetchone()[0] == 999.
        assert value_portfolio(disk, 10000., SESSION, NOW)['net_value'] is None


def test_after_close_quotes_expire_at_next_open_not_midnight():
    conn = fixture()
    close = '2026-11-05T20:58:00Z'
    quote = dict(mark=4.5, last_trade_at=close, source=pnl.SOURCE)
    pnl.save_quote(conn, POSITION, SESSION, quote, None, '2026-11-05T21:05:00Z')
    now = datetime(2026,11,6,1,0,tzinfo=timezone.utc)
    result = value_portfolio(conn, 10000., SESSION, now)
    assert result['complete']
    assert result['valid_until'] == '2026-11-06T09:30:00-05:00'
    next_open = datetime(2026,11,6,14,30,tzinfo=timezone.utc)
    assert value_portfolio(conn, 10000., SESSION, next_open)['net_value'] is None


def test_unavailable_net_cannot_claim_zero_dollar_quarterly_goals_or_zero_capital_needed():
    source = (Path(__file__).resolve().parents[1] / 'generate_dashboard.py').read_text()
    start = source.index('function renderGoalsCard()')
    end = source.index('// Auto-load dividends', start)
    function = source[start:end].replace('{{', '{').replace('}}', '}')
    js = '''
const nodes = {};
const document = {getElementById:id=>nodes[id] ||= {style:{}}};
const D = {totalValue:null,grossStockValue:10000,layerColorsByNum:{}};
const CURRENT_BRACKET = {qualified:0,niit:0};
const _divData = {results:[{annual_income:1200,tax_type:'qualified'}]};
function effectiveRate(){return 0;}
function _flashEl(){}
''' + function + '''
renderGoalsCard();
const goals = nodes['goal-div-milestones'].innerHTML;
if (!goals.includes('Valuation unavailable')) throw Error('missing unavailable state');
if (goals.includes('deploy ~$0')) throw Error('fabricated zero capital recommendation');
if (nodes['goal-port-pct'].textContent !== 'Net value unavailable') throw Error('zero target progress');
'''
    subprocess.run(['node','-e',js], check=True, capture_output=True, text=True)
