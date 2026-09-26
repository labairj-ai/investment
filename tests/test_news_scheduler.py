from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from agents.news.scheduler import run_due_refresh


def moment(hour=6):
    return datetime(2026,9,26,hour,tzinfo=ZoneInfo('America/New_York'))


def test_weekend_six_am_runs_once_and_survives_restart(tmp_path):
    fn=Mock(return_value=True); path=tmp_path/'slot.json'
    assert run_due_refresh(moment(5),path,fn) is None
    assert run_due_refresh(moment(),path,fn)['status']=='ready'
    assert run_due_refresh(moment()+timedelta(minutes=20),path,fn) is None
    fn.assert_called_once_with('06','2026-09-26')
    assert run_due_refresh(moment(12),path,fn)['slot']=='12'


def test_failure_retries_with_backoff_and_stops_after_three(tmp_path):
    fn=Mock(return_value=False); path=tmp_path/'slot.json'; now=moment()
    assert run_due_refresh(now,path,fn)['attempts']==1
    assert run_due_refresh(now+timedelta(minutes=4),path,fn) is None
    assert run_due_refresh(now+timedelta(minutes=5),path,fn)['attempts']==2
    assert run_due_refresh(now+timedelta(minutes=10),path,fn)['attempts']==3
    assert run_due_refresh(now+timedelta(minutes=20),path,fn) is None
    assert fn.call_count==3


def test_restart_only_catches_up_latest_due_slot(tmp_path):
    fn=Mock(return_value=True)
    run_due_refresh(moment(18),tmp_path/'slot.json',fn)
    fn.assert_called_once_with('17','2026-09-26')


def test_busy_worker_does_not_mark_slot_success_or_consume_attempt(tmp_path):
    fn=Mock(side_effect=[None,True]); path=tmp_path/'slot.json'
    state=run_due_refresh(moment(),path,fn)
    assert state['status']=='error' and state['attempts']==0
    assert run_due_refresh(moment()+timedelta(minutes=5),path,fn)['status']=='ready'


def test_legacy_attempt_marker_is_not_assumed_success(tmp_path):
    from agents.news.brief import atomic_json
    path=tmp_path/'slot.json'
    atomic_json(path,{'day':'2026-09-26','slot':'06'})
    fn=Mock(return_value=True)
    assert run_due_refresh(moment(8),path,fn)['status']=='ready'
    fn.assert_called_once()
