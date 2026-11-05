"""Explicit, append-only historical display marks; no portfolio/learning rewrites."""
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta

from covered_call_daily_pnl import number, position_identity, reporting_session
from time_utils import now_utc, TZ_EASTERN
from trade_engine.market_calendar import is_trading_day, nth_trading_session_before, session_close_time


def completed_session(now):
    local=now.astimezone(TZ_EASTERN)
    if is_trading_day(local.date()) and local.time().replace(tzinfo=None)<session_close_time(local.date()):
        return nth_trading_session_before(local.date().isoformat(),1)
    return reporting_session(now)


def collect(conn, ticker_factory, now=None):
    now=now or now_utc()
    first=conn.execute('SELECT min(day) FROM portfolio_day').fetchone()[0]
    end=completed_session(now)
    cur=conn.execute('SELECT * FROM cc_positions')
    columns=[d[0] for d in cur.description]
    positions=[dict(zip(columns,row)) for row in cur]
    observations=[];failures=[];cache={}
    for p in positions:
      try:
        start=max(first,p['opened_date'])
        stop=min(p['expiry'],end)
        if p.get('closed_date'):
            stop=min(stop,(date.fromisoformat(p['closed_date'])-timedelta(days=1)).isoformat())
        if start>stop:
            continue
        root=str(p['ticker']).upper().replace('/','').replace('-','').replace('.','')
        symbol=root+date.fromisoformat(p['expiry']).strftime('%y%m%d')+'C'+f"{round(float(p['strike'])*1000):08d}"
        key=(symbol,start,stop)
        if key not in cache:
            cache[key]=ticker_factory(symbol).history(start=start,end=(date.fromisoformat(stop)+timedelta(days=1)).isoformat(),
                                                       interval='1d',auto_adjust=False,actions=False,timeout=8)
        history=cache[key]
        found=0
        for index,bar in history.iterrows():
            stamp=index.to_pydatetime() if hasattr(index,'to_pydatetime') else index
            if stamp.tzinfo is None:
                continue
            day=stamp.astimezone(TZ_EASTERN).date().isoformat()
            mark,volume=number(bar.get('Close')),number(bar.get('Volume'))
            if not start<=day<=stop or not is_trading_day(date.fromisoformat(day)) or mark is None or mark<=0 or volume is None or volume<=0:
                continue
            source=dict(symbol=symbol,session=day,close=mark,volume=volume,position_id=p['id'],position_identity=position_identity(p))
            evidence_id=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            observations.append(dict(evidence_id=evidence_id,position_id=p['id'],session=day,mark=mark,
                                     source='YAHOO_CONTRACT_DAILY_CLOSE',observed_at=now.isoformat(),
                                     position_identity=position_identity(p),source_json=json.dumps(source,sort_keys=True)))
            found+=1
        if not found:
            failures.append(dict(position_id=p['id'],reason='NO_DATED_CONTRACT_BARS'))
      except Exception as error:
        failures.append(dict(position_id=p['id'],reason=type(error).__name__))
    return dict(completed_session=end,observations=observations,failures=failures)


def apply(conn, observations):
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS cc_display_historical_marks(
          evidence_id TEXT PRIMARY KEY, position_id INTEGER NOT NULL, session TEXT NOT NULL,
          mark REAL NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL,
          position_identity TEXT NOT NULL, source_json TEXT NOT NULL)''')
        before=conn.total_changes
        for r in observations:
            conn.execute('INSERT OR IGNORE INTO cc_display_historical_marks VALUES(?,?,?,?,?,?,?,?)',
                         tuple(r[k] for k in ['evidence_id','position_id','session','mark','source','observed_at','position_identity','source_json']))
        inserted=conn.total_changes-before
        conn.commit()
        return inserted
    except Exception:
        conn.rollback();raise
