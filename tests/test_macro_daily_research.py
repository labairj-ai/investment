"""The displayed signed rule is tested prospectively, with no live influence."""
import json
import sqlite3
import time
from datetime import datetime

import pytest
import agent_db
from agents.learning import macro_experiment as mx


def snap(rate=10, inflation=1, dollar=1):
    return {'coverage_state':'company_supported', 'coverage_certified':True,
            'usable_dimensions':['rate_sensitivity','inflation_hedge','dollar_sensitivity'],
            'rate_sensitivity':{'score':rate}, 'inflation_hedge':{'score':inflation},
            'dollar_sensitivity':{'score':dollar}}


def test_signed_rule_matches_panel_and_does_not_reinterpret_old_protocol():
    p=mx.load_protocol()
    from portfolio_ai import compute_regime_adjusted_risk
    scores=snap(rate=8,inflation=4,dollar=6)
    stress={'rate_stress':.5,'dollar_stress':-.4}
    interactions=compute_regime_adjusted_risk(scores,stress)
    expected=-5/3*sum(interactions[k] for k in ('rate_sensitivity_regime_risk','inflation_hedge_regime_risk','dollar_sensitivity_regime_risk'))
    assert mx.adjustment(scores,p,regime_stress=stress)==pytest.approx(expected)
    legacy=json.loads(mx.PROTOCOL_PATH.with_name('macro_experiment_v2.json').read_text())
    assert mx.adjustment(scores,legacy)==pytest.approx(5*sum(legacy['dimension_weights'][d]*(scores[d]['score']-5.5)/4.5 for d in scores['usable_dimensions']))
    assert mx.adjustment(snap(),p,['rate_sensitivity'],{'rate_stress':.5})<0
    assert mx.adjustment(snap(),p,['rate_sensitivity'],{'rate_stress':-.5})>0
    assert mx.adjustment(snap(inflation=10),p,['inflation_hedge'],{'rate_stress':.5})>0
    with pytest.raises(ValueError,match='regime'):
        mx.adjustment(snap(),p)
    with pytest.raises(ValueError,match='missing interaction'):
        mx.adjustment(snap(),p,['dollar_sensitivity'],{'rate_stress':.5})
    with pytest.raises(ValueError,match='invalid frozen'):
        mx.adjustment(snap(rate=float('nan')),p,regime_stress=stress)


@pytest.fixture
def research(tmp_path,monkeypatch):
    from agents import opportunity_agent as oa
    from agents.learning import macro_provenance as prov
    import macro_context
    at=datetime(2026,11,16,17,tzinfo=mx.ET).timestamp()
    monkeypatch.setattr(mx.time,'time',lambda:at)
    monkeypatch.setattr(agent_db,'DB_PATH',tmp_path/'research.db')
    agent_db.DB_PATH.touch();agent_db.migrate()
    with agent_db._connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS macro_regime_snapshots(snapshot_date TEXT PRIMARY KEY,regime_json TEXT,created_at TEXT)')
        c.commit()
    acc={'record_id':'accepted','accepted_at':1,'scorer_contract_hash':'scorer','config_version':'v1.8','config_hash':'config','model_identity':'model'}
    monkeypatch.setattr(mx,'accepted_contract',lambda *a:acc)
    monkeypatch.setattr(mx,'base_contract',lambda:'base')
    monkeypatch.setattr(macro_context,'fetch',lambda:{'regime':{'rate':{'yield_10y_63d_chg_bps':150},'dollar':{'uup_63d_pct':0},'volatility':{}}})
    monkeypatch.setattr(oa,'_get_buffett_winners',lambda:[{'ticker':'AAA','quality_score':60,'price':100,'sector':'Technology'}, {'ticker':'BBB','quality_score':59,'price':100,'sector':'Industrials'}])
    monkeypatch.setattr(oa,'_get_manual_candidates',lambda:[])
    monkeypatch.setattr(oa,'_get_current_tickers',lambda:set())
    monkeypatch.setattr(oa,'_get_layer_weights',lambda:{})
    monkeypatch.setattr(oa,'_get_holding_sectors',lambda *a:{})
    monkeypatch.setattr(oa,'_score_quality',lambda w:w['quality_score'])
    monkeypatch.setattr(oa,'_score_valuation',lambda w:0)
    monkeypatch.setattr(oa,'_score_portfolio_fit',lambda *a:(0,{}))
    monkeypatch.setattr(oa,'_score_catalyst',lambda w:0)
    monkeypatch.setattr(oa,'_score_evidence',lambda w:0)
    monkeypatch.setattr(oa,'_composite',lambda q,*a:q)
    def frozen(ticker,conn,at):
        s=snap(rate=10 if ticker=='AAA' else 1)
        s['usable_dimensions']=['rate_sensitivity']
        s.update(macro_acceptance_record_id='accepted',scorer_contract_hash='scorer',macro_config_hash='config',prompt_hash='prompt',evidence_hash='evidence',macro_score_timestamp=at-1)
        return s
    monkeypatch.setattr(prov,'snapshot',frozen)
    monkeypatch.setattr(oa,'_llm_select',lambda *a:pytest.fail('research must not call LLM selection'))
    return at


def test_daily_capture_works_without_underweight_or_recommendations_and_deduplicates(research):
    first=mx.collect_daily_research()
    assert first['status']=='OBSERVED' and first['diverged']
    second=mx.collect_daily_research()
    assert second['status']=='already_collected' and second['cohort_id']==first['cohort_id']
    with agent_db._connect() as c:
        row=c.execute('SELECT * FROM macro_experiment_cohorts').fetchone()
        assert (row['control_ticker'],row['macro_ticker'])==('AAA','BBB')
        assert c.execute('SELECT count(*) FROM recommendations').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM trade_intents').fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM agent_runs WHERE agent_type='macro_research' AND status='done'").fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM decision_episodes WHERE selected=1').fetchone()[0]==0
        assert all(r[0].startswith('MACRO_') for r in c.execute('SELECT book_id FROM virtual_fills'))
        # Later regime data cannot change the original adjustment/ranking.
        old=c.execute('SELECT macro_score FROM macro_experiment_candidates ORDER BY ticker').fetchall()
        c.execute("UPDATE macro_regime_snapshots SET regime_json='{}'");c.commit()
        assert c.execute('SELECT macro_score FROM macro_experiment_candidates ORDER BY ticker').fetchall()==old


def test_no_regime_or_coverage_is_visible_exclusion_not_a_recommendation(research,monkeypatch):
    import macro_context
    monkeypatch.setattr(macro_context,'fetch',lambda:{})
    report=mx.collect_daily_research()
    assert report['status']=='EXCLUDED' and report['reason']=='missing_decision_time_regime'
    with agent_db._connect() as c:
        assert c.execute('SELECT count(*) FROM virtual_fills').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM recommendations').fetchone()[0]==0
        assert mx.evaluate(c)['excluded_cohorts']==1


def test_weekend_waits_without_creating_fake_comparison(research,monkeypatch):
    monkeypatch.setattr(mx.time,'time',lambda:research-2*86400)
    assert mx.collect_daily_research()['status']=='waiting_for_trading_day'
    with agent_db._connect() as c:
        assert c.execute('SELECT count(*) FROM macro_experiment_epochs').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM macro_experiment_cohorts').fetchone()[0]==0


def test_card_has_collapsed_guide_and_read_only_progress(tmp_path,monkeypatch):
    import generate_dashboard as dashboard
    import macro_context
    monkeypatch.setattr(macro_context,'fetch',lambda:{'regime':{'rate':{'yield_10y_63d_chg_bps':150}}})
    monkeypatch.setattr(dashboard,'DB_PATH',tmp_path/'absent.db')
    html=dashboard._build_regime_stress_section({'AAA':snap()},[{'ticker':'AAA'}])
    assert '<details ' in html and '<details open' not in html
    assert 'How to read these numbers' in html
    assert 'not a predicted 39%' in html
    assert 'does not measure inflation directly' in html
    assert 'Research status unavailable' in html
    assert not (tmp_path/'absent.db').exists()
