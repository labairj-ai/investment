"""Isolated upgrade host; no real systemd, Scout or investment writes."""
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.discovery import pin_refresh as r,upgrade as u
from test_development_agent_observer_refresh import host


@pytest.fixture
def upgrade_host(host,monkeypatch):
    h=host
    monkeypatch.setattr(u.time,'time',lambda:1792929600.0)
    h.git('branch','-M','main')
    for name in u.CHANGED:(h.ROOT/name).write_text('new reviewed '+name+'\n')
    (h.ROOT/r.IDENTITIES[3]).write_text('OnCalendar=*-*-* 08:15:00 America/New_York\nOnCalendar=2026-10-25 12:15:00 America/New_York\n')
    h.git('add','.');h.git('commit','-qm','reviewed boundary');h.head=h.git('rev-parse','HEAD');h.git('update-ref','refs/remotes/origin/main',h.head)
    monkeypatch.setattr(u,'OLD_HEAD',h.old)
    monkeypatch.setattr(u,'OLD_EXECUTABLE',h.old_config['observer_digest'])
    monkeypatch.setattr(u,'OLD_UNIT',h.old_config['files'][r.IDENTITIES[1]])
    monkeypatch.setattr(u,'OLD_SCOUT_SERVICE',h.old_config['files'][r.IDENTITIES[2]])
    monkeypatch.setattr(u,'OLD_SCOUT_TIMER',h.old_config['files'][r.IDENTITIES[3]])
    (h.ROOT/'holdings.csv').write_text('synthetic')
    (h.ROOT/'out').mkdir()
    for name in ('investment.db','buffett.db'):(h.ROOT/'out'/name).write_bytes(b'synthetic')
    h.git('add','.');h.git('commit','-qm','fixture financial files');h.head=h.git('rev-parse','HEAD');h.git('update-ref','refs/remotes/origin/main',h.head)
    for name in r.IDENTITIES[2:]:
        (h.USER_UNITS/Path(name).name).write_bytes(r.git(h.ROOT,'show',h.old+':'+name))
    original=h.invoke
    h.reloads=0
    def invoke(args,**kw):
        if args[0]=='/usr/bin/busctl':
            h.calls.append(args)
            return SimpleNamespace(returncode=0,stdout=f't {int((time.time()+86400)*1e6)}\n')
        if args[:2]==['/usr/bin/systemctl','--user']:
            h.calls.append(args)
            if args[2]=='daemon-reload':h.reloads+=1;return SimpleNamespace(returncode=0,stdout='')
            assert args[2]=='show' and args[3] in {'development-scout.service','development-scout.timer'}
            return SimpleNamespace(returncode=0,stdout='\n'.join(k+'='+v for k,v in dict(FragmentPath=str(h.USER_UNITS/args[3]),DropInPaths='',NeedDaemonReload='no',ActiveState='active' if args[3].endswith('.timer') else 'failed',ControlPID='0',MainPID='0').items()))
        return original(args,**kw)
    h.upgrade=lambda **kw:u.upgrade(h.ROOT,h.head,h.old,invoke=invoke,**kw)
    return h


def test_plan_only_preserves_all_files(upgrade_host):
    h=upgrade_host;before=h.snapshot();config=h.CONFIG.read_bytes()
    result=h.upgrade()
    assert result['status']=='PLAN_ONLY' and h.starts==h.stops==h.reloads==0
    assert before==h.snapshot() and config==h.CONFIG.read_bytes()
    assert not list(h.CONFIG.parent.glob('observer-upgrade*'))


@pytest.mark.parametrize('attack',['old_head','old_digest','old_unit','dirty','wrong_checkout','not_origin_main','untracked','accepted_history'])
def test_bad_upgrade_source_fails_before_stop(upgrade_host,monkeypatch,attack):
    h=upgrade_host
    if attack=='old_head':monkeypatch.setattr(u,'OLD_HEAD','0'*40)
    if attack=='old_digest':h.SOURCE.write_text('wrong')
    if attack=='old_unit':h.UNIT.write_text('wrong')
    if attack=='dirty':(h.ROOT/'docs/help.md').write_text('dirty')
    if attack=='wrong_checkout':h.git('checkout','--detach','-q')
    if attack=='not_origin_main':h.git('update-ref','refs/remotes/origin/main',h.old)
    if attack=='untracked':(h.ROOT/'untracked').write_text('extra')
    if attack=='accepted_history':(h.STATE/'discovery.json').write_text('{"runs":[{"invocation":"actual"}]}')
    with pytest.raises(ValueError):h.upgrade(apply=True)
    assert h.starts==h.stops==h.reloads==0


def test_atomic_upgrade_preserves_failure_evidence_and_zero_credit(upgrade_host,monkeypatch):
    h=upgrade_host
    evidence={'timer-fires.json':b'["old-failed-fire"]','a'*32+'.pending':b'{"failed":true}'}
    for name,data in evidence.items():(h.STATE/name).write_bytes(data)
    replacements=[];original=u.os.replace
    def replace(source,dest):
        assert not h.active
        assert source.parent==dest.parent
        replacements.append(dest);return original(source,dest)
    monkeypatch.setattr(u.os,'replace',replace)
    result=h.upgrade(apply=True)
    assert result['status']=='UPGRADED_AWAITING_GENUINE_TIMER_RUNS' and not result['ready']
    assert result['accepted_runs']==0 and result['grants_implementation'] is False
    assert h.starts==h.stops==h.reloads==1
    assert len(replacements)==4
    assert {p.name:p.read_bytes() for p in h.STATE.iterdir()}==evidence
    assert h.SOURCE.read_bytes()==(h.ROOT/u.CHANGED[0]).read_bytes()
    assert not (h.STATE/'discovery.json').exists()
    assert not any('development-scout' in a and any(v in a for v in ['start','stop','enable','restart']) for a in h.calls)
    assert not any(a==['/bin/systemctl','daemon-reload'] for a in h.calls)
    backup=Path(result['backup'])
    assert (backup/'0').read_bytes()==r.git(h.ROOT,'show',h.old+':'+u.CHANGED[0])


@pytest.mark.parametrize('failure',['restart','socket','config','digest','runtime'])
def test_restart_verification_rolls_back_exact_files_and_stops(upgrade_host,failure):
    h=upgrade_host;h.fail=failure
    paths=[h.SOURCE,h.CONFIG,h.USER_UNITS/'development-scout.service',h.USER_UNITS/'development-scout.timer'];before=[p.read_bytes() for p in paths]
    result=h.upgrade(apply=True)
    assert result['status']=='ROLLED_BACK_NOT_READY' and result['observer_stopped']
    assert not result['ready'] and [p.read_bytes() for p in paths]==before
    assert not h.active and result['exact_old_files_restored']
    assert Path(result['backup']).is_dir() and not list(h.STATE.iterdir())


def test_failed_rollback_stays_stopped_not_ready(upgrade_host,monkeypatch):
    h=upgrade_host;h.fail='restart';original=u.replace;count=[0]
    def replace(*args):
        count[0]+=1
        if count[0]>4:raise OSError('fixture disk failure')
        return original(*args)
    monkeypatch.setattr(u,'replace',replace)
    result=h.upgrade(apply=True)
    assert result['status']=='FAILED_STOPPED_NOT_READY' and result['observer_stopped']
    assert not result['exact_old_files_restored'] and not h.active and not result['ready']


def test_config_only_refresh_still_refuses_boundary_upgrade(upgrade_host):
    with pytest.raises(ValueError,match='separately reviewed full upgrade'):upgrade_host.run()


@pytest.mark.parametrize('attack',['extra','missing','wrong_day','late'])
def test_recovery_calendar_is_exact_and_future(monkeypatch,attack):
    data=b'OnCalendar=*-*-* 08:15:00 America/New_York\nOnCalendar=2026-10-25 12:15:00 America/New_York\n'
    monkeypatch.setattr(u.time,'time',lambda:1792929600.0)
    if attack=='extra':data+=b'OnCalendar=2026-10-25 15:00:00 America/New_York\n'
    if attack=='missing':data=data.splitlines()[0]+b'\n'
    if attack=='wrong_day':data=data.replace(b'2026-10-25',b'2026-10-26')
    if attack=='late':monkeypatch.setattr(u.time,'time',lambda:1792944900.0)
    with pytest.raises(ValueError):u.recovery_schedule(data)


def test_financial_change_during_upgrade_fails_closed(upgrade_host,monkeypatch):
    h=upgrade_host;original=u.reload_scout;changed=[False]
    def reload(invoke):
        original(invoke)
        if not changed[0]:
            changed[0]=True
            (h.ROOT/'holdings.csv').write_text('independent fixture mutation')
    monkeypatch.setattr(u,'reload_scout',reload)
    result=h.upgrade(apply=True)
    assert not result['ready'] and result['observer_stopped']
