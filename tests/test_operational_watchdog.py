import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import operational_watchdog as wd


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=wd.ET).timestamp()


def test_expected_slots_respect_activation_dst_and_trading_holidays():
    slots=list(wd.due_slots(at('2026-11-02T22:00'),at('2026-10-31T19:00'),[(20,0)],grace=0))
    assert slots[1]-slots[0]==25*3600  # DST fall-back, still 20:00 ET
    slots=list(wd.due_slots(at('2026-09-08T20:00'),at('2026-09-04T20:00'),[(18,30)],sessions=True))
    assert slots==[at('2026-09-08T18:30')]  # holiday and weekend not due
    assert not list(wd.due_slots(at('2026-09-21T18:59'),at('2026-09-21T00:00'),[(18,0)]))


def test_success_is_completed_work_not_started_or_timer():
    since=at('2026-09-21T00:00');now=at('2026-09-21T23:00')
    schedule=wd.SCHEDULES['backup']
    assert wd.run_health('backup',[],now,since,schedule)['status']=='YELLOW'
    rows=[dict(record_id='a',started_at=at('2026-09-21T20:00'),completed_at=None,status='STARTED')]
    assert wd.run_health('backup',rows,now,since,schedule)['status']=='YELLOW'
    assert wd.run_health('backup',rows,now+8*3600,since,schedule)['status']=='RED'
    rows[0].update(status='FAILED',completed_at=now)
    assert wd.run_health('backup',rows,now,since,schedule)['status']=='RED'
    rows.append(dict(record_id='b',started_at=now-50,completed_at=now,status='COMPLETE'))
    assert wd.run_health('backup',rows,now,since,schedule)['status']=='INFO'


def test_incident_dedup_escalation_resolution_and_staleness(tmp_path):
    path=tmp_path/'state.db';c=wd.connect(path)
    wd.persist(c,[wd.result('test','YELLOW','late')],100)
    wd.persist(c,[wd.result('test','YELLOW','still late')],200)
    wd.persist(c,[wd.result('test','RED','failed')],300)
    wd.persist(c,[wd.result('test',reason='recovered')],400)
    rows=c.execute('SELECT * FROM watchdog_events ORDER BY detected_at').fetchall()
    assert [r['transition'] for r in rows]==['OPEN','SEVERITY_CHANGED','RESOLVED']
    assert len({r['incident_id'] for r in rows})==1
    with pytest.raises(sqlite3.IntegrityError): c.execute('DELETE FROM watchdog_events')
    assert wd.report(path,400)['overall']=='HEALTHY'
    assert wd.report(path,400+3600)['overall']=='STALE'
    assert wd.report(tmp_path/'absent',400)['overall']=='UNKNOWN'


def test_red_delivery_retries_and_daily_yellow_digest(tmp_path):
    c=wd.connect(tmp_path/'state');now=at('2026-09-21T12:00')
    wd.persist(c,[wd.result('db','RED','Unavailable'),wd.result('labels','YELLOW','Overdue')],now)
    transport=Mock(side_effect=OSError('fake'))
    wd.deliver(c,now,transport,enabled=False)
    transport.assert_not_called()
    wd.deliver(c,now,transport,enabled=True)
    wd.deliver(c,now+100,transport,enabled=True)
    assert transport.call_count==1
    transport.side_effect=None
    wd.deliver(c,now+901,transport,enabled=True)
    wd.deliver(c,now+1800,transport,enabled=True)
    assert transport.call_count==2
    wd.deliver(c,at('2026-09-21T20:05'),transport,enabled=True)
    wd.deliver(c,at('2026-09-21T20:20'),transport,enabled=True)
    assert transport.call_count==3
    wd.deliver(c,at('2026-09-22T20:05'),transport,enabled=True)
    assert transport.call_count==4


def make_business(mem_db):
    import agent_db
    c=agent_db._connect()
    from agents.learning.macro_experiment import migrate
    migrate(c)
    return c


def test_continuity_catches_no_experiment_row_and_no_receipt(mem_db,tmp_path):
    c=make_business(mem_db);s=wd.connect(tmp_path/'state')
    c.execute("INSERT INTO agent_runs(id,agent_type,started_at,finished_at,status) VALUES (1,'opportunity_hunter',1000,1100,'done')")
    c.commit()
    checks=wd.continuity(c,s,dict(activated_at=900,epoch_id='x'),2000)
    experiment=next(r for r in checks if r['component']=='macro_experiment')
    assert experiment['evidence']['expected']==1
    assert experiment['evidence']['unexplained_missing']==1
    assert experiment['status']=='RED'
    s.execute("INSERT INTO watchdog_sweeps VALUES ('1',1000,0,'[]','no_candidates')");s.commit()
    checks=wd.continuity(c,s,dict(activated_at=900,epoch_id='x'),2000)
    experiment=checks[0]
    assert experiment['status']=='INFO'
    assert experiment['evidence']['excluded']==1
    # Unknown reasons or a non-empty universe cannot manufacture a valid exclusion.
    with pytest.raises(sqlite3.IntegrityError): s.execute("UPDATE watchdog_sweeps SET candidate_n=5")
    assert wd.continuity(c,s,dict(activated_at=1200,epoch_id='x'),2000)[0]['evidence']['expected']==0


def test_due_outcomes_missing_marks_and_inception(mem_db,tmp_path):
    c=make_business(mem_db)
    since=at('2026-09-01T12:00');now=at('2026-09-09T20:00')
    # Minimal real-schema episode; inspect required fields through fixture defaults.
    c.execute("INSERT INTO decision_episodes(episode_id,ticker,captured_at,macro_epoch) VALUES ('e','AAA',?,'x')",(since,))
    c.execute("INSERT INTO virtual_books(book_id) VALUES ('b')")
    c.execute("INSERT INTO virtual_fills(book_id,created_at) VALUES ('b',?)",(at('2026-09-09T12:00'),))
    c.commit()
    findings=wd.outcomes_and_marks(c,dict(epoch_id='x',activated_at=since),now)
    assert findings[0]['status']=='YELLOW'
    assert findings[0]['evidence']['due']==1
    assert findings[1]['evidence']['missing_n']==1
    c.execute("INSERT INTO virtual_book_nav(book_id,date,is_complete,total_nav) VALUES ('b','2026-09-09',0,100)");c.commit()
    assert wd.outcomes_and_marks(c,dict(epoch_id='x',activated_at=since),now)[1]['status']=='YELLOW'
    c.execute("UPDATE virtual_book_nav SET is_complete=1");c.commit()
    assert wd.outcomes_and_marks(c,dict(epoch_id='x',activated_at=since),now)[1]['status']=='INFO'
    assert wd.outcomes_and_marks(c,dict(epoch_id='x',activated_at=since),at('2026-09-01T18:00'))[0]['evidence']['due']==0


def test_consistent_backup_contains_uncheckpointed_wal(tmp_path):
    from scripts.watchdog_backup_snapshot import snapshot
    source=tmp_path/'source.db';dest=tmp_path/'dest.db'
    c=sqlite3.connect(source);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0')
    c.execute('CREATE TABLE data(value TEXT)');c.execute("INSERT INTO data VALUES ('committed')");c.commit()
    snapshot(source,dest)
    d=sqlite3.connect(dest)
    assert d.execute('SELECT value FROM data').fetchone()[0]=='committed'
    assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    d.close();c.close()


def test_watchdog_collect_cannot_mutate_business_database(mem_db,tmp_path,monkeypatch):
    c=make_business(mem_db);c.close()
    ro=sqlite3.connect(f'file:{mem_db}?mode=ro',uri=True);ro.row_factory=sqlite3.Row
    monkeypatch.setattr(wd,'check_identity',lambda *a:[wd.result('contracts')])
    findings=wd.collect(ro,wd.connect(tmp_path/'state'),dict(activated_at=at('2026-09-21T12:00'),epoch_id='x'),at('2026-09-21T12:01'))
    assert findings
    with pytest.raises(sqlite3.OperationalError): ro.execute('DELETE FROM agent_runs')


def test_source_drift_cannot_be_silently_adopted(mem_db,monkeypatch):
    c=make_business(mem_db)
    expected=dict(acceptance={'record_id':'x'},validation_config_hash='c',protocol_hash='p',base_contract_hash='b',influence_sources={'file':'hash'},stage=0)
    monkeypatch.setattr(wd,'identity',lambda *a:{**expected,'influence_sources':{'file':'changed'},'protocol_hash':'changed'})
    findings=wd.check_identity(c,dict(identity=expected,epoch_id='x'),2000)
    assert next(r for r in findings if r['component']=='influence_lock')['status']=='RED'
    assert next(r for r in findings if r['component']=='protocol')['status']=='RED'


def test_failed_backup_propagates_instead_of_advancing_success_flag(monkeypatch):
    # serve.py starts schedulers and migrations at import; execute only this
    # function's AST so the test cannot touch a real DB or launch a job.
    import ast
    import subprocess
    source=ast.parse((wd.ROOT/'serve.py').read_text())
    node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_backup_data')
    scope={'PROJECT_DIR':wd.ROOT}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'serve.py','exec'),scope)
    run=Mock(return_value=Mock(returncode=1,stdout='',stderr='failure'))
    monkeypatch.setattr(subprocess,'run',run)
    with pytest.raises(RuntimeError,match='success flag not advanced'):
        scope['_backup_data']()
    assert 'watchdog_job.py' in run.call_args[0][0][1]


def test_fallback_failure_overrides_recent_healthy_report(tmp_path):
    path=tmp_path/'watchdog.db';c=wd.connect(path)
    wd.persist(c,[wd.result('db')],1000)
    (tmp_path/'watchdog_failure.json').write_text(json.dumps(dict(checked_at=1100,error='OSError')))
    assert wd.report(path,1100)['overall']=='RED'
    wd.persist(c,[wd.result('db')],1200)
    assert wd.report(path,1200)['overall']=='HEALTHY'


def test_resolved_incident_does_not_leave_delivery_failure_active(tmp_path):
    c=wd.connect(tmp_path/'state');now=at('2026-09-21T12:00')
    wd.persist(c,[wd.result('db','RED','down')],now)
    wd.deliver(c,now,Mock(side_effect=OSError()),enabled=True)
    assert wd.delivery_failures(c,now)==1
    wd.persist(c,[wd.result('db')],now+1)
    assert wd.delivery_failures(c,now+1)==0


def test_later_success_resolves_older_stuck_run():
    # A STARTED receipt that predates the last COMPLETE is resolved by that success —
    # consistent with "Historical resolved failures do not page forever" for FAILED records.
    rows=[dict(record_id='stuck',started_at=1000,completed_at=None,status='STARTED'),
          dict(record_id='later',started_at=30000,completed_at=31000,status='COMPLETE')]
    finding=wd.run_health('job',rows,32000,900,timeout=3600)
    assert finding['status']!='RED', (
        f"Stuck run predating last success should be resolved, got {finding['status']}: {finding['evidence']}"
    )


def test_stuck_run_after_last_success_still_fires_red():
    # A STARTED receipt that starts AFTER the last success is still unresolved — RED.
    rows=[dict(record_id='ok',started_at=1000,completed_at=2000,status='COMPLETE'),
          dict(record_id='stuck',started_at=30000,completed_at=None,status='STARTED')]
    finding=wd.run_health('job',rows,34000,900,timeout=3600)
    assert finding['status']=='RED'
    assert finding['evidence']['stuck']==['stuck']


def test_backup_backstop_accepts_verified_earlier_same_day_completion():
    rows=[dict(record_id='backup',started_at=at('2026-09-21T17:00'),completed_at=at('2026-09-21T17:01'),status='COMPLETE')]
    assert wd.run_health('backup',rows,at('2026-09-21T22:00'),at('2026-09-21T00:00'),wd.SCHEDULES['backup'])['status']=='INFO'
