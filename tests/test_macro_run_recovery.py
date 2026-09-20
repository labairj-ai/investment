"""Production interruption, atomic persistence, and certification universe regressions."""
import json
import sqlite3

import pytest


@pytest.fixture
def scoring(tmp_path, monkeypatch):
    import portfolio_ai as pai
    import macro_context
    import ollama_client
    from scripts import validate_macro_scorer as validator
    db = tmp_path / 'macro.db'
    db.touch()
    monkeypatch.setattr(pai, 'DB_PATH', db)
    monkeypatch.setattr(validator, 'DB_PATH', db)
    pai._init_ai_tables()
    monkeypatch.setattr(pai, '_load_holdings_csv', lambda: [{'Stock': t} for t in ['XOM', 'AAPL', 'SPY']])
    monkeypatch.setattr(pai, '_fetch_company_evidence', lambda *a: {'evidence_quality': 'full'})
    monkeypatch.setattr(pai, '_compute_equity_betas', lambda *a: None)
    monkeypatch.setattr(pai, '_n_samples_for_dim', lambda *a: 1)
    monkeypatch.setattr(macro_context, 'fetch', lambda: {})
    monkeypatch.setattr(ollama_client, 'available', lambda: True)
    monkeypatch.setattr(pai.time, 'sleep', lambda *a: None)
    monkeypatch.setattr(pai, 'generate_macro_score_summary', lambda *a: None)
    def stream(prompt, **kwargs):
        ticker = 'AAPL' if 'AAPL' in prompt else 'XOM'
        yield json.dumps({ticker: {d: {'score': 5, 'reason': 'fixture'} for d in pai._MACRO_SCORE_DIMS}})
    monkeypatch.setattr(ollama_client, 'stream_generate', stream)
    return pai, validator, db


@pytest.mark.parametrize('supported,unsupported', [(0, 0), (8, 0), (8, 5), (23, 5)])
def test_stale_run_reconstructs_28_items(scoring, supported, unsupported):
    pai, validator, db = scoring
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO macro_scoring_runs(run_id,run_at,expected_n,scored_n,failed_n,status,scorer_contract_hash) VALUES ('crash','2000-01-01',28,0,0,'STARTED','current')")
        statuses = ['SUPPORTED'] * supported + ['UNSUPPORTED'] * unsupported
        statuses += ['PENDING'] * (28 - len(statuses))
        c.executemany('INSERT INTO macro_scoring_run_items(run_id,ticker,status) VALUES (?,?,?)', [('crash', str(i), state) for i, state in enumerate(statuses)])
        c.commit()
        assert pai._reconcile_stale_runs(c) == 1
        assert c.execute('SELECT scored_n,failed_n,supported_scored_n,unsupported_n,status FROM macro_scoring_runs').fetchone() == (supported + unsupported, 28-supported-unsupported, supported, unsupported, 'STALE_FAILED')
        assert pai._reconcile_stale_runs(c) == 0
    result = validator.run_ledger_integrity('current', True)
    assert result['historical_status'] == 'PASS'
    assert result['certification_status'] == 'FAIL'


def test_recent_progress_prevents_stale_reconciliation(scoring):
    pai, _, db = scoring
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO macro_scoring_runs(run_id,run_at,expected_n,status) VALUES ('live','2000-01-01',2,'STARTED')")
        c.execute("INSERT INTO macro_scoring_run_items(run_id,ticker,status,completed_at) VALUES ('live','XOM','SUPPORTED',datetime('now','localtime'))")
        c.commit()
        assert pai._reconcile_stale_runs(c) == 0


def test_actual_scoring_interruption_retains_fund_and_completed_company(scoring, monkeypatch):
    pai, _, db = scoring
    original = pai._fetch_company_evidence
    def interrupt(ticker, conn):
        if ticker == 'XOM':
            raise KeyboardInterrupt('simulated crash')
        return original(ticker, conn)
    monkeypatch.setattr(pai, '_fetch_company_evidence', interrupt)
    with pytest.raises(KeyboardInterrupt):
        pai.generate_holding_macro_scores(force=True)
    with sqlite3.connect(db) as c:
        assert dict(c.execute('SELECT ticker,status FROM macro_scoring_run_items')) == {'SPY': 'UNSUPPORTED', 'AAPL': 'SUPPORTED', 'XOM': 'PENDING'}
        assert c.execute('SELECT count(*) FROM holding_macro_scores_history').fetchone()[0] == 2
        assert pai._reconcile_stale_runs(c, -1) == 1
        assert c.execute('SELECT scored_n,failed_n,status FROM macro_scoring_runs').fetchone() == (2, 1, 'STALE_FAILED')


def test_score_history_and_item_are_atomic(scoring):
    pai, _, db = scoring
    with sqlite3.connect(db) as c:
        c.execute("CREATE TRIGGER reject_terminal BEFORE UPDATE ON macro_scoring_run_items WHEN NEW.status='SUPPORTED' BEGIN SELECT RAISE(ABORT, 'commit boundary failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='commit boundary'):
        pai.generate_holding_macro_scores(force=True)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM holding_macro_scores WHERE ticker='AAPL'").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM holding_macro_scores_history WHERE ticker='AAPL'").fetchone()[0] == 0
        assert c.execute("SELECT status FROM macro_scoring_run_items WHERE ticker='AAPL'").fetchone()[0] == 'PENDING'
        assert pai._reconcile_stale_runs(c, -1) == 1


def test_production_uses_one_universe_snapshot(scoring, monkeypatch):
    pai, validator, db = scoring
    calls = []
    def holdings():
        calls.append(True)
        return [{'Stock': t} for t in ['XOM', 'SPY', 'AAPL', 'XOM']]
    monkeypatch.setattr(pai, '_load_holdings_csv', holdings)
    pai.generate_holding_macro_scores(force=True)
    assert len(calls) == 1
    universe = pai._current_holdings_universe()
    result = validator.run_ledger_integrity(pai._compute_scorer_contract_hash(), True, universe['count'], universe['hash'])
    assert result['certification_status'] == 'PASS'
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT expected_n,scored_n,failed_n,run_scope FROM macro_scoring_runs').fetchone() == (3, 3, 0, 'full_refresh')


def test_new_and_sold_holdings_use_csv_not_score_cache(scoring, monkeypatch):
    pai, validator, _ = scoring
    pai.generate_holding_macro_scores(force=True)
    before = pai._current_holdings_universe()
    monkeypatch.setattr(pai, '_load_holdings_csv', lambda: [{'Stock': 'NEW'}, {'Stock': 'XOM'}])
    after = pai._current_holdings_universe()
    assert validator._current_portfolio_tickers(pai) == ['NEW', 'XOM']
    assert before['hash'] != after['hash']
    assert validator.run_ledger_integrity(pai._compute_scorer_contract_hash(), True, after['count'], after['hash'])['certification_status'] == 'FAIL'


@pytest.mark.parametrize('scope,expected,portfolio_n', [('incremental', 1, 28), ('full_refresh', 1, 28), ('full_refresh', 28, 1), ('full_refresh', 0, 0)])
def test_partial_or_empty_universe_cannot_certify(scoring, scope, expected, portfolio_n):
    _, validator, db = scoring
    with sqlite3.connect(db) as c:
        c.execute('INSERT INTO macro_scoring_runs(run_at,run_id,expected_n,scored_n,failed_n,supported_scored_n,unsupported_n,status,scorer_contract_hash,run_scope,portfolio_n,portfolio_universe_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('2000-01-01', 'bad', expected, expected, 0, expected, 0, 'COMPLETE', 'current', scope, portfolio_n, 'universe'))
    assert validator.run_ledger_integrity('current', True, 28, 'universe')['certification_status'] == 'FAIL'


def test_fund_transaction_rolls_back_on_terminal_failure(scoring):
    pai, _, db = scoring
    with sqlite3.connect(db) as c:
        c.execute("CREATE TRIGGER reject_fund BEFORE UPDATE ON macro_scoring_run_items WHEN NEW.status='UNSUPPORTED' BEGIN SELECT RAISE(ABORT, 'fund failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='fund failure'):
        pai.generate_holding_macro_scores(force=True)
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT count(*) FROM holding_macro_scores').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM holding_macro_scores_history').fetchone()[0] == 0
        assert pai._reconcile_stale_runs(c, -1) == 1
        assert c.execute('SELECT scored_n,failed_n FROM macro_scoring_runs').fetchone() == (0, 3)


def test_legacy_run_reconstructs_committed_history(scoring):
    pai, _, db = scoring
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO macro_scoring_runs(run_id,run_at,expected_n,scored_n,failed_n,status) VALUES ('legacy','2000-01-01',3,0,0,'STARTED')")
        c.executemany('INSERT INTO holding_macro_scores_history(ticker,scores,scored_at,run_id) VALUES (?,?,?,?)', [('AAPL', '{}', '2000-01-01', 'legacy'), ('SPY', '{"macro_supported":false}', '2000-01-01', 'legacy')])
        c.commit()
        assert pai._reconcile_stale_runs(c) == 1
        assert c.execute('SELECT scored_n,failed_n,supported_scored_n,unsupported_n,status FROM macro_scoring_runs').fetchone() == (2, 1, 1, 1, 'STALE_FAILED')
