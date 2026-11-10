"""Real disposable SQLite handles must close on dashboard read failures."""
import sqlite3

import pytest

import generate_dashboard as dashboard


def assert_closed(conn):
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        conn.execute('SELECT 1')


@pytest.mark.parametrize('table', ['portfolio_day', 'layer_day', 'holding_day'])
def test_load_data_closes_and_preserves_query_error(tmp_path, monkeypatch, table):
    path = tmp_path / 'dashboard.db'
    conn = sqlite3.connect(path)
    conn.executescript('CREATE TABLE portfolio_day(day); CREATE TABLE layer_day(day,layer); CREATE TABLE holding_day(day,layer,ticker);')
    conn.execute('DROP TABLE ' + table)
    monkeypatch.setattr(dashboard, 'DB_PATH', path)
    monkeypatch.setattr(dashboard.sqlite3, 'connect', lambda *a, **kw: conn)
    with pytest.raises(sqlite3.OperationalError, match='no such table: ' + table):
        dashboard.load_data()
    assert_closed(conn)


def test_macro_scores_closes_and_keeps_empty_fallback(tmp_path, monkeypatch):
    path = tmp_path / 'dashboard.db'
    conn = sqlite3.connect(path)
    monkeypatch.setattr(dashboard, 'DB_PATH', path)
    monkeypatch.setattr(dashboard.sqlite3, 'connect', lambda *a, **kw: conn)
    assert dashboard._load_macro_scores() == {}
    assert_closed(conn)


@pytest.mark.parametrize('failure', ['sell-query', 'sell-iteration', 'purchase-markers', 'cc-ytd', 'cc-lifetime'])
def test_dashboard_optional_read_failures_close_and_keep_fallbacks(mem_db, tmp_path, monkeypatch, failure):
    original_connect = sqlite3.connect
    with original_connect(mem_db) as db:
        db.execute('CREATE TABLE IF NOT EXISTS sell_transactions(sell_date,shares_sold,sell_price,ticker)')
        db.execute('CREATE TABLE IF NOT EXISTS cc_positions(status,net_premium,closed_date,expiry)')
    allocated = []
    error = sqlite3.OperationalError('controlled read failure')

    class ObservedConnection(sqlite3.Connection):
        failed = False
        def execute(self, sql, *args, **kwargs):
            is_sell = 'SELECT sell_date, shares_sold * sell_price' in sql
            is_cc = 'SELECT sum(net_premium)' in sql
            if (failure == 'sell-query' and is_sell or
                    failure == 'cc-ytd' and is_cc and 'LIKE ?' in sql or
                    failure == 'cc-lifetime' and is_cc and 'count(*)' in sql):
                self.failed = True
                raise error
            if failure in {'sell-iteration', 'purchase-markers'} and is_sell:
                self.failed = True
            cursor = super().execute(sql, *args, **kwargs)
            if failure == 'sell-iteration' and is_sell:
                class FailedRead:
                    def __iter__(self):
                        raise error
                return FailedRead()
            return cursor

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs, factory=ObservedConnection)
        allocated.append(conn)
        return conn

    def markers(conn):
        if failure == 'purchase-markers':
            raise error
        return []

    holdings = tmp_path / 'holdings.csv'
    holdings.write_text('ticker,shares,layer\n')
    monkeypatch.setattr(dashboard, 'DB_PATH', mem_db)
    monkeypatch.setattr(dashboard, 'HOLDINGS_CSV', holdings)
    monkeypatch.setattr(dashboard, 'load_csv_holdings', lambda: [])
    monkeypatch.setattr(dashboard, 'rebuild_today_holdings', lambda *a: ([], [], 10000.))
    monkeypatch.setattr(dashboard, 'purchase_markers', markers)
    monkeypatch.setattr(dashboard.sqlite3, 'connect', connect)
    page = dashboard.build_dashboard([dict(day='2026-11-09', total_value=10000., total_change_dollars=0., total_change_pct=0., spy_change_pct=0.)], [], [])
    assert 'Stocks vs SPY' in page
    assert '"grossStockValue": 10000.0' in page
    failed = [conn for conn in allocated if conn.failed]
    assert len(failed) == 1  # Exercise the intended real rendering path.
    assert_closed(failed[0])


def test_load_data_success_values_and_close(tmp_path, monkeypatch):
    path = tmp_path / 'dashboard.db'
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE portfolio_day(day); INSERT INTO portfolio_day VALUES('2026-11-09'); CREATE TABLE layer_day(day,layer); CREATE TABLE holding_day(day,layer,ticker);")
    monkeypatch.setattr(dashboard, 'DB_PATH', path)
    monkeypatch.setattr(dashboard.sqlite3, 'connect', lambda *a, **kw: conn)
    assert dashboard.load_data() == ([{'day': '2026-11-09'}], [], [])
    assert_closed(conn)
