"""Regression coverage for the September 21 pipeline failure."""
import sqlite3
import pytest
import agent_db


def test_portfolio_briefing_persists(mem_db, sample_snapshot):
    from agents.orchestrator import _run_single_agent
    from agents.contracts import Recommendation
    recs, run_id = _run_single_agent(
        'briefing', lambda ctx: [Recommendation(ticker=None, action='BRIEFING')],
        sample_snapshot,
    )
    with agent_db._connect() as conn:
        assert conn.execute('SELECT status FROM agent_runs WHERE id=?', (run_id,)).fetchone()[0] == 'done'
        row = conn.execute('SELECT ticker,action FROM recommendations WHERE run_id=?', (run_id,)).fetchone()
        assert tuple(row) == ('', 'BRIEFING')
    conn.close()
    assert len(recs) == 1


def test_failed_insert_releases_lock_while_traceback_is_retained(mem_db):
    # Keep the exception/traceback alive, as the orchestrator does while recording error.
    with pytest.raises(sqlite3.IntegrityError) as failure:
        agent_db.insert_recommendation(None, 'BUY')
    conn = sqlite3.connect(str(mem_db), timeout=0.1)
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.rollback()
    finally:
        conn.close()
    assert failure.value


def test_valuation_uses_real_financial_schema(mem_db, monkeypatch):
    import financials_fetcher
    from agents import sell_trim_agent as agent
    monkeypatch.setattr(financials_fetcher, 'DB_PATH', mem_db)
    monkeypatch.setattr(agent, '_DB', mem_db)
    financials_fetcher._init_tables()
    with agent_db._connect() as conn:
        conn.execute("INSERT INTO company_financials(ticker,period_type,period_end,eps_diluted,free_cash_flow) VALUES ('TEST','Q','2026-06-30',2,100)")
    conn.close()
    score, reason = agent._score_V('TEST', 40)
    assert 0 <= score <= 100
    assert 'P/E=' in reason
