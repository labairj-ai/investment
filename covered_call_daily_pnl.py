"""Dated, fail-closed display estimates for tracked covered calls, not trading inputs."""
from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timedelta

from time_utils import TZ_EASTERN, now_utc, parse_timestamp
from trade_engine.market_calendar import is_trading_day, nth_trading_session_before, session_close_time

MAX_TRADE_LAG_SECONDS = 1800
SOURCE = 'YAHOO_CHAIN_MIDPOINT_VS_DAILY_CLOSE'


def reporting_session(now):
    local = now.astimezone(TZ_EASTERN)
    day = local.date()
    if is_trading_day(day) and local.time().replace(tzinfo=None) >= time(9, 30):
        return day.isoformat()
    day -= timedelta(days=1)
    for _ in range(14):
        if is_trading_day(day):
            return day.isoformat()
        day -= timedelta(days=1)
    raise ValueError('TRADING_SESSION_UNAVAILABLE')


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def position_identity(position):
    return json.dumps([position['ticker'], position['strike'], position['expiry'],
                       position['contracts'], position.get('opened_date')], separators=(',', ':'))


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS cc_daily_pnl_marks (
        position_id INTEGER NOT NULL, session TEXT NOT NULL,
        previous_session TEXT NOT NULL, previous_close REAL,
        quote_json TEXT NOT NULL, observed_at TEXT NOT NULL, position_identity TEXT NOT NULL,
        PRIMARY KEY(position_id, session))''')


def save_quote(conn, position, session, quote, previous_close, observed_at):
    position_id = position["id"]
    identity = position_identity(position)
    previous = nth_trading_session_before(session, 1)
    old = conn.execute('SELECT previous_close, position_identity FROM cc_daily_pnl_marks WHERE position_id=? AND session=?',
                       (position_id, session)).fetchone()
    if old and old[1] != identity:
        quote = dict(quote, error='POSITION_CHANGED')
    if old and old[0] is not None and previous_close is not None and abs(old[0]-previous_close) > 0.000001:
        quote = dict(quote, error='BASELINE_CONFLICT')
    cursor = conn.execute('''INSERT INTO cc_daily_pnl_marks VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(position_id,session) DO UPDATE SET
        previous_close=COALESCE(cc_daily_pnl_marks.previous_close,excluded.previous_close),
        quote_json=excluded.quote_json, observed_at=excluded.observed_at
        WHERE julianday(excluded.observed_at) >= julianday(cc_daily_pnl_marks.observed_at)''',
        (position_id, session, previous, previous_close, json.dumps(quote, allow_nan=False), observed_at, identity))
    return cursor.rowcount > 0


def fetch_quote(position, session, previous_close, ticker_factory, normalize):
    """Require actual contract identity and the exact preceding session's daily bar."""
    ticker = ticker_factory(normalize(position['ticker']))
    calls = ticker.option_chain(position['expiry']).calls
    match = calls[abs(calls['strike']-position['strike']) < 0.01]
    if len(match) != 1:
        raise ValueError('OPTION_CONTRACT_UNAVAILABLE')
    row = match.iloc[0]
    bid, ask = number(row.get('bid')), number(row.get('ask'))
    if bid is None or ask is None or ask < bid or ask <= 0:
        raise ValueError('INVALID_OPTION_QUOTE')
    symbol = str(row['contractSymbol'])
    traded = row.get('lastTradeDate')
    if hasattr(traded, 'to_pydatetime'):
        traded = traded.to_pydatetime()
    traded = parse_timestamp(traded)
    quote = dict(mark=(bid+ask)/2, last_trade_at=traded.isoformat(), contract_symbol=symbol, source=SOURCE)
    if previous_close is None:
        previous = nth_trading_session_before(session, 1)
        history = ticker_factory(symbol).history(start=previous, end=session, interval='1d',
                                                 auto_adjust=False, actions=False, timeout=8)
        matches = []
        for index, bar in history.iterrows():
            stamp = index.to_pydatetime() if hasattr(index, 'to_pydatetime') else index
            if stamp.tzinfo is None:
                raise ValueError('AMBIGUOUS_PREVIOUS_CLOSE_DATE')
            if stamp.astimezone(TZ_EASTERN).date().isoformat() == previous:
                close, volume = number(bar.get('Close')), number(bar.get('Volume'))
                if close is not None and volume is not None and volume > 0:
                    matches.append(close)
        if len(matches) != 1:
            quote['error'] = 'PREVIOUS_CLOSE_UNAVAILABLE'
        else:
            previous_close = matches[0]
    return quote, previous_close


def refresh_marks(path, ticker_factory=None, normalize=lambda ticker: ticker, clock=now_utc):
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    now = clock()
    session = reporting_session(now)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        migrate(conn)
        conn.commit()
        positions = [dict(row) for row in conn.execute("SELECT * FROM cc_positions WHERE status='open'")]
        results = Counter()
        cache = {}
        pending = []
        for position in positions:
            old = conn.execute('SELECT previous_close, position_identity FROM cc_daily_pnl_marks WHERE position_id=? AND session=?',
                               (position['id'], session)).fetchone()
            prior = old[0] if old else None
            key = (position['ticker'], position['expiry'], position['strike'], prior)
            try:
                if key not in cache:
                    cache[key] = fetch_quote(position, session, prior, ticker_factory, normalize)
                quote, baseline = cache[key]
            except Exception:
                # Never fabricate zero, use entry premium, or roll the baseline on errors.
                quote, baseline = {'error':'QUOTE_FETCH_FAILED', 'source':SOURCE}, prior
            pending.append((position, quote, baseline, clock().isoformat()))
            results[quote.get('error', 'FETCHED')] += 1
        # Network calls complete before any write transaction starts. Keep the
        # production database available to the dashboard and other scheduled jobs.
        for position, quote, baseline, observed in pending:
            applied = save_quote(conn, position, session, quote, baseline, observed)
            mark = number(quote.get('mark'))
            if applied and mark is not None:
                # Preserve legacy prev_mark; it is not a daily-close baseline.
                conn.execute("""UPDATE cc_positions SET current_mark=? WHERE id=? AND status='open'
                    AND ticker=? AND strike=? AND expiry=? AND contracts=?""",
                    (mark, position['id'], position['ticker'], position['strike'], position['expiry'], position['contracts']))
        conn.commit()
        return dict(session=session, positions=len(positions), fetch_results=dict(results))
    finally:
        conn.close()


def position_daily_pnl(position, record, now):
    session = reporting_session(now)
    result = dict(pnl_day=None, pnl_day_status='UNVERIFIED_LEGACY_MARK', pnl_day_session=session,
                  pnl_day_as_of=None, pnl_day_observed_at=None, pnl_day_previous_session=None,
                  pnl_day_source=SOURCE)
    if record is None:
        return result
    result.update(pnl_day_observed_at=record['observed_at'], pnl_day_previous_session=record['previous_session'])
    try:
        quote = json.loads(record['quote_json'])
        result['pnl_day_as_of'] = quote.get('last_trade_at')
        if record['session'] != session:
            raise ValueError('STALE_SESSION')
        if quote.get('error'):
            raise ValueError(quote['error'])
        if record['position_identity'] != position_identity(position):
            raise ValueError('POSITION_CHANGED')
        try:
            entry_date = date.fromisoformat(position.get('opened_date', ''))
        except (ValueError, TypeError):
            raise ValueError('OPEN_DATE_UNAVAILABLE')
        if entry_date.isoformat() >= session:
            raise ValueError('OPENED_THIS_SESSION')
        if record['previous_session'] != nth_trading_session_before(session, 1):
            raise ValueError('WRONG_PREVIOUS_SESSION')
        prior, mark = number(record['previous_close']), number(quote.get('mark'))
        if prior is None:
            raise ValueError('PREVIOUS_CLOSE_UNAVAILABLE')
        if mark is None or quote.get('source') != SOURCE:
            raise ValueError('INVALID_OPTION_QUOTE')
        traded = parse_timestamp(quote['last_trade_at'])
        observed = parse_timestamp(record['observed_at'])
        day = date.fromisoformat(session)
        opened = datetime.combine(day, time(9,30), TZ_EASTERN)
        closed = datetime.combine(day, session_close_time(day), TZ_EASTERN)
        reference = min(now, closed)
        # A recent trade is only a conservative activity/freshness check. The
        # midpoint was observed at fetch time; it has no exchange quote timestamp.
        if traded < opened or traded > reference + timedelta(seconds=5) or (reference-traded).total_seconds() > MAX_TRADE_LAG_SECONDS:
            raise ValueError('STALE_OPTION_QUOTE')
        if observed > now + timedelta(seconds=5) or observed < opened or (reference-observed).total_seconds() > MAX_TRADE_LAG_SECONDS:
            raise ValueError('STALE_OPTION_OBSERVATION')
        contracts = number(position.get('contracts'))
        if contracts is None or contracts <= 0:
            raise ValueError('INVALID_CONTRACT_COUNT')
        result.update(pnl_day=round((prior-mark)*contracts*100,2), pnl_day_status='ESTIMATED')
    except (ValueError, KeyError, TypeError) as error:
        result['pnl_day_status'] = str(error) if isinstance(error, ValueError) else 'INVALID_MARK_RECORD'
    return result


def annotate_positions(conn, positions, now=None):
    now = now or now_utc()
    session = reporting_session(now)
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cc_daily_pnl_marks'").fetchone()
    records = {}
    if exists:
        for row in conn.execute('SELECT * FROM cc_daily_pnl_marks ORDER BY session DESC'):
            records.setdefault(row['position_id'], dict(row))
    for position in positions:
        if position['status'] != 'open':
            position['pnl_day'] = None
    open_positions = [p for p in positions if p['status']=='open']
    for p in open_positions:
        p.update(position_daily_pnl(p, records.get(p['id']), now))
    priced = [p for p in open_positions if p['pnl_day'] is not None]
    closed_today = sum(p['status']!='open' and p.get('closed_date')==session for p in positions)
    complete = len(priced)==len(open_positions) and not closed_today
    return dict(session=session, open_count=len(open_positions), priced_count=len(priced),
                options_pnl=round(sum(p['pnl_day'] for p in priced),2) if complete else None,
                partial_options_pnl=round(sum(p['pnl_day'] for p in priced),2) if priced else None,
                complete=complete, closed_this_session=closed_today,
                statuses=dict(Counter(p['pnl_day_status'] for p in open_positions)),
                source=SOURCE, reconciled_to_broker=False)
