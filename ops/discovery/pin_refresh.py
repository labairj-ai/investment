"""Config-only, zero-run observer pin transition. Never upgrades installed code."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import time
from ops.install_discovery_observer import prepare,source_manifest,git
from dev_agent.structured_json import loads

ROOT_UID=0
ROOT=Path('/home/optiplex/investment')
SOURCE=Path('/opt/investment-discovery-observer/observer.py')
CONFIG=Path('/etc/investment-discovery-observer/config.json')
UNIT=Path('/etc/systemd/system/investment-discovery-observer.service')
SOCKET=Path('/run/investment-discovery-observer/observer.sock')
STATE=Path('/var/lib/investment-development-acceptance')
CONTROL=Path('/home/optiplex/.local/share/investment-development')
USER_UNITS=Path('/home/optiplex/.config/systemd/user')
RUNTIME=Path('/usr/bin/python3')
PROC=Path('/proc')
SERVICE='investment-discovery-observer.service'
IDENTITIES=('ops/discovery/observer.py','ops/discovery/investment-discovery-observer.service','systemd/development-scout.service','systemd/development-scout.timer')
DISCOVERY=tuple(n+s for n in ('development-scout','development-signal-collector','development-scheduler-observer','development-supervised-loop') for s in ('.service','.timer'))
ENV=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',LANG='C.UTF-8')


def sha(data):return hashlib.sha256(data).hexdigest()
def encoded(data):return json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'


def protected(path,*,directory=False):
    info=path.lstat()
    if path.is_symlink() or info.st_uid!=ROOT_UID or info.st_mode&0o022 or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):raise ValueError('root-protected nonsymlinked observer path required')
    for parent in path.parents:
        s=parent.lstat()
        if parent.is_symlink() or s.st_uid not in {0,ROOT_UID} or s.st_mode&0o022:raise ValueError('protected observer ancestry required')
    return info


def flags_disabled(root):
    cfg=loads((root/'config/development_agent.json').read_bytes())
    if any(cfg.get(k) is not False for k in ('autonomous_implementation','supervised_loop_enabled','supervised_publish_pr','auto_merge')) or cfg.get('autonomy_stage')!='SHADOW' or cfg.get('autonomous_max_risk')!='L2' or cfg.get('required_human_merge') is not True or cfg.get('emergency_stop') is not False:raise ValueError('disabled SHADOW human-merge configuration required')


def manifest_matches(root,manifest):
    for name,digest in manifest.items():
        path=root/name
        if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('relative tracked source required')
        for p in [path,*path.parents]:
            if p==root.parent:break
            if p.is_symlink():raise ValueError('source symlink denied')
        if not path.is_file() or sha(path.read_bytes())!=digest:raise ValueError('target source manifest mismatch')


def configuration(head,manifest):
    return dict(head=head,observer_digest=manifest[IDENTITIES[0]],unit_digest=manifest[IDENTITIES[2]],timer_digest=manifest[IDENTITIES[3]],files=manifest)


def command(invoke,args,**kwargs):
    return invoke(args,capture_output=True,text=True,timeout=30,env=ENV,**kwargs)


def properties(raw):
    if not isinstance(raw,str) or len(raw)>65536:raise ValueError('bounded systemd observation required')
    result={}
    for line in raw.splitlines():
        if '=' not in line:raise ValueError('complete systemd observation required')
        k,v=line.split('=',1)
        if k in result:raise ValueError('duplicate systemd property')
        result[k]=v
    return result


def no_discovery(invoke):
    account=pwd.getpwnam('optiplex')
    protected(STATE,directory=True)
    if list(STATE.iterdir()):raise ValueError('observer evidence exists; no acceptance migration/reset permitted')
    for path in (CONTROL/'operational-signals.json',CONTROL/'worktrees'):
        if path.exists() or path.is_symlink():raise ValueError('pre-discovery spool/worktree absence required')
    for name in DISCOVERY:
        if (USER_UNITS/name).exists() or (USER_UNITS/name).is_symlink():raise ValueError('user discovery units must remain absent')
        result=invoke(['/usr/bin/systemctl','--user','show',name,'--property=LoadState,ActiveState,UnitFileState'],capture_output=True,text=True,timeout=15,
                      env=dict(ENV,XDG_RUNTIME_DIR='/run/user/'+str(account.pw_uid)),user=account.pw_uid,group=account.pw_gid,extra_groups=[])
        p=properties(result.stdout)
        if result.returncode not in (0,1) or p.get('LoadState')!='not-found' or p.get('ActiveState')!='inactive' or p.get('UnitFileState','')!='' or set(p)-{'LoadState','ActiveState','UnitFileState'}:raise ValueError('no loaded/enabled discovery user units permitted')
    ledger=CONTROL/'development-control.sqlite3'
    if ledger.exists() or ledger.is_symlink():
        if ledger.is_symlink() or not ledger.is_file():raise ValueError('regular read-only control ledger required')
        if ledger.stat().st_size>32_000_000:raise ValueError('bounded control ledger required')
        if any(ledger.with_name(ledger.name+suffix).exists() or ledger.with_name(ledger.name+suffix).is_symlink() for suffix in ('-wal','-journal')):raise ValueError('pending ledger journal requires separate inspection')
        # Deserialize into memory: even mode=ro can create SQLite WAL/SHM files.
        with sqlite3.connect(':memory:') as db:
            db.deserialize(ledger.read_bytes())
            if db.execute("SELECT 1 FROM dev_events WHERE kind IN ('SCHEDULE','SCHEDULE_ATTEMPT','SCHEDULE_FAILURE','SCHEDULE_DUPLICATE') LIMIT 1").fetchone():raise ValueError('scheduled history exists; no run carry-forward/reset permitted')


def socket_probe(pid,gid):
    protected(SOCKET.parent,directory=True)
    info=SOCKET.lstat()
    if SOCKET.is_symlink() or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=ROOT_UID or info.st_gid!=gid or stat.S_IMODE(info.st_mode)!=0o660:raise ValueError('private trusted observer socket required')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
        channel.settimeout(5);channel.connect(str(SOCKET))
        peer=struct.unpack('3i',channel.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if peer!=(pid,ROOT_UID,gid):raise ValueError('observer socket peer mismatch')
        # Root is deliberately not an authenticated Scout ControlPID. This must
        # reject without a bookend, timer fire, source snapshot or evidence write.
        channel.sendall(b'{}\n');channel.shutdown(socket.SHUT_WR)
        if channel.recv(1024)!=b'FAILED\n':raise ValueError('observer rejected-client boundary changed')
    return (info.st_dev,info.st_ino,info.st_ctime_ns)


def boundary(config,invoke):
    for p in (SOURCE,CONFIG,UNIT):protected(p)
    if loads(CONFIG.read_bytes())!=config:raise ValueError('installed observer configuration mismatch')
    if sha(SOURCE.read_bytes())!=config['observer_digest']:raise ValueError('installed observer source mismatch')
    if sha(UNIT.read_bytes())!=config['files'][IDENTITIES[1]]:raise ValueError('installed observer unit mismatch')
    runtime=RUNTIME.resolve(strict=True);protected(runtime)
    if RUNTIME.is_symlink() and RUNTIME.lstat().st_uid!=ROOT_UID:raise ValueError('root-controlled Python runtime required')
    expected=dict(User='root',Group='optiplex',FragmentPath=str(UNIT),DropInPaths='',NeedDaemonReload='no',ActiveState='active',SubState='running',
                  PrivateNetwork='yes',PrivateTmp='yes',PrivateDevices='yes',ProtectSystem='strict',ProtectHome='read-only',NoNewPrivileges='yes',
                  ProtectKernelTunables='yes',ProtectKernelModules='yes',ProtectControlGroups='yes',RestrictSUIDSGID='yes',RestrictAddressFamilies='AF_UNIX',
                  ReadWritePaths=str(STATE)+' '+str(SOCKET.parent),InaccessiblePaths='-/home/optiplex/.ssh -/home/optiplex/.aws -/home/optiplex/.config/gh -/home/optiplex/investment/.env')
    fields=[*expected,'MainPID','InvocationID','CapabilityBoundingSet','EnvironmentFiles']
    p=properties(command(invoke,['/bin/systemctl','show',SERVICE,'--property='+','.join(fields)],check=True).stdout)
    if set(p)-{'EnvironmentFiles'}!=set(fields)-{'EnvironmentFiles'} or any(p.get(k)!=v for k,v in expected.items()) or p.get('EnvironmentFiles','')!='' or set(p.get('CapabilityBoundingSet','').split())!={'cap_dac_read_search','cap_setgid','cap_setuid'}:raise ValueError('loaded observer boundary changed')
    if not re.fullmatch('[a-f0-9]{32}',p.get('InvocationID','')) or not re.fullmatch('[1-9][0-9]*',p.get('MainPID','')):raise ValueError('actual observer process required')
    pid=int(p['MainPID']);process=PROC/str(pid);gid=pwd.getpwnam('optiplex').pw_gid
    if (process/'cmdline').read_bytes().split(b'\0')[:-1]!=[str(RUNTIME).encode(),b'-I',b'-S',str(SOURCE).encode(),b'serve']:raise ValueError('unexpected observer executable')
    status=dict(line.split(':',1) for line in (process/'status').read_text().splitlines() if ':' in line)
    if status.get('Uid','').split()!=[str(ROOT_UID)]*4 or status.get('Gid','').split()!=[str(gid)]*4:raise ValueError('observer process identity mismatch')
    if (process/'exe').resolve(strict=True)!=runtime or (process/'exe').stat().st_ino!=runtime.stat().st_ino:raise ValueError('running Python runtime mismatch')
    observed=socket_probe(pid,gid)
    if loads(CONFIG.read_bytes())!=config:raise ValueError('configuration changed during socket verification')
    return dict(invocation=p['InvocationID'],pid=pid,socket=observed,runtime_sha256=sha(runtime.read_bytes()))


def inspect(root,head,old,repository,invoke):
    if sys.platform!='linux' or os.geteuid()!=ROOT_UID or Path(root)!=ROOT:raise ValueError('fixed OptiPlex Linux root refresh required')
    if not re.fullmatch('[a-f0-9]{40}',str(old)) or not re.fullmatch('[a-f0-9]{40}',str(head)) or old==head:raise ValueError('distinct exact old and target heads required')
    if ROOT.is_symlink() or ROOT.resolve(strict=True)!=ROOT:raise ValueError('fixed nonsymlinked live checkout required')
    target=prepare(root,head,repository);git(root,'merge-base','--is-ancestor',old,head)
    old_manifest=source_manifest(root,old)
    for name in IDENTITIES:
        if old_manifest.get(name)!=target['manifest'].get(name):raise ValueError('observer/Scout bytes changed; separately reviewed full upgrade required')
    if protected(CONFIG).st_size>2_000_000:raise ValueError('bounded trusted configuration required')
    raw=CONFIG.read_bytes();current=loads(raw)
    if current!=configuration(old,old_manifest):raise ValueError('unexpected/tampered current observer configuration')
    protected(UNIT)
    if sha(UNIT.read_bytes())!=old_manifest[IDENTITIES[1]]:raise ValueError('installed observer unit mismatch')
    flags_disabled(ROOT);manifest_matches(ROOT,target['manifest']);no_discovery(invoke)
    observed=boundary(current,invoke)
    desired=configuration(head,target['manifest'])
    return dict(root=root,head=head,old=old,repository=repository,raw=raw,current=current,desired=desired,observed=observed,mode=stat.S_IMODE(CONFIG.stat().st_mode),gid=CONFIG.stat().st_gid)


def sync_directory():
    fd=os.open(CONFIG.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def durable_file(path,data,mode,gid):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:
        os.fchown(f.fileno(),ROOT_UID,gid);os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
    sync_directory()


def replace_config(path):
    os.replace(path,CONFIG);sync_directory()


def service(invoke,verb):
    if verb not in {'stop','start'}:raise ValueError('fixed observer lifecycle only')
    command(invoke,['/bin/systemctl',verb,SERVICE],check=True)


def wait_socket(previous):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try:
            info=SOCKET.lstat()
            if stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode)==0o660 and (info.st_dev,info.st_ino,info.st_ctime_ns)!=previous:return
        except FileNotFoundError:pass
        time.sleep(0.05)
    raise ValueError('recreated private observer socket unavailable')


def stop_verified(invoke):
    service(invoke,'stop')
    p=properties(command(invoke,['/bin/systemctl','show',SERVICE,'--property=ActiveState,SubState'],check=True).stdout)
    if p!={'ActiveState':'inactive','SubState':'dead'}:raise ValueError('observer stop not verified')


def refresh(root,head,old,repository='labairj-ai/investment',*,apply=False,invoke=subprocess.run):
    plan=inspect(root,head,old,repository,invoke)
    summary=dict(expected_old_head=old,target_head=head,unchanged_observer_and_units=True,runtime_sha256=plan['observed']['runtime_sha256'],manifest_files=len(plan['desired']['files']),accepted_runs_carried=0,grants_implementation=False)
    if not apply:return dict(summary,status='PLAN_ONLY',changes_applied=False)
    lock=CONFIG.parent/'pin-refresh.lock'
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as handle:
        protected(lock);fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        again=inspect(root,head,old,repository,invoke)
        if again['raw']!=plan['raw'] or again['observed']!=plan['observed']:raise ValueError('observer changed since preflight')
        backup=CONFIG.parent/('pin-refresh-backup-'+old+'.json');temp=CONFIG.parent/'config.json.refreshing'
        if backup.exists() or backup.is_symlink() or temp.exists() or temp.is_symlink():raise ValueError('existing refresh recovery material requires investigation')
        durable_file(backup,plan['raw'],plan['mode'],plan['gid'])
        try:
            stop_verified(invoke)
            if CONFIG.read_bytes()!=plan['raw']:raise ValueError('configuration changed before replacement')
            durable_file(temp,encoded(plan['desired']),plan['mode'],plan['gid']);replace_config(temp)
            service(invoke,'start');wait_socket(plan['observed']['socket'])
            if loads(CONFIG.read_bytes())!=plan['desired']:raise ValueError('post-restart config mismatch')
            if sha(UNIT.read_bytes())!=plan['desired']['files'][IDENTITIES[1]]:raise ValueError('post-restart unit mismatch')
            result=boundary(plan['desired'],invoke)
            if result['invocation']==plan['observed']['invocation'] or result['socket']==plan['observed']['socket'] or result['runtime_sha256']!=plan['observed']['runtime_sha256']:raise ValueError('observer restart/runtime/socket not verified')
            fresh=prepare(root,head,repository)
            if fresh['manifest']!=plan['desired']['files']:raise ValueError('target Git manifest changed')
            manifest_matches(ROOT,fresh['manifest']);flags_disabled(ROOT);no_discovery(invoke)
            return dict(summary,status='PIN_REFRESHED',changes_applied=True,backup=str(backup),observer_invocation=result['invocation'])
        except Exception as error:
            restored=False;config_restored=False
            try:
                stop_verified(invoke);protected(backup)
                if backup.read_bytes()!=plan['raw']:raise ValueError('rollback backup changed')
                replace_config(backup)
                if CONFIG.read_bytes()!=plan['raw']:raise ValueError('rollback configuration mismatch')
                config_restored=True
                service(invoke,'start');wait_socket(plan['observed']['socket'])
                previous=boundary(plan['current'],invoke)
                if previous['runtime_sha256']!=plan['observed']['runtime_sha256'] or previous['invocation']==plan['observed']['invocation'] or previous['socket']==plan['observed']['socket']:raise ValueError('rollback runtime/restart not verified')
                flags_disabled(ROOT);no_discovery(invoke);restored=True
            except Exception:
                try:stop_verified(invoke);stopped=True
                except Exception:stopped=False
            if not config_restored:
                try:
                    protected(CONFIG)
                    if CONFIG.read_bytes()==plan['raw']:config_restored=True
                    else:
                        quarantine=CONFIG.parent/('config.failed-refresh-'+head+'.json')
                        if quarantine.exists() or quarantine.is_symlink():raise ValueError('existing quarantine refused')
                        os.replace(CONFIG,quarantine);sync_directory()
                except (OSError,ValueError):pass  # Stop/NOT READY is mandatory even if storage cannot recover.
            try:temp.unlink(missing_ok=True)
            except OSError:pass  # Recovery material is never treated as authoritative config.
            if restored:return dict(summary,status='ROLLED_BACK_NOT_READY',changes_applied=False,prior_exact_configuration_restored=True,reason=type(error).__name__)
            return dict(summary,status='FAILED_STOPPED' if stopped else 'FAILED_STOP_UNCONFIRMED',changes_applied=False,prior_exact_configuration_restored=config_restored,rollback_boundary_verified=False,reason=type(error).__name__)
