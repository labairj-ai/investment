"""Broker fallback is dated display evidence, never a position or baseline update."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from cc_broker_quotes import prepare, append, load, SOURCE
from covered_call_daily_pnl import migrate, save_quote, SOURCE as FEED
from portfolio_valuation import value_portfolio, verified_mark
from scripts.import_cc_broker_quote import run

NOW = datetime(2026, 11, 12, 23, 45, tzinfo=timezone.utc)
POSITION = dict(id=67, ticker='TEST-B', strike=605.0, expiry='2026-12-31', contracts=1,
                opened_date='2026-11-12', status='open')
INPUT = dict(position_id=67, ticker='TEST-B', strike=605.0, expiry='2026-12-31', contracts=1,
             opened_date='2026-11-12', bid=7.80, ask=10.95, quoted_at='2026-11-12T16:00:00-05:00',
             evidence_sha256='a' * 64)


def database():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE cc_positions (id,ticker,strike,expiry,contracts,opened_date,status)')
    conn.execute('INSERT INTO cc_positions VALUES (?,?,?,?,?,?,?)', tuple(POSITION.values()))
    migrate(conn)
    save_quote(conn, POSITION, '2026-11-12', {'error':'QUOTE_FETCH_FAILED', 'source':FEED}, None, NOW.isoformat())
    conn.commit()
    return conn


def test_missing_contract_is_completed_from_exact_dated_broker_spread_without_db_write():
    conn = database()
    before = conn.total_changes
    assert value_portfolio(conn, 10000, '2026-11-12', NOW)['net_value'] is None
    record = prepare(POSITION, INPUT, NOW)
    result = value_portfolio(conn, 10000, '2026-11-12', NOW, broker_quotes=[record])
    assert result['complete'] and result['call_liability'] == 937.50
    assert result['net_value'] == 9062.50
    assert result['broker_quote_positions'] == ['TEST-B #67']
    assert result['valid_until'] == '2026-11-13T09:30:00-05:00'
    assert conn.total_changes == before
    assert not result['reconciled_to_broker']
    # Same evidence cannot be carried into the next session or change position identity.
    next_open = datetime(2026, 11, 13, 14, 30, tzinfo=timezone.utc)
    assert value_portfolio(conn, 10000, '2026-11-13', next_open, broker_quotes=[record])['net_value'] is None
    conn.execute('UPDATE cc_positions SET contracts=2')
    assert value_portfolio(conn, 10000, '2026-11-12', NOW, broker_quotes=[record])['net_value'] is None


@pytest.mark.parametrize('change', [dict(bid=-1), dict(ask=0), dict(bid=11), dict(bid=True),
    dict(ask=float('nan')), dict(quoted_at='2026-11-12T16:00:00'),
    dict(quoted_at='2026-11-13T16:00:00-05:00'), dict(evidence_sha256=''),
    dict(expiry='2026-12-18'), dict(contracts=2), dict(ticker='WRONG')])
def test_invalid_import_is_rejected(change):
    with pytest.raises((ValueError, KeyError)):
        prepare(POSITION, dict(INPUT, **change), NOW)


def test_stale_and_outside_session_broker_quotes_do_not_get_new_retrieval_time():
    old = prepare(POSITION, dict(INPUT, quoted_at='2026-11-12T10:00:00-05:00'), NOW)
    with pytest.raises(ValueError, match='STALE_OPTION_QUOTE'):
        verified_mark(POSITION, old, '2026-11-12', NOW)
    evening = prepare(POSITION, dict(INPUT, quoted_at='2026-11-12T18:00:00-05:00'), NOW)
    with pytest.raises(ValueError, match='BROKER_QUOTE_OUTSIDE_SESSION'):
        verified_mark(POSITION, evening, '2026-11-12', NOW)


def test_valid_feed_quote_takes_precedence_but_later_feed_failure_cannot_erase_broker_evidence():
    conn = database()
    broker = prepare(POSITION, INPUT, NOW)
    save_quote(conn, POSITION, '2026-11-12', dict(mark=8, source=FEED), None, '2026-11-12T21:00:00Z')
    report = value_portfolio(conn, 10000, '2026-11-12', NOW, broker_quotes=[broker])
    assert report['net_value'] == 9200
    assert report['broker_quote_positions'] == []


def test_import_dry_run_and_apply_only_write_display_artifacts(tmp_path):
    db = tmp_path / 'investment.db'
    conn = database()
    with sqlite3.connect(db) as target:
        conn.backup(target)
    before = db.read_bytes()
    quotes = tmp_path / 'cc-broker-quotes.json'
    snapshot = tmp_path / 'portfolio-valuation.json'
    initial = dict(gross_stock_value=10000, stock_session='2026-11-12', stock_snapshot_day='2026-11-12')
    snapshot.write_text(json.dumps(initial))
    dry = run(db, INPUT, quotes, snapshot, now=NOW)
    assert dry['valuation']['net_value'] == 9062.50
    assert not quotes.exists() and json.loads(snapshot.read_text()) == initial
    assert db.read_bytes() == before
    applied = run(db, INPUT, quotes, snapshot, now=NOW, apply=True)
    assert applied['inserted'] and json.loads(snapshot.read_text())['net_value'] == 9062.50
    assert json.loads(load(quotes)[0]['quote_json'])['source'] == SOURCE
    assert db.read_bytes() == before
    # Reimport cannot refresh quote time or create a new identical observation.
    again = run(db, INPUT, quotes, snapshot, now=NOW + timedelta(minutes=1), apply=True)
    assert not again['inserted'] and len(load(quotes)) == 1
    assert load(quotes)[0]['observed_at'] == '2026-11-12T21:00:00+00:00'


def test_broker_provenance_is_required_even_for_direct_records():
    record = prepare(POSITION, INPUT, NOW)
    quote = json.loads(record['quote_json'])
    quote['evidence_sha256'] = ''
    record['quote_json'] = json.dumps(quote)
    with pytest.raises(ValueError, match='INVALID_BROKER_EVIDENCE'):
        verified_mark(POSITION, record, '2026-11-12', NOW)
