"""Bounded news regression tests: evidence integrity, atomicity, deadlines, no retry storms."""
import copy
import json
import sqlite3
import subprocess
import time
from unittest.mock import patch

import pytest
from agents.news import brief, intelligence as intel
from test_news_intelligence import _make_db


def article(t='AAA'):
    return {'title': t+' raises revenue guidance to $20 million', 'url': 'https://example.com/'+t,
            'source': 'Company', 'pub_date': 'Fri, 25 Sep 2026 09:00:00 GMT',
            'model_input_text': 'Revenue guidance was raised to $20 million. '+('Evidence. '*80)}


def response(selected):
    return {'holdings': {t: {'status': 'material', 'news': 'Revenue guidance rose to $20 million.',
        'why_it_matters': 'Higher revenue could support the growth thesis.', 'watch_next': 'Watch reported revenue.',
        'article_ids': [intel._article_id(a[0])], 'events': [{
            'event_type': 'GUIDANCE_CHANGE', 'direction': 'POSITIVE', 'magnitude': 'MEDIUM',
            'horizon': 'SHORT', 'confidence': .8, 'affected_metric': 'revenue',
            'evidence': 'Revenue guidance rose to $20 million.',
            'article_ids': [intel._article_id(a[0])], 'causal_driver': None,
            'causal_event_key': t+'_REVENUE_GUIDANCE'}]} for t, a in selected.items()}}


def test_complete_grounded_synthesis_and_exact_snapshot():
    selected = {'AAA': [article()]}
    summaries, events = brief.validate(response(selected), selected)
    assert summaries['AAA']['status'] == 'material'
    assert events['AAA'][0]['titles'] == [article()['title']]
    snap = intel.build_news_snapshot(selected)
    assert snap['articles'][0]['model_input_text'] == article()['model_input_text']
    assert len(snap['articles'][0]['model_input_text']) > 150
    changed = copy.deepcopy(selected)
    changed['AAA'][0]['model_input_text'] += ' Changed.'
    assert intel.build_news_snapshot(changed)['snapshot_hash'] != snap['snapshot_hash']


@pytest.mark.parametrize('mutation', ['missing', 'cross_ticker', 'unknown', 'bad_event', 'nan', 'empty', 'status'])
def test_invalid_output_cannot_be_published(mutation):
    selected = {'AAA': [article()], 'BBB': [article('BBB')]}
    result = response(selected)
    s = result['holdings']['AAA']
    if mutation == 'missing': del result['holdings']['BBB']
    if mutation == 'cross_ticker': s['article_ids'] = [intel._article_id(article('BBB'))]
    if mutation == 'unknown': s['events'][0]['article_ids'] = ['invented']
    if mutation == 'bad_event': s['events'][0]['event_type'] = 'UNSUPPORTED'
    if mutation == 'nan': s['events'][0]['confidence'] = float('nan')
    if mutation == 'empty': s['news'] = ''
    if mutation == 'status': s['status'] = 'no_material_change'
    with pytest.raises(ValueError): brief.validate(result, selected)


def test_observed_taxonomy_regressions():
    selected = {'AAA': [article()]}
    result = response(selected)
    result['holdings']['AAA']['events'][0]['evidence'] = 'HSBC downgraded the analyst rating.'
    _, events = brief.validate(result, selected)
    assert events['AAA'][0]['event_type'] == 'ANALYST_RATING'
    result = response(selected)
    ev = result['holdings']['AAA']['events'][0]
    ev.update(event_type='EARNINGS', evidence='Company announced its earnings release date.')
    _, events = brief.validate(result, selected)
    assert events['AAA'][0]['event_type'] == 'EARNINGS_CALENDAR'
    assert events['AAA'][0]['direction'] == 'NEUTRAL'


def test_explicit_empty_is_distinct_from_omission():
    selected = {'AAA': [article()]}
    result = response(selected)
    result['holdings']['AAA'].update(status='no_material_change', events=[])
    summaries, events = brief.validate(result, selected)
    assert summaries['AAA']['status'] == 'no_material_change'
    assert events == {'AAA': []}


def test_slow_io_does_not_hold_stage_open():
    start = time.monotonic()
    def slow():
        time.sleep(.3)
        return 'late'
    result = brief.parallel_until([('slow', ())], slow, start+.03)
    assert result == {}
    assert time.monotonic()-start < .2


def test_supervisor_timeout_preserves_last_good(tmp_path):
    db = tmp_path / 'investment.db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE news_summaries(day TEXT, summaries TEXT, generated_at TEXT)')
        c.execute('INSERT INTO news_summaries VALUES (?,?,?)', ('2026-09-24', '{"AAA":{"news":"previous"}}', '2026-09-24 12:00:00'))
    with patch.object(brief.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 86)) as run:
        result = brief.refresh(True, db)
    assert result['status'] == 'error'
    assert run.call_args.kwargs['timeout'] == brief.TOTAL_SECONDS
    assert brief.latest(db)[0]['AAA']['news'] == 'previous'
    assert brief.read_json(tmp_path/'news_brief_state.json')['status'] == 'error'


def test_cross_process_lock_prevents_duplicate_generation(tmp_path):
    import fcntl
    with open(tmp_path/'news_brief.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch.object(brief.subprocess, 'run') as run:
            assert brief.refresh(True, tmp_path/'investment.db')['status'] == 'generating'
            run.assert_not_called()


def test_publish_is_atomic_on_summary_failure():
    conn = _make_db()
    selected = {'AAA': [article()]}
    summaries, events = brief.validate(response(selected), selected)
    snap = intel.build_news_snapshot(selected)
    conn.execute('DROP TABLE news_summaries')
    conn.commit()
    # Missing summary table forces failure after event INSERT. All must roll back.
    with pytest.raises(sqlite3.OperationalError):
        brief.publish(conn, summaries, events, [], snap, selected, '2026-09-25')
    assert conn.execute('SELECT COUNT(*) FROM news_events').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM news_snapshots').fetchone()[0] == 0


def test_portfolio_context_and_no_outlook_rewrite():
    prompt = brief.build_prompt({'AAA':[article()]}, {'AAA':{'weight_pct':12, 'thesis':['Recurring revenue']}})
    assert 'Recurring revenue' in prompt and '12' in prompt
    assert article()['model_input_text'] in prompt
    assert 'ANALYST_RATING is NOT company GUIDANCE_CHANGE' in prompt


def test_selection_covers_each_holding_before_extra_articles():
    selected = brief.select_evidence({str(i): [article(str(i))]*3 for i in range(27)}, {})
    assert all(len(v) == 1 for v in selected.values())


def test_model_truncation_is_failure(tmp_path):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.__enter__.return_value.__iter__.return_value = iter([b'data: '+json.dumps({'choices':[{'finish_reason':'length','delta':{'content':'{}'}}]}).encode()])
    with patch.object(brief.urllib.request, 'urlopen', return_value=r), patch.object(brief, 'ROOT', tmp_path):
        with pytest.raises(ValueError, match='output budget'):
            brief.call_model('prompt', 1)


def test_invented_numeric_claim_is_rejected():
    selected = {'AAA': [article()]}
    result = response(selected)
    result['holdings']['AAA']['news'] = 'Revenue rose 97%.'
    with pytest.raises(ValueError, match='Unsupported numeric fact'):
        brief.validate(result, selected)


def test_compact_model_response_retains_contract():
    selected = {'AAA':[article()]}
    compact = {'rows': {'AAA': ['material','GUIDANCE_CHANGE','POSITIVE','MEDIUM',
        'Revenue guidance rose to $20 million.', 'This could support growth.', 'Watch reported revenue.',
        [intel._article_id(article())]]}}
    summaries, events = brief.validate(compact, selected)
    assert summaries['AAA']['news'] == events['AAA'][0]['evidence']
    assert events['AAA'][0]['causal_event_key']


def api_handler(tmp_path):
    """Load only the handler AST: importing serve would start scheduled production work."""
    import ast
    import threading
    from pathlib import Path
    import time_utils
    tree = ast.parse((Path(__file__).resolve().parents[1]/'serve.py').read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_handle_news_summary')
    module = ast.Module(body=[fn], type_ignores=[])
    ns = {'_news_summary_generating': False, '_news_summary_lock': threading.Lock(),
          'threading': threading, 'time': time, 'json': json, 'PROJECT_DIR': tmp_path}
    for name in ('today_eastern','now_utc','parse_timestamp','format_eastern'):
        ns[name] = getattr(time_utils, name)
    exec(compile(module, 'serve.py', 'exec'), ns)
    return ns['_handle_news_summary']


def test_api_retains_previous_brief_and_reports_failure(tmp_path):
    import portfolio_ai
    from unittest.mock import MagicMock
    handler = api_handler(tmp_path)
    brief.atomic_json(tmp_path/'out/news_brief_state.json', {'status':'error', 'error':'Deadline reached', 'finished_epoch':time.time()})
    old = {'AAA':{'news':'Prior brief'}, '_holdings':['AAA']}
    self = MagicMock()
    with patch.object(brief, 'latest', return_value=(old,'2026-09-24 12:00:00')), \
         patch.object(portfolio_ai, '_load_holdings_csv', return_value=[{'Stock':'AAA'}]), \
         patch('threading.Thread') as thread:
        handler(self, {})
        thread.assert_not_called()
    result = self._json.call_args.args[0]
    assert result['status'] == 'error'
    assert result['summaries'] == old and result['stale']
    assert result['error'] == 'Deadline reached'


def test_api_does_not_start_second_external_job(tmp_path):
    import portfolio_ai
    from unittest.mock import MagicMock
    handler = api_handler(tmp_path)
    brief.atomic_json(tmp_path/'out/news_brief_state.json', {'status':'generating','started_epoch':time.time()})
    self = MagicMock()
    with patch.object(brief, 'latest', return_value=(None,None)), \
         patch.object(brief, 'generation_running', return_value=True), \
         patch.object(portfolio_ai, '_load_holdings_csv', return_value=[]), \
         patch('threading.Thread') as thread:
        handler(self, {'force':['1']})
        thread.assert_not_called()
    assert self._json.call_args.args[0]['status'] == 'generating'


def test_commentary_cannot_be_promoted_to_fresh_company_event():
    a = article()
    a['title'] = 'Why AAA is a Good Investment at Today’s Price'
    selected = {'AAA':[a]}
    result = response(selected)
    summaries, events = brief.validate(result, selected)
    assert summaries['AAA']['status'] == 'no_material_change'
    assert events['AAA'] == []
    assert summaries['AAA']['news'].startswith('Background commentary:')


def test_direct_downgrade_outranks_newer_commentary():
    direct = dict(article(), title='Netflix Edges Higher Despite HSBC Engagement Expectations Cut')
    opinion = dict(article(), title='Jim Cramer Wants To Focus On The Fundamentals For Netflix')
    assert brief.rank_article(direct) > brief.rank_article(opinion)


def test_current_holdings_quantities_determine_weights():
    rows = [{'Stock':'AAA','Shares':'2'}, {'Stock':'AAA','Shares':'3'}, {'Stock':'BBB','Shares':'5'}]
    prices = {'AAA':{'price':10,'weight_pct':90}, 'BBB':{'price':30,'weight_pct':10}}
    result = brief.current_position_prices(rows, prices)
    assert result['AAA']['weight_pct'] == 25
    assert result['BBB']['weight_pct'] == 75
    assert prices['AAA']['weight_pct'] == 90
    assert brief.current_position_prices(rows, {'AAA':{'price':10}})['AAA']['weight_pct'] is None


def test_maintenance_runs_without_optional_dotenv(tmp_path):
    import sys
    import portfolio_ai as pai
    from agents.news import maintenance
    with patch.dict(sys.modules, {'dotenv':None}), \
         patch.object(pai, '_init_ai_tables'), \
         patch.object(pai, '_load_holdings_csv', side_effect=RuntimeError('stop after maintenance')), \
         patch.object(maintenance, 'run_daily_sweep') as sweep, \
         patch.object(pai, 'DB_PATH', tmp_path/'investment.db'), \
         patch('agent_db.DB_PATH', tmp_path/'investment.db'), \
         patch.object(maintenance, '_DB_PATH', tmp_path/'investment.db'):
        with pytest.raises(RuntimeError, match='stop after maintenance'):
            brief.worker({'db_path':str(tmp_path/'investment.db')})
        sweep.assert_called_once()


def test_orphaned_generation_marker_does_not_block_refresh(tmp_path):
    import portfolio_ai
    from unittest.mock import MagicMock
    handler = api_handler(tmp_path)
    brief.atomic_json(tmp_path/'out/news_brief_state.json', {'status':'generating','started_epoch':time.time()})
    self = MagicMock()
    with patch.object(brief, 'latest', return_value=(None,None)), \
         patch.object(brief, 'generation_running', return_value=False), \
         patch.object(portfolio_ai, '_load_holdings_csv', return_value=[]), \
         patch('threading.Thread') as thread:
        handler(self, {'force':['1']})
        thread.return_value.start.assert_called_once()


def test_generation_liveness_tracks_lock_not_old_marker(tmp_path):
    import fcntl
    db = tmp_path/'investment.db'
    assert not brief.generation_running(db)
    with open(tmp_path/'news_brief.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert brief.generation_running(db)
    assert not brief.generation_running(db)


def test_subscriber_feeds_and_direct_publisher_duplicate_priority(tmp_path, monkeypatch):
    import news_fetcher as nf
    from email.utils import formatdate
    from urllib.error import HTTPError
    monkeypatch.setattr(nf, 'SUBSCRIBER_FEEDS', [
        ('WSJ', 'https://feeds.content.dowjones.io/public/rss/business'),
        ('Barrons', 'https://feeds.a.dj.com/rss/BarronsFront.xml')])
    monkeypatch.setattr(nf, 'PUBLIC_FEEDS', [])
    monkeypatch.setattr(nf, '_get_dj_cookies', lambda allow_login: 'secret' if not allow_login else None)
    monkeypatch.setattr(nf, '_build_matcher', lambda *a: lambda text: True)
    monkeypatch.setattr(nf, '_parenthetical_mismatch', lambda *a: False)
    calls = []
    class Feed:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            return ('<rss><channel><item><title>AAA raises guidance</title>'
                    '<link>https://wsj.com/article</link><pubDate>'+formatdate(usegmt=True)+
                    '</pubDate><description>Revenue guidance rises.</description>'
                    '</item></channel></rss>').encode()
    def fetch(req, timeout):
        calls.append(req)
        if 'BarronsFront' in req.full_url:
            raise HTTPError(req.full_url, 403, 'Forbidden', {}, None)
        return Feed()
    monkeypatch.setattr(brief.urllib.request, 'urlopen', fetch)
    result = brief.fetch_evidence(['AAA'], True, time.monotonic()+1, tmp_path)
    assert result['by_ticker']['AAA'][0]['source'] == 'WSJ'
    assert len(result['by_ticker']['AAA']) == 1
    assert result['subscriber_credentials_available']
    assert any(h.get('http_status') == 403 for h in result['source_health'])
    assert 'secret' not in json.dumps(result)
    for req in calls:
        if 'finance.yahoo.com' in req.full_url:
            assert not req.has_header('Cookie')
        else:
            assert req.unredirected_hdrs['Cookie'] == 'secret'
            assert 'Cookie' not in req.headers
            redirected = brief.urllib.request.HTTPRedirectHandler().redirect_request(
                req, None, 302, 'Found', {}, 'https://other.example/')
            assert not redirected.has_header('Cookie')


def test_fast_auth_never_attempts_sso(tmp_path, monkeypatch):
    import news_fetcher as nf
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a: None)
    monkeypatch.setattr(nf, 'SESSION_FILE', tmp_path/'session')
    for key in ('WSJ_TAC', 'WSJ_TR', 'WSJ_SESSION'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('WSJ_EMAIL', 'example@example.com')
    monkeypatch.setenv('WSJ_PASSWORD', 'secret')
    with patch.object(nf, '_dj_login') as login:
        assert nf._get_dj_cookies(allow_login=False) is None
        login.assert_not_called()
    monkeypatch.setenv('WSJ_TAC', 'saved-token')
    assert nf._get_dj_cookies(allow_login=False) == '__tac=saved-token'
