#!/usr/bin/python3
"""Installed fixed discovery bookends. No application imports or execution API.

Root server measures state; a pinned client runs only as Scout's systemd control
process. Requests contain sandbox probe booleans, never paths, hashes or commands.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import socketserver
import sqlite3
import stat
import struct
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

SOURCE=Path('/opt/investment-discovery-observer/observer.py')
CONFIG=Path('/etc/investment-discovery-observer/config.json')
SOCKET=Path('/run/investment-discovery-observer/observer.sock')
STATE=Path('/var/lib/investment-development-acceptance')
ROOT=Path('/home/optiplex/investment')
LEDGER=Path('/home/optiplex/.local/share/investment-development/development-control.sqlite3')
WORKTREES=LEDGER.parent/'worktrees'
CHECKS={'source_read_only','state_inaccessible','credentials_inaccessible','network_isolated'}


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()
def unique(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('duplicate observation field')
        result[k]=v
    return result
def loads(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('nonfinite observation')))


def protected(path):
    for p in [path,*path.parents]:
        info=p.lstat()
        if p.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('protected observer installation required')


def atomic(path,data):
    temporary=path.with_suffix('.new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    try:
        with os.fdopen(fd,'wb') as f:f.write(encoded(data)+b'\n');f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def denied(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK);os.close(fd);return False
    except PermissionError:return True
    except FileNotFoundError:return True


def probes():
    # Read/open checks only: never attempt a database write or connect to a broker.
    credentials=[ROOT/'.env',ROOT.parent/'.ssh',ROOT.parent/'.aws',ROOT.parent/'.config/gh',ROOT.parent/'.config/investment-development/github-read.token',LEDGER.parent/'service.env']
    flags=os.statvfs(ROOT).f_flag
    return dict(source_read_only=bool(flags&os.ST_RDONLY),
                state_inaccessible=all(denied(p) for p in [ROOT/'out',ROOT/'holdings.csv']),
                credentials_inaccessible=all(denied(p) for p in credentials),
                network_isolated=not Path('/proc/net/route').read_text().splitlines()[1:])


def file_hash(path):
    if path.is_symlink() or not path.is_file():raise ValueError('regular observed file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def database_hash(path):
    if path.is_symlink() or not path.is_file():raise ValueError('protected database unavailable')
    h=hashlib.sha256()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        for line in db.iterdump():h.update(line.encode());h.update(b'\n')
    return h.hexdigest()


def ledger_snapshot():
    if LEDGER.is_symlink() or not LEDGER.is_file():raise ValueError('real discovery ledger unavailable')
    for suffix in ('-wal','-journal'):
        if LEDGER.with_name(LEDGER.name+suffix).exists():raise ValueError('stable ledger snapshot required')
    raw=LEDGER.read_bytes()
    if len(raw)>32_000_000 or raw!=LEDGER.read_bytes():raise ValueError('bounded stable ledger required')
    for suffix in ('-wal','-journal'):
        if LEDGER.with_name(LEDGER.name+suffix).exists():raise ValueError('ledger transaction raced')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(raw);db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        rows=db.execute('SELECT seq,event_id,candidate,kind,created,payload FROM dev_events ORDER BY seq').fetchall()
        if len(rows)>100000:raise ValueError('bounded observation ledger required')
        schema=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        return dict(seq=rows[-1][0] if rows else 0,prefix=digest(rows),schema=digest(schema)),rows


def snapshot(config):
    source={name:file_hash(ROOT/name) for name in config['files']}
    if source!=config['files']:raise ValueError('reviewed discovery source changed')
    gitdir=ROOT/'.git'
    if not gitdir.is_dir() or gitdir.is_symlink():raise ValueError('fixed live Git directory required')
    head=(gitdir/'HEAD').read_text().strip()
    if head.startswith('ref: '):
        ref=head[5:]
        if not re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]+',ref) or '..' in ref:raise ValueError('invalid current source ref')
        refpath=gitdir/ref
        if refpath.is_file():head=refpath.read_text().strip()
        else:
            packed=dict((line.split()[1],line.split()[0]) for line in (gitdir/'packed-refs').read_text().splitlines() if line and line[0] not in '#^')
            head=packed.get(ref)
    if head!=config['head']:raise ValueError('discovery head changed')
    cfg=loads((ROOT/'config/development_agent.json').read_bytes())
    if any(cfg[k] is not False for k in ('autonomous_implementation','supervised_loop_enabled','supervised_publish_pr','auto_merge')) or cfg['autonomy_stage']!='SHADOW' or cfg['required_human_merge'] is not True:raise ValueError('discovery-only activation required')
    ledger,rows=guarded('LEDGER_SNAPSHOT_INVALID',ledger_snapshot)
    return dict(holdings=file_hash(ROOT/'holdings.csv'),investment=database_hash(ROOT/'out/investment.db'),
                auxiliary=database_hash(ROOT/'out/buffett.db') if (ROOT/'out/buffett.db').exists() or (ROOT/'out/buffett.db').is_symlink() else None,
                source=digest(source),worktrees=sorted(str(p.relative_to(WORKTREES)) for p in WORKTREES.rglob('*')) if WORKTREES.exists() else [],ledger=ledger),rows


class TrustFailure(ValueError):
    """Only reviewed constants cross the root journal boundary."""
    def __init__(self,code):
        self.code=code
        super().__init__(code)


REASONS=frozenset({'SANDBOX_PROBE_FAILED','SCOUT_CONTROL_PROCESS_INVALID',
    'SCOUT_SANDBOX_INVALID','INVOCATION_INVALID','TIMER_UNIT_INVALID',
    'TIMER_TRIGGER_INVALID','SOURCE_SNAPSHOT_INVALID','LEDGER_SNAPSHOT_INVALID',
    'BOOKEND_INVALID','REQUEST_INVALID','SCOUT_CONTROL_PID_MISMATCH',
    'SCOUT_FRAGMENT_MISMATCH','SCOUT_DROP_IN_UNEXPECTED','SCOUT_RELOAD_REQUIRED',
    'SCOUT_UNIT_DIGEST_MISMATCH','SCOUT_ARGV_MISMATCH','SCOUT_EXECUTION_RECORD_INVALID',
    'SCOUT_MANAGER_QUERY_FAILED'})


def guarded(code,operation,*args,**kwargs):
    try:return operation(*args,**kwargs)
    except TrustFailure:raise
    except Exception:raise TrustFailure(code) from None


def root_failure(error):
    code=error.code if type(error) is TrustFailure and error.code in REASONS else 'BOOKEND_INVALID'
    print('DISCOVERY_OBSERVER_FAILURE '+code,file=sys.stderr,flush=True)


def timer_timestamp(options):
    # busctl retains the D-Bus type. systemctl show renders this as a duration.
    raw=subprocess.check_output(['/usr/bin/busctl','--system','get-property',
        'org.freedesktop.systemd1',
        '/org/freedesktop/systemd1/unit/development_2dscout_2etimer',
        'org.freedesktop.systemd1.Timer','LastTriggerUSecMonotonic'],**options)
    if not re.fullmatch(rb't [0-9]{1,20}\n',raw):raise TrustFailure('TIMER_TRIGGER_INVALID')
    value=int(raw[2:])
    if not 0<value<2**64:raise TrustFailure('TIMER_TRIGGER_INVALID')
    return value


def activation(options,pid,invocation,fired,phase='begin'):
    # Unit.ActivationDetails is retained across v255 invocations. Only the
    # current installed start Job can attest this activation. No fallback.
    service='/org/freedesktop/systemd1/unit/development_2dscout_2eservice'
    timer='/org/freedesktop/systemd1/unit/development_2dscout_2etimer'
    def prop(path,interface,name,kind):
        raw=subprocess.check_output(['/usr/bin/busctl','--system','--json=short','get-property',
            'org.freedesktop.systemd1',path,interface,name],**options)
        if len(raw)>8192:raise TrustFailure('TIMER_TRIGGER_INVALID')
        value=loads(raw)
        if set(value)!={'type','data'} or value['type']!=kind:raise TrustFailure('TIMER_TRIGGER_INVALID')
        return value['data']
    def capture():
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if not re.fullmatch('[a-f0-9-]{36}',boot):raise TrustFailure('TIMER_TRIGGER_INVALID')
        job=prop(service,'org.freedesktop.systemd1.Unit','Job','(uo)')
        if (not isinstance(job,list) or len(job)!=2 or type(job[0]) is not int or not 0<job[0]<2**32
            or job[1]!='/org/freedesktop/systemd1/job/'+str(job[0])):raise TrustFailure('TIMER_TRIGGER_INVALID')
        path=job[1]
        identity=(prop(path,'org.freedesktop.systemd1.Job','Id','u'),prop(path,'org.freedesktop.systemd1.Job','Unit','(so)'),
                  prop(path,'org.freedesktop.systemd1.Job','JobType','s'),prop(path,'org.freedesktop.systemd1.Job','State','s'))
        if type(identity[0]) is not int or identity!=(job[0],['development-scout.service',service],'start','running'):raise TrustFailure('TIMER_TRIGGER_INVALID')
        pairs=prop(path,'org.freedesktop.systemd1.Job','ActivationDetails','a(ss)')
        if not isinstance(pairs,list) or any(not isinstance(p,list) or len(p)!=2 or any(type(v) is not str for v in p) for p in pairs):raise TrustFailure('TIMER_TRIGGER_INVALID')
        details=unique(pairs)
        if set(details)!={'trigger_unit','trigger_timer_monotonic_usec','trigger_timer_realtime_usec'} or details['trigger_unit']!='development-scout.timer':raise TrustFailure('TIMER_TRIGGER_INVALID')
        stamps=[]
        for name,key in [('LastTriggerUSecMonotonic','trigger_timer_monotonic_usec'),('LastTriggerUSec','trigger_timer_realtime_usec')]:
            stamp=prop(timer,'org.freedesktop.systemd1.Timer',name,'t')
            if type(stamp) is not int or not 0<stamp<2**64 or details[key]!=str(stamp):raise TrustFailure('TIMER_TRIGGER_INVALID')
            stamps.append(stamp)
        if stamps[0]!=fired or not 0<=time.monotonic()-stamps[0]/1e6<=180 or not -5<=time.time()-stamps[1]/1e6<=180:raise TrustFailure('TIMER_TRIGGER_INVALID')
        return dict(job_id=job[0],boot_id=boot,timer_monotonic_usec=stamps[0],timer_realtime_usec=stamps[1])
    first=capture()
    command_record(options,pid,invocation,phase)
    record=manager_property(options,'org.freedesktop.systemd1.Service',{'begin':'ExecStartPre','scout':'ExecStart'}[phase])['data'][0]
    if first['timer_monotonic_usec']>record[4] or first['timer_realtime_usec']>record[3]:raise TrustFailure('TIMER_TRIGGER_INVALID')
    if capture()!=first:raise TrustFailure('TIMER_TRIGGER_INVALID')
    command_record(options,pid,invocation,phase)
    return first


def manager_property(options,interface,name):
    raw=subprocess.check_output(['/usr/bin/busctl','--system','--json=short','get-property',
        'org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/development_2dscout_2eservice',interface,name],**options)
    if len(raw)>8192:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    value=loads(raw)
    if set(value)!={'type','data'}:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    return value


def command_record(options,pid,invocation,phase):
    name={'begin':'ExecStartPre','scout':'ExecStart','end':'ExecStopPost'}[phase]
    value=manager_property(options,'org.freedesktop.systemd1.Service',name)
    if value['type']!='a(sasbttttuii)' or not isinstance(value['data'],list) or len(value['data'])!=1:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    row=value['data'][0]
    if not isinstance(row,list) or len(row)!=10:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    binary,argv,ignore,start_real,start_mono,finish_real,finish_mono,command_pid,code,status=row
    if binary!='/usr/bin/python3' or argv!=['/usr/bin/python3','-I','-S',str(SOURCE),phase]:raise TrustFailure('SCOUT_ARGV_MISMATCH')
    if ignore is not False or any(type(x) is not int for x in row[3:]) or command_pid!=pid or pid<=0:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    if min(start_real,start_mono)<=0 or any((finish_real,finish_mono,code,status)):raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    entered=manager_property(options,'org.freedesktop.systemd1.Unit','InactiveExitTimestampMonotonic')
    # v255 timestamps start-pre fork just before entering ACTIVATING (28us on
    # this host). Bound that manager ordering, never accept an old completed row.
    if entered['type']!='t' or type(entered['data']) is not int or entered['data']<=0 or start_mono<entered['data']-1_000_000:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    if not 0<=time.monotonic()-start_mono/1e6<=240 or not -5<=time.time()-start_real/1e6<=240:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    raw=subprocess.check_output(['/usr/bin/systemctl','--system','show','development-scout.service','--no-pager',
        '--property=InvocationID,ControlPID,ActiveState,SubState'+(',MainPID' if phase=='scout' else '')],**options).decode()
    values=unique(line.split('=',1) for line in raw.splitlines() if '=' in line)
    if values.get('InvocationID')!=invocation:raise TrustFailure('INVOCATION_INVALID')
    if values.get('ControlPID') not in {'0',str(pid)}:raise TrustFailure('SCOUT_CONTROL_PID_MISMATCH')
    if phase=='scout' and values.get('MainPID')!=str(pid):raise TrustFailure('SCOUT_CONTROL_PID_MISMATCH')
    expected={'begin':('activating','start-pre'),'scout':('activating','start'),'end':('deactivating','stop-post')}[phase]
    if (values.get('ActiveState'),values.get('SubState'))!=expected:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')
    again=manager_property(options,'org.freedesktop.systemd1.Service',name)
    if again!=value:raise TrustFailure('SCOUT_EXECUTION_RECORD_INVALID')


def systemd(config,pid,phase):
    options=dict(timeout=10,env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'})
    command=['/usr/bin/systemctl','--system','show']
    properties='ControlPID,InvocationID,FragmentPath,DropInPaths,NeedDaemonReload,Result,PrivateNetwork,NoNewPrivileges,ProtectSystem,ProtectHome,RefuseManualStart,TriggeredBy,User,Group,WorkingDirectory,RequiredBy,WantedBy,UpheldBy,BoundBy,ConsistsOf'
    raw=guarded('SCOUT_MANAGER_QUERY_FAILED',subprocess.check_output,command+['development-scout.service','--no-pager','--property='+properties],**options).decode()
    values=unique(line.split('=',1) for line in raw.splitlines() if '=' in line)
    unit=Path('/etc/systemd/system/development-scout.service')
    for code,ok in [('SCOUT_CONTROL_PID_MISMATCH',values.get('ControlPID') in {'0',str(pid)}),
                    ('SCOUT_FRAGMENT_MISMATCH',values.get('FragmentPath')==str(unit)),
                    ('SCOUT_DROP_IN_UNEXPECTED',values.get('DropInPaths')==''),
                    ('SCOUT_RELOAD_REQUIRED',values.get('NeedDaemonReload')=='no')]:
        if not ok:raise TrustFailure(code)
    if guarded('SCOUT_UNIT_DIGEST_MISMATCH',file_hash,unit)!=config['unit_digest']:raise TrustFailure('SCOUT_UNIT_DIGEST_MISMATCH')
    expected={'PrivateNetwork':'yes','NoNewPrivileges':'yes','ProtectSystem':'strict','ProtectHome':'read-only','User':'optiplex','Group':'optiplex','WorkingDirectory':str(ROOT)}
    if any(values.get(k)!=v for k,v in expected.items()):raise TrustFailure('SCOUT_SANDBOX_INVALID')
    invocation=values.get('InvocationID','')
    if not re.fullmatch('[a-f0-9]{32}',invocation) or invocation=='0'*32:raise TrustFailure('INVOCATION_INVALID')
    guarded('SCOUT_EXECUTION_RECORD_INVALID',command_record,options,pid,invocation,phase)
    if phase in {'begin','scout'}:
        if any(values.get(k)!='' for k in ('RequiredBy','WantedBy','UpheldBy','BoundBy','ConsistsOf')):raise TrustFailure('TIMER_UNIT_INVALID')
        if values.get('RefuseManualStart')!='yes' or values.get('TriggeredBy')!='development-scout.timer':raise TrustFailure('TIMER_UNIT_INVALID')
        raw=subprocess.check_output(command+['development-scout.timer','--no-pager','--property=FragmentPath,DropInPaths,NeedDaemonReload,ActiveState,UnitFileState'],**options).decode()
        timer=unique(line.split('=',1) for line in raw.splitlines() if '=' in line)
        path=Path('/etc/systemd/system/development-scout.timer')
        if timer.get('FragmentPath')!=str(path) or timer.get('DropInPaths')!='' or timer.get('NeedDaemonReload')!='no' or timer.get('ActiveState')!='active' or timer.get('UnitFileState') not in {'enabled','enabled-runtime'} or file_hash(path)!=config['timer_digest']:raise TrustFailure('TIMER_UNIT_INVALID')
        fired=guarded('TIMER_TRIGGER_INVALID',timer_timestamp,options)
        if not 0<=time.monotonic()-fired/1_000_000<=180:raise TrustFailure('TIMER_TRIGGER_INVALID')
        provenance=guarded('TIMER_TRIGGER_INVALID',activation,options,pid,invocation,fired,phase)
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if not re.fullmatch('[a-f0-9-]{36}',boot):raise TrustFailure('TIMER_TRIGGER_INVALID')
        # Repeat immutable boundary checks after the manager reads.
        if file_hash(unit)!=config['unit_digest'] or file_hash(path)!=config['timer_digest']:raise TrustFailure('TIMER_UNIT_INVALID')
        again=subprocess.check_output(command+['development-scout.service','--no-pager','--property='+properties],**options).decode()
        if unique(line.split('=',1) for line in again.splitlines() if '=' in line)!=values:raise TrustFailure('INVOCATION_INVALID')
        if boot!=provenance['boot_id']:raise TrustFailure('TIMER_TRIGGER_INVALID')
        return dict(invocation=invocation,timer_fire=boot+':'+str(fired),provenance=provenance)
    if values.get('Result')!='success':raise TrustFailure('BOOKEND_INVALID')
    return dict(invocation=invocation)


def receipt_path(config):
    epoch=config.get('acceptance_epoch')
    if epoch is None:return STATE/'discovery.json'
    if not isinstance(epoch,str) or not re.fullmatch('[a-f0-9]{40}',epoch) or epoch!=config.get('head'):raise ValueError('exact qualification epoch required')
    parent=STATE/'epochs'/epoch
    protected(parent)
    if not parent.is_dir():raise ValueError('installed qualification epoch required')
    return parent/'discovery.json'


def epoch_ready(config):
    if config.get('acceptance_epoch') is None:return
    marker=receipt_path(config).parent/'transition.json';protected(marker)
    if not marker.is_file() or marker.stat().st_size>4096:raise ValueError('committed epoch transition required')
    data=loads(marker.read_bytes())
    if set(data)!={'status','source_head','old_head','nonce'} or data['status']!='COMMITTED' or data['source_head']!=config['head'] or not re.fullmatch('[a-f0-9]{40}',str(data['old_head'])) or not re.fullmatch('[A-Za-z0-9-]{16,128}',str(data['nonce'])):raise ValueError('committed exact source epoch required')


class Observer:
    def __init__(self,config):self.config=config
    def handle(self,uid,pid,request):
        if uid!=pwd.getpwnam('optiplex').pw_uid:raise ValueError('discovery identity required')
        if not isinstance(request,dict) or set(request)!={'phase','checks'} or request['phase'] not in {'begin','end'}:raise ValueError('fixed bookend required')
        if request['checks']!={k:True for k in CHECKS}:raise TrustFailure('SANDBOX_PROBE_FAILED')
        phase=request['phase'];epoch_ready(self.config);authority=guarded('SCOUT_CONTROL_PROCESS_INVALID',systemd,self.config,pid,phase);invocation=authority['invocation'];pending=STATE/(invocation+'.pending')
        if phase=='begin':
            fires=STATE/'timer-fires.json';used=loads(fires.read_bytes()) if fires.exists() else []
            if authority['timer_fire'] in used:raise ValueError('timer firing already observed')
            atomic(fires,(used+[authority['timer_fire']])[-256:])
        current,rows=guarded('SOURCE_SNAPSHOT_INVALID',snapshot,self.config);now=time.time()
        if phase=='begin':
            if pending.exists():raise ValueError('replayed discovery begin')
            atomic(pending,dict(invocation=invocation,head=self.config['head'],started=now,before=current,provenance=authority.get('provenance')))
            return
        if not pending.is_file():raise ValueError('no trusted before observation')
        before=loads(pending.read_bytes());pending.unlink()
        if before['head']!=self.config['head'] or not 0<=now-before['started']<=240:raise ValueError('expired bookend')
        old=before['before'];prefix=[r for r in rows if r[0]<=old['ledger']['seq']];new=[r for r in rows if r[0]>old['ledger']['seq']]
        if digest(prefix)!=old['ledger']['prefix'] or current['ledger']['schema']!=old['ledger']['schema']:raise ValueError('discovery ledger history changed')
        for r in new:
            if r[3] not in {'STATE','SCORE','SIGNAL_OBSERVATION','SCHEDULE_ATTEMPT','SCHEDULE','SCHEDULER_OBSERVATION'}:raise ValueError('unexpected discovery authority activity')
            if r[3]=='STATE' and loads(r[5]).get('state')!='DISCOVERED':raise ValueError('implementation state entered')
        runs=[loads(r[5]) for r in new if r[3]=='SCHEDULE']
        if len(runs)!=1:raise ValueError('one successful scheduled run required')
        run=runs[0]
        if (run.get('status')!='COLLECTED' or run.get('head')!=self.config['head'] or run.get('fixture_only') is True or run.get('trigger')!=dict(source='systemd-observed-timer',invocation=invocation)
            or not before['started']<=run['started_at']<=run['ended_at']<=now):raise ValueError('genuine bookended run required')
        if (not isinstance(run.get('enabled_sources'),list) or not {'ci','telemetry','performance'}<=set(run['enabled_sources'])
            or not isinstance(run.get('unavailable'),list) or set(run['unavailable'])&{'CI','ci','telemetry','performance'}
            or run.get('availability_status')=='UNKNOWN_DUE_TO_RUN_FAILURE'
            or any(type(run.get(k)) is not int or run[k]<0 for k in ('created','deduplicated','suppressed','signal_count','proposal_count'))
            or run.get('slot')!='scout:'+datetime.fromtimestamp(run['started_at'],ZoneInfo('America/New_York')).date().isoformat()):raise ValueError('incomplete scheduled discovery evidence')
        for k in ('holdings','investment','auxiliary','source','worktrees'):
            if old[k]!=current[k]:raise ValueError('protected state or source changed')
        receipt=receipt_path(self.config)
        data=loads(receipt.read_bytes()) if receipt.exists() else dict(runs=[])
        if receipt.exists() and data.get('source_head')!=self.config['head']:raise ValueError('historical acceptance cannot be replaced')
        records=data['runs']
        if any(r['invocation']==invocation or r['slot']==run['slot'] for r in records):raise ValueError('duplicate observed invocation or slot')
        if self.config.get('acceptance_epoch') and not isinstance(before.get('provenance'),dict):raise ValueError('authenticated job evidence required')
        record=dict(invocation=invocation,slot=run['slot'],observed_at=now,provenance=before.get('provenance'),**{k:True for k in ('no_builder','no_worktree','no_source_mutation','no_pr','no_deploy','no_financial_execution')})
        for k in ('holdings','investment'):record.update({k+'_before':old[k],k+'_after':current[k]})
        atomic(receipt,dict(source_head=self.config['head'],fixture_only=False,os_boundary_verified=True,observed_at=now,runs=(records+[record])[-30:],grants_implementation=False))


def client(phase):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
        channel.settimeout(60);channel.connect(str(SOCKET));channel.sendall(encoded(dict(phase=phase,checks=probes()))+b'\n')
        if channel.recv(1024)!=b'OK\n':raise ValueError('trusted discovery observation failed')


def respond(observer,uid,pid,raw):
    try:
        if len(raw)>4096 or not raw.endswith(b'\n'):raise TrustFailure('REQUEST_INVALID')
        observer.handle(uid,pid,loads(raw))
        return b'OK\n'
    except Exception as error:
        root_failure(error)
        return b'FAILED\n'


def serve():
    if sys.platform!='linux' or os.geteuid()!=0:raise ValueError('installed root observer required')
    protected(SOURCE);protected(CONFIG);protected(STATE)
    config=loads(CONFIG.read_bytes())
    if config.get('scout_manager')!='system':raise ValueError('system Scout configuration required')
    if file_hash(SOURCE)!=config['observer_digest']:raise ValueError('observer source changed')
    observer=Observer(config)
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(60)
            try:
                pid,uid,gid=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                raw=self.rfile.readline(4097)
                self.wfile.write(respond(observer,uid,pid,raw))
            except Exception as error:
                root_failure(error);self.wfile.write(b'FAILED\n')
    if SOCKET.exists():
        if not SOCKET.is_socket() or SOCKET.is_symlink() or SOCKET.stat().st_uid!=0:raise ValueError('unsafe observer socket')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as old:
            try:old.connect(str(SOCKET))
            except ConnectionRefusedError:SOCKET.unlink()
            else:raise ValueError('observer already active')
    with socketserver.UnixStreamServer(str(SOCKET),Handler) as server:
        os.chown(SOCKET,0,pwd.getpwnam('optiplex').pw_gid);SOCKET.chmod(0o660);server.serve_forever()


def scout():
    # Fixed unprivileged entry point, system Python with site hooks disabled.
    # No forwarding of caller commands/arguments and no model/tool selection.
    if os.getuid()!=pwd.getpwnam('optiplex').pw_uid:raise ValueError('discovery service identity required')
    # Checkout bytecode is writable governance/runtime state, never authority.
    sys.pycache_prefix='/run/investment-discovery-observer/reviewed-pycache'
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT))
    from dev_agent.cli import main
    return main(['scout','--root',str(ROOT)])


if __name__=='__main__':
    if len(sys.argv)!=2 or sys.argv[1] not in {'serve','begin','end','scout'}:raise SystemExit('fixed observer mode required')
    if sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='scout':raise SystemExit(scout())
    else:client(sys.argv[1])
