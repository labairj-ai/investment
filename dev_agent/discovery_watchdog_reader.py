"""Fixed read-only discovery observations. No producer/service-control interface."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat
import subprocess
import time
from datetime import datetime,timezone
from .structured_json import loads
from .discovery_watchdog import VERSION,policy,HEX40,HEX64,valid_hex

OBSERVER=Path('/etc/investment-discovery-observer/config.json')
HOST_PROOF=Path('/var/lib/investment-development-acceptance/discovery.json')
OBSERVER_SOURCE=Path('/opt/investment-discovery-observer/observer.py')
OBSERVER_SOCKET=Path('/run/investment-discovery-observer/observer.sock')
ROOT_UID=0
SYSTEM_UNIT_DIR=Path('/etc/systemd/system')
PROC=Path('/proc')
NAMES=('development-scout','development-signal-collector','development-scheduler-observer','development-supervised-loop')
USER_UNITS=frozenset(n+s for n in NAMES for s in ('.service','.timer'))
SYSTEM_UNITS=frozenset(('macro-health-watchdog.timer','macro-health-watchdog.service','investment-discovery-observer.service'))
FIELDS=('LoadState','UnitFileState','ActiveState','SubState','FragmentPath','DropInPaths','NeedDaemonReload','Result','InvocationID','MainPID','NextElapseUSecRealtime','LastTriggerUSec','LastTriggerUSecMonotonic','TimersCalendar','RandomizedDelayUSec','AccuracyUSec')
CODE_FILES=('operational_watchdog.py','scripts/macro_health_watchdog.py','dev_agent/discovery_watchdog.py','dev_agent/discovery_watchdog_reader.py','dev_agent/watchdog_gate.py','config/development_watchdog.json')
ENV=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',LANG='C',TZ='UTC',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_NO_REPLACE_OBJECTS='1',GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0')


def digest(data):return hashlib.sha256(data).hexdigest()


def read_bytes(path,limit=2_000_000,*,uid=None,private=False,root_protected=False):
    path=Path(path);before=path.lstat()
    if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size>limit or (uid is not None and before.st_uid!=uid) or before.st_mode&(0o077 if private else 0o022 if uid is not None or root_protected else 0o002):raise ValueError('protected bounded regular evidence required')
    for p in path.parents:
        info=p.lstat()
        if p.is_symlink() or root_protected and (info.st_uid not in {0,ROOT_UID} or info.st_mode&0o022):raise ValueError('protected evidence ancestry required')
    with path.open('rb') as stream:data=stream.read(limit+1)
    after=path.lstat()
    if len(data)>limit or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('evidence changed while inspecting')
    return data


def read_json(path,**kwargs):return loads(read_bytes(path,**kwargs))


def protected_json(path):return read_json(path,uid=ROOT_UID,root_protected=True)


class ReadLedger:
    """Immutable in-memory SQL snapshot; exposes no migration/event/candidate API."""
    def __init__(self,path,uid):
        self.path=Path(path)
        if self.path.name!='development-control.sqlite3':raise ValueError('fixed discovery ledger required')
        if any(self.path.with_name(self.path.name+s).exists() or self.path.with_name(self.path.name+s).is_symlink() for s in ('-journal','-wal')):raise ValueError('ledger transaction in progress')
        self._data=read_bytes(self.path,32_000_000,uid=uid,private=True)
        if self._data[:16]!=b'SQLite format 3\x00' or self._data[18:20]!=b'\x01\x01':raise ValueError('stable non-WAL discovery ledger required')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        try:
            db.deserialize(self._data);db.execute('PRAGMA query_only=ON');yield db
        finally:db.close()


class ReadOnlySystemd:
    def __init__(self,uid):self.uid=uid
    def show(self,unit):
        if unit not in USER_UNITS|SYSTEM_UNITS:raise ValueError('fixed observational unit required')
        args=['/usr/bin/systemctl']+(['--user'] if unit in USER_UNITS else [])+['show',unit,'--no-pager','--property='+','.join(FIELDS)]
        proc=subprocess.run(args,env=dict(ENV,XDG_RUNTIME_DIR='/run/user/'+str(self.uid)),capture_output=True,text=True,timeout=10)
        if proc.returncode not in (0,1) or len(proc.stdout)>64000:raise ValueError('bounded systemd read unavailable')
        result={}
        for line in proc.stdout.splitlines():
            k,v=line.split('=',1)
            if k in result or k not in FIELDS:raise ValueError('unexpected systemd observation')
            result[k]=v
        return result


def git_read(root,*args):
    if args not in {('rev-parse','HEAD'),('rev-parse','origin/main'),('status','--porcelain','--untracked-files=no'),('worktree','list','--porcelain')} and not (len(args)==2 and args[0]=='show' and re.fullmatch('[a-f0-9]{40}:config/development_agent.json',args[1])):raise ValueError('fixed read-only Git query required')
    p=subprocess.run(['/usr/bin/git','--no-optional-locks','-C',str(root),'-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','core.attributesFile=/dev/null','-c','safe.directory='+str(root),*args],env=ENV,capture_output=True,text=True,timeout=30,check=True)
    if len(p.stdout)>64000:raise ValueError('bounded Git observation required')
    return p.stdout.strip()


def code_identity(root):
    return digest(json.dumps({name:digest(read_bytes(Path(root)/name)) for name in CODE_FILES},sort_keys=True,separators=(',',':')).encode())


def source_binding(root):
    root=Path(root);head=git_read(root,'rev-parse','HEAD')
    if not valid_hex(head,HEX40):raise ValueError('exact deployed source required')
    cached_main=git_read(root,'rev-parse','origin/main')
    if not valid_hex(cached_main,HEX40):raise ValueError('cached main identity unavailable')
    observer=protected_json(OBSERVER)
    if observer.get('head')!=head or git_read(root,'status','--porcelain','--untracked-files=no'):raise ValueError('source/observer drift')
    manifest=observer.get('files')
    if not isinstance(manifest,dict) or not 1<=len(manifest)<=10000:raise ValueError('bounded trusted source manifest required')
    for name,value in manifest.items():
        if not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or not valid_hex(value,HEX64) or digest(read_bytes(root/name,32_000_000))!=value:raise ValueError('trusted source bytes differ')
    observer_digest=manifest.get('ops/discovery/observer.py')
    if observer.get('observer_digest')!=observer_digest or digest(read_bytes(OBSERVER_SOURCE,uid=ROOT_UID,root_protected=True))!=observer_digest:raise ValueError('installed observer executable differs')
    reviewed=loads(git_read(root,'show',head+':config/development_agent.json'))
    if digest(read_bytes(root/'config/development_agent.json'))!=manifest.get('config/development_agent.json'):raise ValueError('authority configuration differs')
    for name in CODE_FILES:
        if digest(read_bytes(root/name))!=manifest.get(name):raise ValueError('watchdog component not installed from reviewed source')
    return dict(head=head,observer_head=head,cached_main=cached_main,reviewed_config=reviewed,manifest=manifest,code_identity=code_identity(root),source_pinned_at=OBSERVER.stat().st_ctime)


def timestamp(value):
    if not value:return None
    for fmt in ('%a %Y-%m-%d %H:%M:%S UTC','%a %Y-%m-%d %H:%M:%S.%f UTC'):
        try:return datetime.strptime(value,fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:pass
    raise ValueError('UTC systemd timestamp required')


def duration(value):
    if value=='0':return 0
    parts=re.findall(r'(\d+(?:\.\d+)?)(us|ms|s|min|h)',value or '')
    if not parts or re.sub(r'\d+(?:\.\d+)?(?:us|ms|s|min|h)','',value).strip():raise ValueError('bounded systemd duration required')
    return sum(float(n)*{'us':.000001,'ms':.001,'s':1,'min':60,'h':3600}[u] for n,u in parts)


def pinned_unit(root,unit,props,uid):
    user=unit in USER_UNITS
    path=(Path(pwd.getpwuid(uid).pw_dir)/'.config/systemd/user'/unit) if user else SYSTEM_UNIT_DIR/unit
    expected=read_bytes(Path(root)/('ops/discovery' if unit=='investment-discovery-observer.service' else 'systemd')/unit)
    actual=read_bytes(path,uid=uid if user else ROOT_UID,root_protected=not user)
    return (actual==expected and props.get('FragmentPath')==str(path) and not props.get('DropInPaths') and props.get('NeedDaemonReload')=='no')


def observe(root,*,now=None,previous=None):
    """Read-only adapter. Catches unavailable evidence as explicit component RED."""
    root=Path(root);fixed_now=now;now=time.time() if now is None else now;uid=os.getuid()
    out=dict(errors=[],units={},runs=[],failed_runs=[],previous_failures=previous or {})
    def read(label,fn):
        try:return fn()
        except Exception:out['errors'].append(label);return None
    binding=read('source',lambda:source_binding(root))
    if binding:out.update(binding,source_ok=True)
    else:
        out['head']=read('head',lambda:git_read(root,'rev-parse','HEAD'));out['observer_head']=read('observer',lambda:protected_json(OBSERVER).get('head'))
    out['policy']=read('policy',lambda:policy(read_json(root/'config/development_watchdog.json')))
    out['config']=read('authority',lambda:read_json(root/'config/development_agent.json'))
    systemd=ReadOnlySystemd(uid)
    for unit in sorted(USER_UNITS|SYSTEM_UNITS):
        props=read(unit,lambda unit=unit:systemd.show(unit))
        if props is None:continue
        props=dict(props);out['units'][unit]=props
        if unit not in {'development-supervised-loop.service','development-supervised-loop.timer'}:
            props['pinned']=read(unit+':pin',lambda unit=unit,props=props:pinned_unit(root,unit,props,uid)) is True
        if unit.endswith('.timer'):
            props['next_at']=read(unit+':next',lambda props=props:timestamp(props.get('NextElapseUSecRealtime')))
            props['last_at']=read(unit+':last',lambda props=props:timestamp(props.get('LastTriggerUSec')))
    scout=out['units'].get('development-scout.timer',{})
    scout['calendar_valid']=read('calendar',lambda:scout.get('Persistent')=='yes' and duration(scout.get('RandomizedDelayUSec'))==120 and duration(scout.get('AccuracyUSec'))==60 and re.fullmatch(r'\{ OnCalendar=\*-\*-\* 08:15:00 America/New_York ; next_elapse=[^{}]+ \}',scout.get('TimersCalendar','')) is not None) is True
    def observer_socket():
        value=OBSERVER_SOCKET.lstat();parent=OBSERVER_SOCKET.parent.lstat()
        if OBSERVER_SOCKET.is_symlink() or OBSERVER_SOCKET.parent.is_symlink() or not stat.S_ISSOCK(value.st_mode) or value.st_uid!=ROOT_UID or value.st_gid!=pwd.getpwuid(uid).pw_gid or stat.S_IMODE(value.st_mode)!=0o660 or parent.st_uid!=ROOT_UID or parent.st_mode&0o022:raise ValueError('private observer socket boundary unavailable')
        return True
    out['observer_socket_ok']=read('observer-socket',observer_socket) is True
    out['supervised_units_absent']=all(out['units'].get('development-supervised-loop'+s,{}).get('LoadState')=='not-found' for s in ('.service','.timer'))
    home=Path(pwd.getpwuid(uid).pw_dir);state=home/'.local/share/investment-development'
    out['worktree_present']=(state/'worktrees').exists() or (state/'worktrees').is_symlink()
    # Read proc metadata only. Unknown/inaccessible process inventory is explicit RED.
    def builders():
        count=0
        for path in PROC.iterdir():
            try:owned=path.name.isdigit() and path.stat().st_uid==uid
            except FileNotFoundError:continue
            if owned:
                try:
                    with (path/'cmdline').open('rb') as stream:raw=stream.read(64001)
                except FileNotFoundError:continue
                if len(raw)>64000:raise ValueError('bounded process metadata required')
                if any(v in raw for v in (b'run_supervised_loop.py',b'run_supervised_cycle.py',b'run_development_loop.py',b'dev_agent.builder',b'dev_agent.pipeline',b'dev_agent.cli\x00supervised-cycle',b'dev_agent.cli\x00autonomous-cycle',b'dev_agent.cli\x00build\x00',b'dev_agent.cli\x00worktree\x00')):count+=1
        return count
    out['builder_processes']=read('processes',builders)
    ledger=read('ledger',lambda:ReadLedger(state/'development-control.sqlite3',uid))
    if ledger:
        def records():
            with ledger.connect() as db:
                rows=db.execute('SELECT kind,created,payload FROM dev_events ORDER BY seq DESC LIMIT 1001').fetchall()
                if len(rows)>1000:raise ValueError('complete bounded ledger evidence required')
                observations=[dict(created=r['created'],payload=loads(r['payload'])) for r in rows if r['kind']=='SCHEDULER_OBSERVATION']
                out['scheduler']=observations[0]['payload'] if observations else {}
                first=min((r['created'] for r in observations),default=None)
                epoch=out.get('source_pinned_at',0)
                out['installed_at']=max(first,epoch) if first is not None else None
                scoped=[r for r in rows if r['created']>=epoch]
                out['runs']=[loads(r['payload']) for r in scoped if r['kind']=='SCHEDULE']
                out['failed_runs']=[loads(r['payload']) for r in scoped if r['kind']=='SCHEDULE_FAILURE']
                allowed={'SCHEDULE','SCHEDULE_ATTEMPT','SCHEDULE_FAILURE','SCHEDULE_DUPLICATE','SCHEDULER_OBSERVATION','SCORE','SIGNAL_OBSERVATION','STATE'}
                out['implementation_events']=any(r['kind'] not in allowed or r['kind']=='STATE' and loads(r['payload']).get('state')!='DISCOVERED' for r in scoped)
            from .scheduler_health import acceptance
            out['acceptance']=acceptance(ledger,out.get('head'),fixed_now)
        read('ledger-records',records)
    def spool():
        from .signals import load_spool
        path=state/'operational-signals.json';raw=read_bytes(path,64000,uid=uid,private=True)
        data=loads(raw);out['spool']=data if isinstance(data,dict) else {}
        if not isinstance(data,dict) or set(data)!={'version','created','enabled_sources','unavailable','health','observations'} or not isinstance(data.get('observations'),list) or len(data['observations'])>50 or any(not isinstance(item,dict) or item.get('synthetic') is not False for item in data['observations']):raise ValueError('bounded genuine signal payload required')
        load_spool(path)
        if read_bytes(path,64000,uid=uid,private=True)!=raw:raise ValueError('signal snapshot changed')
        out['spool_valid']=True
    read('spool',spool)
    if HOST_PROOF.exists() or HOST_PROOF.is_symlink():
        proof=read('host-safety',lambda:read_json(HOST_PROOF,limit=64000,uid=ROOT_UID,root_protected=True))
        if proof:out.update(host_proof=proof,host_proof_protected=True)
        else:out['host_proof_invalid']=True
    producer=out['units'].get('macro-health-watchdog.service',{})
    invocation=os.environ.get('INVOCATION_ID','')
    out['producer_verified']=(producer.get('pinned') is True and re.fullmatch('[a-f0-9]{32}',invocation) is not None and producer.get('InvocationID')==invocation and producer.get('MainPID')==str(os.getpid()))
    out['producer_invocation']=invocation if out['producer_verified'] else None
    out['producer_pid']=os.getpid() if out['producer_verified'] else None
    out['observed_at']=time.time() if fixed_now is None else fixed_now
    return out
