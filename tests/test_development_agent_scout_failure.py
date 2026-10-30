"""Synthetic regression for October 25; never live acceptance."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.discovery import observer as o

LIVE='2month 1w 6d 14h 7min 28.893213s'


def test_exact_production_representation_is_not_an_integer():
    with pytest.raises(ValueError):int(LIVE)


@pytest.mark.parametrize('raw',[b't 6433648893213\n',b't 1\n'])
def test_typed_first_nonzero_trigger(monkeypatch,raw):
    def output(command,**options):
        assert command==['/usr/bin/busctl','--system','get-property','org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/development_2dscout_2etimer','org.freedesktop.systemd1.Timer','LastTriggerUSecMonotonic']
        return raw
    monkeypatch.setattr(o.subprocess,'check_output',output)
    assert o.timer_timestamp({})==int(raw[2:])


@pytest.mark.parametrize('raw',[b't 0\n',LIVE.encode(),b't -1\n',b's 123\n',b't 18446744073709551616\n',b't 1\nsecret',b''])
def test_zero_absent_malformed_timer_fails_closed(monkeypatch,raw):
    monkeypatch.setattr(o.subprocess,'check_output',lambda *a,**k:raw)
    with pytest.raises(o.TrustFailure,match='TIMER_TRIGGER_INVALID'):o.timer_timestamp({})


@pytest.fixture
def system(monkeypatch):
    h=SimpleNamespace(fired=6433648893213,invocation='a'*32,env=None,timer={},real=1793304006896140,phase='begin',job_id=77,job_changes={})
    h.values=dict(RequiredBy='',WantedBy='',UpheldBy='',BoundBy='',ConsistsOf='',ControlPID='123',InvocationID=h.invocation,FragmentPath='/etc/systemd/system/development-scout.service',DropInPaths='',NeedDaemonReload='no',Result='success',PrivateNetwork='yes',NoNewPrivileges='yes',ProtectSystem='strict',ProtectHome='read-only',RefuseManualStart='yes',TriggeredBy='development-scout.timer',User='optiplex',Group='optiplex',WorkingDirectory=str(o.ROOT))
    monkeypatch.setattr(o.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=123,pw_gid=123))
    monkeypatch.setattr(o.time,'monotonic',lambda:h.fired/1e6+1)
    monkeypatch.setattr(o.time,'time',lambda:h.real/1e6+1)
    monkeypatch.setattr(o,'file_hash',lambda p:'reviewed')
    def output(cmd,**kw):
        assert '--user' not in cmd and 'user' not in kw and 'XDG_RUNTIME_DIR' not in kw['env']
        if cmd[0]=='/usr/bin/busctl':
            if any(n in cmd for n in ('ExecStartPre','ExecStopPost','ExecStart')):return json.dumps(dict(type='a(sasbttttuii)',data=[['/usr/bin/python3',['/usr/bin/python3','-I','-S',str(o.SOURCE),'end' if 'ExecStopPost' in cmd else 'scout' if 'ExecStart' in cmd else 'begin'],False,h.real,h.fired,0,0,123,0,0]])).encode()
            if 'InactiveExitTimestampMonotonic' in cmd:return json.dumps(dict(type='t',data=h.fired-3600_000_000 if '/org/freedesktop/systemd1/unit/development_2dscout_2etimer' in cmd else h.fired)).encode()
            if '--json=short' in cmd:
                prop=cmd[-1]
                defaults={'Job':('(uo)',[h.job_id,'/org/freedesktop/systemd1/job/'+str(h.job_id)]),'Id':('u',h.job_id),'Unit':('(so)',['development-scout.service','/org/freedesktop/systemd1/unit/development_2dscout_2eservice']),'JobType':('s','start'),'State':('s','running'),'LastTriggerUSecMonotonic':('t',h.fired),'LastTriggerUSec':('t',h.real)}
                if prop=='ActivationDetails':return h.env if h.env is not None else json.dumps(dict(type='a(ss)',data=[['trigger_unit','development-scout.timer'],['trigger_timer_monotonic_usec',str(h.fired)],['trigger_timer_realtime_usec',str(h.real)]])).encode()
                kind,data=h.job_changes.get(prop,defaults[prop]);return json.dumps(dict(type=kind,data=data)).encode()
            return f't {h.fired}\n'.encode()
        if cmd[-1].startswith('--property=InvocationID,ControlPID,ActiveState,SubState'):return f'ControlPID=123\nMainPID=123\nInvocationID={h.invocation}\nActiveState={"deactivating" if h.phase=="end" else "activating"}\nSubState={"start" if h.phase=="scout" else "stop-post" if h.phase=="end" else "start-pre"}\n'.encode()
        data=dict(LastTriggerUSecMonotonic=LIVE,FragmentPath='/etc/systemd/system/development-scout.timer',DropInPaths='',NeedDaemonReload='no',ActiveState='active',UnitFileState='enabled',**h.timer) if 'development-scout.timer' in cmd else h.values
        return '\n'.join(k+'='+v for k,v in data.items()).encode()
    monkeypatch.setattr(o.subprocess,'check_output',output)
    def read(p):
        if p.name=='environ':return h.env if h.env is not None else f'INVOCATION_ID={h.invocation}\0TRIGGER_UNIT=development-scout.timer\0TRIGGER_TIMER_MONOTONIC_USEC={h.fired}\0'.encode()
        return b'\0'.join([b'/usr/bin/python3',b'-I',b'-S',str(o.SOURCE).encode(),b'begin',b''])
    monkeypatch.setattr(Path,'read_bytes',read)
    monkeypatch.setattr(Path,'read_text',lambda p:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    h.run=lambda:o.systemd(dict(unit_digest='reviewed',timer_digest='reviewed'),123,'begin')
    return h


def test_genuine_activation_uses_typed_value_despite_live_formatted_show(system):
    assert system.run()==dict(invocation='a'*32,timer_fire='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:6433648893213',provenance=dict(job_id=77,boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',timer_monotonic_usec=system.fired,timer_realtime_usec=system.real,timer_active_since_monotonic_usec=system.fired-3600_000_000))


@pytest.mark.parametrize('attack',['manual','stale','wrong_timer','wrong_pid','wrong_invocation','missing_metadata','wrong_metadata','manual_allowed'])
def test_provenance_attacks_fail_closed(system,monkeypatch,attack):
    if attack=='manual':system.env=b'{"type":"a(ss)","data":[]}'
    if attack=='stale':monkeypatch.setattr(o.time,'monotonic',lambda:system.fired/1e6+181)
    if attack=='wrong_timer':system.values['TriggeredBy']='other.timer'
    if attack=='wrong_pid':system.values['ControlPID']='999'
    if attack=='wrong_invocation':system.invocation='b'*32
    if attack=='missing_metadata':system.env=b'{"type":"a(ss)","data":[]}'
    if attack=='wrong_metadata':system.env=f'INVOCATION_ID={system.invocation}\0TRIGGER_UNIT=other.timer\0TRIGGER_TIMER_MONOTONIC_USEC={system.fired}\0'.encode()
    if attack=='manual_allowed':system.values['RefuseManualStart']='no'
    with pytest.raises((o.TrustFailure,ValueError)):system.run()


def test_sanitized_diagnostics_never_emit_exception_text(capsys):
    for e in [ValueError('/secret/path credential=holdings database contents'),o.TrustFailure('SANDBOX_PROBE_FAILED'),o.TrustFailure('SECRET')]:o.root_failure(e)
    assert capsys.readouterr().err=='DISCOVERY_OBSERVER_FAILURE BOOKEND_INVALID\nDISCOVERY_OBSERVER_FAILURE SANDBOX_PROBE_FAILED\nDISCOVERY_OBSERVER_FAILURE BOOKEND_INVALID\n'


def test_failed_prestart_has_no_evidence_and_next_distinct_slot_proceeds(tmp_path,monkeypatch):
    monkeypatch.setattr(o,'STATE',tmp_path)
    monkeypatch.setattr(o.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=123))
    server=o.Observer(dict(head='a'*40));request=dict(phase='begin',checks={k:True for k in o.CHECKS})
    def fail(*a):raise o.TrustFailure('TIMER_TRIGGER_INVALID')
    monkeypatch.setattr(o,'systemd',fail)
    with pytest.raises(o.TrustFailure):server.handle(123,123,request)
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(o,'systemd',lambda *a:dict(invocation='b'*32,timer_fire='next-genuine-slot'))
    monkeypatch.setattr(o,'snapshot',lambda c:({},[]))
    server.handle(123,123,request)
    assert (tmp_path/('b'*32+'.pending')).exists()
    assert not (tmp_path/'discovery.json').exists()  # still 0/3; begin never grants credit
    with pytest.raises(ValueError):server.handle(123,123,request)  # replay


def test_failed_sandbox_is_first_invariant_and_never_queries_timer(tmp_path,monkeypatch):
    monkeypatch.setattr(o.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=123))
    monkeypatch.setattr(o,'systemd',lambda *a:pytest.fail('must reject before systemd'))
    with pytest.raises(o.TrustFailure,match='SANDBOX_PROBE_FAILED'):
        o.Observer({}).handle(123,123,dict(phase='begin',checks={k:False for k in o.CHECKS}))


def test_client_failure_contains_no_root_reason(monkeypatch):
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def settimeout(self,*a):pass
        def connect(self,*a):pass
        def sendall(self,*a):pass
        def recv(self,*a):return b'FAILED\n'
    monkeypatch.setattr(o.socket,'socket',lambda *a:Channel())
    monkeypatch.setattr(o,'probes',lambda:{})
    with pytest.raises(ValueError,match='^trusted discovery observation failed$'):o.client('begin')


def test_root_response_emits_only_fixed_reason_and_failed(capsys):
    class Reject:
        def handle(self,*args):raise o.TrustFailure('SANDBOX_PROBE_FAILED')
    raw=b'{"credential":"secret","holdings":"sensitive"}\n'
    assert o.respond(Reject(),123,123,raw)==b'FAILED\n'
    assert capsys.readouterr().err=='DISCOVERY_OBSERVER_FAILURE SANDBOX_PROBE_FAILED\n'
    class Unexpected:
        def handle(self,*args):raise ValueError('/sensitive/path secret database holdings')
    assert o.respond(Unexpected(),123,123,raw)==b'FAILED\n'
    assert capsys.readouterr().err=='DISCOVERY_OBSERVER_FAILURE BOOKEND_INVALID\n'


def test_system_scout_daily_only_schedule_in_reviewed_source():
    timer=Path('systemd/development-scout.timer').read_text()
    assert [l for l in timer.splitlines() if l.startswith('OnCalendar=')]==[
        'OnCalendar=*-*-* 16:00:00 America/New_York']
    assert 'RefuseManualStart=yes' in Path('systemd/development-scout.service').read_text()


def test_typed_first_nonzero_value_does_not_authorize_early_boot_catchup(system):
    system.fired=1
    assert o.timer_timestamp(dict(env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'}))==1
    with pytest.raises(o.TrustFailure,match='TIMER_TRIGGER_INVALID'):system.run()


@pytest.mark.parametrize('raw,recent,expected',[
    ('t 6433648893213\n',True,'systemd-observed-timer'),
    ('t 6433648893213\n',False,'operator'),
    (LIVE,True,'operator'),('t 0\n',True,'operator'),
    ('t 18446744073709551616\n',True,'operator'),('s 123\n',True,'operator')])
def test_scout_scheduler_uses_same_typed_timestamp(system,monkeypatch,raw,recent,expected):
    from dev_agent import scheduler, discovery
    system.phase='scout'
    monkeypatch.setenv('INVOCATION_ID',system.invocation)
    monkeypatch.setattr(scheduler.os,'getpid',lambda:123)
    monkeypatch.setattr(o,'protected',lambda p:None)
    config=dict(head='a'*40,observer_digest='reviewed',unit_digest='reviewed',timer_digest='reviewed')
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda p:o.encoded(config) if p==o.CONFIG else original(p))
    monkeypatch.setattr(discovery,'git',lambda *a:'a'*40)
    base=o.subprocess.check_output
    def output(cmd,**kw):
        if cmd[0]=='/usr/bin/busctl' and '--json=short' not in cmd:return raw.encode()
        return base(cmd,**kw)
    monkeypatch.setattr(o.subprocess,'check_output',output)
    monkeypatch.setattr(o.time,'monotonic',lambda:system.fired/1e6+(1 if recent else 181))
    assert scheduler.trigger()['source']==expected
