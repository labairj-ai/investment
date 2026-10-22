"""Regression checks for chart returns and purchase history after sales."""
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from dashboard_transactions import purchase_markers


def test_original_purchase_survives_partial_and_full_sales():
    conn = sqlite3.connect(":memory:")
    conn.executescript("CREATE TABLE cost_lots(id, ticker, purchase_date, cost_per_share, shares); CREATE TABLE sell_transactions(ticker, fifo_detail);")
    conn.execute("INSERT INTO cost_lots VALUES(1, 'ABC', '2026-01-01', 100, 2)")
    def sell(shares):
        conn.execute("INSERT INTO sell_transactions VALUES(?, ?)", ('ABC', json.dumps([dict(lot_id=1, purchase_date='2026-01-01', cost_per_share=100, shares=shares)])))
    sell(4)
    sell(4)
    assert purchase_markers(conn) == [dict(date='2026-01-01', type='buy', ticker='ABC', shares=10, price=100)]
    conn.execute("DELETE FROM cost_lots")
    sell(2)
    assert purchase_markers(conn)[0]['shares'] == 10
    conn.execute("DELETE FROM sell_transactions WHERE rowid=3")
    conn.execute("INSERT INTO cost_lots VALUES(1, 'ABC', '2026-01-01', 100, 2)")
    assert purchase_markers(conn)[0]['shares'] == 10  # undo restores rather than duplicates
    conn.close()


def test_timeframe_returns_compound_growth_factors():
    if not shutil.which('node'):
        pytest.skip('node unavailable')
    source = (Path(__file__).resolve().parents[1] / 'generate_dashboard.py').read_text()
    start = source.index('function _cumFilterData(tf)')
    end = source.index('function buildCumChart(tf)', start)
    function = source[start:end].replace('{{', '{').replace('}}', '}')
    script = 'const D={dates:["2026-09-21","2026-10-21"],portCum:[20,32],spyCum:[10,21]}; const _txnByDate={};' + function + 'console.log(JSON.stringify(_cumFilterData("1M")));'
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data['portCum'] == [0, 10]
    assert data['spyCum'] == [0, 10]
