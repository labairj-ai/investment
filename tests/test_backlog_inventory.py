"""Inventory conservation, projection recovery and dated snapshot regressions (0746–0756)."""
import csv
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import threading

import pytest
import portfolio_mutations as mutations


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(mutations,'today_eastern',lambda:date(2026,10,21))
    (tmp_path/'out').mkdir()
    (tmp_path/'holdings.csv').write_text('Stock,Shares,AvgCost,Layer\nABC,100,100,3\n')
    conn=sqlite3.connect(tmp_path/'out/investment.db')
    conn.executescript('''
      CREATE TABLE cost_lots(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker,shares,cost_per_share,purchase_date,notes);
      CREATE TABLE sell_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker,shares_sold,sell_price,sell_date,realized_gain,st_gain,lt_gain,fifo_detail,notes);
      CREATE TABLE holding_day(day,ticker,layer,shares,price,value,change_dollars,change_pct,weight_pct,PRIMARY KEY(day,ticker));
      CREATE TABLE portfolio_day(day PRIMARY KEY,total_value,total_change_dollars,total_change_pct,spy_change_pct);
      CREATE TABLE layer_day(day,layer,value,change_dollars,change_pct,weight_pct,PRIMARY KEY(day,layer));
      INSERT INTO cost_lots VALUES(1,'ABC',100,100,'2025-01-01','');
      INSERT INTO holding_day VALUES('2026-10-20','ABC','Layer 3: Core Compounders',100,150,15000,100,1,100);
      INSERT INTO holding_day VALUES('2026-10-21','ABC','Layer 3: Core Compounders',100,151,15100,100,1,100);
      INSERT INTO portfolio_day VALUES('2026-10-20',15000,100,1,0);
      INSERT INTO portfolio_day VALUES('2026-10-21',15100,100,1,0);
    ''')
    conn.commit();conn.close()
    return tmp_path


def query(root, sql, args=()):
    with sqlite3.connect(root/'out/investment.db') as conn:
        return conn.execute(sql,args).fetchall()


def rows(root):
    with (root/'holdings.csv').open(newline='') as stream:
        return list(csv.DictReader(stream))


def sell(root, qty, day='2026-10-21', **kw):
    return mutations.mutate(root,'sell',dict(ticker='ABC',shares_sold=qty,sell_price=150,sell_date=day),**kw)


def test_concurrent_sales_conserve_inventory(inventory):
    barrier=threading.Barrier(2)
    def request(_):
        barrier.wait()
        try: return sell(inventory,70)['ok']
        except ValueError: return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request,range(2)))==[False,True]
    assert query(inventory,'SELECT SUM(shares_sold) FROM sell_transactions')==[(70,)]
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(30,)]
    assert float(rows(inventory)[0]['Shares'])==30


def test_out_of_order_undo_and_retries(inventory):
    first=sell(inventory,40);second=sell(inventory,60)
    mutations.mutate(inventory,'undo_sell',{'id':first['id']})
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(40,)]
    assert query(inventory,'SELECT SUM(shares_sold) FROM sell_transactions')==[(60,)]
    assert float(rows(inventory)[0]['Shares'])==40
    mutations.mutate(inventory,'undo_sell',{'id':first['id']})
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(40,)]
    mutations.mutate(inventory,'undo_sell',{'id':second['id']})
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(100,)]


def test_full_sale_and_undo_restore_snapshots_and_aggregates(inventory):
    result=sell(inventory,100)
    assert rows(inventory)==[]
    assert query(inventory,"SELECT shares FROM holding_day WHERE day='2026-10-21'")==[]
    assert query(inventory,"SELECT total_value FROM portfolio_day WHERE day='2026-10-21'")==[(0,)]
    mutations.mutate(inventory,'undo_sell',{'id':result['id']})
    assert float(rows(inventory)[0]['Shares'])==100
    assert query(inventory,"SELECT shares,value FROM holding_day WHERE day='2026-10-21'")==[(100,15100)]
    assert query(inventory,"SELECT total_value FROM portfolio_day WHERE day='2026-10-21'")==[(15100,)]


def test_backdated_sale_preserves_later_purchase_and_quotes(inventory):
    mutations.mutate(inventory,'add_lot',dict(ticker='ABC',shares=20,cost_per_share=200,purchase_date='2026-10-21'))
    sell(inventory,40,'2026-10-20')
    assert query(inventory,'SELECT day,shares,price FROM holding_day ORDER BY day')==[
        ('2026-10-20',60,150),('2026-10-21',80,151)]


def test_fifo_basis_and_one_csv_position(inventory):
    with sqlite3.connect(inventory/'out/investment.db') as conn:
        conn.execute('UPDATE cost_lots SET shares=50')
        conn.execute("INSERT INTO cost_lots VALUES(2,'ABC',50,200,'2025-02-01','')")
    (inventory/'holdings.csv').write_text('Stock,Shares,AvgCost,Layer\nABC,50,100,3\nABC,50,200,3\n')
    sell(inventory,50)
    assert len(rows(inventory))==1
    assert float(rows(inventory)[0]['AvgCost'])==200
    assert float(rows(inventory)[0]['Shares'])==50


def test_delete_last_lot_removes_phantom_position(inventory):
    mutations.mutate(inventory,'delete_lot',{'id':1})
    assert rows(inventory)==[]
    assert query(inventory,'SELECT * FROM holding_day')==[]


@pytest.mark.parametrize('field,value',[
    ('shares',-20),('shares',0),('shares','nan'),('shares','inf'),
    ('cost_per_share',-1),('cost_per_share','inf'),
    ('purchase_date','bad'),('purchase_date','2027-01-01')])
def test_invalid_lot_changes_nothing(inventory,field,value):
    before=(inventory/'holdings.csv').read_bytes()
    body=dict(ticker='ABC',shares=1,cost_per_share=100,purchase_date='2026-10-21');body[field]=value
    with pytest.raises(ValueError): mutations.mutate(inventory,'add_lot',body)
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(100,)]
    assert (inventory/'holdings.csv').read_bytes()==before


def test_fractional_zero_basis_lot_and_alias(inventory):
    result=mutations.mutate(inventory,'add_lot',dict(ticker='brk.b',shares=.25,cost_per_share=0,purchase_date='2026-10-21'))
    assert result['total_shares']==.25
    assert query(inventory,"SELECT ticker FROM cost_lots WHERE ticker='BRK-B'")==[('BRK-B',)]


def test_projection_failure_recovers_without_repeating_sale(inventory,monkeypatch):
    original=mutations._atomic_csv
    monkeypatch.setattr(mutations,'_atomic_csv',lambda *a:(_ for _ in ()).throw(OSError('disk error')))
    with pytest.raises(mutations.ProjectionPending) as error:
        sell(inventory,20,request_id='sale-request')
    assert error.value.mutation_id=='sale-request'
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(80,)]
    monkeypatch.setattr(mutations,'_atomic_csv',original)
    assert sell(inventory,20,request_id='sale-request')['total_shares']==80
    assert len(query(inventory,'SELECT * FROM sell_transactions'))==1
    assert float(rows(inventory)[0]['Shares'])==80
    with pytest.raises(ValueError): sell(inventory,30,request_id='sale-request')


def test_transaction_rolls_back_before_projection(inventory,monkeypatch):
    before=(inventory/'holdings.csv').read_bytes()
    monkeypatch.setattr(mutations,'_snapshot',lambda *a:(_ for _ in ()).throw(RuntimeError('snapshot failure')))
    with pytest.raises(RuntimeError): sell(inventory,20)
    assert query(inventory,'SELECT SUM(shares) FROM cost_lots')==[(100,)]
    assert query(inventory,'SELECT * FROM sell_transactions')==[]
    assert (inventory/'holdings.csv').read_bytes()==before


def test_opening_holding_uses_same_inventory_projection(inventory):
    result=mutations.mutate(inventory,'add_holding',dict(ticker='NEW',shares=2,cost_per_share=80,
        purchase_date='2026-10-21',layer_num=4,price=100),request_id='opening')
    assert result['total_shares']==2
    assert {r['Stock']:r['Shares'] for r in rows(inventory)}=={'ABC':'100','NEW':'2.0'}
    assert query(inventory,"SELECT total_value FROM portfolio_day WHERE day='2026-10-21'")==[(15300,)]
    with pytest.raises(ValueError):
        mutations.mutate(inventory,'add_holding',dict(ticker='NEW',shares=2,cost_per_share=80,
            purchase_date='2026-10-21',layer_num=4,price=100))


def test_inventory_audit_is_read_only(inventory):
    from scripts.audit_portfolio_inventory import audit
    database=inventory/'out/investment.db'
    original=database.read_bytes()
    report=audit(inventory)
    assert report['read_only']
    assert database.read_bytes()==original
    assert (inventory/'holdings.csv').read_text().count('ABC')==1


def test_http_handlers_use_transactional_inventory(inventory):
    import ast
    import types
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/'serve.py').read_text()
    names={'_inventory_mutation','_handle_lot_add','_handle_sell_add','_handle_sell_undo','_handle_lot_delete'}
    selected=[n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name in names]
    namespace={'PROJECT_DIR':inventory}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'serve.py','exec'),namespace)
    output=[]
    request=types.SimpleNamespace(headers={},_json=lambda value:output.append(value),
        _json_error=lambda status,error:output.append(dict(status=status,error=error)),
        _send_json=lambda value,status:output.append(dict(value,status=status)))
    for name in names:setattr(request,name,types.MethodType(namespace[name],request))
    request._read_body=lambda:dict(ticker='ABC',shares_sold=100,sell_price=150,sell_date='2026-10-21')
    request._handle_sell_add()
    sold=output[-1]['id']
    assert rows(inventory)==[]
    request._handle_sell_undo(sold)
    assert float(rows(inventory)[0]['Shares'])==100
    request._read_body=lambda:dict(ticker='ABC',shares=-1,cost_per_share=10,purchase_date='2026-10-21')
    request._handle_lot_add()
    assert output[-1]['status']==400
