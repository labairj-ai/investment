"""Model-loader fallbacks must not retain a failed SQLite connection."""
import sqlite3

import pytest

import agent_db
from agents.learning.calibration import ChallengerModel


@pytest.mark.parametrize('loader', ['load_paper_active', 'load_latest_trained'])
def test_model_loader_closes_connection_when_query_fails(monkeypatch, loader):
    conn = sqlite3.connect(':memory:')
    monkeypatch.setattr(agent_db, '_connect', lambda: conn)
    try:
        assert getattr(ChallengerModel, loader)() is None
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            conn.execute('SELECT 1')
    finally:
        conn.close()
