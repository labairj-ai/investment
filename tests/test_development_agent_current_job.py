"""Synthetic manager/epoch contracts; no fixture grants live acceptance."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.discovery import observer as o
from dev_agent import scheduler,discovery
from test_development_agent_scout_failure import system
BASELINE_GIT_OUTPUT=o.subprocess.check_output

@pytest.mark.parametrize('day',[1,2])
@pytest.mark.parametrize('consumer',['observer','scheduler'])
def test_two_day_current_job_ignores_retained_unit_metadata(system,monkeypatch,day,consumer):
    h=system;h.fired=6807047895028 if day==1 else 6893457894997
    h.invocation='8608a7c10e9b4c23b96cf91bcc8fa51f' if day==1 else '77541c9232d74e578d6d0f596cce954d';h.values['InvocationID']=h.invocation
    h.real={1:1793304006896140,2:1793390416896108}[day]
    monkeypatch.setattr(o.time,'time',lambda:h.real/1e6+1)
    h.job_id=77+day;queries=[];base=o.subprocess.check_output
    def output(cmd,**kw):
        queries.append(cmd)
        if cmd[-2:]==['org.freedesktop.systemd1.Unit','ActivationDetails']:
            return json.dumps(dict(type='a(ss)',data=[['trigger_unit','development-scout.timer'],['trigger_timer_monotonic_usec','6807047895028']])).encode()
        return base(cmd,**kw)
    monkeypatch.setattr(o.subprocess,'check_output',output)
    if consumer=='observer':
        # Execute only the exact reviewed baseline function in the isolated fake
        # manager namespace: demonstrate red against a27, green against repair.
        import ast,subprocess
        old=BASELINE_GIT_OUTPUT(['git','show','a27bed1ebd3a69df5723212784842df456e153b3:ops/discovery/observer.py'])
        definition=next(n for n in ast.parse(old).body if isinstance(n,ast.FunctionDef) and n.name=='activation')
        scope=dict(vars(o));exec(compile(ast.Module(body=[definition],type_ignores=[]),'reviewed-a27-activation','exec'),scope)
        if day==2:
            with pytest.raises(o.TrustFailure,match='TIMER_TRIGGER_INVALID'):scope['activation'](dict(env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'}),123,h.invocation,h.fired)
        else:scope['activation'](dict(env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'}),123,h.invocation,h.fired)
        queries.clear()
        assert h.run()['invocation']==h.invocation
    else:
        h.phase='scout';monkeypatch.setenv('INVOCATION_ID',h.invocation);monkeypatch.setattr(o.os,'getpid',lambda:123)
        monkeypatch.setattr(o,'protected',lambda p:None);config=dict(head='a'*40,observer_digest='reviewed',unit_digest='reviewed',timer_digest='reviewed')
        original=Path.read_bytes;monkeypatch.setattr(Path,'read_bytes',lambda p:o.encoded(config) if p==o.CONFIG else original(p));monkeypatch.setattr(discovery,'git',lambda *a:'a'*40)
        assert scheduler.trigger()==dict(source='systemd-observed-timer',invocation=h.invocation)
    assert not any(c[-2:]==['org.freedesktop.systemd1.Unit','ActivationDetails'] for c in queries)
    assert any(c[-2:]==['org.freedesktop.systemd1.Job','ActivationDetails'] for c in queries)

@pytest.mark.parametrize('attack',['zero_invocation','operator_dependency','manual','replay','stale_job','wrong_job_id','wrong_job_path','wrong_service','wrong_timer','missing_job','wrong_type','job_waiting','conflicting','missing_realtime','wrong_pid','wrong_phase','changed_invocation','boot_changed','stale_clock','future_clock','future_real','metadata_changed','timer_changed','malformed','unavailable'])
@pytest.mark.parametrize('consumer',['observer','scheduler'])
def test_current_job_attacks_reject_without_receipt(system,monkeypatch,tmp_path,attack,consumer):
    h=system;original=o.subprocess.check_output;calls={}
    if attack=='operator_dependency':h.values['WantedBy']='operator.target'
    if attack=='zero_invocation':h.invocation='0'*32;h.values['InvocationID']=h.invocation
    def output(cmd,**kw):
        key=cmd[-1];calls[key]=calls.get(key,0)+1
        if attack=='unavailable' and key=='Job':raise OSError('private failure omitted')
        raw=original(cmd,**kw)
        if attack=='malformed' and key=='Job':return b'{bad'
        if '--json=short' in cmd:
            value=json.loads(raw);data=value['data']
            if key=='Job':
                if attack=='missing_job':value['data']=[0,'/']
                if attack=='wrong_job_path':value['data']=[77,'/org/freedesktop/systemd1/job/78']
            if key=='Id' and attack=='wrong_job_id':value['data']=78
            if key=='Unit' and attack=='wrong_service':value['data'][0]='other.service'
            if key=='JobType' and attack=='wrong_type':value['data']='restart'
            if key=='State' and attack=='job_waiting':value['data']='waiting'
            if key=='ActivationDetails':
                if attack=='manual':value['data']=[]
                if attack=='stale_job':data[1][1]='6807047895028'
                if attack=='wrong_timer':data[0][1]='other.timer'
                if attack=='conflicting':data.append(['trigger_unit','other.timer'])
                if attack=='missing_realtime':value['data']=data[:2]
                if attack=='metadata_changed' and calls[key]>1:data[1][1]=str(h.fired-1)
            if key=='ExecStartPre':
                if attack=='wrong_pid':data[0][7]=999
                if attack=='wrong_phase':data[0][1][-1]='scout'
                if attack=='future_real':data[0][3]=h.real+10_000_000
            if key=='LastTriggerUSecMonotonic' and attack=='timer_changed' and calls[key]>2:value['data']=h.fired+1
            return json.dumps(value).encode()
        if attack in {'changed_invocation','replay'} and key.startswith('--property=InvocationID'):
            return raw.replace(h.invocation.encode(),b'b'*32)
        return raw
    if attack=='stale_clock':monkeypatch.setattr(o.time,'monotonic',lambda:h.fired/1e6+181)
    if attack=='future_clock':monkeypatch.setattr(o.time,'monotonic',lambda:h.fired/1e6-1)
    if attack=='boot_changed':
        n=[0]
        def boot(p):
            n[0]+=1;return 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' if n[0]==1 else 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        monkeypatch.setattr(Path,'read_text',boot)
    monkeypatch.setattr(o.subprocess,'check_output',output);monkeypatch.setattr(o,'STATE',tmp_path)
    if consumer=='observer':
        with pytest.raises((o.TrustFailure,ValueError)):
            o.Observer(dict(head='a'*40,unit_digest='reviewed',timer_digest='reviewed')).handle(123,123,dict(phase='begin',checks={k:True for k in o.CHECKS}))
    else:
        # Main uses the very same independent manager checks. Rewrite attacks
        # aimed at the command record to the current Main phase.
        h.phase='scout';monkeypatch.setenv('INVOCATION_ID',h.invocation);monkeypatch.setattr(o.os,'getpid',lambda:123)
        monkeypatch.setattr(o,'protected',lambda p:None)
        config=dict(head='a'*40,observer_digest='reviewed',unit_digest='reviewed',timer_digest='reviewed')
        original_bytes=Path.read_bytes
        monkeypatch.setattr(Path,'read_bytes',lambda p:o.encoded(config) if p==o.CONFIG else original_bytes(p))
        monkeypatch.setattr(discovery,'git',lambda *a:'a'*40)
        def main_output(cmd,**kw):
            translated=[('ExecStartPre' if x=='ExecStart' else x) for x in cmd]
            raw=output(translated,**kw)
            if 'ExecStart' in cmd:
                value=json.loads(raw)
                if attack!='wrong_phase':value['data'][0][1][-1]='scout'
                else:value['data'][0][1][-1]='begin'
                return json.dumps(value).encode()
            return raw
        monkeypatch.setattr(o.subprocess,'check_output',main_output)
        assert scheduler.trigger()==dict(source='operator',invocation=None)
    assert not list(tmp_path.iterdir())


def test_epoch_path_cannot_overwrite_historical_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(o,'STATE',tmp_path);monkeypatch.setattr(o,'protected',lambda p:None)
    old=tmp_path/'discovery.json';old.write_bytes(b'permanent historical evidence')
    epoch=tmp_path/'epochs'/('a'*40);epoch.mkdir(parents=True)
    assert o.receipt_path(dict(head='a'*40,acceptance_epoch='a'*40))==epoch/'discovery.json'
    assert old.read_bytes()==b'permanent historical evidence'
    for value in ('../discovery.json','b'*40,True):
        with pytest.raises(ValueError):o.receipt_path(dict(head='a'*40,acceptance_epoch=value))


@pytest.mark.parametrize('status',[None,'STAGED','COMMITTED'])
def test_uncommitted_epoch_cannot_authorize_scout(tmp_path,monkeypatch,status):
    monkeypatch.setattr(o,'STATE',tmp_path);monkeypatch.setattr(o,'protected',lambda p:None)
    epoch=tmp_path/'epochs'/('a'*40);epoch.mkdir(parents=True)
    config=dict(head='a'*40,acceptance_epoch='a'*40)
    if status:(epoch/'transition.json').write_text(json.dumps(dict(status=status,source_head='a'*40,old_head='b'*40,nonce='fresh-owner-authorization-123')))
    if status=='COMMITTED':o.epoch_ready(config)
    else:
        with pytest.raises((OSError,ValueError)):o.epoch_ready(config)
    assert not (epoch/'discovery.json').exists()
