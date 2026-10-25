"""Observational discovery watchdog fixtures; never production acceptance evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import socket
import subprocess
import tempfile
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import operational_watchdog as wd
from dev_agent import discovery_watchdog as w
from dev_agent import discovery_watchdog_reader as reader
from dev_agent import watchdog_gate as gate

H='a'*40;I='b'*32

def at(text):return datetime.fromisoformat(text).replace(tzinfo=w.ET).timestamp()


def run(now,slot='2026-10-25',invocation=I):
    start=at(slot+'T08:16:00')
    return dict(head=H,slot='scout:'+slot,trigger=dict(source='systemd-observed-timer',invocation=invocation),started_at=start,ended_at=start+2,duration_seconds=2,status='COLLECTED',enabled_sources=['ci','telemetry','performance'],unavailable=[],signal_count=0,proposal_count=0,created=0,deduplicated=0,suppressed=0,candidates=[])


def proof(runs,now):
    return dict(source_head=H,fixture_only=False,os_boundary_verified=True,observed_at=now-1,runs=[dict(invocation=p['trigger']['invocation'],slot=p['slot'],**{k:True for k in ('no_builder','no_worktree','no_source_mutation','no_pr','no_deploy','no_financial_execution')},holdings_before='d'*64,holdings_after='d'*64,investment_before='e'*64,investment_after='e'*64) for p in runs])


def healthy_snapshot(now=None):
    now=at('2026-10-25T09:00:00') if now is None else now
    config=dict(autonomous_implementation=False,auto_merge=False,supervised_loop_enabled=False,supervised_publish_pr=False,autonomy_stage='SHADOW',autonomous_max_risk='L2',required_human_merge=True)
    units={}
    for name in ('development-scout','development-signal-collector','development-scheduler-observer','macro-health-watchdog'):
        units[name+'.timer']=dict(LoadState='loaded',UnitFileState='enabled',ActiveState='active',pinned=True)
        units[name+'.service']=dict(Result='success')
    units['development-scout.timer'].update(calendar_valid=True,next_at=at('2026-10-26T08:16:00'),last_at=at('2026-10-25T08:16:00'))
    units['investment-discovery-observer.service']=dict(ActiveState='active',SubState='running',pinned=True)
    r=run(now)
    return dict(observer_socket_ok=True,observed_at=now,head=H,observer_head=H,source_ok=True,policy=dict(w.DEFAULTS),config=config,reviewed_config=copy.deepcopy(config),supervised_units_absent=True,worktree_present=False,builder_processes=0,implementation_events=False,units=units,spool=dict(created=now-600,enabled_sources=['ci','telemetry','performance'],unavailable=[]),spool_valid=True,scheduler=dict(status='SCHEDULED',created=now-300,enabled=True,active='active'),installed_at=at('2026-10-24T20:00:00'),runs=[r],failed_runs=[],host_proof=proof([r],now),host_proof_protected=True,producer_verified=True,producer_invocation=I,producer_pid=os.getpid(),acceptance=dict(source_head=H,status='NOT READY',successful_runs=1,required_runs=3,runs=[r],host_safety_accepted=False),errors=[],code_identity='f'*64)


@pytest.fixture
def healthy():return healthy_snapshot()


def summary(s):return w.evaluate(s,s['observed_at'])[-1]
def component(s,name):return next(c for c in w.evaluate(s,s['observed_at']) if c['component']=='development_discovery_'+name)


def test_clean_one_of_three_is_healthy_not_ready_and_no_grant(healthy):
    before=copy.deepcopy(healthy);result=summary(healthy)
    assert result['status']=='INFO' and result['evidence']['status']=='HEALTHY' and result['evidence']['acceptance']=='ACCEPTING 1/3'
    assert result['evidence']['host_safety']=='PASS' and not result['evidence']['host_safety_accepted'] and result['evidence']['grants_implementation'] is False
    assert healthy==before


@pytest.mark.parametrize('count',[0,1,2,3])
def test_acceptance_only_projects_existing_calculation(healthy,count):
    now=healthy['observed_at']
    runs=[run(now,'2026-10-'+str(25-i),chr(98+i)*32) for i in range(count)]
    healthy['runs']=runs;healthy['host_proof']=proof(runs,now) if runs else None
    healthy['acceptance'].update(successful_runs=count,runs=runs,host_safety_accepted=count==3,status='READY' if count==3 else 'NOT READY')
    if count==0:
        healthy['observed_at']=at('2026-10-25T07:00:00');healthy['installed_at']=at('2026-10-24T20:00:00');healthy['spool']['created']=healthy['observed_at']-60;healthy['scheduler']['created']=healthy['observed_at']-60
        healthy['units']['development-scout.timer'].update(last_at=None,next_at=at('2026-10-25T08:16:00'))
    e=summary(healthy)['evidence']
    assert e['acceptance']==('READY 3/3' if count==3 else f'ACCEPTING {count}/3') and e['accepted_runs']==count
    assert e['grants_implementation'] is False


@pytest.mark.parametrize('field,value',[('LoadState','not-found'),('UnitFileState','disabled'),('ActiveState','inactive'),('pinned',False),('calendar_valid',False),('next_at',None)])
def test_bad_scout_timer_red(healthy,field,value):
    healthy['units']['development-scout.timer'][field]=value
    assert component(healthy,'schedule')['status']=='RED' and summary(healthy)['evidence']['acceptance']=='BLOCKED'


@pytest.mark.parametrize('minutes,severity',[(5,'INFO'),(23,'YELLOW'),(129,'RED')])
def test_missing_run_completion_grace_then_red(healthy,minutes,severity):
    now=at('2026-10-25T08:15:00')+minutes*60
    healthy.update(observed_at=now,runs=[],host_proof=None)
    healthy['acceptance'].update(runs=[],successful_runs=0)
    healthy['spool']['created']=healthy['scheduler']['created']=now-60
    assert component(healthy,'execution')['status']==severity


def test_required_slots_are_eastern_and_dst_aware():
    since=at('2026-10-30T20:00:00')
    a=w.required_slot(at('2026-10-31T09:00:00'),since)
    b=w.required_slot(at('2026-11-01T09:00:00'),since)
    assert a.hour==b.hour==8 and (b.timestamp()-a.timestamp())==25*3600
    assert w.required_slot(at('2026-10-25T07:00:00'),at('2026-10-24T20:00:00')) is None
    assert w.required_slot(at('2026-10-25T09:00:00'),at('2026-10-24T20:00:00')).date().isoformat()=='2026-10-25'
    spring_a=w.required_slot(at('2026-03-07T09:00:00'),at('2026-03-06T20:00:00'))
    spring_b=w.required_slot(at('2026-03-08T09:00:00'),at('2026-03-06T20:00:00'))
    assert spring_b.timestamp()-spring_a.timestamp()==23*3600


@pytest.mark.parametrize('mutation',['manual','fixture','synthetic','wrong-head','wrong-slot','duration','unavailable','invalid-invocation','negative-count','missing-candidates'])
def test_invalid_or_forged_run_cannot_clear_incident(healthy,mutation):
    p=healthy['runs'][0]
    if mutation=='manual':p['trigger']['source']='operator'
    if mutation=='fixture':p['fixture_only']=True
    if mutation=='synthetic':p['synthetic']=True
    if mutation=='wrong-head':p['head']='c'*40
    if mutation=='wrong-slot':p['slot']='scout:2026-10-24'
    if mutation=='duration':p['ended_at']+=300;p['duration_seconds']+=300
    if mutation=='unavailable':p['unavailable']=['ci']
    if mutation=='invalid-invocation':p['trigger']['invocation']='fake'
    if mutation=='negative-count':p['signal_count']=-1
    if mutation=='missing-candidates':p.pop('candidates')
    assert summary(healthy)['status']=='RED'


@pytest.mark.parametrize('mutation',['missing','unprotected','wrong-source','fixture','os-boundary','slot','invocation','unsafe','holdings','investment','duplicate','future','malformed'])
def test_root_safety_failure_red_after_success(healthy,mutation):
    p=healthy['host_proof'];r=p['runs'][0]
    if mutation=='missing':healthy['host_proof']=None
    if mutation=='unprotected':healthy['host_proof_protected']=False
    if mutation=='wrong-source':p['source_head']='c'*40
    if mutation=='fixture':p['fixture_only']=True
    if mutation=='os-boundary':p['os_boundary_verified']=False
    if mutation=='slot':r['slot']='scout:2026-10-24'
    if mutation=='invocation':r['invocation']='c'*32
    if mutation=='unsafe':r['no_builder']=False
    if mutation=='holdings':r['holdings_after']='f'*64
    if mutation=='investment':r['investment_after']='f'*64
    if mutation=='duplicate':p['runs'].append(copy.deepcopy(r))
    if mutation=='future':p['observed_at']=healthy['observed_at']+3600
    if mutation=='malformed':healthy['host_proof']={}
    assert component(healthy,'host_safety')['status']=='RED'


@pytest.mark.parametrize('case',['missing','stale','private','unavailable','missing-source','timer','repeat-fail'])
def test_signal_failures_red_without_repair(healthy,case):
    if case=='missing':healthy['spool']={}
    if case=='stale':healthy['spool']['created']=healthy['observed_at']-129601
    if case=='private':healthy['spool_valid']=False
    if case=='unavailable':healthy['spool']['unavailable']=['ci']
    if case=='missing-source':healthy['spool']['enabled_sources']=['ci','telemetry']
    if case=='timer':healthy['units']['development-signal-collector.timer']['UnitFileState']='disabled'
    if case=='repeat-fail':
        healthy['units']['development-signal-collector.service']=dict(Result='exit-code',InvocationID='c'*32)
        healthy['previous_failures']={'development-signal-collector':['d'*32]}
    before=copy.deepcopy(healthy);assert component(healthy,'signals')['status']=='RED';assert healthy==before


@pytest.mark.parametrize('case',['delayed','single-fail'])
def test_collector_yellow_while_spool_still_valid(healthy,case):
    if case=='delayed':healthy['spool']['created']=healthy['observed_at']-4501
    else:healthy['units']['development-signal-collector.service']=dict(Result='exit-code',InvocationID='c'*32)
    assert component(healthy,'signals')['status']=='YELLOW'


@pytest.mark.parametrize('age,severity',[(100,'INFO'),(1801,'YELLOW'),(3601,'RED')])
def test_scheduler_freshness_thresholds(healthy,age,severity):
    healthy['scheduler']['created']=healthy['observed_at']-age
    assert component(healthy,'scheduler')['status']==severity


@pytest.mark.parametrize('mutation',['pin','dirty','authority','builder','worktree','events','supervised-unit','source-acceptance','producer','watchdog-timer','observer-offline','observer-socket'])
def test_source_authority_and_monitoring_fail_closed_immediately(healthy,mutation):
    if mutation=='pin':healthy['observer_head']='c'*40
    if mutation=='dirty':healthy['source_ok']=False
    if mutation=='authority':healthy['config']['supervised_loop_enabled']=True
    if mutation=='builder':healthy['builder_processes']=1
    if mutation=='worktree':healthy['worktree_present']=True
    if mutation=='events':healthy['implementation_events']=True
    if mutation=='supervised-unit':healthy['supervised_units_absent']=False
    if mutation=='source-acceptance':healthy['acceptance']['source_head']='c'*40
    if mutation=='producer':healthy['producer_verified']=False
    if mutation=='watchdog-timer':healthy['units']['macro-health-watchdog.timer']['ActiveState']='inactive'
    if mutation=='observer-offline':healthy['units']['investment-discovery-observer.service']['ActiveState']='inactive'
    if mutation=='observer-socket':healthy['observer_socket_ok']=False
    assert summary(healthy)['status']=='RED'


def test_real_failure_red_and_duplicates_do_not_count(healthy):
    healthy['failed_runs']=[dict(slot=healthy['runs'][0]['slot'],status='FAILED')]
    assert component(healthy,'execution')['status']=='RED'
    healthy['failed_runs']=[];healthy['runs'].append(copy.deepcopy(healthy['runs'][0]))
    assert component(healthy,'execution')['status']=='RED'


def test_no_sensitive_payload_in_projection_or_email(healthy,tmp_path):
    secret='ghp_'+('z'*32)
    healthy['spool']['unavailable']=['ci',secret];healthy['runs'][0]['problem']=secret
    checks=w.evaluate(healthy,healthy['observed_at']);assert secret not in json.dumps(checks)
    state=wd.connect(tmp_path/'watchdog.db');wd.persist(state,checks,healthy['observed_at'])
    sent=[];wd.deliver(state,healthy['observed_at'],lambda subject,body:sent.append((subject,body)),enabled=True)
    assert len(sent)==1 and secret not in json.dumps(sent)
    assert all('Source:' in body and 'Expected slot:' in body for _,body in sent)


def test_existing_incident_dedup_and_resolution_reused(healthy,tmp_path):
    state=wd.connect(tmp_path/'watchdog.db');healthy['units']['development-scout.timer']['ActiveState']='inactive'
    wd.persist(state,w.evaluate(healthy,healthy['observed_at']),healthy['observed_at'])
    opened=state.execute('SELECT count(*) FROM watchdog_events').fetchone()[0]
    wd.persist(state,w.evaluate(healthy,healthy['observed_at']),healthy['observed_at']+1)
    assert state.execute('SELECT count(*) FROM watchdog_events').fetchone()[0]==opened
    healthy['units']['development-scout.timer']['ActiveState']='active'
    wd.persist(state,w.evaluate(healthy,healthy['observed_at']),healthy['observed_at']+2)
    assert state.execute("SELECT count(*) FROM watchdog_events WHERE transition='RESOLVED'").fetchone()[0]>0


def test_threshold_config_cannot_expand_existing_freshness():
    for k,v in [('spool_warning_seconds',129601),('scheduler_warning_seconds',3601),('missed_run_red_seconds',86400)]:
        data=dict(w.DEFAULTS);data[k]=v
        with pytest.raises(ValueError):w.policy(data)


def test_systemd_adapter_only_fixed_read_commands(monkeypatch):
    calls=[]
    def invoke(args,**kwargs):
        calls.append(args);assert 'start' not in args and 'restart' not in args and 'enable' not in args and 'disable' not in args and 'shell' not in kwargs
        return SimpleNamespace(returncode=0,stdout='LoadState=loaded\nActiveState=active\n')
    monkeypatch.setattr(reader.subprocess,'run',invoke)
    api=reader.ReadOnlySystemd(os.getuid())
    assert api.show('development-scout.timer')['LoadState']=='loaded'
    for bad in ['development-scout.service; restart','investment.service','start','../../service']:
        with pytest.raises(ValueError):api.show(bad)
    assert len(calls)==1 and calls[0][1:3]==['--user','show']
    assert 'Persistent' in calls[0][-1].split('=',1)[1].split(',')
    assert not any(hasattr(api,n) for n in ['start','restart','enable','disable','repair','run'])


@pytest.mark.parametrize('args',[('fetch','origin'),('checkout','main'),('push',),('commit','-m','x'),('config','x','y'),('worktree','add','x')])
def test_git_adapter_denies_every_mutation(tmp_path,args):
    with pytest.raises(ValueError):reader.git_read(tmp_path,*args)


def test_readonly_ledger_has_no_producer_and_cannot_write(tmp_path):
    from dev_agent.store import Store
    p=tmp_path/'development-control.sqlite3';Store(p).migrate();before=p.read_bytes()
    view=reader.ReadLedger(p,os.getuid())
    for name in ['migrate','event','discover','transition','decide']:assert not hasattr(view,name)
    with pytest.raises(TypeError):
        with view.connect(True):pass
    with view.connect() as db:
        with pytest.raises(sqlite3.OperationalError):db.execute("INSERT INTO dev_events(kind) VALUES ('SCHEDULE')")
    assert p.read_bytes()==before and not p.with_name(p.name+'-wal').exists()


@pytest.mark.parametrize('case',['symlink','writable','oversized','journal'])
def test_ledger_bad_boundary_refuses_without_mutation(tmp_path,case):
    from dev_agent.store import Store
    p=tmp_path/'development-control.sqlite3';Store(p).migrate()
    if case=='symlink':p.rename(tmp_path/'real');p.symlink_to(tmp_path/'real')
    if case=='writable':p.chmod(0o666)
    if case=='oversized':p.write_bytes(b'x'*32_000_001)
    if case=='journal':p.with_name(p.name+'-journal').write_text('transaction')
    with pytest.raises(ValueError):reader.ReadLedger(p,os.getuid())


@pytest.mark.parametrize('case',['symlink','writable','wrong-owner','parent-writable'])
def test_root_evidence_permissions_fail_closed(monkeypatch,case):
    with tempfile.TemporaryDirectory(dir=Path.home(),prefix='.wd-') as directory:
        p=Path(directory)/'proof.json';p.write_text('{}');monkeypatch.setattr(reader,'ROOT_UID',os.getuid())
        if case=='symlink':p.rename(p.with_name('real'));p.symlink_to(p.with_name('real'))
        if case=='writable':p.chmod(0o666)
        if case=='wrong-owner':monkeypatch.setattr(reader,'ROOT_UID',os.getuid()+1)
        if case=='parent-writable':p.parent.chmod(0o777)
        with pytest.raises(ValueError):reader.protected_json(p)


def test_normalize_timestamps_and_duration_are_bounded():
    assert reader.duration('2min')==120 and reader.duration('1min 30s')==90
    assert reader.timestamp('Sun 2026-10-25 12:16:04 UTC')==at('2026-10-25T08:16:04')
    assert reader.timestamp(None) is None
    for value in ['tomorrow','Sun 2026-10-25 08:16:04 EDT']:
        with pytest.raises(ValueError):reader.timestamp(value)


def write_coverage(path,snapshot):
    c=wd.connect(path);wd.persist(c,w.evaluate(snapshot,snapshot['observed_at']),snapshot['observed_at']);c.close()


@pytest.fixture
def coverage(healthy,tmp_path,monkeypatch):
    healthy['config'].update(supervised_loop_enabled=True,supervised_publish_pr=True);healthy['reviewed_config']=copy.deepcopy(healthy['config'])
    healthy['acceptance'].update(status='READY',successful_runs=3,host_safety_accepted=True)
    path=tmp_path/'watchdog.db';write_coverage(path,healthy)
    binding=dict(head=H,code_identity='f'*64,reviewed_config=healthy['reviewed_config'])
    monkeypatch.setattr(gate,'coverage_path',lambda root:path)
    monkeypatch.setattr(gate,'source_binding',lambda root:binding)
    timer=dict(LoadState='loaded',UnitFileState='enabled',ActiveState='active')
    monkeypatch.setattr(gate.ReadOnlySystemd,'show',lambda self,unit:timer)
    monkeypatch.setattr(gate,'pinned_unit',lambda *a:True)
    return path,healthy,binding,timer


def test_coverage_is_readonly_prerequisite_not_authority(coverage):
    p,s,_,_=coverage;before=p.read_bytes()
    result=gate.require_coverage(Path('.'),now=s['observed_at'])
    assert result['status']=='PASS' and result['grants_implementation'] is False and p.read_bytes()==before


@pytest.mark.parametrize('case',['missing','stale','future','red','wrong-head','wrong-code','manual','not-ready','no-host','phase','timer','partial'])
def test_coverage_missing_or_unsafe_blocks(coverage,case):
    p,s,binding,timer=coverage;now=s['observed_at']
    if case=='missing':p.unlink()
    elif case=='stale':now+=2101
    elif case=='future':now-=1
    elif case=='timer':timer['ActiveState']='inactive'
    elif case=='wrong-head':binding['head']='c'*40
    elif case=='wrong-code':binding['code_identity']='d'*64
    else:
        with sqlite3.connect(p) as db:
            if case=='red':db.execute("UPDATE system_watchdog_state SET status='RED',incident_id='red' WHERE component='development_discovery_signals'")
            elif case=='partial':db.execute("DELETE FROM system_watchdog_state WHERE component='development_discovery_schedule'")
            else:
                detail=json.loads(db.execute("SELECT detail FROM system_watchdog_state WHERE component='development_discovery'").fetchone()[0]);e=detail['evidence']
                if case=='manual':e['producer_verified']=False
                if case=='not-ready':e['acceptance']='ACCEPTING 2/3'
                if case=='no-host':e['host_safety_accepted']=False
                if case=='phase':e['phase']='discovery'
                db.execute("UPDATE system_watchdog_state SET detail=? WHERE component='development_discovery'",(json.dumps(detail),))
    with pytest.raises(ValueError,match='watchdog coverage'):gate.require_coverage(Path('.'),now=now)


def test_no_remediation_imports_or_calls_in_pure_classifier():
    import ast
    tree=ast.parse(Path(w.__file__).read_text())
    forbidden={'subprocess','sqlite3','os','pathlib','owner_gateway','deployment_agent','builder','worktrees','scheduler'}
    imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
    assert not any(v and any(part in forbidden for part in v.split('.')) for v in imports)
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'start','restart','enable','disable','migrate','event','discover','create','publish','merge','deploy','write_text','write_bytes'} for n in ast.walk(tree))


def test_dashboard_contains_only_readonly_discovery_controls():
    source=Path('generate_dashboard.py').read_text();panel=source[source.index('function loadWatchdogPanel'):source.index('function showLCalTab')]
    assert 'Development Discovery' in panel and 'Host Safety:' in panel and 'Builder:' in panel
    assert 'textContent' in panel and 'POST' not in panel
    for text in ['Run Scout','Reset Acceptance','Enable Builder','Repair','Retry']:assert text not in panel
    checked=subprocess.run(['node','--check'],input=panel.replace('{{','{').replace('}}','}'),capture_output=True,text=True,timeout=15)
    assert checked.returncode==0,checked.stderr


def test_valid_root_json_boundary(monkeypatch):
    with tempfile.TemporaryDirectory(dir=Path.home(),prefix='.wd-') as directory:
        p=Path(directory)/'proof.json';p.write_text('{"real":true}');monkeypatch.setattr(reader,'ROOT_UID',os.getuid())
        assert reader.protected_json(p)=={'real':True}


@pytest.mark.parametrize('activity',[None,'script','cli'])
def test_observe_real_read_adapters_never_mutate_or_receive_producer(monkeypatch,activity):
    """Real temporary Git/SQLite/files; systemd metadata is the only fake input."""
    from dev_agent.store import Store
    from datetime import timedelta
    with tempfile.TemporaryDirectory(dir=Path.home(),prefix='.wd-host-') as directory:
        base=Path(directory);home=base/'home';root=home/'investment';root.mkdir(parents=True)
        proc=base/'proc';proc.mkdir();(proc/str(os.getpid())).mkdir();(proc/str(os.getpid())/'cmdline').write_bytes(b'fixture-watchdog\0' if activity is None else b'python\0scripts/run_supervised_cycle.py\0' if activity=='script' else b'python\0-m\0dev_agent.cli\0build\0')
        system=base/'system';system.mkdir();user=home/'.config/systemd/user';user.mkdir(parents=True)
        origin=Path(__file__).resolve().parents[1]
        for name in reader.CODE_FILES:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((origin/name).read_bytes())
        for unit in reader.USER_UNITS|reader.SYSTEM_UNITS:
            if unit.startswith('development-supervised'):continue
            p=root/('ops/discovery' if unit=='investment-discovery-observer.service' else 'systemd')/unit;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((origin/('ops/discovery' if unit=='investment-discovery-observer.service' else 'systemd')/unit).read_bytes())
            target=(user if unit in reader.USER_UNITS else system)/unit;target.write_bytes(p.read_bytes())
        (root/'ops/discovery/observer.py').write_bytes((origin/'ops/discovery/observer.py').read_bytes())
        installed=base/'observer.py';installed.write_bytes((root/'ops/discovery/observer.py').read_bytes())
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock=base/'observer.sock';listener.bind(str(sock));sock.chmod(0o660)
        config=dict(autonomous_implementation=False,auto_merge=False,supervised_loop_enabled=False,supervised_publish_pr=False,required_human_merge=True,autonomy_stage='SHADOW',autonomous_max_risk='L2')
        (root/'config/development_agent.json').write_text(json.dumps(config))
        def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL).decode().strip()
        git('init','-q');git('config','user.email','fixture@invalid');git('config','user.name','Fixture');git('add','.');git('commit','-qm','Reviewed fixture');head=git('rev-parse','HEAD');git('update-ref','refs/remotes/origin/main',head)
        tracked=git('ls-files').splitlines();manifest={n:reader.digest((root/n).read_bytes()) for n in tracked}
        observer=base/'observer.json';observer.write_text(json.dumps(dict(head=head,files=manifest,observer_digest=manifest['ops/discovery/observer.py'])))
        state=home/'.local/share/investment-development';state.mkdir(parents=True);ledger=Store(state/'development-control.sqlite3');ledger.migrate()
        now=__import__('time').time();next_day=datetime.fromtimestamp(now,w.ET).replace(hour=8,minute=15,second=0,microsecond=0)
        if next_day.timestamp()<=now:next_day+=timedelta(days=1)
        observation=dict(status='SCHEDULED',created=now-30,enabled=True,active='active')
        with ledger.connect(True) as db:ledger._append(db,None,'SCHEDULER_OBSERVATION',observation,'fixture-observer')
        now=__import__('time').time()
        spool=state/'operational-signals.json';spool.write_text(json.dumps(dict(version='development-signals-1',created=now-30,enabled_sources=['ci','telemetry','performance'],unavailable=[],health=dict(http_status=200),observations=[])));spool.chmod(0o600)
        for name in ['holdings.csv','out/investment.db','.env']:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('protected fixture; must not be opened')
        monkeypatch.setattr(reader,'OBSERVER_SOURCE',installed);monkeypatch.setattr(reader,'OBSERVER_SOCKET',sock);monkeypatch.setattr(reader,'ROOT_UID',os.getuid());monkeypatch.setattr(reader,'OBSERVER',observer);monkeypatch.setattr(reader,'HOST_PROOF',base/'absent.json');monkeypatch.setattr(reader,'SYSTEM_UNIT_DIR',system);monkeypatch.setattr(reader,'PROC',proc)
        monkeypatch.setattr(reader.pwd,'getpwuid',lambda uid:SimpleNamespace(pw_dir=str(home),pw_gid=os.getgid()))
        monkeypatch.setenv('INVOCATION_ID',I)
        calls=[]
        def show(self,unit):
            calls.append(unit);assert unit in reader.USER_UNITS|reader.SYSTEM_UNITS
            if unit.startswith('development-supervised'):return dict(LoadState='not-found',ActiveState='inactive')
            props=dict(LoadState='loaded',UnitFileState='enabled',ActiveState='active',FragmentPath=str((user if unit in reader.USER_UNITS else system)/unit),DropInPaths='',NeedDaemonReload='no',Result='success')
            if unit=='development-scout.timer':props.update(NextElapseUSecRealtime=datetime.fromtimestamp(next_day.timestamp(),timezone.utc).strftime('%a %Y-%m-%d %H:%M:%S UTC'),LastTriggerUSec='',TimersCalendar='{ OnCalendar=*-*-* 08:15:00 America/New_York ; next_elapse=future }',RandomizedDelayUSec='2min',AccuracyUSec='1min',Persistent='yes')
            if unit=='macro-health-watchdog.service':props.update(InvocationID=I,MainPID=str(os.getpid()))
            if unit=='investment-discovery-observer.service':props['SubState']='running'
            return props
        monkeypatch.setattr(reader.ReadOnlySystemd,'show',show)
        # Trap all writer APIs, and all reads of financial/credential fixtures.
        monkeypatch.setattr(Store,'migrate',lambda *a:pytest.fail('migrate is a producer'))
        monkeypatch.setattr(Store,'event',lambda *a,**k:pytest.fail('ledger event is a producer'))
        monkeypatch.setattr(Store,'discover',lambda *a:pytest.fail('candidate creation forbidden'))
        from dev_agent import scheduler_health
        monkeypatch.setattr(scheduler_health,'record',lambda *a:pytest.fail('scheduler producer forbidden'))
        sqlite_connect=reader.sqlite3.connect
        def memory_only(database,*args,**kwargs):
            assert database==':memory:','watchdog opened a filesystem SQLite writer'
            return sqlite_connect(database,*args,**kwargs)
        monkeypatch.setattr(reader.sqlite3,'connect',memory_only)
        original=Path.open
        def checked_open(path,*args,**kwargs):
            assert path not in {root/'holdings.csv',root/'out/investment.db',root/'.env'}
            mode=args[0] if args else kwargs.get('mode','r');assert not any(c in mode for c in 'wax+')
            return original(path,*args,**kwargs)
        def inventory():return {str(p.relative_to(base)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in base.rglob('*') if p.is_file()}
        before=inventory();monkeypatch.setattr(Path,'open',checked_open)
        snapshot=reader.observe(root,now=now);result=w.evaluate(snapshot,now)[-1]
        assert snapshot['errors']==[]
        assert snapshot['builder_processes']==(0 if activity is None else 1)
        assert result['status']==('INFO' if activity is None else 'RED'),json.dumps(w.evaluate(snapshot,now),indent=2)
        assert result['evidence']['acceptance']==('ACCEPTING 0/3' if activity is None else 'BLOCKED')
        monkeypatch.setattr(Path,'open',original);assert inventory()==before
        assert set(calls)==reader.USER_UNITS|reader.SYSTEM_UNITS
        listener.close()


def ready_watchdog_fixture(monkeypatch,tmp_path,config,source,now):
    """Add the new real coverage prerequisite to pre-existing entry-point fixtures.

    Only external host/source reads are replaced; gate SQL/validation stays real.
    """
    from datetime import timedelta
    s=healthy_snapshot(now);local=datetime.fromtimestamp(now,w.ET)
    day=local.date() if local.hour>8 or local.hour==8 and local.minute>=17 else local.date()-timedelta(days=1)
    runs=[run(now,(day-timedelta(days=i)).isoformat(),chr(98+i)*32) for i in range(3)]
    for p in runs:p['head']=source
    safety=proof(runs,now);safety['source_head']=source
    s.update(head=source,observer_head=source,config=copy.deepcopy(config),reviewed_config=copy.deepcopy(config),runs=runs,host_proof=safety,installed_at=now-5*86400)
    next_time=local.replace(hour=8,minute=16,second=0,microsecond=0)
    if next_time.timestamp()<=now:next_time+=timedelta(days=1)
    s['units']['development-scout.timer'].update(next_at=next_time.timestamp(),last_at=runs[0]['started_at'])
    s['spool']['created']=s['scheduler']['created']=now-10
    s['acceptance']=dict(source_head=source,status='READY',successful_runs=3,required_runs=3,runs=runs,host_safety_accepted=True)
    checks=w.evaluate(s,now);assert checks[-1]['status']=='INFO'
    # Independent coverage has the same actual inspection/check clock.
    p=tmp_path/'watchdog.db';c=wd.connect(p);wd.persist(c,checks,now);c.close()
    monkeypatch.setattr(gate,'coverage_path',lambda root:p)
    monkeypatch.setattr(gate,'source_binding',lambda root:dict(head=source,code_identity=s['code_identity'],reviewed_config=config))
    monkeypatch.setattr(gate.ReadOnlySystemd,'show',lambda self,unit:dict(LoadState='loaded',UnitFileState='enabled',ActiveState='active'))
    monkeypatch.setattr(gate,'pinned_unit',lambda *a:True)
    return p


def test_unresolved_red_incident_cannot_be_hidden_by_projection(coverage):
    p,s,_,_=coverage
    with sqlite3.connect(p) as db:
        db.execute("UPDATE system_watchdog_state SET incident_id='unresolved' WHERE component='development_discovery_signals'")
        db.execute("INSERT INTO watchdog_events VALUES ('red','unresolved','development_discovery_signals','RED',?,'OPEN','failed','{}')",(s['observed_at'],))
    with pytest.raises(ValueError,match='watchdog coverage'):gate.require_coverage(Path('.'),now=s['observed_at'])


def test_next_trigger_drift_and_real_persistent_metadata(healthy):
    timer=healthy['units']['development-scout.timer'];timer['next_at']=healthy['observed_at']+3600
    assert component(healthy,'schedule')['status']=='RED'
    timer.update(Persistent='yes',last_at=at('2026-10-24T08:16:00'),next_at=healthy['observed_at']+60)
    assert component(healthy,'schedule')['status']=='INFO'
    healthy.update(runs=[],host_proof=None);healthy['acceptance'].update(runs=[],successful_runs=0)
    assert component(healthy,'execution')['status']=='YELLOW'  # queued catch-up is not success


@pytest.mark.parametrize('command',['worktree','build','pr','autonomous-cycle'])
def test_alternate_cli_paths_cannot_bypass_monitoring(tmp_path,monkeypatch,command):
    from dev_agent import cli
    monkeypatch.setattr(cli,'configured_store',lambda:SimpleNamespace(get=lambda *a:pytest.fail('candidate touched before gate')))
    monkeypatch.setattr(gate,'source_binding',lambda root:(_ for _ in ()).throw(ValueError('no independent coverage')))
    monkeypatch.setattr(cli,'configured_provider',lambda *a:pytest.fail('provider invoked before gate'))
    monkeypatch.setattr(cli.Worktrees,'create',lambda *a:pytest.fail('worktree created before gate'))
    with pytest.raises(ValueError,match='watchdog coverage'):cli.main([command,'--root',str(tmp_path),'--candidate','c'])


def test_inflight_bookend_waits_bounded_window_but_cannot_clear_overdue(healthy):
    p=healthy['runs'][0];now=p['ended_at']+1;healthy['observed_at']=now;healthy['host_proof']=None
    healthy['spool']['created']=healthy['scheduler']['created']=now-1
    healthy['units']['development-scout.service'].update(ActiveState='deactivating',InvocationID=I)
    assert component(healthy,'host_safety')['status']=='INFO' and component(healthy,'execution')['evidence']['code']=='execution_pending'
    healthy['observed_at']=p['started_at']+241
    assert component(healthy,'host_safety')['status']=='RED'
    # A late unproven/manual retry must not clear the existing missed-slot alarm.
    now=at('2026-10-25T12:00:00');healthy['observed_at']=now;p.update(started_at=now-3,ended_at=now-1,duration_seconds=2)
    assert component(healthy,'execution')['status']=='RED'


def test_later_genuine_root_bookended_success_resolves_prior_failure(healthy):
    healthy['failed_runs']=[dict(slot=healthy['runs'][0]['slot'],status='FAILED',ended_at=healthy['runs'][0]['started_at']-10)]
    assert component(healthy,'execution')['status']=='INFO'


def test_watchdog_execution_failure_after_scan_blocks_until_fresh_scan(coverage):
    p,s,_,_=coverage;marker=p.parent/'watchdog_failure.json'
    marker.write_text(json.dumps(dict(overall='RED',checked_at=s['observed_at']+1,error='fixture')))
    with pytest.raises(ValueError,match='watchdog coverage'):gate.require_coverage(Path('.'),now=s['observed_at']+2)
    marker.write_text(json.dumps(dict(overall='RED',checked_at=s['observed_at']-1,error='older fixture')))
    assert gate.require_coverage(Path('.'),now=s['observed_at']+2)['status']=='PASS'
