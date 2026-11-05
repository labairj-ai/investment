"""Read-only historical stocks-less-calls estimates from dated source evidence.

Never rewrite stock snapshots, fills, decisions, learning labels or old quotes.
"""
import json
import math
from datetime import datetime, timezone

from covered_call_daily_pnl import number, position_identity, reporting_session, SOURCE
from portfolio_valuation import quote_records
from time_utils import parse_timestamp
from trade_engine.market_calendar import nth_trading_session_before


def rows(conn, table, query=None):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return []
    cur = conn.execute(query or 'SELECT * FROM '+table)
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur]


def contract(position):
    ticker = str(position['ticker']).upper().replace('/', '-').replace('.', '-')
    return ticker, str(position.get('expiry', position.get('expiration'))), round(float(position['strike']), 4)


def historical_values(conn, portfolio):
    positions = rows(conn, 'cc_positions')
    has_book = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='cc_positions'").fetchone())
    contracts = {contract(p) for p in positions}
    by_id = {p['id']:p for p in positions}
    evidence = {}

    def add(key, session, mark, basis, observed, reference, priority):
        mark = number(mark)
        if key not in contracts or mark is None:
            return
        stamp = parse_timestamp(observed)
        item = dict(mark=mark, basis=basis, observed_at=stamp.isoformat(), reference=reference)
        score = (priority, -stamp.timestamp())
        old = evidence.get((key, session))
        if old is None or score < old[0]:
            evidence[key,session] = (score,item)

    for r in quote_records(conn):
      try:
        p = by_id.get(r['position_id'])
        if p is None or r['position_identity'] != position_identity(p):
            continue
        key = contract(p)
        quote = json.loads(r['quote_json'])
        if not isinstance(quote,dict) or quote.get('source')!=SOURCE:
            continue
        reference = r.get('evidence_id') or f"cc_daily_pnl_marks:{p['id']}:{r['session']}"
        previous = nth_trading_session_before(r['session'], 1)
        if r['previous_session'] == previous and r.get('previous_close') is not None and quote.get('error') not in ('BASELINE_CONFLICT','POSITION_CHANGED'):
            add(key, previous, r['previous_close'], 'CONTRACT_DAILY_CLOSE', r['observed_at'], reference+':previous_close', 1)
        if quote.get('error') not in (None,'PREVIOUS_CLOSE_UNAVAILABLE'):
            continue
        if reporting_session(parse_timestamp(r['observed_at'])) != r['session']:
            continue
        basis = quote.get('mark_basis','STORED_MIDPOINT')
        mark=quote.get('mark')
        if basis=='BID_ASK_MIDPOINT':
            bid,ask=number(quote.get('bid')),number(quote.get('ask'))
            if bid is None or ask is None or ask<=0 or ask<bid:
                continue
            mark=(bid+ask)/2
        add(key, r['session'], mark, basis, r['observed_at'], reference, 0 if basis=='PROVIDER_MARK' else 2)
      except (ValueError,TypeError,KeyError,OverflowError):
        continue

    for r in rows(conn,'cc_display_historical_marks'):
      try:
        p=by_id.get(r['position_id'])
        if p is None or r['position_identity']!=position_identity(p):
            continue
        if r['source']!='YAHOO_CONTRACT_DAILY_CLOSE':
            continue
        add(contract(p),r['session'],r['mark'],'CONTRACT_DAILY_CLOSE',r['observed_at'],r['evidence_id'],1)
      except (ValueError,TypeError,KeyError,OverflowError):
        continue

    for r in rows(conn, 'option_quote_snapshots'):
      try:
        bid,ask = number(r['bid']),number(r['ask'])
        if bid is None or ask is None or ask<=0 or ask<bid:
            continue
        observed = datetime.fromtimestamp(float(r['captured_at']),timezone.utc)
        add(contract(r),reporting_session(observed),(bid+ask)/2,'BID_ASK_MIDPOINT',observed.isoformat(),f"option_quote_snapshots:{r['id']}",2)
      except (ValueError,TypeError,KeyError,OverflowError):
        continue

    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cc_decisions'").fetchone():
      for r in rows(conn,'cc_candidates', '''SELECT c.episode_id,c.candidate_id,c.features_json,d.ticker
          FROM cc_candidates c JOIN cc_decisions d ON d.id=c.episode_id WHERE d.prospective=1'''):
       try:
        q = json.loads(r['features_json'])
        if q.get('data_mode') != 'live' or not q.get('quote_timestamp'):
            continue
        bid,ask = number(q.get('bid')),number(q.get('ask'))
        if bid is None or ask is None or ask<=0 or ask<bid:
            continue
        observed = parse_timestamp(q['quote_timestamp'])
        key = contract(dict(ticker=r['ticker'],expiry=q['expiration'],strike=q['strike']))
        add(key,reporting_session(observed),(bid+ask)/2,'BID_ASK_MIDPOINT',observed.isoformat(),f"cc_candidates:{r['episode_id']}:{r['candidate_id']}",2)
       except (ValueError,TypeError,KeyError,OverflowError):
        continue

    result = []
    for row in portfolio:
        day = row['day']
        issues = [] if has_book else ['OPTION_BOOK_UNAVAILABLE']
        active = []
        for p in positions:
            opened = p.get('opened_date') or ''
            closed = p.get('closed_date')
            if opened <= day <= p['expiry'] and (not closed or day < closed):
                active.append(p)
                if p['status']!='open' and not closed:
                    issues.append(f"MISSING_CLOSE_DATE:{p['id']}")
        liability = 0.
        marks = []
        for p in active:
            item = evidence.get((contract(p),day))
            count = number(p['contracts'])
            if item is None or count is None or count<=0 or not count.is_integer():
                issues.append(f"MISSING_MARK:{p['id']}")
                continue
            item = dict(item[1],position_id=p['id'])
            liability += item['mark']*count*100
            marks.append(item)
        gross = number(row['total_value'])
        if gross is None or not math.isfinite(liability):
            issues.append('INVALID_VALUE')
        complete = not issues
        result.append(dict(day=day,gross_stock_value=gross,call_liability=round(liability,2) if complete else None,
                           net_value=round(gross-liability,2) if complete else None,
                           complete=complete,open_count=len(active),priced_count=len(marks),marks=marks,issues=issues))
    return result
