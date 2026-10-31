from test_development_agent_scout_failure import system
"""Automatic producers: synthetic fixtures grant no live host/run credit."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import pytest
from ops.discovery import observer
from ops.validator import live_acceptance as acceptance
from ops import install_discovery
from test_development_agent_live_rollout import qualifying_payload

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def observed(tmp_path,monkeypatch):
    monkeypatch.setattr(observer,'STATE',tmp_path)
    monkeypatch.setattr(observer.pwd,'getpwnam',lambda name:SimpleNamespace(pw_uid=123,pw_gid=123))
    invocation=['a'*32]
    monkeypatch.setattr(observer,'systemd',lambda *a:dict(invocation=invocation[0],timer_fire='fixture-fire:'+invocation[0]))
    now=time.time();rows=[]
    base=dict(holdings='a'*64,investment='b'*64,auxiliary='c'*64,source='d'*64,worktrees=[])
    def snapshot(config):
        return dict(base,ledger=dict(seq=rows[-1][0] if rows else 0,prefix=observer.digest(rows),schema='schema')),copy.deepcopy(rows)
    monkeypatch.setattr(observer,'snapshot',snapshot)
    server=observer.Observer(dict(head='f'*40))
    def request(phase):return dict(phase=phase,checks={k:True for k in observer.CHECKS})
    def finish(**changes):
        run=qualifying_payload(time.time(),head='f'*40,invocation=invocation[0]);run.update(started_at=time.time(),ended_at=time.time(),**changes)
        rows.append([len(rows)+1,'event',None,'SCHEDULE',now,json.dumps(run)])
        return run
    return server,request,finish,base,rows,invocation


def test_observer_automatically_publishes_only_bookended_measured_runs(observed,tmp_path,monkeypatch):
    server,request,finish,base,rows,invocation=observed
    actual=time.time
    for n,char in enumerate('abc'):
        monkeypatch.setattr(observer.time,'time',lambda:actual()+n*86400)
        invocation[0]=char*32
        server.handle(123,900,request('begin'));run=finish();server.handle(123,900,request('end'))
    data=json.loads((tmp_path/'discovery.json').read_text())
    assert len(data['runs'])==3 and data['fixture_only'] is False and not data['grants_implementation']
    assert data['source_head']=='f'*40 and data['os_boundary_verified'] is True
    assert all(r['holdings_before']==r['holdings_after']=='a'*64 for r in data['runs'])
    assert 'commands' not in data and 'candidates' not in data
    assert not list(tmp_path.glob('*.pending'))


@pytest.mark.parametrize('failure',['missing_begin','replay_begin','wrong_uid','false_probe','extra_command','manual','changed_head','failed_run','fixture','state_mutation','source_mutation','worktree','ledger_prefix','builder_event','implementation_state','duplicate_slot','expired'])
def test_discovery_producer_fails_closed(observed,tmp_path,failure,monkeypatch):
    server,request,finish,base,rows,invocation=observed
    if failure=='missing_begin':
        finish()
        with pytest.raises(ValueError):server.handle(123,900,request('end'))
        return
    server.handle(123,900,request('begin'))
    if failure=='replay_begin':
        with pytest.raises(ValueError):server.handle(123,900,request('begin'))
        return
    run=finish()
    req=request('end');uid=123
    if failure=='wrong_uid':uid=234
    if failure=='false_probe':req['checks']['network_isolated']=False
    if failure=='extra_command':req['command']='deploy'
    if failure=='manual':run['trigger']['source']='operator'
    if failure=='changed_head':run['head']='e'*40
    if failure=='failed_run':run['status']='FAILED'
    if failure=='fixture':run['fixture_only']=True
    if failure=='state_mutation':base['investment']='e'*64
    if failure=='source_mutation':base['source']='e'*64
    if failure=='worktree':base['worktrees']=['implementation']
    if failure=='ledger_prefix':
        pending=tmp_path/(invocation[0]+'.pending');data=json.loads(pending.read_text());data['before']['ledger']['prefix']='bad';pending.write_text(json.dumps(data))
    rows[-1][5]=json.dumps(run)
    if failure in {'builder_event','implementation_state'}:rows.append([2,'forbidden',None,'RUN' if failure=='builder_event' else 'STATE',time.time(),json.dumps(dict(state='BUILDING'))])
    if failure=='duplicate_slot':(tmp_path/'discovery.json').write_text(json.dumps(dict(source_head='f'*40,runs=[dict(invocation='z'*32,slot=run['slot'])])))
    if failure=='expired':
        original=time.time_ns()/1e9;monkeypatch.setattr(observer.time,'time',lambda:original+1000)
    with pytest.raises(ValueError):server.handle(uid,900,req)
    if (tmp_path/'discovery.json').exists():assert len(json.loads((tmp_path/'discovery.json').read_text())['runs'])==1


def test_sandbox_network_probe_rejects_default_route(tmp_path,monkeypatch):
    route=tmp_path/'route';route.write_text('Iface Destination\neth0 00000000\n')
    real=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:real(route) if str(p)=='/proc/net/route' else real(p,*a,**k))
    monkeypatch.setattr(observer.os,'statvfs',lambda p:SimpleNamespace(f_flag=os.ST_RDONLY))
    monkeypatch.setattr(observer,'denied',lambda p:True)
    assert observer.probes()['network_isolated'] is False
    route.write_text('Iface Destination\n')
    assert all(observer.probes().values())


def test_observer_authentication_rejects_wrong_control_process_before_reading_state(monkeypatch):
    monkeypatch.setattr(observer.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=123,pw_gid=123))
    calls=[]
    def output(command,**kwargs):
        calls.append((command,kwargs));return b'ControlPID=999\n'
    monkeypatch.setattr(observer.subprocess,'check_output',output)
    with pytest.raises(ValueError):observer.systemd({},123,'begin')
    assert calls[0][0][:3]==['/usr/bin/systemctl','--system','show']
    assert 'user' not in calls[0][1] and 'XDG_RUNTIME_DIR' not in calls[0][1]['env']


def test_acceptance_harness_has_no_development_host_authority():
    with pytest.raises(ValueError):acceptance.identity()


@pytest.mark.parametrize('kind',['timeout','crash','duplicate','truncated'])
def test_fixed_harness_faults_are_actual_processes(kind):
    command=[sys.executable,'-I','-S',str(ROOT/'ops/validator/live_acceptance.py'),'--fault',kind]
    if kind=='timeout':
        with pytest.raises(subprocess.TimeoutExpired):subprocess.run(command,capture_output=True,timeout=0.05,check=True)
    else:
        result=subprocess.run(command,capture_output=True,timeout=5)
        if kind=='crash':assert result.returncode==7
        else:
            rows=json.loads(result.stdout)['results'];assert len(rows)==(5 if kind=='duplicate' else 3)


def test_live_matrix_exercises_installed_process_boundary_without_issuing_host_receipt(monkeypatch):
    source=ROOT/'ops/validator/static_oracle.py'
    spec=importlib.util.spec_from_file_location('matrix_fixture_oracle',source);oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    monkeypatch.setattr(acceptance,'SOURCE',source);monkeypatch.setattr(acceptance,'SELF',ROOT/'ops/validator/live_acceptance.py')
    pins=dict(validator_source_digest=acceptance.sha(source),runtime_identity='python@sha256:'+acceptance.sha(Path(sys.executable).resolve()))
    # Private ancestry is required by the real socket daemon; /tmp is intentionally denied.
    with tempfile.TemporaryDirectory(prefix='l0-host-fixture-',dir=Path.home()) as directory:
        monkeypatch.setattr(acceptance,'RUNTIME',Path(directory)/'not-installed')
        rows=acceptance.matrix(oracle,Path(directory),pins)
    results={r['id']:r['status'] for r in rows}
    assert set(results)==set(acceptance.MATRIX)
    assert all(results[k]=='PASS' for k in ('valid-document','active-markup','executable','test-delete','test-rewrite','fake-pass','fake-junit','symlink','worker-timeout','worker-crash','worker-duplicate','worker-truncated','runtime-mismatch','source-mismatch','key-permissions','socket-permissions'))
    assert results['installed-socket']=='FAIL'  # This fixture cannot pass actual host acceptance.


@pytest.fixture
def discovery_install(tmp_path,monkeypatch):
    home=tmp_path/'home';home.mkdir();settings=home/'.config/investment-development';settings.mkdir(parents=True)
    (settings/'github-read.token').write_text('fixture-readonly')
    monkeypatch.setattr(install_discovery.sys,'platform','linux')
    monkeypatch.setattr(install_discovery.pwd,'getpwuid',lambda uid:SimpleNamespace(pw_dir=str(home),pw_name='optiplex'))
    monkeypatch.setattr(install_discovery,'verify_reader',lambda client:None)
    monkeypatch.setattr(install_discovery,'protected_parents',lambda p:None)
    real=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:'{"head":"'+('a'*40)+'"}' if str(p)=='/etc/investment-discovery-observer/config.json' else real(p,*a,**k))
    from ops.install_discovery import UNITS
    plan=dict(root=str(home/'investment'),head='a'*40,repository='owner/repo',files={n:b'fixture unit' for n in UNITS})
    commands=[]
    def invoke(command,**kwargs):
        commands.append(command)
        if command==['systemctl','--user','start','development-signal-collector.service']:
            state=home/'.local/share/investment-development';p=state/'operational-signals.json'
            p.write_text(json.dumps(dict(version='development-signals-1',created=time.time(),enabled_sources=['ci','telemetry','performance'],unavailable=[],observations=[])));p.chmod(0o600)
        return SimpleNamespace(returncode=0)
    return home,plan,commands,invoke


def test_discovery_install_primes_real_collector_and_validates_before_any_timer(discovery_install):
    home,plan,commands,invoke=discovery_install
    result=install_discovery.apply(plan,invoke=invoke)
    prime=commands.index(['systemctl','--user','start','development-signal-collector.service'])
    enabled=[i for i,c in enumerate(commands) if 'enable' in c]
    assert enabled and all(i>prime for i in enabled)
    assert result['accepted_runs']==0 and result['implementation_enabled'] is False
    assert not any('development-scout.service' in c for c in commands)


@pytest.mark.parametrize('failure',['collector','missing','unavailable','stale'])
def test_priming_failure_never_enables_scout_and_rolls_back(discovery_install,failure):
    home,plan,commands,invoke=discovery_install
    def broken(command,**kwargs):
        if command==['systemctl','--user','start','development-signal-collector.service']:
            if failure=='collector':raise subprocess.CalledProcessError(1,command)
            if failure=='missing':commands.append(command);return SimpleNamespace(returncode=0)
            result=invoke(command,**kwargs)
            path=home/'.local/share/investment-development/operational-signals.json';data=json.loads(path.read_text())
            if failure=='unavailable':data['unavailable']=['ci']
            else:data['created']=0
            path.write_text(json.dumps(data));return result
        return invoke(command,**kwargs)
    with pytest.raises((ValueError,OSError,subprocess.CalledProcessError)):install_discovery.apply(plan,invoke=broken)
    assert not any('enable' in c for c in commands)
    assert not (home/'.config/systemd/user/development-scout.timer').exists()


def test_failed_host_identity_replaces_previous_pass_with_sanitized_failure(tmp_path,monkeypatch,capsys):
    tmp_path.chmod(0o700);output=tmp_path/'live-acceptance.json';output.write_text('{"status":"PASS"}')
    monkeypatch.setattr(acceptance,'OUTPUT',output)
    monkeypatch.setattr(acceptance,'service_context',lambda:'fixture-invocation')
    def reject():raise ValueError('secret-fixture-material-must-not-be-exported')
    monkeypatch.setattr(acceptance,'identity',reject)
    assert acceptance.main()==1
    data=json.loads(output.read_text());assert data['status']=='FAIL' and data['diagnostic']=='ValueError'
    assert not data['grants_implementation'] and not data['grants_activation']
    assert 'secret-fixture-material' not in output.read_text() and 'secret-fixture-material' not in capsys.readouterr().out


def test_standalone_harness_cannot_overwrite_receipt(tmp_path,monkeypatch):
    output=tmp_path/'acceptance.json';output.write_text('{"status":"PASS"}')
    monkeypatch.setattr(acceptance,'OUTPUT',output)
    monkeypatch.setattr(acceptance,'service_context',lambda:(_ for _ in ()).throw(ValueError('not installed')))
    with pytest.raises(ValueError):acceptance.main()
    assert output.read_text()=='{"status":"PASS"}'


def test_fixed_discovery_launcher_has_no_command_forwarding(monkeypatch):
    monkeypatch.setattr(observer.sys,'pycache_prefix',observer.sys.pycache_prefix)
    monkeypatch.setattr(observer.sys,'dont_write_bytecode',observer.sys.dont_write_bytecode)
    from dev_agent import cli
    monkeypatch.setattr(observer.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=os.getuid()))
    calls=[];monkeypatch.setattr(cli,'main',lambda args:calls.append(args) or 0)
    assert observer.scout()==0
    assert calls==[['scout','--root','/home/optiplex/investment']]
    assert observer.sys.dont_write_bytecode and observer.sys.pycache_prefix=='/run/investment-discovery-observer/reviewed-pycache'


def test_observer_root_bootstrap_has_no_development_authority(monkeypatch):
    from ops import install_discovery_observer
    monkeypatch.setattr(install_discovery_observer.os,'geteuid',lambda:501)
    with pytest.raises(ValueError):install_discovery_observer.apply({},invoke=lambda *a,**k:pytest.fail('no real installs'))


def test_fixed_positive_head_changes_only_document_in_protected_git_fixture(tmp_path):
    from ops.validator.install import acceptance_head
    authority=tmp_path/'authority.git'
    subprocess.run(['git','init','--bare',str(authority)],check=True,capture_output=True)
    def git(*args,input=None):return subprocess.check_output(['git','--git-dir='+str(authority),'-c','user.name=fixture','-c','user.email=fixture@invalid',*args],input=input).decode().strip()
    tree=git('mktree',input=b'');base=git('commit-tree',tree,input=b'fixture base\n')
    head=acceptance_head(authority,base)
    assert git('diff','--name-only',base,head)=='docs/help/validator-acceptance.md'
    assert git('show',head+':docs/help/validator-acceptance.md').startswith('Bounded L0 validator')
    assert git('rev-parse','refs/acceptance/document')==head
    assert not (tmp_path/'acceptance.index').exists()


@pytest.mark.parametrize('attack',['none','dropin','reload','sandbox','invocation','argv','timer','result'])
def test_root_observer_verifies_loaded_unit_peer_and_real_timer(system,monkeypatch,attack):
    if attack=='dropin':system.values['DropInPaths']='unreviewed.conf'
    if attack=='reload':system.values['NeedDaemonReload']='yes'
    if attack=='sandbox':system.values['PrivateNetwork']='no'
    if attack=='invocation':system.values['InvocationID']='operator'
    if attack=='timer':monkeypatch.setattr(observer.time,'monotonic',lambda:system.fired/1e6+1000)
    if attack=='argv':
        original=observer.subprocess.check_output
        def output(command,**kw):
            raw=original(command,**kw)
            if 'ExecStartPre' in command:
                value=json.loads(raw);value['data'][0][1][-1]='wrong';return json.dumps(value).encode()
            return raw
        monkeypatch.setattr(observer.subprocess,'check_output',output)
    if attack=='result':
        system.values['Result']='exit-code';system.phase='end'
        with pytest.raises(ValueError,match='BOOKEND_INVALID'):observer.systemd(dict(unit_digest='reviewed',timer_digest='reviewed'),123,'end')
    elif attack=='none':assert system.run()['invocation']=='a'*32
    else:
        with pytest.raises(ValueError):system.run()


@pytest.mark.parametrize('attack',['none','runtime','source','unit','proof_inode','proof_stale','proof_identity'])
def test_live_acceptance_requires_root_pins_and_fresh_off_identity_denial(monkeypatch,attack):
    monkeypatch.setattr(acceptance,'service_context',lambda:'a'*32)
    monkeypatch.setattr(acceptance,'protected',lambda p:None)
    monkeypatch.setattr(acceptance.os,'statvfs',lambda p:SimpleNamespace(f_flag=os.ST_RDONLY))
    monkeypatch.setattr(acceptance,'private',lambda *a:SimpleNamespace(st_ino=123))
    observed=dict(validator_source_digest='a'*64,harness_source_digest='b'*64,unit_digest='c'*64,acceptance_unit_digest='d'*64,runtime_identity='python@sha256:'+'e'*64)
    pins=dict(observed)
    if attack in {'runtime','source','unit'}:pins[{'runtime':'runtime_identity','source':'validator_source_digest','unit':'unit_digest'}[attack]]='wrong'
    denial=dict(status='DENIED',source_digest='b'*64,socket_inode=123,key_inode=123,observed_at=time.time())
    if attack=='proof_inode':denial['socket_inode']=456
    if attack=='proof_stale':denial['observed_at']=0
    if attack=='proof_identity':denial['status']='NOT_RUN'
    hashes={acceptance.SOURCE:'a'*64,acceptance.SELF:'b'*64,acceptance.UNIT:'c'*64,acceptance.ACCEPTANCE_UNIT:'d'*64}
    monkeypatch.setattr(acceptance,'sha',lambda p:hashes.get(p,'e'*64))
    monkeypatch.setattr(Path,'read_bytes',lambda p:json.dumps(pins if p.name=='installation.json' else denial).encode())
    monkeypatch.setattr(Path,'read_text',lambda p:'NoNewPrivs:\t1\n')
    if attack=='none':
        result,invocation=acceptance.identity();assert result['candidate_denial_verified'] is True and invocation=='a'*32
    else:
        with pytest.raises(ValueError):acceptance.identity()


def test_one_timer_firing_cannot_be_reused_by_manual_restart_even_after_interruption(observed,tmp_path,monkeypatch):
    server,request,finish,base,rows,invocation=observed
    monkeypatch.setattr(observer,'systemd',lambda *a:dict(invocation=invocation[0],timer_fire='same-real-fire'))
    server.handle(123,900,request('begin'))
    invocation[0]='b'*32
    with pytest.raises(ValueError,match='timer firing already'):server.handle(123,900,request('begin'))
    assert not (tmp_path/'discovery.json').exists()
