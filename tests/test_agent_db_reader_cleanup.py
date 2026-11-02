"""Metadata/history readers release SQLite resources even when a query fails."""
import sqlite3

import pytest

import agent_db


READERS = [
    (agent_db.get_valuation_ratio_history, ('FIXTURE', 'pe'), []),
    (agent_db.get_latest_valuation_metric, ('FIXTURE',), None),
    (agent_db.get_estimate_history, ('FIXTURE', 'FY', 'EPS'), []),
]


@pytest.mark.parametrize('reader,args,empty', READERS)
def test_reader_closes_connection_when_query_fails(monkeypatch, reader, args, empty):
    conn = sqlite3.connect(':memory:')
    monkeypatch.setattr(agent_db, '_connect', lambda: conn)
    try:
        with pytest.raises(sqlite3.OperationalError, match='no such table'):
            reader(*args)
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            conn.execute('SELECT 1')
    finally:
        conn.close()


@pytest.mark.parametrize('reader,args,empty', READERS)
def test_reader_preserves_empty_results_and_closes_connection(mem_db, monkeypatch, reader, args, empty):
    conn = agent_db._connect()
    monkeypatch.setattr(agent_db, '_connect', lambda: conn)
    try:
        assert reader(*args) == empty
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            conn.execute('SELECT 1')
    finally:
        conn.close()
