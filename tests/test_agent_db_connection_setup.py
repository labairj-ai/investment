"""Connection setup releases its handle on failure and preserves SQLite safeguards."""
import sqlite3

import pytest

import agent_db


@pytest.mark.parametrize('failed_pragma', ['PRAGMA journal_mode=WAL', 'PRAGMA foreign_keys=ON'])
def test_setup_failure_closes_connection_and_preserves_error(monkeypatch, failed_pragma):
    error = sqlite3.OperationalError('fixture setup failure')

    class SetupFailure(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == failed_pragma:
                raise error
            return super().execute(sql, *args, **kwargs)

    conn = sqlite3.connect(':memory:', factory=SetupFailure)
    monkeypatch.setattr(agent_db.sqlite3, 'connect', lambda *args, **kwargs: conn)
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            agent_db._connect()
        assert caught.value is error
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            conn.execute('SELECT 1')
    finally:
        conn.close()


def test_successful_setup_retains_wal_foreign_keys_and_row_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_db, 'DB_PATH', tmp_path/'fixture.sqlite3')
    conn = agent_db._connect()
    try:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert conn.execute('SELECT 1 AS value').fetchone()['value'] == 1
    finally:
        conn.close()
