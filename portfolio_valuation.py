"""Read-only valuation of tracked stocks less verified short-call liabilities.

This is a market-data estimate, excluding cash and untracked instruments.
Legacy current_mark values alone are never sufficient evidence.
"""
import json
import math
import sqlite3
import re
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
    from cc_broker_quotes import SOURCE as BROKER_SOURCE
    broker = quote.get('source') == BROKER_SOURCE
    if broker and (quote.get('mark_basis') != 'BID_ASK_MIDPOINT' or
                   not re.fullmatch('[a-f0-9]{64}', str(quote.get('evidence_sha256', ''))) or
                   parse_timestamp(quote.get('quoted_at')) != parse_timestamp(record['observed_at'])):
        raise ValueError('INVALID_BROKER_EVIDENCE')
    if mark is None or quote.get('source') not in {SOURCE, BROKER_SOURCE}:
        raise ValueError('INVALID_OPTION_QUOTE')
    if quote.get('mark_basis') == 'BID_ASK_MIDPOINT':
        bid, ask = number(quote.get('bid')), number(quote.get('ask'))
        if bid is None or ask is None or ask <= 0 or ask < bid:
            raise ValueError('INVALID_OPTION_QUOTE')
        mark = (bid+ask)/2
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
    observed = parse_timestamp(record['observed_at'])
    if broker and not opened <= observed <= closed:
        raise ValueError('BROKER_QUOTE_OUTSIDE_SESSION')
    if observed < opened or observed > now + timedelta(seconds=5) or (reference-observed).total_seconds() > MAX_TRADE_LAG_SECONDS:
        raise ValueError('STALE_OPTION_QUOTE')
    if now < closed:
        valid_until = observed + timedelta(seconds=MAX_TRADE_LAG_SECONDS)
    else:
        next_day = day + timedelta(days=1)
        while not is_trading_day(next_day):
            next_day += timedelta(days=1)
        valid_until = datetime.combine(next_day, time(9, 30), TZ_EASTERN)
    value=mark*contracts*100
    if not math.isfinite(value):
        raise ValueError('INVALID_OPTION_VALUE')
    return value, observed.isoformat(), valid_until.isoformat()


def quote_records(conn, session=None):
    records = []
    for table in ('cc_daily_pnl_marks', 'cc_display_quote_observations'):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (table,)).fetchone():
            continue
        cur = conn.execute('SELECT * FROM '+table+(' WHERE session=?' if session else ''),
                           (session,) if session else ())
        columns = [d[0] for d in cur.description]
        records.extend(dict(zip(columns, row)) for row in cur)
    return records


def value_portfolio(conn, gross_value, stock_session, now=None, *, broker_quotes=()):
    """No migrations, writes, network calls, or fallback to entry premiums."""
    now = now or now_utc()
    gross_value = number(gross_value)
    session = reporting_session(now)
    snapshot_day = stock_session
    try:
        labelled = date.fromisoformat(stock_session)
        local = now.astimezone(TZ_EASTERN)
        reference = now if labelled==local.date() else datetime.combine(labelled,time(16),TZ_EASTERN)
        # Newsletter rows are labelled by generation day, including premarket
        # and weekends; their regular-session prices belong to the prior session.
        stock_session = reporting_session(reference)
    except (TypeError,ValueError):
        stock_session = None
    result = dict(gross_stock_value=gross_value, net_value=None, call_liability=None,
                  complete=False, session=session, stock_session=stock_session,
                  stock_snapshot_day=snapshot_day,
                  open_count=0, priced_count=0, issues=[], observations=[],
                  reconciled_to_broker=False, source=SOURCE, valid_until=None, broker_quote_positions=[])
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
        for r in [*quote_records(conn, session), *broker_quotes]:
            if r.get('session') != session:
                continue
            records.setdefault(r['position_id'], []).append(r)
        liability = 0.0
        deadlines = []
        for position in positions:
            def priority(record):
                try:
                    q = json.loads(record['quote_json'])
                    return (2 if q.get('source') != SOURCE else
                            0 if q.get('mark_basis') == 'PROVIDER_MARK' else 1,
                            -parse_timestamp(record['observed_at']).timestamp())
                except (ValueError,TypeError,AttributeError):
                    return (2,0)
            candidates = sorted(records.get(position['id'], []),key=priority)
            issue = 'MISSING_QUOTE'
            for record in candidates:
                try:
                    value, observed, deadline = verified_mark(position, record, session, now)
                    liability += value
                    result['observations'].append(observed)
                    deadlines.append(deadline)
                    result['priced_count'] += 1
                    if json.loads(record['quote_json']).get('source') != SOURCE:
                        result['broker_quote_positions'].append(f"{position['ticker']} #{position['id']}")
                    break
                except (ValueError, TypeError, KeyError, OverflowError) as error:
                    issue = str(error)
            else:
                result['issues'].append(f"{position['ticker']} #{position['id']}: {issue}")
        if not result['issues']:
            result.update(complete=True, call_liability=round(liability, 2),
                          net_value=round(gross_value-liability, 2),
                          valid_until=min(deadlines, key=parse_timestamp) if deadlines else None)
    except sqlite3.Error:
        result['issues'].append('OPTION_DATA_UNAVAILABLE')
    return result
