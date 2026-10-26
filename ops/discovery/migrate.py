"""Exact root-only user-Scout -> system-Scout migration; plan-only by default.

No Scout service invocation, timer history edit, ledger write or credit migration.
Use the standalone isolated influence launcher before importing this module.
"""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from ops.discovery import pin_refresh as r,upgrade as u,observer as o
from ops.discovery.influence import audit,isolated

OLD_HEAD='43d4fda5d7c032290d51574a6d2f283d09127ee4'
OLD_OBSERVER='a7f2217b18fa4c23d432cba5c0213e3e9efed6d3ed91ef7dbf6e9b2ff1416743'
OLD_UNIT='8254a9471e3219bffca6312ddc6c763fa1ea8ae8a2633a5a3341c8eb4869c9e0'
OLD_SERVICE='dcf90c2f64f93c86a1fda46db85f48d612f62fffbef25f8e3d6aa08fd6815304'
OLD_TIMER='503231c21176889918974ef244d91a032ff8b299270d331d943c3d7336ff02a4'
SYSTEM=Path('/etc/systemd/system')
STAMP=Path('/var/lib/systemd/timers/stamp-development-scout.timer')
CERT_SOURCE=Path('/opt/investment-discovery-observer/sandbox_certify.py')
CERT_UNIT='development-scout-sandbox-certification.service'
CERT_FILES=('ops/discovery/sandbox_certify.py','ops/discovery/'+CERT_UNIT)


def system(invoke,*args,check=True):
    return invoke(['/usr/bin/systemctl','--system',*args],capture_output=True,text=True,timeout=30,check=check,env=r.ENV)


def properties(invoke,name,user=False):
    args=['show',name,'--property=LoadState,FragmentPath,DropInPaths,NeedDaemonReload,ActiveState,SubState,UnitFileState,MainPID,ControlPID,InvocationID,Result,ExecMainStatus,User,Group,RefuseManualStart']
    return r.properties((u.user(invoke,args) if user else system(invoke,*args)).stdout)


def timer_state(invoke,user,active):
    p=properties(invoke,'development-scout.timer',user)
    if active:
        if p.get('ActiveState')!='active' or p.get('UnitFileState') not in {'enabled','enabled-runtime'}:raise ValueError('expected active enabled timer')
    elif p.get('ActiveState') not in {'inactive','failed'} or p.get('UnitFileState') in {'enabled','enabled-runtime'}:raise ValueError('other timer must be inactive disabled')
    return p


def quiescent(invoke,user):
    p=properties(invoke,'development-scout.service',user)
    if p.get('ActiveState') not in {'inactive','failed'} or p.get('MainPID')!='0' or p.get('ControlPID')!='0':raise ValueError('no active Scout process permitted')
    return p


def first_activation_slot(now=None):
    """Authorize only today's pre-09:50 Eastern window; never roll to tomorrow."""
    now=time.time() if now is None else now
    local=datetime.fromtimestamp(now,ZoneInfo('America/New_York'))
    slot=local.replace(hour=10,minute=0,second=0,microsecond=0).timestamp()
    if now>=slot-600:raise ValueError('first system timer activation requires today before 09:50 Eastern')
    return slot


def daily_only(raw):
    lines=raw.decode().splitlines()
    if [s for s in lines if s.startswith('OnCalendar=')]!=['OnCalendar=*-*-* 10:00:00 America/New_York']:raise ValueError('daily-only calendar required; elapsed recovery forbidden')
    for line in ('Persistent=true','RandomizedDelaySec=120','Unit=development-scout.service'):
        if lines.count(line)!=1:raise ValueError('exact reviewed timer settings required')


def next_timer(invoke,user):
    cmd=['/usr/bin/busctl']+(['--user'] if user else ['--system'])+['get-property','org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/development_2dscout_2etimer','org.freedesktop.systemd1.Timer','NextElapseUSecRealtime']
    if user:
        a=r.pwd.getpwnam('optiplex');options=dict(user=a.pw_uid,group=a.pw_gid,extra_groups=[],env=dict(r.ENV,XDG_RUNTIME_DIR='/run/user/'+str(a.pw_uid)))
    else:options=dict(env=r.ENV)
    raw=invoke(cmd,capture_output=True,text=True,check=True,timeout=15,**options).stdout
    import re
    if not re.fullmatch(r't [0-9]{1,20}\n',raw):raise ValueError('typed next timer required')
    value=int(raw[2:])/1e6
    if not 600<value-time.time()<172800:raise ValueError('quiet timer window required')
    return value


def source_file(path):
    s=path.lstat()
    if path.is_symlink() or not stat.S_ISREG(s.st_mode) or s.st_mode&0o022:raise ValueError('fixed regular boundary required')
    return dict(path=path,data=path.read_bytes(),mode=stat.S_IMODE(s.st_mode),uid=s.st_uid,gid=s.st_gid)


def ledger_unchanged(before):
    current,rows=o.ledger_snapshot();prefix=[v for v in rows if v[0]<=before['seq']]
    if o.digest(prefix)!=before['prefix'] or current['schema']!=before['schema'] or any(v[3]!='SCHEDULER_OBSERVATION' for v in rows if v[0]>before['seq']):raise ValueError('ledger prefix/schema/authority changed')


def inspect(root,head,old,invoke):
    if sys.platform!='linux' or os.geteuid()!=r.ROOT_UID or Path(root)!=r.ROOT or r.ROOT.is_symlink() or old!=OLD_HEAD or head==old or not isolated():raise ValueError('fixed root isolated exact migration required')
    slot=first_activation_slot()
    influence=audit(root,head)
    if influence['untracked_source_influence']!='PASS':raise ValueError('source influence failed')
    target=r.prepare(root,head,'labairj-ai/investment');r.git(root,'merge-base','--is-ancestor',old,head)
    if r.git(root,'branch','--show-current').strip()!=b'main':raise ValueError('exact merged main required')
    before=r.source_manifest(root,old)
    if [before[k] for k in r.IDENTITIES]!=[OLD_OBSERVER,OLD_UNIT,OLD_SERVICE,OLD_TIMER]:raise ValueError('old exact boundary identities required')
    if target['manifest'][r.IDENTITIES[1]]!=OLD_UNIT:raise ValueError('root observer unit must not change')
    current=r.configuration(old,before);observed=r.boundary(current,invoke)
    evidence=u.state()
    if 'discovery.json' in evidence:raise ValueError('no discovery receipt permitted before migration')
    fingerprints=u.protected_state();ledger,rows=o.ledger_snapshot()
    if any(v[3] not in {'SCHEDULER_OBSERVATION'} for v in rows):raise ValueError('zero discovery/implementation history required')
    if not (r.CONTROL/'operational-signals.json').is_file():raise ValueError('existing spool required')
    oldfiles=[source_file(r.SOURCE),source_file(r.CONFIG)]
    for name,key in [('development-scout.service',r.IDENTITIES[2]),('development-scout.timer',r.IDENTITIES[3])]:
        path=r.USER_UNITS/name;item=source_file(path);p=properties(invoke,name,True)
        if r.sha(item['data'])!=before[key] or p.get('FragmentPath')!=str(path) or p.get('DropInPaths')!='' or p.get('NeedDaemonReload')!='no':raise ValueError('old user Scout boundary mismatch')
        oldfiles.append(item)
    timer_state(invoke,True,True);quiescent(invoke,True);next_timer(invoke,True)
    r.protected(STAMP.parent,directory=True)
    if STAMP.exists() or STAMP.is_symlink():raise ValueError('new system timer must have no prior persistent history; never reset it')
    desired=r.configuration(head,target['manifest']);desired['scout_manager']='system'
    targets=[(r.SOURCE,r.git(root,'show',head+':'+r.IDENTITIES[0]),oldfiles[0]['mode']),
             (r.CONFIG,r.encoded(desired),oldfiles[1]['mode']),
             (SYSTEM/'development-scout.service',r.git(root,'show',head+':'+r.IDENTITIES[2]),0o644),
             (SYSTEM/'development-scout.timer',r.git(root,'show',head+':'+r.IDENTITIES[3]),0o644),
             (CERT_SOURCE,r.git(root,'show',head+':'+CERT_FILES[0]),0o755),
             (SYSTEM/CERT_UNIT,r.git(root,'show',head+':'+CERT_FILES[1]),0o644)]
    daily_only(targets[3][1])
    if first_activation_slot()!=slot:raise ValueError('migration local date changed')
    for path,_,_ in targets[2:]:
        if path.exists() or path.is_symlink():raise ValueError('new system boundary collision')
        r.protected(path.parent,directory=True)
    for name in ('development-scout.service','development-scout.timer',CERT_UNIT):
        p=properties(invoke,name)
        if p.get('LoadState')!='not-found' or p.get('DropInPaths','')!='':raise ValueError('unexpected loaded system unit')
    return dict(slot=slot,current=current,desired=desired,observed=observed,evidence=evidence,fingerprints=fingerprints,ledger=ledger,oldfiles=oldfiles,targets=targets,influence=influence)


def system_boundary(invoke,desired):
    for name,key in [('development-scout.service',r.IDENTITIES[2]),('development-scout.timer',r.IDENTITIES[3])]:
        path=SYSTEM/name;p=properties(invoke,name)
        if path.is_symlink() or r.sha(path.read_bytes())!=desired['files'][key] or p.get('FragmentPath')!=str(path) or p.get('DropInPaths')!='' or p.get('NeedDaemonReload')!='no':raise ValueError('system Scout unit identity mismatch')
        if name.endswith('.service'):
            expected={'User':'optiplex','Group':'optiplex','RefuseManualStart':'yes','PrivateNetwork':'yes','PrivateTmp':'yes','ProtectSystem':'strict','ProtectHome':'read-only','NoNewPrivileges':'yes','WorkingDirectory':str(r.ROOT)}
            raw=system(invoke,'show',name,'--property='+','.join(expected)).stdout
            actual=r.properties(raw)
            if any(actual.get(k)!=v for k,v in expected.items()) or p.get('InvocationID','') not in {'','0'*32}:raise ValueError('system Scout sandbox or unexpected execution')
            quiescent(invoke,False)


def certify(invoke,start):
    # No application source import and no Scout call. Three separate sandboxed
    # phases must all execute, covering the former stop-post namespace failure.
    p=properties(invoke,CERT_UNIT)
    if p.get('FragmentPath')!=str(SYSTEM/CERT_UNIT) or p.get('DropInPaths')!='' or p.get('NeedDaemonReload')!='no' or p.get('User')!='optiplex' or p.get('Group')!='optiplex':raise ValueError('certification unit identity invalid')
    system(invoke,'start',CERT_UNIT)
    p=properties(invoke,CERT_UNIT)
    if p.get('Result')!='success' or p.get('ExecMainStatus')!='0':raise ValueError('runtime namespace certification failed')
    inv=p.get('InvocationID','')
    import re
    if not re.fullmatch('[a-f0-9]{32}',inv):raise ValueError('real certification invocation required')
    raw=invoke(['/usr/bin/journalctl','--no-pager','-o','json','_SYSTEMD_INVOCATION_ID='+inv,'--since=@'+str(start)],capture_output=True,text=True,check=True,timeout=30,env=r.ENV).stdout
    if len(raw)>65536:raise ValueError('bounded certification journal required')
    expected={'network_namespace_isolated','repository_read_only','protected_state_inaccessible','credentials_inaccessible','process_uid_expected','system_manager_readable','execution_record_current','test_evidence_only','accepted_scout_run'};reports=[]
    for line in raw.splitlines():
        message=r.loads(line).get('MESSAGE','')
        if message.startswith('{'):
            report=r.loads(message)
            if set(report)!=expected or any(v is not True for k,v in report.items() if k!='accepted_scout_run') or report['accepted_scout_run'] is not False:raise ValueError('certification runtime booleans failed')
            reports.append(report)
    if len(reports)!=3:raise ValueError('pre/main/post certification reports required')
    return dict(invocation=inv,test_evidence_only=True,accepted_scout_run=False,reports=reports)


def install_new(path,data,mode,installed):
    if path.exists() or path.is_symlink():raise FileExistsError('reviewed new boundary already exists')
    temporary=path.with_name(path.name+'.scout-migrating')
    if temporary.exists() or temporary.is_symlink():raise ValueError('migration temporary collision')
    try:
        u.write(temporary,data,mode,r.ROOT_UID,os.getgid())
        # Link a completely fsynced inode with no overwrite of a competing path.
        os.link(temporary,path,follow_symlinks=False);installed.append(path);u.sync(path.parent)
    finally:
        if temporary.exists():temporary.unlink();u.sync(path.parent)


def migrate(root,head,old,*,apply=False,invoke=subprocess.run):
    plan=inspect(root,head,old,invoke)
    summary=dict(status='PLAN_ONLY',changes_applied=False,source_head=head,expected_old_head=old,accepted_runs=0,grants_implementation=False,scout_manager='system',untracked_source_influence=plan['influence'],old_boundary={k:plan['current'][k] for k in ('observer_digest','unit_digest','timer_digest')},new_boundary={k:plan['desired'][k] for k in ('observer_digest','unit_digest','timer_digest')},changed_files=[str(p) for p,_,_ in plan['targets']])
    if not apply:return summary
    lock=r.CONFIG.parent/'scout-system-migration.lock';fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as handle:
        r.protected(lock);fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if inspect(root,head,old,invoke)!=plan:raise ValueError('migration preflight changed')
        if first_activation_slot()!=plan['slot']:raise ValueError('migration activation window changed')
        backup=r.CONFIG.parent/('scout-system-migration-backup-'+head);backup.mkdir(mode=0o700);u.sync(backup.parent)
        for i,item in enumerate(plan['oldfiles']):u.write(backup/str(i),item['data'],item['mode'],item['uid'],item['gid'])
        u.write(backup/'manifest.json',r.encoded(dict(old=old,head=head,old_files=[{k:str(v) if k=='path' else v for k,v in f.items() if k!='data'}|{'sha256':r.sha(f['data'])} for f in plan['oldfiles']],new_paths=[str(p) for p,_,_ in plan['targets'][2:]],evidence={name:r.sha(data) for name,data in plan['evidence'].items()},old_user_timer_enabled=True)),0o600,r.ROOT_UID,os.getgid())
        for name,data in plan['evidence'].items():u.write(backup/('evidence-'+name),data,0o600,r.ROOT_UID,os.getgid())
        quiescent(invoke,True)
        if first_activation_slot()!=plan['slot']:raise ValueError('migration activation window changed before timer stop')
        started=time.time();installed=[]
        try:
            u.user(invoke,['disable','--now','development-scout.timer']);timer_state(invoke,True,False);quiescent(invoke,True)
            r.stop_verified(invoke)
            for path,data,mode in plan['targets']:
                if path in {r.SOURCE,r.CONFIG}:
                    original=next(f for f in plan['oldfiles'] if f['path']==path);u.replace(path,data,mode,original['uid'],original['gid'])
                else:install_new(path,data,mode,installed)
            system(invoke,'daemon-reload');timer_state(invoke,False,False);system_boundary(invoke,plan['desired'])
            cert=certify(invoke,started)
            ledger_unchanged(plan['ledger'])
            if u.state()!=plan['evidence'] or u.protected_state()!=plan['fingerprints']:raise ValueError('certification touched protected state')
            timer_state(invoke,True,False)
            # Reauthorize today's pre-slot window after certification. Never
            # rely on tomorrow's calendar or edit/copy persistent timer history.
            if first_activation_slot()!=plan['slot'] or STAMP.exists() or STAMP.is_symlink():raise ValueError('quiet first system timer activation required')
            system(invoke,'enable','--now','development-scout.timer');timer_state(invoke,False,True);timer_state(invoke,True,False)
            nxt=next_timer(invoke,False)
            if not plan['slot']<=nxt<=plan['slot']+120:raise ValueError('new timer must target next normal Eastern slot')
            quiescent(invoke,False)
            r.service(invoke,'start');r.wait_socket(plan['observed']['socket']);seen=r.boundary(plan['desired'],invoke)
            if seen['invocation']==plan['observed']['invocation'] or seen['socket']==plan['observed']['socket'] or seen['runtime_sha256']!=plan['observed']['runtime_sha256']:raise ValueError('new observer restart verification failed')
            ledger_unchanged(plan['ledger']);r.manifest_matches(root,plan['desired']['files'])
            if u.state()!=plan['evidence'] or u.protected_state()!=plan['fingerprints'] or audit(root,head)['untracked_source_influence']!='PASS':raise ValueError('post-migration protected state changed')
            for path,data,_ in plan['targets']:
                if path.read_bytes()!=data:raise ValueError('installed boundary changed')
            timer_state(invoke,True,False);timer_state(invoke,False,True);system_boundary(invoke,plan['desired'])
            result=dict(summary,status='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS',changes_applied=True,backup=str(backup),certification=cert,observer=seen)
        except Exception:
            restored=False;stopped=False
            try:
                system(invoke,'disable','--now','development-scout.timer',check=False);u.user(invoke,['disable','--now','development-scout.timer'])
                r.stop_verified(invoke);stopped=True
                for i,item in enumerate(plan['oldfiles']):
                    if (backup/str(i)).read_bytes()!=item['data']:raise ValueError('old backup integrity failed')
                    u.replace(item['path'],item['data'],item['mode'],item['uid'],item['gid'])
                for path in reversed(installed):path.unlink();u.sync(path.parent)
                system(invoke,'daemon-reload')
                timer_state(invoke,True,False);quiescent(invoke,True)
                restored=not any(path.exists() or path.is_symlink() for path,_,_ in plan['targets'][2:]) and all(f['path'].read_bytes()==f['data'] and stat.S_IMODE(f['path'].stat().st_mode)==f['mode'] and f['path'].stat().st_uid==f['uid'] and f['path'].stat().st_gid==f['gid'] for f in plan['oldfiles'])
            except Exception:
                try:r.stop_verified(invoke);stopped=True
                except Exception:pass
            # Both timers/observer remain stopped. Restored old observer pins old
            # source, so never present it as ready against the new checkout.
            result=dict(summary,status='ROLLED_BACK_STOPPED_NOT_READY' if restored else 'FAILED_STOPPED_NOT_READY' if stopped else 'FAILED_STOP_UNCONFIRMED_NOT_READY',changes_applied=False,backup=str(backup),old_files_restored=restored,observer_stopped=stopped)
        u.write(backup/'result.json',r.encoded(result),0o600,r.ROOT_UID,os.getgid())
        return result
