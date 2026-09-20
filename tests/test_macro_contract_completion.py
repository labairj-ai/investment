"""Behavioral coverage for the completed 0529–0534 acceptance contract."""
import copy
import hashlib
import json
import sqlite3
import uuid

import pytest

from scripts import validate_macro_scorer as v


def passing():
    config = v._load_validation_config()
    results = {
        'synthetic_regression': {'tests': [{'recovered': 2., 'expected': 2.}]},
        'regime_direction': {'tests': [{'test': 'missing_rate_is_none', 'status': 'PASS'},
                                      {'test': 'rising_rates_positive', 'status': 'PASS'}]},
        'fund_classification': {'tickers': [{'expected': 'fund', 'status': 'PASS'},
                                          {'expected': 'company', 'status': 'PASS'}]},
        'ledger_integrity': {'runs': [{'expected': 2, 'scored': 1, 'failed': 1}]},
        'anchor_calibration': {'XOM': {'dims': {'rate': {'actual': 5, 'expected_range': [1, 10]}}},
                               '_ordering': {'checks': [{'lo': 1, 'hi': 2}]}},
        'drift': {'comparisons': []},
        'repeatability': {tk: {d: {'n': 20, 'range': 0, 'mean': 5., 'stdev': 0.}
                              for d in v.DIMS} for tk in config['repeatability_universe']},
    }
    return config, results


@pytest.mark.parametrize('key', sorted(v._REQUIRED_THRESHOLDS))
def test_each_threshold_changes_verdict(key):
    config, results = passing()
    if key == 'beta_recovery_tolerance':
        results['synthetic_regression']['tests'][0]['recovered'] = 3.
        good, bad = 1., .99
    elif key == 'anchor_ordering_failures':
        results['anchor_calibration']['_ordering']['checks'] = [{'lo': 2, 'hi': 1}]
        good, bad = 1, 0
    elif key == 'missing_data_unknown_pct':
        results['regime_direction']['tests'].append({'test': 'missing_dollar_is_none', 'status': 'FAIL'})
        good, bad = 50, 51
    elif key == 'fund_unsupported_pct':
        results['fund_classification']['tickers'].append({'expected': 'fund', 'status': 'FAIL'})
        good, bad = 50, 51
    elif key == 'ledger_integrity_pct':
        results['ledger_integrity']['runs'].append({'expected': 2, 'scored': 0, 'failed': 0})
        good, bad = 50, 51
    elif key == 'same_input_score_max_range':
        results['repeatability']['XOM'][v.DIMS[0]]['range'] = 2
        good, bad = 2, 1
    elif key == 'unexplained_large_swings':
        results['drift']['comparisons'] = [{'ticker': 'XOM', 'delta': 2}]
        good, bad = 1, 0
    else:
        results['drift']['comparisons'] = [{'ticker': 'XOM', 'delta': 2}]
        good, bad = 2, 1
    config['thresholds'][key] = good
    assert v._check_thresholds(results, config)['verdict'] == 'PASS'
    config['thresholds'][key] = bad
    assert v._check_thresholds(results, config)['verdict'] == 'BLOCK'


@pytest.fixture
def db(tmp_path, monkeypatch):
    import portfolio_ai as pai
    path = tmp_path / 'test.db'
    path.touch()
    monkeypatch.setattr(pai, 'DB_PATH', path)
    monkeypatch.setattr(v, 'DB_PATH', path)
    pai._init_ai_tables()
    return path


def acceptance():
    import portfolio_ai as pai
    config, results = passing()
    return {
        'record_id': str(uuid.uuid4()), 'output_path': '/tmp/result.json',
        'timestamp': '2026-09-20T12:00:00Z', 'run_type': 'acceptance', 'verdict': 'PASS',
        'acceptance_contract': 'macro_validation_v1', 'commit_sha': 'test-commit',
        'model_identity': pai.ollama_client.DEFAULT_MODEL,
        'scorer_contract_hash': pai._compute_scorer_contract_hash(),
        'validation_config_version': config['version'], 'validation_config_hash': 'config-hash',
        'config_used': config, 'results': results,
        'evidence_snapshot': {tk: {'prompt_hash': 'prompt', 'evidence_hash': 'evidence'}
                              for tk in config['repeatability_universe']},
    }


def test_real_activation_duplicate_and_32_rows(db):
    output = acceptance()
    assert v._persist_run(db, output)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM macro_dimension_validation').fetchone()[0] == 32
        assert conn.execute('SELECT count(*) FROM macro_acceptance_state').fetchone()[0] == 1
        assert conn.execute('SELECT prompt_hash,evidence_hash,scorer_contract_hash FROM macro_dimension_validation LIMIT 1').fetchone() == ('prompt', 'evidence', output['scorer_contract_hash'])
    with pytest.raises(sqlite3.IntegrityError):
        v._persist_run(db, output)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM macro_validation_runs').fetchone()[0] == 1


def test_activation_failure_rolls_back_everything(db):
    first = acceptance()
    v._persist_run(db, first)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_activation BEFORE UPDATE ON macro_acceptance_state BEGIN SELECT RAISE(ABORT, 'activation failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match='activation failed'):
        v._persist_run(db, acceptance())
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT record_id FROM macro_acceptance_state').fetchone()[0] == first['record_id']
        assert conn.execute('SELECT count(*) FROM macro_validation_runs').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM macro_dimension_validation').fetchone()[0] == 32
        conn.execute('BEGIN IMMEDIATE')  # failed writer released its lock


def test_database_lock_preserves_acceptance(db):
    first = acceptance()
    v._persist_run(db, first)
    conn = sqlite3.connect(db)
    try:
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            v._persist_run(db, acceptance(), timeout=.01)
    finally:
        conn.rollback()
        conn.close()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT record_id FROM macro_acceptance_state').fetchone()[0] == first['record_id']
        conn.execute('BEGIN IMMEDIATE')


@pytest.mark.parametrize('component', ['model', 'prompt', 'dims', 'temperature', 'tokens', 'schema', 'evidence', 'aggregation'])
def test_each_contract_component_invalidates(db, monkeypatch, component):
    import portfolio_ai as pai
    v._persist_run(db, acceptance())
    if component == 'model':
        monkeypatch.setattr(pai.ollama_client, 'DEFAULT_MODEL', 'changed')
    elif component == 'prompt':
        original = pai._build_macro_score_request
        monkeypatch.setattr(pai, '_build_macro_score_request', lambda *args: original(*args) + 'changed')
    elif component == 'dims':
        dims = copy.deepcopy(pai.MACRO_DIMS)
        first = next(iter(dims))
        dims[first] = dict(dims[first], description='changed')
        monkeypatch.setattr(pai, 'MACRO_DIMS', dims)
    else:
        name = {'temperature': '_MACRO_SCORE_TEMPERATURE', 'tokens': '_MACRO_SCORE_NUM_PREDICT',
                'schema': 'MACRO_SCORE_SCHEMA_VERSION', 'evidence': 'MACRO_EVIDENCE_SCHEMA_VERSION',
                'aggregation': 'MACRO_AGGREGATION_VERSION'}[component]
        monkeypatch.setattr(pai, name, 'changed')
    with sqlite3.connect(db) as conn:
        result = pai._accepted_dim_state('XOM', v.DIMS[0], conn)
    assert result['usable'] is False
    assert result['usable_reason'] == 'acceptance_stale_scorer_contract'


def test_production_and_validator_requests_and_persisted_hash(db, monkeypatch):
    import portfolio_ai as pai
    import macro_context
    import ollama_client
    monkeypatch.setattr(pai, 'ollama_client', ollama_client)
    calls = []
    evidence = {'evidence_quality': 'full', 'sector': 'Energy'}
    monkeypatch.setattr(pai, '_load_holdings_csv', lambda: [{'Stock': 'XOM'}])
    monkeypatch.setattr(pai, '_fetch_company_evidence', lambda *args: copy.deepcopy(evidence))
    monkeypatch.setattr(pai, '_compute_equity_betas', lambda *args: None)
    monkeypatch.setattr(pai, '_n_samples_for_dim', lambda *args: 1)
    monkeypatch.setattr(macro_context, 'fetch', lambda: {})
    monkeypatch.setattr(ollama_client, 'available', lambda: True)
    monkeypatch.setattr(pai.time, 'sleep', lambda *args: None)
    def stream(prompt, **kwargs):
        calls.append((prompt, kwargs))
        yield json.dumps({'XOM': {d: {'score': 5, 'reason': 'fixture'} for d in v.DIMS}})
    monkeypatch.setattr(ollama_client, 'stream_generate', stream)
    result = pai.generate_holding_macro_scores(force=True)
    assert 'XOM' in result
    production_calls = list(calls)
    calls.clear()
    assert v._score_one_ticker('XOM', evidence, None)
    assert calls and all(c == calls[0] for c in production_calls)
    assert result['XOM']['scorer_contract_hash'] == pai._compute_scorer_contract_hash()
    with sqlite3.connect(db) as conn:
        saved = json.loads(conn.execute('SELECT scores FROM holding_macro_scores_history WHERE ticker=?', ('XOM',)).fetchone()[0])
    assert saved['scorer_contract_hash'] == result['XOM']['scorer_contract_hash']
    assert saved['prompt_hash'] == hashlib.sha256(calls[0][0].encode()).hexdigest()


def episodes(n=80):
    return [{'macro': {'rate_interaction': 1 if i % 2 else -1,
                       'challenger_recommendation': 'BUY', 'base_recommendation': 'HOLD',
                       'challenger_alpha': 1., 'base_alpha': 1.},
             'alpha': 2. if i % 2 else 0., 'captured_at': f'2026-09-{i % 10 + 1:02d}T12:00:00'} for i in range(n)]


def test_bootstrap_excludes_invalid_dates_and_interactions():
    from scripts.macro_attribution import analyse
    baseline = analyse(episodes(), '3m')['cohort_bootstrap_ci']
    assert baseline['status'] == 'ok'
    bad = []
    for value in [None, '', 'not-a-date', '2026-02-30T12:00:00', '2026-09-01garbage']:
        e = episodes(1)[0]; e.update(captured_at=value, alpha=100000); bad.append(e)
    for value in [None, 'invalid', float('nan'), float('inf')]:
        e = episodes(1)[0]; e['macro']['rate_interaction'] = value; e['alpha'] = 100000; bad.append(e)
    actual = analyse(episodes() + bad, '3m')['cohort_bootstrap_ci']
    assert actual == baseline


def test_ties_and_small_decidable_subgroups():
    from scripts.macro_attribution import analyse
    result = analyse(episodes(), '3m')['divergence_analysis']
    assert result['status'] == 'ok'
    for group in result['regime_group_win_rates'].values():
        assert group['ties'] == 40 and group['wins'] == group['losses'] == 0
    data = episodes()
    for e in data[4:]:
        e['macro']['challenger_alpha'] = None
    result = analyse(data, '3m')['divergence_analysis']
    for group in result['regime_group_win_rates'].values():
        assert group['suppressed'] and 'challenger_win_rate' not in group


@pytest.mark.parametrize('live,smoke,override,verdict,expected', [
    (False,False,None,'PASS','dry_run'), (True,False,None,'PASS','acceptance'),
    (True,False,None,'BLOCK','validation_failed'), (True,True,None,'PASS','smoke'),
    (True,False,2,'PASS','smoke')])
def test_run_modes(live,smoke,override,verdict,expected):
    assert v._run_type(live,smoke,override,verdict) == expected


@pytest.mark.parametrize('value', [-1, float('nan'), True, '100'])
def test_bad_numeric_config_rejected(value):
    config, _ = passing()
    config['thresholds']['ledger_integrity_pct'] = value
    with pytest.raises(ValueError): v._validate_config(config)


def test_missing_samples_and_status_only_results_block():
    config, results = passing()
    results['repeatability']['XOM'][v.DIMS[0]]['n'] = 19
    assert v._check_thresholds(results, config)['verdict'] == 'BLOCK'
    results = {key: {'status': 'PASS'} for key in results}
    assert v._check_thresholds(results, config)['verdict'] == 'BLOCK'


@pytest.mark.parametrize('live,fail,mode', [(True,False,'acceptance'), (True,True,'validation_failed'), (False,False,'dry_run')])
def test_main_artifact_and_database_modes(db, tmp_path, monkeypatch, live, fail, mode):
    import sys
    import portfolio_ai as pai
    import ollama_client
    config, results = passing()
    identity = str(uuid.uuid4())
    allocated = []
    def new_uuid():
        allocated.append(identity)
        return identity
    monkeypatch.setattr(v.uuid, 'uuid4', new_uuid)
    monkeypatch.setattr(ollama_client, 'available', lambda: True)
    monkeypatch.setattr(pai, '_fetch_company_evidence', lambda *args: {'sector': 'Energy'})
    monkeypatch.setattr(pai, '_compute_equity_betas', lambda *args: {'rate_beta_100bp_return_pct': 1, 'r_squared': .3, 'n_weeks': 104})
    freeze = v._freeze_validation_evidence
    def checked_freeze(*args):
        assert allocated == [identity]
        return freeze(*args)
    monkeypatch.setattr(v, '_freeze_validation_evidence', checked_freeze)
    monkeypatch.setattr(v, 'run_repeatability', lambda *args, **kwargs: results['repeatability'])
    monkeypatch.setattr(v, 'run_anchor_calibration', lambda *args: results['anchor_calibration'])
    for name, key in [('run_concordance','concordance'), ('run_drift_detection','drift'),
                      ('run_synthetic_regression','synthetic_regression'), ('run_regime_direction_tests','regime_direction'),
                      ('run_fund_classification_tests','fund_classification'), ('run_ledger_integrity','ledger_integrity')]:
        monkeypatch.setattr(v, name, lambda *args, key=key: results.get(key, {}))
    if fail:
        results['repeatability']['XOM'][v.DIMS[0]]['n'] = 19
    out = tmp_path / 'acceptance.json'
    monkeypatch.setattr(sys, 'argv', ['validate', '--out', str(out)] + (['--live'] if live else []))
    if fail or not live:
        with pytest.raises(SystemExit): v.main()
    else:
        v.main()
    record = json.loads(out.read_text())
    assert record['record_id'] == identity
    assert record['run_type'] == mode
    assert record['activated'] == (mode == 'acceptance')
    if live:
        assert len(record['evidence_snapshot']) == 9  # eight repeatability companies + NEE
        for tk, snapshot in record['evidence_snapshot'].items():
            prompt = pai._build_macro_score_request(tk, snapshot['evidence'], snapshot['betas'])
            assert record['prompt_hash'][tk] == hashlib.sha256(prompt.encode()).hexdigest()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT run_type FROM macro_validation_runs').fetchone()[0] == mode
        assert conn.execute('SELECT count(*) FROM macro_acceptance_state').fetchone()[0] == (mode == 'acceptance')
    with pytest.raises(FileExistsError): v.main()
    assert json.loads(out.read_text()) == record


def test_anchor_uses_frozen_production_evidence_and_skips_funds(monkeypatch):
    requests = []
    snapshot = {tk: {'evidence': {'ticker': tk}, 'betas': {}} for tk in ['NEE', 'XOM']}
    def score(ticker, evidence, betas):
        requests.append((ticker, evidence, betas))
        return {d: 5 for d in v.DIMS}
    monkeypatch.setattr(v, '_score_one_ticker', score)
    monkeypatch.setattr(v.time, 'sleep', lambda *args: None)
    result = v.run_anchor_calibration(snapshot)
    assert [r[0] for r in requests] == ['NEE', 'XOM']
    assert all(ev == snapshot[tk]['evidence'] for tk, ev, _ in requests)
    assert result['BIL']['status'] == result['VNQ']['status'] == 'UNSUPPORTED'
