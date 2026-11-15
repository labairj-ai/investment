"""Exercise owned SQLite handles without importing server startup side effects."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sqlite3

import pytest


def notification_reader(connect):
    tree = ast.parse(Path('serve.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_dispatch_urgent_notifications')
    namespace = {'agent_db': SimpleNamespace(_connect=connect)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'serve.py', 'exec'), namespace)
    return namespace[node.name]


@pytest.mark.parametrize('failure', ['query', 'fetch', 'none'])
def test_notification_read_closes_connection_and_preserves_fallback(failure, capsys):
    error = sqlite3.OperationalError('controlled notification read failure')

    class Connection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            if failure == 'query':
                raise error
            if failure == 'fetch':
                class Cursor:
                    def fetchall(self):
                        raise error
                return Cursor()
            return super().execute(*args, **kwargs)

    conn = sqlite3.connect(':memory:', factory=Connection)
    conn.executescript('CREATE TABLE recommendations(id,ticker,action,why_now,rationale,recommendation_score,status,urgency_level,created_at); CREATE TABLE notification_events(recommendation_id,level);')
    notification_reader(lambda: conn)()
    assert ('DB query failed: controlled notification read failure' in capsys.readouterr().out) == (failure != 'none')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        sqlite3.Connection.execute(conn, 'SELECT 1')


def test_notification_connect_failure_keeps_fallback(capsys):
    def connect():
        raise sqlite3.OperationalError('connect failed')
    notification_reader(connect)()
    assert 'DB query failed: connect failed' in capsys.readouterr().out
