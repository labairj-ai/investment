"""Serialized inventory transactions with a durable, recoverable CSV projection."""
from __future__ import annotations

import csv
import fcntl
import io
import json
import math
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from portfolio_positions import _normalize
from strategy_config import LAYER_LABELS
from tax_utils import is_long_term
from time_utils import today_eastern


class ProjectionPending(RuntimeError):
    """Inventory committed; retry with this mutation ID, never repeat blindly."""
    def __init__(self, mutation_id):
        self.mutation_id = mutation_id
        super().__init__('Inventory committed; CSV projection pending. Retry with request_id=' + mutation_id)


def number(value, label, *, zero=False):
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(label + ' must be numeric')
    if not math.isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(label + ' must be finite and ' + ('nonnegative' if zero else 'positive'))
    return value


def purchase_day(value):
    try:
        day = date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ValueError('purchase_date must be YYYY-MM-DD')
    if day > today_eastern():
        raise ValueError('purchase_date cannot be in the future')
    return day.isoformat()


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _csv_text(root, conn, ticker, layer_override=None):
    path = root / 'holdings.csv'
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    if not fields or not {'Stock','Shares','AvgCost','Layer'} <= set(fields):
        raise ValueError('holdings.csv requires Stock, Shares, AvgCost, Layer')
    old = next((r for r in rows if _normalize(r['Stock']) == ticker), None)
    rows = [r for r in rows if _normalize(r['Stock']) != ticker]
    lots = conn.execute('SELECT shares,cost_per_share,purchase_date FROM cost_lots WHERE ticker=? ORDER BY purchase_date,id', (ticker,)).fetchall()
    shares = sum(r['shares'] for r in lots)
    if shares > 1e-6:
        layer = str(layer_override or 3)
        if old:
            layer = old['Layer']
        else:
            row = conn.execute('SELECT layer FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 1', (ticker,)).fetchone()
            if row:
                layer = str(next((k for k,v in LAYER_LABELS.items() if v == row[0]),3))
        item = dict(old or {}, Stock=ticker, Shares=str(round(shares,6)),
                    AvgCost=str(round(sum(r['shares']*r['cost_per_share'] for r in lots)/shares,8)), Layer=layer)
        if 'PurchaseDate' in fields:
            item['PurchaseDate'] = lots[0]['purchase_date']
        rows.append({k:item.get(k,'') for k in fields})
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def _atomic_csv(path, content):
    descriptor, temp = tempfile.mkstemp(prefix='.holdings-', dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',newline='') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _flush(root, conn):
    for row in conn.execute('SELECT id,csv_text FROM portfolio_mutation_receipts WHERE projected=0 ORDER BY rowid').fetchall():
        try:
            _atomic_csv(root/'holdings.csv',row['csv_text'])
        except OSError as error:
            raise ProjectionPending(row['id']) from error
        conn.execute('UPDATE portfolio_mutation_receipts SET projected=1 WHERE id=?',(row['id'],))
        conn.commit()


@contextmanager
def _locked(root):
    root = Path(root)
    with (root/'out/portfolio-mutations.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        conn = sqlite3.connect(root/'out/investment.db',timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('''CREATE TABLE IF NOT EXISTS portfolio_mutation_receipts
                (id TEXT PRIMARY KEY, request_json TEXT NOT NULL, result_json TEXT NOT NULL,
                 csv_text TEXT NOT NULL, projected INTEGER NOT NULL DEFAULT 0)''')
            conn.execute('CREATE TABLE IF NOT EXISTS portfolio_inventory_quotes (ticker TEXT,day TEXT,snapshot_json TEXT NOT NULL,PRIMARY KEY(ticker,day))')
            conn.commit()
            _flush(root,conn)
            conn.execute('BEGIN IMMEDIATE')
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _snapshot(conn, ticker, since):
    """Rebuild existing dated rows from acquisitions minus the surviving sale ledger."""
    tables = _tables(conn)
    if 'holding_day' not in tables:
        return
    lots = {}
    for row in conn.execute('SELECT * FROM cost_lots WHERE ticker=?',(ticker,)):
        lots[(row['id'],row['purchase_date'],row['cost_per_share'])] = float(row['shares'])
    sales = []
    for row in conn.execute('SELECT sell_date,fifo_detail FROM sell_transactions WHERE ticker=?',(ticker,)):
        for allocation in json.loads(row['fifo_detail'] or '[]'):
            key = (allocation['lot_id'],allocation['purchase_date'],allocation['cost_per_share'])
            lots[key] = lots.get(key,0) + allocation['shares']
            sales.append((row['sell_date'],key,allocation['shares']))
    today = today_eastern().isoformat()
    for row in conn.execute('SELECT * FROM holding_day WHERE ticker=?',(ticker,)).fetchall():
        conn.execute('INSERT OR REPLACE INTO portfolio_inventory_quotes VALUES(?,?,?)',(ticker,row['day'],json.dumps(dict(row))))
    preserved = {r['day']:json.loads(r['snapshot_json']) for r in conn.execute('SELECT * FROM portfolio_inventory_quotes WHERE ticker=?',(ticker,))}
    # Preserve the last available quote before changing any rows.
    last = conn.execute('SELECT * FROM holding_day WHERE ticker=? AND day<=? ORDER BY day DESC LIMIT 1',(ticker,today)).fetchone()
    if last is None and preserved:
        last = preserved[max(preserved)]
    days = {r[0] for r in conn.execute('SELECT DISTINCT day FROM holding_day WHERE day>=? AND day<=?',(since,today))}
    days.update(d for d in preserved if since <= d <= today)
    if last:
        days.add(today)
    for day in sorted(days):
        qty = sum(q for (_,purchased,_),q in lots.items() if purchased <= day)
        qty -= sum(q for sold,key,q in sales if sold <= day and key[1] <= day)
        existing = conn.execute('SELECT * FROM holding_day WHERE ticker=? AND day=?',(ticker,day)).fetchone()
        row = existing or preserved.get(day)
        if qty < 1e-6:
            conn.execute('DELETE FROM holding_day WHERE ticker=? AND day=?',(ticker,day))
        elif existing:
            prior_qty = row['shares'] or 0
            change = (row['change_dollars'] or 0)*qty/prior_qty if prior_qty else 0
            conn.execute('UPDATE holding_day SET shares=?,value=?,change_dollars=? WHERE ticker=? AND day=?',
                         (qty,qty*row['price'],change,ticker,day))
        elif row or (day == today and last):
            last_quote = row or last
            conn.execute('''INSERT INTO holding_day(day,ticker,layer,shares,price,value,change_dollars,change_pct,weight_pct)
                VALUES(?,?,?,?,?,?,0,0,0)''',(day,ticker,last_quote['layer'],qty,last_quote['price'],qty*last_quote['price']))
        total = conn.execute('SELECT COALESCE(SUM(value),0),COALESCE(SUM(change_dollars),0) FROM holding_day WHERE day=?',(day,)).fetchone()
        conn.execute('UPDATE holding_day SET weight_pct=CASE WHEN ? > 0 THEN value*100.0/? ELSE 0 END WHERE day=?',(total[0],total[0],day))
        if 'portfolio_day' in tables:
            conn.execute('INSERT INTO portfolio_day(day,total_value,total_change_dollars,total_change_pct,spy_change_pct) VALUES(?,?,?,?,0) ON CONFLICT(day) DO UPDATE SET total_value=excluded.total_value,total_change_dollars=excluded.total_change_dollars,total_change_pct=excluded.total_change_pct',
                         (day,total[0],total[1],100*total[1]/(total[0]-total[1]) if total[0]!=total[1] else 0))
        if 'layer_day' in tables:
            conn.execute('DELETE FROM layer_day WHERE day=?',(day,))
            for layer,value,change in conn.execute('SELECT layer,SUM(value),SUM(change_dollars) FROM holding_day WHERE day=? GROUP BY layer',(day,)).fetchall():
                change = change or 0
                conn.execute('INSERT INTO layer_day(day,layer,value,change_dollars,change_pct,weight_pct) VALUES(?,?,?,?,?,?)',
                    (day,layer,value,change,100*change/(value-change) if value!=change else 0,100*value/total[0] if total[0] else 0))


def mutate(root, action, body, *, request_id=None):
    root = Path(root)
    if not isinstance(body,dict):
        raise ValueError('Mutation body must be an object')
    # Reject malformed requests before taking locks or creating journal tables.
    if action in ('add_lot','add_holding','sell'):
        if not _normalize(str(body.get('ticker') or '')):
            raise ValueError('ticker is required')
        if action == 'sell':
            number(body.get('shares_sold'),'shares_sold');number(body.get('sell_price'),'sell_price')
            purchase_day(body.get('sell_date'))
        else:
            number(body.get('shares'),'shares');number(body.get('cost_per_share'),'cost_per_share',zero=True)
            purchase_day(body.get('purchase_date'))
            if body.get('layer_num') is not None and int(body['layer_num']) not in LAYER_LABELS:
                raise ValueError('layer_num must be 1–5')
    identity = str(request_id or body.get('request_id') or uuid.uuid4())
    request = json.dumps([action,{k:v for k,v in body.items() if k not in ('request_id','price')}],sort_keys=True,allow_nan=False)
    with _locked(root) as conn:
        old = conn.execute('SELECT request_json,result_json FROM portfolio_mutation_receipts WHERE id=?',(identity,)).fetchone()
        if old:
            if old['request_json'] != request:
                raise ValueError('request_id already used for a different mutation')
            return json.loads(old['result_json'])
        result = dict(ok=True,request_id=identity)
        if action in ('add_lot','add_holding'):
            ticker = _normalize(str(body.get('ticker') or ''))
            if not ticker:
                raise ValueError('ticker is required')
            if action == 'add_holding':
                with (root/'holdings.csv').open(newline='') as stream:
                    if any(_normalize(r['Stock'])==ticker for r in csv.DictReader(stream)):
                        raise ValueError('Ticker already held; use add lot')
                if conn.execute('SELECT 1 FROM cost_lots WHERE ticker=?',(ticker,)).fetchone():
                    raise ValueError('Existing inventory must be reconciled before adding holding')
            qty=number(body.get('shares'),'shares');cost=number(body.get('cost_per_share'),'cost_per_share',zero=True)
            since=purchase_day(body.get('purchase_date'))
            if body.get('layer_num') is not None and int(body['layer_num']) not in LAYER_LABELS:
                raise ValueError('layer_num must be 1–5')
            result['id']=conn.execute('INSERT INTO cost_lots(ticker,shares,cost_per_share,purchase_date,notes) VALUES(?,?,?,?,?)',
                                     (ticker,qty,cost,since,body.get('notes',''))).lastrowid
        elif action == 'sell':
            ticker=_normalize(str(body.get('ticker') or ''))
            qty=number(body.get('shares_sold'),'shares_sold');price=number(body.get('sell_price'),'sell_price')
            since=purchase_day(body.get('sell_date'))
            allocations=[];remaining=qty
            for row in conn.execute('SELECT * FROM cost_lots WHERE ticker=? ORDER BY purchase_date,id',(ticker,)).fetchall():
                if remaining <= 1e-6:
                    break
                if row['shares'] <= 0 or not math.isfinite(row['shares']) or row['cost_per_share'] < 0:
                    raise ValueError('Invalid existing lot; reconcile inventory first')
                if row['purchase_date'] > since:
                    continue
                used=min(remaining,row['shares']);gain=used*(price-row['cost_per_share'])
                allocations.append(dict(lot_id=row['id'],purchase_date=row['purchase_date'],cost_per_share=row['cost_per_share'],
                    original_shares=row['shares'],shares=used,gain=gain,term='LT' if is_long_term(date.fromisoformat(row['purchase_date']),date.fromisoformat(since)) else 'ST',notes=row['notes']))
                remaining-=used
            if remaining > 1e-6:
                raise ValueError('Insufficient shares available on sell_date')
            gains={term:sum(a['gain'] for a in allocations if a['term']==term) for term in ('ST','LT')}
            result.update(realized_gain=sum(gains.values()),st_gain=gains['ST'],lt_gain=gains['LT'],allocations=allocations)
            result['id']=conn.execute('''INSERT INTO sell_transactions(ticker,shares_sold,sell_price,sell_date,realized_gain,st_gain,lt_gain,fifo_detail,notes)
                VALUES(?,?,?,?,?,?,?,?,?)''',(ticker,qty,price,since,result['realized_gain'],gains['ST'],gains['LT'],json.dumps(allocations),body.get('notes',''))).lastrowid
            for a in allocations:
                left=round(a['original_shares']-a['shares'],6)
                if left < 1e-6:
                    conn.execute('DELETE FROM cost_lots WHERE id=?',(a['lot_id'],))
                else:
                    conn.execute('UPDATE cost_lots SET shares=? WHERE id=?',(left,a['lot_id']))
        elif action == 'undo_sell':
            row=conn.execute('SELECT * FROM sell_transactions WHERE id=?',(body['id'],)).fetchone()
            if not row:
                return dict(ok=True,already_undone=True,request_id=identity)
            ticker=row['ticker'];since=row['sell_date']
            for a in json.loads(row['fifo_detail'] or '[]'):
                existing=conn.execute('SELECT * FROM cost_lots WHERE id=?',(a['lot_id'],)).fetchone()
                if existing:
                    if (existing['ticker'],existing['purchase_date'],existing['cost_per_share']) != (ticker,a['purchase_date'],a['cost_per_share']):
                        raise ValueError('Lot identity conflict; reconcile before undo')
                    conn.execute('UPDATE cost_lots SET shares=shares+? WHERE id=?',(a['shares'],a['lot_id']))
                else:
                    conn.execute('INSERT INTO cost_lots(id,ticker,shares,cost_per_share,purchase_date,notes) VALUES(?,?,?,?,?,?)',
                                 (a['lot_id'],ticker,a['shares'],a['cost_per_share'],a['purchase_date'],a.get('notes','')))
            conn.execute('DELETE FROM sell_transactions WHERE id=?',(body['id'],))
        elif action == 'delete_lot':
            row=conn.execute('SELECT * FROM cost_lots WHERE id=?',(body['id'],)).fetchone()
            if not row:
                return dict(ok=True,already_deleted=True,request_id=identity)
            ticker=row['ticker'];since=row['purchase_date']
            conn.execute('DELETE FROM cost_lots WHERE id=?',(body['id'],))
        else:
            raise ValueError('Unknown inventory mutation')
        if action == 'add_holding' and body.get('price'):
            price=number(body['price'],'price')
            conn.execute('INSERT INTO holding_day(day,ticker,layer,shares,price,value,change_dollars,change_pct,weight_pct) VALUES(?,?,?,?,?,?,0,0,0)',
                (today_eastern().isoformat(),ticker,LAYER_LABELS[int(body['layer_num'])],qty,price,qty*price))
        _snapshot(conn,ticker,since)
        totals=conn.execute('SELECT COALESCE(SUM(shares),0),COALESCE(SUM(shares*cost_per_share),0) FROM cost_lots WHERE ticker=?',(ticker,)).fetchone()
        result.update(total_shares=totals[0],avg_cost=totals[1]/totals[0] if totals[0] else 0)
        projected=_csv_text(root,conn,ticker,body.get('layer_num'))
        conn.execute('INSERT INTO portfolio_mutation_receipts(id,request_json,result_json,csv_text) VALUES(?,?,?,?)',
                     (identity,request,json.dumps(result),projected))
        conn.commit()
        _flush(root,conn)
        return result
