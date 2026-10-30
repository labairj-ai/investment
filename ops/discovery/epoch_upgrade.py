"""One separately authorized source/observer transaction; never controls Scout/timer.

Default PLAN_ONLY. Root release-controller authorization is a verified solo-owner
receipt, not a caller bool or a model claim. Existing zero-history tools stay shut.
An incomplete transition cannot authorize Scout; rollback uses the durable journal.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from ops.discovery import observer as o, pin_refresh as r, upgrade as u, migrate as m
from ops.discovery.influence import audit, git_boundary, git as reviewed_git, isolated

OLD='a27bed1ebd3a69df5723212784842df456e153b3'
AUTH=r.CONFIG.parent/'scout-epoch-authorization.json'
STAMP=Path('/var/lib/systemd/timers/stamp-development-scout.timer')
ALLOWED={'.github/workflows/test.yml','ops/discovery/observer.py','ops/discovery/epoch_upgrade.py','ops/discovery/influence.py','dev_agent/scheduler.py','dev_agent/scheduler_health.py'}
SCOPE='scout-source-epoch-transition-once'


def require(ok,message):
    if not ok:raise ValueError(message)


def authorization(path,old,head):
    r.protected(path)
    require(path.stat().st_size<=16000,'bounded authorization required')
    raw=path.read_bytes();a=r.loads(raw)
    fields={'version','repository','scope','old_head','target_head','reviewed_head','merge_sha','risk','decision','nonce','created','financial_ack','execution_ack','authentication_source','owner_object','owner_verified','ci_head','ci_status','historical_receipt_sha256','historical_runs'}
    require(set(a)==fields,'exact release authorization schema required')
    require(a['version']=='scout-epoch-authorization-1' and a['repository']=='labairj-ai/investment' and a['scope']==SCOPE,'fixed authorization scope required')
    require(a['old_head']==old and a['target_head']==a['merge_sha']==a['ci_head']==head and a['ci_status']=='PASS','exact merged target and CI required')
    require(re.fullmatch('[a-f0-9]{40}',str(a['reviewed_head'])) is not None,'reviewed PR head required')
    require(a['risk']=='L5' and a['decision']=='APPROVE' and a['financial_ack'] is True and a['execution_ack'] is True,'explicit L5 domain acknowledgments required')
    require(a['authentication_source']=='solo-owner-1' and a['owner_verified'] is True and re.fullmatch(r'https://github.com/labairj-ai/investment/pull/[1-9][0-9]*#issuecomment-[1-9][0-9]*',str(a['owner_object'])) is not None,'verified authenticated owner object required')
    require(type(a['created']) in (int,float) and 0<=time.time()-a['created']<=3600 and re.fullmatch('[A-Za-z0-9-]{16,128}',str(a['nonce'])) is not None,'fresh single-use authorization required')
    require(re.fullmatch('[a-f0-9]{64}',str(a['historical_receipt_sha256'])) is not None and type(a['historical_runs']) is int and 1<=a['historical_runs']<=30,'exact historical acceptance binding required')
    require(path.read_bytes()==raw,'authorization changed')
    return a


class Host:
    """Fixed privileged release adapter. No Scout/timer control method exists."""
    def __init__(self,head,old=OLD,invoke=subprocess.run):self.head=head;self.old=old;self.invoke=invoke
    def git(self,*args):return reviewed_git(r.ROOT,*args)
    def quiet(self):
        m.quiescent(self.invoke,False);m.timer_state(self.invoke,False,True);m.timer_state(self.invoke,True,False)
        value=m.next_timer(self.invoke,False)
        # Prove no queued current start job, even before ControlPID is published.
        raw=self.invoke(['/usr/bin/busctl','--system','--json=short','get-property','org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/development_2dscout_2eservice','org.freedesktop.systemd1.Unit','Job'],capture_output=True,text=True,check=True,timeout=10,env=r.ENV).stdout
        require(r.loads(raw)=={'type':'(uo)','data':[0,'/']},'no active Scout activation job permitted')
        return value
    def timer_identity(self):
        r.protected(STAMP)
        fields='LastTriggerUSec,LastTriggerUSecMonotonic,NextElapseUSecRealtime,InactiveExitTimestampMonotonic,UnitFileState,ActiveState,FragmentPath,DropInPaths,NeedDaemonReload'
        p=r.properties(r.command(self.invoke,['/usr/bin/systemctl','--system','show','development-scout.timer','--property='+fields],check=True).stdout)
        return dict(properties=p,stamp=r.sha(STAMP.read_bytes()),stamp_mtime_ns=STAMP.stat().st_mtime_ns,stamp_inode=STAMP.stat().st_ino)
    def unit_boundary(self,config):
        # A completed/failed oneshot may retain InvocationID; zero PIDs and no
        # current Job establish quiescence, never an empty historical property.
        for name,key in [('development-scout.service',r.IDENTITIES[2]),('development-scout.timer',r.IDENTITIES[3])]:
            path=m.SYSTEM/name;r.protected(path);p=m.properties(self.invoke,name)
            require(r.sha(path.read_bytes())==config['files'][key] and p.get('FragmentPath')==str(path) and p.get('DropInPaths')=='' and p.get('NeedDaemonReload')=='no','reviewed SYSTEM unit identity required')
        expected={'User':'optiplex','Group':'optiplex','RefuseManualStart':'yes','PrivateNetwork':'yes','PrivateTmp':'yes','ProtectSystem':'strict','ProtectHome':'read-only','NoNewPrivileges':'yes','WorkingDirectory':str(r.ROOT)}
        actual=r.properties(m.system(self.invoke,'show','development-scout.service','--property='+','.join(expected)).stdout)
        require(all(actual.get(k)==v for k,v in expected.items()),'unchanged SYSTEM sandbox required')
        m.quiescent(self.invoke,False)
    def staged_boundary(self,target):
        # Root release tooling itself must come from the reviewed protected
        # staging tree, never the user-writable live checkout or bytecode.
        stage=Path(__file__).resolve().parents[2]
        require(stage==Path('/var/cache/investment-discovery-epoch-source')/self.head,'fixed protected release source required')
        for name,module in tuple(sys.modules.items()):
            if name.startswith(('ops.','dev_agent.')) and getattr(module,'__file__',None):
                path=Path(module.__file__);r.protected(path)
                rel=str(path.relative_to(stage))
                require(rel in target and r.sha(path.read_bytes())==target[rel],'exact staged release module required')
    def inspect(self):
        require(sys.platform=='linux' and os.geteuid()==0 and str(r.ROOT)=='/home/optiplex/investment' and isolated(),'fixed isolated Linux root release path required')
        require(self.old==OLD and re.fullmatch('[a-f0-9]{40}',self.head) is not None and self.head!=self.old,'exact reviewed transition required')
        require(not git_boundary(r.ROOT),'reviewed Git boundary required')
        for head in (self.old,self.head):
            require(audit(r.ROOT,head)['untracked_source_influence']=='PASS','old and target source influence required before transition')
        require(self.git('rev-parse','HEAD').decode().strip()==self.old and not self.git('status','--porcelain','--untracked-files=no').strip(),'clean exact old source required')
        require(self.git('rev-parse','origin/main').decode().strip()==self.head,'exact merged main target required')
        self.git('merge-base','--is-ancestor',self.old,self.head)
        changed=self.git('diff','--name-only',self.old,self.head).decode().splitlines()
        require(changed and all(n in ALLOWED or n.startswith(('tests/','docs/')) for n in changed),'narrow nonfinancial Scout release required')
        r.flags_disabled(r.ROOT)
        r.protected(r.CONFIG);current=r.loads(r.CONFIG.read_bytes())
        require(current.get('head')==self.old and current.get('scout_manager')=='system' and 'acceptance_epoch' not in current,'exact legacy SYSTEM boundary required')
        r.boundary(current,self.invoke);self.unit_boundary(current)
        r.manifest_matches(r.ROOT,current['files'])
        ledger,rows=o.ledger_snapshot();before=dict(ledger=ledger,protected=u.protected_state())
        require(not list(r.STATE.glob('*.pending')) and not (r.CONTROL/'worktrees').is_symlink() and not ((r.CONTROL/'worktrees').exists() and any((r.CONTROL/'worktrees').iterdir())),'no pending bookends/worktrees permitted')
        receipt=r.STATE/'discovery.json';r.protected(receipt)
        data=r.loads(receipt.read_bytes())
        require(data.get('source_head')==self.old and data.get('fixture_only') is False and data.get('os_boundary_verified') is True and data.get('grants_implementation') is False,'historical source authority required')
        require(type(data.get('runs')) is list and 1<=len(data['runs'])<=30,'bounded nonempty historical acceptance required')
        require(len({x['slot'] for x in data['runs']})==len(data['runs'])==len({x['invocation'] for x in data['runs']}),'distinct historical records required')
        require(any(x['slot']=='scout:2026-10-29' and x['invocation']=='8608a7c10e9b4c23b96cf91bcc8fa51f' for x in data['runs']),'October 29 history required')
        for x in data['runs']:
            matched=[r.loads(row[5]) for row in rows if row[3]=='SCHEDULE' and r.loads(row[5]).get('slot')==x['slot']]
            require(len(matched)==1 and matched[0].get('head')==self.old and matched[0].get('status')=='COLLECTED' and matched[0].get('trigger')==dict(source='systemd-observed-timer',invocation=x['invocation']),'historical receipt must join original collection')
            require(all(x.get(k) is True for k in ('no_builder','no_worktree','no_source_mutation','no_pr','no_deploy','no_financial_execution')) and all(x.get(k+'_before')==x.get(k+'_after') and re.fullmatch('[a-f0-9]{64}',str(x.get(k+'_before'))) for k in ('holdings','investment')),'historical safety required')
        # Archive the exact observed failed invocation, sanitized trusted fields only.
        raw=r.command(self.invoke,['/usr/bin/journalctl','--no-pager','-o','json','_SYSTEMD_INVOCATION_ID=77541c9232d74e578d6d0f596cce954d'],check=True).stdout
        require(len(raw)<=2_000_000,'bounded failure journal required')
        failure=[]
        for line in raw.splitlines():
            e=r.loads(line)
            if e.get('_SYSTEMD_UNIT')=='development-scout.service':failure.append({k:e[k] for k in ('_SYSTEMD_UNIT','_SYSTEMD_INVOCATION_ID','_BOOT_ID','_PID','_UID','__REALTIME_TIMESTAMP','__MONOTONIC_TIMESTAMP') if k in e})
        require(failure,'retained October 30 failure identity required')
        raw=r.command(self.invoke,['/usr/bin/journalctl','--no-pager','-o','json','_SYSTEMD_UNIT=investment-discovery-observer.service','--since','2026-10-30 19:59:00 UTC','--until','2026-10-30 20:05:00 UTC'],check=True).stdout
        require(len(raw)<=2_000_000,'bounded observer failure journal required')
        codes=[]
        for line in raw.splitlines():
            e=r.loads(line)
            if e.get('_UID')=='0':
                for code in re.findall(r'DISCOVERY_OBSERVER_FAILURE (TIMER_TRIGGER_INVALID|BOOKEND_INVALID)',e.get('MESSAGE','')):
                    codes.append(dict(code=code,boot=e.get('_BOOT_ID'),at=e.get('__REALTIME_TIMESTAMP')))
        require({c['code'] for c in codes}=={'TIMER_TRIGGER_INVALID','BOOKEND_INVALID'},'retained rejected bookends required')
        failure=dict(service=failure,observer=codes)
        target=r.source_manifest(r.ROOT,self.head)
        self.staged_boundary(target)
        for name in r.IDENTITIES[1:]:require(target[name]==current['files'][name],'all unit bytes must remain unchanged')
        desired=r.configuration(self.head,target);desired.update(scout_manager='system',acceptance_epoch=self.head)
        self.quiet()
        return dict(old=self.old,head=self.head,current=current,desired=desired,before=before,timer=self.timer_identity(),receipt=receipt.read_bytes(),fires=(r.STATE/'timer-fires.json').read_bytes(),failure=r.encoded(failure),source=r.SOURCE.read_bytes(),config=r.CONFIG.read_bytes(),new_source=self.git('show',self.head+':ops/discovery/observer.py'),new_config=r.encoded(desired))
    def recovery_guard(self,plan):
        require(sys.platform=='linux' and os.geteuid()==0 and isolated() and str(r.ROOT)=='/home/optiplex/investment','fixed isolated root recovery required')
        require(plan['old']==self.old and plan['head']==self.head and self.old==OLD,'exact recovery source required')
        require(not git_boundary(r.ROOT),'reviewed Git recovery boundary required')
        self.staged_boundary(r.source_manifest(r.ROOT,self.head))
    def authorize(self):
        a=authorization(AUTH,self.old,self.head)
        # The protected release-controller attestation cannot substitute a different
        # PR head into a target: reviewed head must be in this merged source.
        self.git('merge-base','--is-ancestor',a['reviewed_head'],self.head)
        return a
    def guard(self,plan):
        self.quiet();require(self.timer_identity()==plan['timer'],'persistent timer history changed')
        require((r.STATE/'discovery.json').read_bytes()==plan['receipt'] and (r.STATE/'timer-fires.json').read_bytes()==plan['fires'],'historical evidence changed')
        m.ledger_unchanged(plan['before']['ledger']);r.flags_disabled(r.ROOT)
    def stop(self):
        r.command(self.invoke,['/bin/systemctl','stop',r.SERVICE],check=True)
        p=r.properties(r.command(self.invoke,['/bin/systemctl','show',r.SERVICE,'--property=ActiveState,SubState,MainPID'],check=True).stdout)
        require(p=={'ActiveState':'inactive','SubState':'dead','MainPID':'0'},'observer must be stopped')
        self.quiet()
    def checkout(self,head):
        account=r.pwd.getpwnam('optiplex')
        self.invoke(['/usr/bin/git','-C',str(r.ROOT),'-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','checkout','--detach',head],check=True,capture_output=True,timeout=120,env=dict(r.ENV,GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_NO_REPLACE_OBJECTS='1'),user=account.pw_uid,group=account.pw_gid,extra_groups=[])
    def install(self,plan):
        self.checkout(self.head)
        u.replace(r.SOURCE,plan['new_source'],0o644,0,os.getgid())
        # Config/epoch selector is the last commit point. Observer remains stopped.
        u.replace(r.CONFIG,plan['new_config'],0o644,0,os.getgid())
    def verify(self,plan,new):
        config=plan['desired'] if new else plan['current']
        require(self.git('rev-parse','HEAD').decode().strip()==config['head'] and not self.git('status','--porcelain','--untracked-files=no').strip(),'exact coherent source required')
        require(r.CONFIG.read_bytes()==(plan['new_config'] if new else plan['config']) and r.sha(r.SOURCE.read_bytes())==config['observer_digest'],'coherent installed boundary required')
        result=audit(r.ROOT,config['head']);require(result['untracked_source_influence']=='PASS','source influence must pass')
        r.manifest_matches(r.ROOT,config['files'])
        require(u.protected_state()==plan['before']['protected'],'protected state changed; never restore financial data')
        self.guard(plan);self.unit_boundary(config)
    def start(self,plan,new):
        r.command(self.invoke,['/bin/systemctl','start',r.SERVICE],check=True)
        r.boundary(plan['desired'] if new else plan['current'],self.invoke)
    def restore(self,plan):
        self.checkout(self.old)
        u.replace(r.SOURCE,plan['source'],0o644,0,os.getgid());u.replace(r.CONFIG,plan['config'],0o644,0,os.getgid())


def encode_plan(plan):return {k:(dict(bytes_hex=v.hex()) if isinstance(v,bytes) else v) for k,v in plan.items()}
def decode_plan(plan):return {k:(bytes.fromhex(v['bytes_hex']) if isinstance(v,dict) and set(v)=={'bytes_hex'} else v) for k,v in plan.items()}


def transaction(host,*,apply=False):
    plan=host.inspect()
    summary=dict(old_head=host.old,source_head=host.head,historical_runs=len(r.loads(plan['receipt'])['runs']),current_epoch_runs=0,grants_implementation=False)
    if not apply:return dict(summary,status='PLAN_ONLY',changes_applied=False)
    a=host.authorize()
    require(a['historical_receipt_sha256']==r.sha(plan['receipt']) and a['historical_runs']==summary['historical_runs'],'owner authorization historical state changed')
    base=r.CONFIG.parent/'epoch-transitions';r.protected(base.parent)
    if not base.exists():base.mkdir(mode=0o700);u.sync(base.parent)
    r.protected(base,directory=True)
    lock=base/'lock'
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as stream:
        r.protected(lock);fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(encode_plan(host.inspect())==encode_plan(plan),'preflight changed')
        require(host.authorize()==a,'authorization changed')
        attempt=base/a['nonce'];attempt.mkdir(mode=0o700);u.sync(base) # O_EXCL nonce consumption, never retried
        u.write(attempt/'plan.json',r.encoded(encode_plan(plan)),0o600,0,os.getgid())
        u.write(attempt/'authorization.json',r.encoded(a),0o600,0,os.getgid())
        events=[]
        def stage(name,**detail):
            events.append(dict(stage=name,at=time.time(),**detail))
            u.replace(attempt/'journal.json',r.encoded(dict(events=events,head=host.head,old=host.old)),0o600,0,os.getgid())
        stage('BACKUP_DURABLE')
        def preserved():
            for name,key in [('discovery.json','receipt'),('timer-fires.json','fires'),('october30-failure.json','failure')]:
                r.protected(archive/name);require((archive/name).read_bytes()==plan[key],'permanent archive changed')
            r.protected(epoch,directory=True)
            require(not (epoch/'discovery.json').exists() and not (epoch/'discovery.json').is_symlink(),'new epoch must have zero runs before genuine timer')
        operation='QUIET_WINDOW'
        try:
            host.guard(plan);operation='STOP_OBSERVER';host.stop();stage('OBSERVER_STOPPED');host.guard(plan)
            operation='ARCHIVE_HISTORY'
            # Archives and epochs are created once, never rewritten or cleaned up.
            history=r.STATE/'history'
            if not history.exists():history.mkdir(mode=0o755);u.sync(r.STATE)
            r.protected(history,directory=True)
            archive=history/(host.old+'-'+r.sha(plan['receipt']));archive.mkdir(mode=0o755);u.sync(history)
            for name,key in [('discovery.json','receipt'),('timer-fires.json','fires'),('october30-failure.json','failure')]:u.write(archive/name,plan[key],0o644,0,os.getgid())
            epochs=r.STATE/'epochs'
            if not epochs.exists():epochs.mkdir(mode=0o755);u.sync(r.STATE)
            r.protected(epochs,directory=True)
            epoch=epochs/host.head;epoch.mkdir(mode=0o755);u.sync(epochs)
            stage('HISTORY_ARCHIVED');preserved();host.guard(plan);operation='INSTALL_SOURCE';host.install(plan);stage('SOURCE_COMMITTED')
            operation='VERIFY_SOURCE';host.verify(plan,True);preserved();stage('NEW_BOUNDARY_VERIFIED');operation='START_OBSERVER';host.start(plan,True);operation='VERIFY_STARTED_OBSERVER';host.verify(plan,True);preserved()
            operation='COMMIT_EPOCH'
            u.write(epoch/'transition.json',r.encoded(dict(status='COMMITTED',source_head=host.head,old_head=host.old,nonce=a['nonce'])),0o644,0,os.getgid())
            stage('COMPLETE')
            return dict(summary,status='NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS',changes_applied=True,attempt=str(attempt))
        except Exception as error:
            try:stage('FAILED_NO_RETRY',failed_operation=operation,failure_type=type(error).__name__)
            except OSError:pass
            try:
                # Stop even if initial stop verification failed: never install over
                # a possibly live observer or old/new Scout invocation.
                host.stop();host.restore(plan);host.verify(plan,False);host.start(plan,False);host.verify(plan,False);stage('ROLLED_BACK')
                return dict(summary,status='ROLLED_BACK_NOT_READY',changes_applied=False,attempt=str(attempt))
            except Exception as rollback_error:
                try:host.stop()
                except Exception:pass
                try:stage('ROLLBACK_UNVERIFIED_STOP_REQUIRED',failure_type=type(rollback_error).__name__)
                except OSError:pass
                return dict(summary,status='FAILED_CLOSED_REQUIRES_INTERVENTION',changes_applied=False,attempt=str(attempt))


def _rollback(host,nonce):
    """Explicit recovery of interrupted transaction; never roll forward/retry APPLY."""
    require(re.fullmatch('[A-Za-z0-9-]{16,128}',nonce) is not None,'fixed attempt nonce required')
    attempt=r.CONFIG.parent/'epoch-transitions'/nonce
    for name in ('plan.json','authorization.json','journal.json'):r.protected(attempt/name)
    plan=decode_plan(r.loads((attempt/'plan.json').read_bytes()));a=r.loads((attempt/'authorization.json').read_bytes())
    require(plan['old']==host.old and plan['head']==host.head and a['nonce']==nonce,'exact interrupted attempt required')
    journal=r.loads((attempt/'journal.json').read_bytes())
    require(journal['events'][-1]['stage'] not in {'COMPLETE','ROLLED_BACK'},'completed attempt cannot be replayed')
    host.recovery_guard(plan)
    try:
        host.stop();host.restore(plan);host.verify(plan,False);host.start(plan,False);host.verify(plan,False)
    except Exception:
        try:host.stop()
        except Exception:pass
        raise
    journal['events'].append(dict(stage='ROLLED_BACK',at=time.time()));u.replace(attempt/'journal.json',r.encoded(journal),0o600,0,os.getgid())
    return dict(status='ROLLED_BACK_NOT_READY',grants_implementation=False)


def rollback(host,nonce):
    lock=r.CONFIG.parent/'epoch-transitions'/'lock';r.protected(lock)
    fd=os.open(lock,os.O_RDWR|os.O_NOFOLLOW)
    with os.fdopen(fd,'r') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _rollback(host,nonce)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--head',required=True);parser.add_argument('--apply',action='store_true');parser.add_argument('--rollback')
    args=parser.parse_args();require(not (args.apply and args.rollback),'choose one transition mode')
    host=Host(args.head)
    result=rollback(host,args.rollback) if args.rollback else transaction(host,apply=args.apply)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['status'] in {'PLAN_ONLY','NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'} else 1)
