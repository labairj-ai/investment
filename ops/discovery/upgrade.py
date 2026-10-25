"""Separately reviewed fixed observer upgrade. Never invokes Scout or changes credit.

Only the observer executable and Scout service/timer may change in this upgrade family.
The root observer unit must remain byte-identical. Apply requires
an exact reviewed merged main, not a PR head. Default is a read-only plan.
"""
import argparse
import fcntl
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from ops.discovery import pin_refresh as r

OLD_HEAD='19fd140227a5b9b3cec27e6a2f91e610842e9947'
OLD_EXECUTABLE='8537f44523e434052dfa2379796f43bf85c9c6919ef9e99362c20de682801888'
OLD_UNIT='8254a9471e3219bffca6312ddc6c763fa1ea8ae8a2633a5a3341c8eb4869c9e0'
OLD_SCOUT_SERVICE='e117fd0c25ff2e1d72b6944ff2a9b5ab0753ba71b4c1e53928f2f9f8f5fd7f13'
OLD_SCOUT_TIMER='3428a3290345f0dcb0730e21963c390d8168c1aacd22816ab336ce9e2d14db98'
CHANGED=(r.IDENTITIES[0],r.IDENTITIES[2],r.IDENTITIES[3])


def state():
    r.protected(r.STATE,directory=True)
    result={}
    for p in r.STATE.iterdir():
        r.protected(p)
        if p.stat().st_size>2_000_000:raise ValueError('bounded failure evidence required')
        if p.name not in {'timer-fires.json','discovery.json'} and not re.fullmatch('[a-f0-9]{32}\\.pending',p.name):raise ValueError('unreviewed acceptance evidence')
        result[p.name]=p.read_bytes()
    if 'discovery.json' in result and r.loads(result['discovery.json']).get('runs')!=[]:raise ValueError('zero accepted runs required; migration forbidden')
    return result


def user(invoke,args):
    account=r.pwd.getpwnam('optiplex')
    return invoke(['/usr/bin/systemctl','--user',*args],capture_output=True,text=True,timeout=15,check=True,
        env=dict(r.ENV,XDG_RUNTIME_DIR='/run/user/'+str(account.pw_uid)),user=account.pw_uid,group=account.pw_gid,extra_groups=[])


def scouts(invoke,manifest):
    # Never stop/start/enable a discovery unit. Require a quiet upgrade window.
    for name,key in (('development-scout.service',r.IDENTITIES[2]),('development-scout.timer',r.IDENTITIES[3])):
        path=r.USER_UNITS/name
        if path.is_symlink() or r.sha(path.read_bytes())!=manifest[key]:raise ValueError('installed Scout identity mismatch')
        p=r.properties(user(invoke,['show',name,'--property=FragmentPath,DropInPaths,NeedDaemonReload,ActiveState,ControlPID,MainPID']).stdout)
        if p.get('FragmentPath')!=str(path) or p.get('DropInPaths')!='' or p.get('NeedDaemonReload')!='no':raise ValueError('loaded Scout identity mismatch')
        if name.endswith('.service') and (p.get('ActiveState') not in {'inactive','failed'} or p.get('ControlPID')!='0' or p.get('MainPID')!='0'):raise ValueError('Scout must be quiescent')
        if name.endswith('.timer') and p.get('ActiveState')!='active':raise ValueError('existing Scout timer must remain active')
    # Typed realtime avoids locale/date parsing. This is a window guard, never
    # provenance or acceptance. No attempt is manufactured by upgrade tooling.
    account=r.pwd.getpwnam('optiplex')
    raw=invoke(['/usr/bin/busctl','--user','get-property','org.freedesktop.systemd1',
        '/org/freedesktop/systemd1/unit/development_2dscout_2etimer','org.freedesktop.systemd1.Timer','NextElapseUSecRealtime'],
        capture_output=True,text=True,timeout=15,check=True,env=dict(r.ENV,XDG_RUNTIME_DIR='/run/user/'+str(account.pw_uid)),
        user=account.pw_uid,group=account.pw_gid,extra_groups=[]).stdout
    if not re.fullmatch(r't [0-9]{1,20}\n',raw) or not 600<int(raw[2:])/1e6-time.time()<172800:raise ValueError('quiet genuine timer window required')


def protected_state():
    # Hash only; do not open SQLite, execute application code or emit contents.
    r.flags_disabled(r.ROOT)
    worktrees=r.CONTROL/'worktrees'
    if worktrees.is_symlink() or worktrees.exists() and any(worktrees.iterdir()):raise ValueError('no implementation worktree permitted')
    result={}
    for name in ('config/development_agent.json','holdings.csv','out/investment.db','out/buffett.db'):
        path=r.ROOT/name
        if path.is_symlink() or not path.is_file():raise ValueError('regular protected financial state required')
        result[name]=r.sha(path.read_bytes())
        if name.endswith('.db'):
            for suffix in ('-wal','-journal'):
                side=path.with_name(path.name+suffix)
                if side.is_symlink():raise ValueError('financial sidecar symlink refused')
                result[name+suffix]=r.sha(side.read_bytes()) if side.exists() else None
    return result


def recovery_schedule(data):
    entries=[line for line in data.decode().splitlines() if line.startswith('OnCalendar=')]
    if entries!=['OnCalendar=*-*-* 08:15:00 America/New_York','OnCalendar=2026-10-25 12:15:00 America/New_York']:raise ValueError('exact normal and single recovery calendar required')
    recovery=datetime(2026,10,25,12,15,tzinfo=ZoneInfo('America/New_York')).timestamp()
    if recovery-time.time()<600:raise ValueError('reviewed recovery window has passed or is too close')


def inspect(root,head,old,invoke):
    if sys.platform!='linux' or os.geteuid()!=r.ROOT_UID or Path(root)!=r.ROOT or r.ROOT.is_symlink():raise ValueError('fixed root-only OptiPlex layout required')
    if old!=OLD_HEAD or not re.fullmatch('[a-f0-9]{40}',head) or head==old:raise ValueError('exact reviewed old and new heads required')
    target=r.prepare(root,head,'labairj-ai/investment')
    if r.git(root,'status','--porcelain').strip() or r.git(root,'branch','--show-current').strip()!=b'main':raise ValueError('clean main checkout required')
    r.git(root,'merge-base','--is-ancestor',old,head)
    before=r.source_manifest(root,old);after=target['manifest']
    if {n for n in r.IDENTITIES if before[n]!=after[n]}!=set(CHANGED):raise ValueError('only explicitly reviewed executable and Scout service/timer changes allowed')
    if before[r.IDENTITIES[0]]!=OLD_EXECUTABLE or before[r.IDENTITIES[1]]!=OLD_UNIT or before[r.IDENTITIES[2]]!=OLD_SCOUT_SERVICE or before[r.IDENTITIES[3]]!=OLD_SCOUT_TIMER:raise ValueError('old reviewed boundary identity mismatch')
    current=r.configuration(old,before)
    r.flags_disabled(root);r.manifest_matches(root,after)
    observed=r.boundary(current,invoke);scouts(invoke,before);evidence=state();fingerprints=protected_state()
    paths=(r.SOURCE,r.CONFIG,r.USER_UNITS/'development-scout.service',r.USER_UNITS/'development-scout.timer')
    files=[]
    for path in paths:
        info=path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode&0o022:raise ValueError('regular fixed upgrade file required')
        files.append((path,path.read_bytes(),stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid))
    recovery_schedule(r.git(root,'show',head+':'+r.IDENTITIES[3]))
    desired=r.configuration(head,after)
    new=(r.git(root,'show',head+':'+CHANGED[0]),r.encoded(desired),r.git(root,'show',head+':'+CHANGED[1]),r.git(root,'show',head+':'+CHANGED[2]))
    return dict(current=current,desired=desired,observed=observed,evidence=evidence,files=files,new=new,fingerprints=fingerprints)


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def write(path,data,mode,uid,gid):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:
        os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
    sync(path.parent)


def replace(path,data,mode,uid,gid):
    temp=path.with_name(path.name+'.observer-upgrading')
    write(temp,data,mode,uid,gid);os.replace(temp,path);sync(path.parent)


def reload_scout(invoke):
    # Only Scout user units change; no system-manager daemon-reload needed.
    user(invoke,['daemon-reload'])


def upgrade(root,head,old,*,apply=False,invoke=subprocess.run):
    plan=inspect(root,head,old,invoke)
    summary=dict(expected_old_head=old,target_head=head,accepted_runs=0,grants_implementation=False,ready=False,
        expected_old_observer=OLD_EXECUTABLE,expected_old_scout_service=OLD_SCOUT_SERVICE,expected_old_scout_timer=OLD_SCOUT_TIMER,
        target_observer=plan['desired']['observer_digest'],target_scout_service=plan['desired']['unit_digest'],target_scout_timer=plan['desired']['timer_digest'],
        fingerprints=plan['fingerprints'],changed_boundary_files=list(CHANGED),runtime_sha256=plan['observed']['runtime_sha256'])
    if not apply:return dict(summary,status='PLAN_ONLY',changes_applied=False)
    lock=r.CONFIG.parent/'observer-upgrade.lock'
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as handle:
        r.protected(lock);fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        again=inspect(root,head,old,invoke)
        if again!=plan:raise ValueError('upgrade preflight changed')
        backup=r.CONFIG.parent/('observer-upgrade-backup-'+head)
        backup.mkdir(mode=0o700);sync(backup.parent)
        for i,(_,data,mode,uid,gid) in enumerate(plan['files']):write(backup/str(i),data,mode,uid,gid)
        for name,data in plan['evidence'].items():write(backup/('evidence-'+name),data,0o600,r.ROOT_UID,os.getgid())
        write(backup/'manifest.json',r.encoded(dict(old=old,head=head,files=[dict(path=str(p),sha256=r.sha(data),mode=mode,uid=uid,gid=gid) for p,data,mode,uid,gid in plan['files']])),0o600,r.ROOT_UID,os.getgid())
        try:
            r.stop_verified(invoke)
            scouts(invoke,plan['current']['files'])
            if state()!=plan['evidence'] or protected_state()!=plan['fingerprints']:raise ValueError('failure evidence/protected state changed')
            for (path,data,mode,uid,gid),new in zip(plan['files'],plan['new']):
                if path.read_bytes()!=data:raise ValueError('boundary changed before atomic install')
                replace(path,new,mode,uid,gid)
            recovery_schedule(plan['new'][3])
            reload_scout(invoke)
            scouts(invoke,plan['desired']['files'])
            r.service(invoke,'start');r.wait_socket(plan['observed']['socket'])
            seen=r.boundary(plan['desired'],invoke)
            if seen['invocation']==plan['observed']['invocation'] or seen['socket']==plan['observed']['socket'] or seen['runtime_sha256']!=plan['observed']['runtime_sha256']:raise ValueError('restart verification failed')
            fresh=r.prepare(root,head,'labairj-ai/investment');r.manifest_matches(root,fresh['manifest']);r.flags_disabled(root)
            if fresh['manifest']!=plan['desired']['files'] or state()!=plan['evidence'] or protected_state()!=plan['fingerprints']:raise ValueError('source/evidence changed')
            scouts(invoke,plan['desired']['files'])
            return dict(summary,status='UPGRADED_AWAITING_GENUINE_TIMER_RUNS',changes_applied=True,backup=str(backup))
        except Exception:
            restored=False;stopped=False
            try:
                r.stop_verified(invoke)
                for i,(path,data,mode,uid,gid) in enumerate(plan['files']):
                    if (backup/str(i)).read_bytes()!=data:raise ValueError('backup mismatch')
                    # Keep durable backups; never consume them on restoration.
                    replace(path,data,mode,uid,gid)
                reload_scout(invoke)
                for path,data,mode,uid,gid in plan['files']:
                    info=path.stat()
                    if path.read_bytes()!=data or stat.S_IMODE(info.st_mode)!=mode or (info.st_uid,info.st_gid)!=(uid,gid):raise ValueError('rollback file mismatch')
                scouts(invoke,plan['current']['files'])
                if state()!=plan['evidence']:raise ValueError('evidence changed; no repair/fabrication allowed')
                # Old config pins old source. Target checkout is new main; keep
                # observer stopped rather than present an unusable old snapshot.
                restored=True;stopped=True
            except Exception:
                try:r.stop_verified(invoke);stopped=True
                except Exception:pass
            return dict(summary,status='ROLLED_BACK_NOT_READY' if restored else 'FAILED_STOPPED_NOT_READY' if stopped else 'FAILED_STOP_UNCONFIRMED_NOT_READY',changes_applied=False,exact_old_files_restored=restored,observer_stopped=stopped,backup=str(backup))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--head',required=True);p.add_argument('--expected-old-head',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    result=upgrade(a.root,a.head,a.expected_old_head,apply=a.apply)
    print(r.encoded(result).decode(),end='')
    if 'NOT_READY' in result['status']:raise SystemExit(1)
