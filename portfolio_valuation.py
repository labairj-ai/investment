"""Read-only valuation of tracked stocks less verified short-call liabilities.

This is a market-data estimate, excluding cash and untracked instruments.
Legacy current_mark values alone are never sufficient evidence.
"""
import json
import sqlite3
from datetime import date, datetime, time, timedelta

from covered_call_daily_pnl import (
    MAX_TRADE_LAG_SECONDS, SOURCE, number, position_identity, reporting_session,
)
from time_utils import TZ_EASTERN, now_utc, parse_timestamp
from trade_engine.market_calendar import session_close_time, is_trading_day


def verified_mark(position, record, session, now):
    if record is None:
        raise ValueError('MISSING_QUOTE')
    if record['session'] != session:
        raise ValueError('STALE_SESSION')
    if record['position_identity'] != position_identity(position):
        raise ValueError('POSITION_CHANGED')
    quote = json.loads(record['quote_json'])
    if not isinstance(quote, dict):
        raise ValueError('INVALID_OPTION_QUOTE')
    mark = number(quote.get('mark'))
    # A previous-close failure affects daily P&L, not a valid current midpoint.
    if quote.get('error') not in (None, 'PREVIOUS_CLOSE_UNAVAILABLE'):
        raise ValueError(quote['error'])
    if mark is None or quote.get('source') != SOURCE:
        raise ValueError('INVALID_OPTION_QUOTE')
    contracts = number(position['contracts'])
    if contracts is None or contracts <= 0 or not contracts.is_integer():
        raise ValueError('INVALID_CONTRACT_COUNT')
    if date.fromisoformat(position['expiry']).isoformat() < session:
        raise ValueError('EXPIRED_POSITION_UNRESOLVED')
    if date.fromisoformat(position['opened_date']).isoformat() > session:
        raise ValueError('FUTURE_POSITION')
    day = date.fromisoformat(session)
    opened = datetime.combine(day, time(9, 30), TZ_EASTERN)
    closed = datetime.combine(day, session_close_time(day), TZ_EASTERN)
    reference = min(now, closed)
    traded = parse_timestamp(quote['last_trade_at'])
    observed = parse_timestamp(record['observed_at'])
    for stamp, latest in ((traded, reference), (observed, now)):
        if stamp < opened or stamp > latest + timedelta(seconds=5) or (reference-stamp).total_seconds() > MAX_TRADE_LAG_SECONDS:
            raise ValueError('STALE_OPTION_QUOTE')
    if now < closed:
        valid_until = min(traded, observed) + timedelta(seconds=MAX_TRADE_LAG_SECONDS)
    else:
        next_day = day + timedelta(days=1)
        while not is_trading_day(next_day):
            next_day += timedelta(days=1)
        valid_until = datetime.combine(next_day, time(9, 30), TZ_EASTERN)
    return mark * contracts * 100, observed.isoformat(), valid_until.isoformat()


def value_portfolio(conn, gross_value, stock_session, now=None):
    """No migrations, writes, network calls, or fallback to entry premiums."""
    now = now or now_utc()
    gross_value = number(gross_value)
    session = reporting_session(now)
    result = dict(gross_stock_value=gross_value, net_value=None, call_liability=None,
                  complete=False, session=session, stock_session=stock_session,
                  open_count=0, priced_count=0, issues=[], observations=[],
                  reconciled_to_broker=False, source=SOURCE, valid_until=None)
    if number(gross_value) is None:
        result['issues'].append('INVALID_STOCK_VALUE')
    if stock_session != session:
        result['issues'].append('STOCK_SESSION_MISMATCH')
    try:
        cur = conn.execute("SELECT * FROM cc_positions WHERE status='open'")
        columns = [d[0] for d in cur.description]
        positions = [dict(zip(columns, row)) for row in cur]
        result['open_count'] = len(positions)
        records = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='cc_daily_pnl_marks' AND type='table'").fetchone():
            cur = conn.execute('SELECT * FROM cc_daily_pnl_marks WHERE session=?', (session,))
            columns = [d[0] for d in cur.description]
            records = {r['position_id']: r for r in (dict(zip(columns, row)) for row in cur)}
        liability = 0.0
        deadlines = []
        for position in positions:
            try:
                value, observed, deadline = verified_mark(position, records.get(position['id']), session, now)
                liability += value
                result['observations'].append(observed)
                deadlines.append(deadline)
                result['priced_count'] += 1
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                result['issues'].append(f"{position['ticker']} #{position['id']}: {error}")
        if not result['issues']:
            result.update(complete=True, call_liability=round(liability, 2),
                          net_value=round(gross_value-liability, 2),
                          valid_until=min(deadlines, key=parse_timestamp) if deadlines else None)
    except sqlite3.Error:
        result['issues'].append('OPTION_DATA_UNAVAILABLE')
    return result
