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
import uuid
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from ops.discovery import pin_refresh as r,upgrade as u,observer as o
from ops.discovery.influence import audit,isolated,git_boundary,git as reviewed_git

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


def system_prestate(invoke,name):
    """Require absent inactive units; service process fields do not apply to timers."""
    code={
        'development-scout.service':'SYSTEM_SCOUT_SERVICE_PRESTATE_INVALID',
        'development-scout.timer':'SYSTEM_SCOUT_TIMER_PRESTATE_INVALID',
        CERT_UNIT:'CERTIFICATION_SERVICE_PRESTATE_INVALID',
    }[name]
    p=preflight(code,lambda:properties(invoke,name))
    source_require(p.get('LoadState')=='not-found' and p.get('DropInPaths')=='' and p.get('ActiveState')=='inactive',code)
    if name.endswith('.service'):
        source_require(p.get('MainPID')=='0' and p.get('ControlPID')=='0',code)
    return p


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
    """Authorize only today's pre-15:50 Eastern window; never roll to tomorrow."""
    now=time.time() if now is None else now
    local=datetime.fromtimestamp(now,ZoneInfo('America/New_York'))
    slot=local.replace(hour=16,minute=0,second=0,microsecond=0).timestamp()
    if now>=slot-600:raise ValueError('first system timer activation requires today before 15:50 Eastern')
    return slot


def daily_only(raw):
    lines=raw.decode().splitlines()
    if [s for s in lines if s.startswith('OnCalendar=')]!=['OnCalendar=*-*-* 16:00:00 America/New_York']:raise ValueError('daily-only calendar required; elapsed recovery forbidden')
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


def stopped_observer(config,invoke):
    # A stopped boundary is verified statically; never start old code to probe it.
    for path in (r.SOURCE,r.CONFIG,r.UNIT):r.protected(path)
    if r.CONFIG.read_bytes()!=r.encoded(config) or r.sha(r.SOURCE.read_bytes())!=config['observer_digest'] or r.sha(r.UNIT.read_bytes())!=config['files'][r.IDENTITIES[1]]:raise ValueError('exact restored observer boundary required')
    runtime=r.RUNTIME.resolve(strict=True);r.protected(runtime)
    if r.RUNTIME.is_symlink() and r.RUNTIME.lstat().st_uid!=r.ROOT_UID:raise ValueError('root runtime required')
    p=r.properties(r.command(invoke,['/bin/systemctl','show',r.SERVICE,'--property=ActiveState,SubState,MainPID,FragmentPath,DropInPaths,NeedDaemonReload'],check=True).stdout)
    if p!={'ActiveState':'inactive','SubState':'dead','MainPID':'0','FragmentPath':str(r.UNIT),'DropInPaths':'','NeedDaemonReload':'no'}:raise ValueError('exact stopped observer required')
    if r.SOCKET.exists() or r.SOCKET.is_symlink():raise ValueError('no stopped observer socket permitted')
    processes=list(r.PROC.iterdir())
    if len(processes)>65536:raise ValueError('bounded process inventory required')
    for process in processes:
        if not process.name.isdecimal():continue
        try:
            with (process/'cmdline').open('rb') as stream:raw=stream.read(8193)
            if len(raw)>8192:raise ValueError('bounded observer process identity required')
            argv=raw.split(b'\0')
        except (FileNotFoundError,ProcessLookupError):continue
        if str(r.SOURCE).encode() in argv:raise ValueError('observer process remains')
    return dict(invocation=None,pid=0,socket=None,runtime_sha256=r.sha(runtime.read_bytes()))


def preflight(code,action):
    """Keep rejected invariants distinct without leaking exception text."""
    try:return action()
    except MigrationFailure:raise
    except Exception:raise MigrationFailure('PREFLIGHT_VERIFIED',code) from None


def source_require(condition,code):
    require(condition,'PREFLIGHT_VERIFIED',code)


def deployed_source(root,head,old):
    """Read exact deployed objects; owner/main/CI authority precedes migration.

    Executor.checkout deliberately detaches HEAD and fetches into FETCH_HEAD.
    Branch names and cached remote refs cannot attest deployment authority.
    No network or credential use here. User-owned release receipts cannot be
    promoted to root authority; the preceding verified deployment is mandatory.
    """
    root=Path(root)
    source_require(root==r.ROOT and not root.is_symlink() and root.resolve(strict=True)==root,'DEPLOYED_SOURCE_AUTHORITY_INVALID')
    source_require(isinstance(head,str) and re.fullmatch('[a-f0-9]{40}',head) is not None,'DEPLOYED_SOURCE_SHA_INVALID')
    source_require(not git_boundary(root),'DEPLOYED_SOURCE_AUTHORITY_INVALID')
    def exact():
        source_require(reviewed_git(root,'cat-file','-t',head).strip()==b'commit','DEPLOYED_SOURCE_SHA_INVALID')
        source_require(reviewed_git(root,'rev-parse','HEAD').decode().strip()==head,'DEPLOYED_SOURCE_SHA_INVALID')
    preflight('DEPLOYED_SOURCE_SHA_INVALID',exact)
    source_require(not reviewed_git(root,'status','--porcelain','--untracked-files=no').strip(),'DEPLOYED_SOURCE_DIRTY')
    origin=preflight('REPOSITORY_ORIGIN_INVALID',lambda:reviewed_git(root,'remote','get-url','origin').decode().strip())
    source_require(origin in {'https://github.com/labairj-ai/investment.git','git@github.com:labairj-ai/investment.git'},'REPOSITORY_ORIGIN_INVALID')
    preflight('OLD_BOUNDARY_INVALID',lambda:reviewed_git(root,'merge-base','--is-ancestor',old,head))
    manifest=preflight('DEPLOYED_SOURCE_AUTHORITY_INVALID',lambda:r.source_manifest(root,head))
    preflight('DEPLOYED_SOURCE_AUTHORITY_INVALID',lambda:r.manifest_matches(root,manifest))
    return dict(root=str(root),head=head,repository='labairj-ai/investment',manifest=manifest)


def start_boundary(config,invoke):
    p=preflight('STOPPED_OBSERVER_INVALID',lambda:r.properties(r.command(invoke,['/bin/systemctl','show',r.SERVICE,'--property=ActiveState,SubState,MainPID'],check=True).stdout))
    timer=preflight('OLD_USER_SCOUT_BOUNDARY_INVALID',lambda:properties(invoke,'development-scout.timer',True))
    if p.get('ActiveState')=='active' and timer.get('ActiveState')=='active' and timer.get('UnitFileState') in {'enabled','enabled-runtime'}:
        return 'NORMAL_ACTIVE',preflight('OLD_BOUNDARY_INVALID',lambda:r.boundary(config,invoke))
    if p=={'ActiveState':'inactive','SubState':'dead','MainPID':'0'}:
        source_require(timer.get('ActiveState')=='inactive' and timer.get('UnitFileState')=='disabled','OLD_USER_SCOUT_BOUNDARY_INVALID')
        return 'STOPPED_ROLLBACK',preflight('STOPPED_OBSERVER_INVALID',lambda:stopped_observer(config,invoke))
    raise MigrationFailure('PREFLIGHT_VERIFIED','STOPPED_OBSERVER_INVALID')


def inspect(root,head,old,invoke):
    source_require(sys.platform=='linux' and os.geteuid()==r.ROOT_UID and isolated(),'DEPLOYED_SOURCE_AUTHORITY_INVALID')
    source_require(old==OLD_HEAD,'OLD_BOUNDARY_INVALID')
    source_require(head!=old,'DEPLOYED_SOURCE_SHA_INVALID')
    try:slot=first_activation_slot()
    except Exception:raise MigrationFailure('PREFLIGHT_VERIFIED','ACTIVATION_WINDOW_EXPIRED') from None
    target=preflight('DEPLOYED_SOURCE_AUTHORITY_INVALID',lambda:deployed_source(root,head,old))
    influence=preflight('DEPLOYED_SOURCE_AUTHORITY_INVALID',lambda:audit(root,head))
    source_require(influence['untracked_source_influence']=='PASS','DEPLOYED_SOURCE_AUTHORITY_INVALID')
    before=preflight('OLD_BOUNDARY_INVALID',lambda:r.source_manifest(root,old))
    def old_boundary():
        source_require([before[k] for k in r.IDENTITIES]==[OLD_OBSERVER,OLD_UNIT,OLD_SERVICE,OLD_TIMER],'OLD_BOUNDARY_INVALID')
        source_require(target['manifest'][r.IDENTITIES[1]]==OLD_UNIT,'OLD_BOUNDARY_INVALID')
        current=r.configuration(old,before)
        for path in (r.SOURCE,r.CONFIG,r.UNIT):r.protected(path)
        source_require(r.CONFIG.read_bytes()==r.encoded(current) and r.sha(r.SOURCE.read_bytes())==current['observer_digest'] and r.sha(r.UNIT.read_bytes())==current['files'][r.IDENTITIES[1]],'OLD_BOUNDARY_INVALID')
        return current
    current=preflight('OLD_BOUNDARY_INVALID',old_boundary)
    start_mode,observed=start_boundary(current,invoke)
    evidence=preflight('ACCEPTANCE_PRECONDITION_INVALID',u.state)
    source_require('discovery.json' not in evidence,'ACCEPTANCE_PRECONDITION_INVALID')
    fingerprints=preflight('PROTECTED_STATE_CHANGED',u.protected_state)
    ledger,rows=preflight('ACCEPTANCE_PRECONDITION_INVALID',o.ledger_snapshot)
    source_require(all(v[3]=='SCHEDULER_OBSERVATION' for v in rows),'ACCEPTANCE_PRECONDITION_INVALID')
    source_require((r.CONTROL/'operational-signals.json').is_file(),'OPERATIONAL_SIGNALS_MISSING')
    oldfiles=preflight('OLD_BOUNDARY_INVALID',lambda:[source_file(r.SOURCE),source_file(r.CONFIG)])
    def old_scout():
        for name,key in [('development-scout.service',r.IDENTITIES[2]),('development-scout.timer',r.IDENTITIES[3])]:
            path=r.USER_UNITS/name;item=source_file(path);p=properties(invoke,name,True)
            source_require(r.sha(item['data'])==before[key] and p.get('FragmentPath')==str(path) and p.get('DropInPaths')=='' and p.get('NeedDaemonReload')=='no','OLD_USER_SCOUT_BOUNDARY_INVALID')
            oldfiles.append(item)
        timer_state(invoke,True,start_mode=='NORMAL_ACTIVE');quiescent(invoke,True)
        if start_mode=='NORMAL_ACTIVE':next_timer(invoke,True)
    preflight('OLD_USER_SCOUT_BOUNDARY_INVALID',old_scout)
    preflight('SYSTEM_UNIT_STATE_INVALID',lambda:r.protected(STAMP.parent,directory=True))
    if STAMP.exists() or STAMP.is_symlink():raise MigrationFailure('PREFLIGHT_VERIFIED','PERSISTENT_TIMER_STAMP_PRESENT')
    desired=r.configuration(head,target['manifest']);desired['scout_manager']='system'
    def target_files():
        return [(r.SOURCE,r.git(root,'show',head+':'+r.IDENTITIES[0]),oldfiles[0]['mode']),
                (r.CONFIG,r.encoded(desired),oldfiles[1]['mode']),
                (SYSTEM/'development-scout.service',r.git(root,'show',head+':'+r.IDENTITIES[2]),0o644),
                (SYSTEM/'development-scout.timer',r.git(root,'show',head+':'+r.IDENTITIES[3]),0o644),
                (CERT_SOURCE,r.git(root,'show',head+':'+CERT_FILES[0]),0o755),
                (SYSTEM/CERT_UNIT,r.git(root,'show',head+':'+CERT_FILES[1]),0o644)]
    targets=preflight('DEPLOYED_SOURCE_AUTHORITY_INVALID',target_files)
    preflight('SYSTEM_UNIT_STATE_INVALID',lambda:daily_only(targets[3][1]))
    source_require(preflight('ACTIVATION_WINDOW_EXPIRED',first_activation_slot)==slot,'ACTIVATION_WINDOW_EXPIRED')
    for path,_,_ in targets[2:]:
        source_require(not (path.exists() or path.is_symlink()),'SYSTEM_BOUNDARY_COLLISION')
        preflight('SYSTEM_UNIT_STATE_INVALID',lambda:r.protected(path.parent,directory=True))
    for name in ('development-scout.service','development-scout.timer',CERT_UNIT):
        system_prestate(invoke,name)
    return dict(start_mode=start_mode,slot=slot,current=current,desired=desired,observed=observed,evidence=evidence,fingerprints=fingerprints,ledger=ledger,oldfiles=oldfiles,targets=targets,influence=influence)


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


CERTIFICATION_CODES=tuple('CERTIFICATION_'+name for name in (
    'UNIT_IDENTITY_INVALID','START_FAILED','RESULT_INVALID','EXEC_STATUS_INVALID',
    'INVOCATION_INVALID','JOURNAL_QUERY_FAILED','JOURNAL_OVERSIZE','JOURNAL_DECODE_INVALID',
    'REPORT_SCHEMA_INVALID','REPORT_BOOLEAN_INVALID','REPORT_COUNT_INVALID','TRACE_PERSIST_FAILED'))


class CertificationTrace:
    """Fixed bounded decision evidence, retained independently of installed units."""
    def __init__(self,progress,start):
        self.path=progress.backup/'certification-trace.json'
        self.data=dict(schema='scout-certification-trace-1',attempt_id=progress.identity['attempt_id'],
            source_target_sha=progress.identity['source_target_sha'],certification_started_at=start,
            certification_started_at_repr=repr(start),current_step='INITIALIZED',completed_subchecks=[],
            observations={},certification_result='RUNNING',failure_code=None)
        self.persist()

    def persist(self):
        try:
            r.protected(self.path.parent,directory=True)
            if self.path.exists() or self.path.is_symlink():
                r.protected(self.path)
                if stat.S_IMODE(self.path.stat().st_mode)!=0o600:raise ValueError('trace mode')
            raw=r.encoded(self.data)
            if len(raw)>16384:raise ValueError('trace bound')
            temp=self.path.with_name('certification-trace.next')
            u.write(temp,raw,0o600,r.ROOT_UID,os.getgid())
            os.replace(temp,self.path);u.sync(self.path.parent)
        except Exception:
            raise MigrationFailure('SANDBOX_CERTIFICATION_PASSED','CERTIFICATION_TRACE_PERSIST_FAILED') from None

    def observe(self,step,**values):
        self.data['current_step']=step;self.data['observations'].update(values);self.persist()

    def decision(self,step,valid,code):
        self.data['current_step']=step
        self.data['observations'][step]='PASS' if valid else 'FAIL'
        if valid:self.data['completed_subchecks'].append(step)
        else:self.data.update(certification_result='FAIL',failure_code=code)
        self.persist()
        if not valid:raise MigrationFailure('SANDBOX_CERTIFICATION_PASSED',code)


def certify(invoke,start,progress):
    # Preserve the reviewed sequence and journal time filter. Never call Scout.
    trace=CertificationTrace(progress,start)
    try:return certify_steps(invoke,start,trace)
    except MigrationFailure:raise
    except Exception:
        trace.decision('unexpected_failure',False,'SANDBOX_CERTIFICATION_FAILED')


def certify_steps(invoke,start,trace):
    def query(step,code,action):
        trace.observe(step)
        try:return action()
        except Exception:
            trace.decision(step,False,code)
    identity=dict(FragmentPath=str(SYSTEM/CERT_UNIT),DropInPaths='',NeedDaemonReload='no',User='optiplex',Group='optiplex')
    p=query('unit_identity_query','CERTIFICATION_UNIT_IDENTITY_INVALID',lambda:properties(invoke,CERT_UNIT))
    # Invalid arbitrary property contents are classified, never copied to evidence.
    trace.observe('unit_identity',unit_identity_properties={k:(p.get(k) if p.get(k)==v else None if k not in p else '<unexpected>') for k,v in identity.items()})
    trace.decision('unit_identity',all(p.get(k)==v for k,v in identity.items()),'CERTIFICATION_UNIT_IDENTITY_INVALID')
    completed=query('start','CERTIFICATION_START_FAILED',lambda:system(invoke,'start',CERT_UNIT,check=False))
    trace.observe('start',start_returncode=completed.returncode,start_stdout_length=len(getattr(completed,'stdout','') or ''),start_stderr_length=len(getattr(completed,'stderr','') or ''))
    trace.decision('start_result',completed.returncode==0,'CERTIFICATION_START_FAILED')
    p=query('post_run_properties','CERTIFICATION_RESULT_INVALID',lambda:properties(invoke,CERT_UNIT))
    patterns=dict(ActiveState=r'[a-z-]{1,40}',SubState=r'[a-z-]{1,40}',Result=r'[a-z-]{1,40}',ExecMainStatus=r'[0-9]{1,20}',InvocationID=r'[a-f0-9]{32}',MainPID=r'[0-9]{1,20}',ControlPID=r'[0-9]{1,20}')
    trace.observe('post_run_properties',post_run_properties={k:(None if k not in p else p[k] if p[k]=='' or re.fullmatch(pattern,p[k]) else '<invalid>') for k,pattern in patterns.items()})
    trace.decision('result_property_valid',p.get('Result')=='success','CERTIFICATION_RESULT_INVALID')
    trace.decision('exec_main_status_valid',p.get('ExecMainStatus')=='0','CERTIFICATION_EXEC_STATUS_INVALID')
    inv=p.get('InvocationID','')
    trace.decision('invocation_id_valid',re.fullmatch('[a-f0-9]{32}',inv) is not None,'CERTIFICATION_INVOCATION_INVALID')
    command=['/usr/bin/journalctl','--no-pager','-o','json','_SYSTEMD_INVOCATION_ID='+inv,'--since=@'+str(start)]
    trace.observe('journal_query',journal_query=dict(invocation=inv,since_argument=command[-1],query_type='invocation-and-realtime',arguments=command))
    completed=query('journal_query','CERTIFICATION_JOURNAL_QUERY_FAILED',lambda:invoke(command,capture_output=True,text=True,check=False,timeout=30,env=r.ENV))
    raw=completed.stdout
    trace.observe('journal_query',journal_returncode=completed.returncode,stdout_length=len(raw),stderr_length=len(getattr(completed,'stderr','') or ''),journal_line_count=raw.count('\n')+int(bool(raw) and not raw.endswith('\n')))
    trace.decision('journal_query_result',completed.returncode==0,'CERTIFICATION_JOURNAL_QUERY_FAILED')
    trace.decision('journal_output_bounded',len(raw)<=65536,'CERTIFICATION_JOURNAL_OVERSIZE')
    expected={'network_namespace_isolated','repository_read_only','protected_state_inaccessible','credentials_inaccessible','process_uid_expected','system_manager_readable','execution_record_current','test_evidence_only','accepted_scout_run'};reports=[]
    counters=dict(total_journal_json_lines=0,json_message_candidates=0,decoded_candidate_reports=0,exact_schema_reports=0,valid_boolean_reports=0,final_accepted_reports=0)
    trace.observe('journal_decode',parsing_counters=dict(counters))
    for line in raw.splitlines():
        try:
            entry=r.loads(line)
            if not isinstance(entry,dict) or not isinstance(entry.get('MESSAGE',''),str):raise ValueError('journal shape')
            message=entry.get('MESSAGE','')
        except Exception:trace.decision('journal_decode',False,'CERTIFICATION_JOURNAL_DECODE_INVALID')
        counters['total_journal_json_lines']+=1
        trace.observe('journal_decode',parsing_counters=dict(counters))
        if message.startswith('{'):
            counters['json_message_candidates']+=1
            trace.observe('report_decode',parsing_counters=dict(counters))
            try:report=r.loads(message)
            except Exception:trace.decision('report_decode',False,'CERTIFICATION_JOURNAL_DECODE_INVALID')
            counters['decoded_candidate_reports']+=1
            trace.observe('report_schema',parsing_counters=dict(counters))
            trace.decision('report_schema_'+str(len(reports)+1),isinstance(report,dict) and set(report)==expected,'CERTIFICATION_REPORT_SCHEMA_INVALID')
            counters['exact_schema_reports']+=1
            trace.observe('report_booleans',parsing_counters=dict(counters))
            trace.decision('report_booleans_'+str(len(reports)+1),all(v is True for k,v in report.items() if k!='accepted_scout_run') and report['accepted_scout_run'] is False,'CERTIFICATION_REPORT_BOOLEAN_INVALID')
            counters['valid_boolean_reports']+=1;reports.append(report)
            counters['final_accepted_reports']+=1
            trace.observe('report_parsed',parsing_counters=dict(counters))
            # Stop beyond the exact contract; never grow trace with arbitrary reports.
            if len(reports)>3:trace.decision('report_count_valid',False,'CERTIFICATION_REPORT_COUNT_INVALID')
    trace.observe('report_count',parsing_counters=dict(counters))
    trace.decision('report_count_valid',len(reports)==3,'CERTIFICATION_REPORT_COUNT_INVALID')
    trace.data['certification_result']='PASS';trace.data['current_step']='COMPLETE';trace.persist()
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


STAGES=('PREFLIGHT_VERIFIED','BACKUP_CREATED','OLD_SCOUT_QUIESCENT','OLD_USER_TIMER_DISABLED','OLD_OBSERVER_STOPPED','SYSTEM_BOUNDARY_INSTALLED','SYSTEM_DAEMON_RELOADED','SYSTEM_BOUNDARY_VERIFIED','SANDBOX_CERTIFICATION_STARTED','SANDBOX_CERTIFICATION_PASSED','POST_CERT_LEDGER_VERIFIED','POST_CERT_ACCEPTANCE_STATE_VERIFIED','POST_CERT_PROTECTED_STATE_VERIFIED','OLD_USER_TIMER_DISABLED_VERIFIED','ACTIVATION_WINDOW_VERIFIED','SYSTEM_TIMER_ENABLED','SYSTEM_TIMER_STATE_VERIFIED','NEXT_ELAPSE_VERIFIED','NEW_OBSERVER_STARTED','FINAL_BOUNDARY_VERIFIED','MIGRATION_COMPLETE','ROLLBACK_STARTED','ROLLBACK_COMPLETE')
FAILURE_CODES=frozenset(('LEDGER_CONTINUITY_CHANGED','ACCEPTANCE_STATE_CHANGED','PROTECTED_STATE_CHANGED','OLD_USER_TIMER_STATE_INVALID','ACTIVATION_WINDOW_EXPIRED','PERSISTENT_TIMER_STAMP_PRESENT','SYSTEM_TIMER_ENABLE_FAILED','SYSTEM_TIMER_STATE_INVALID','NEXT_ELAPSE_INVALID','OBSERVER_START_FAILED','OBSERVER_BOUNDARY_INVALID','SYSTEM_BOUNDARY_CHANGED','SANDBOX_CERTIFICATION_FAILED','ROLLBACK_FAILED','UNCLASSIFIED_MIGRATION_FAILURE','DEPLOYED_SOURCE_SHA_INVALID','DEPLOYED_SOURCE_DIRTY','DEPLOYED_SOURCE_AUTHORITY_INVALID','REPOSITORY_ORIGIN_INVALID','OLD_BOUNDARY_INVALID','STOPPED_OBSERVER_INVALID','OLD_USER_SCOUT_BOUNDARY_INVALID','ACCEPTANCE_PRECONDITION_INVALID','OPERATIONAL_SIGNALS_MISSING','SYSTEM_BOUNDARY_COLLISION','SYSTEM_UNIT_STATE_INVALID','SYSTEM_SCOUT_SERVICE_PRESTATE_INVALID','SYSTEM_SCOUT_TIMER_PRESTATE_INVALID','CERTIFICATION_SERVICE_PRESTATE_INVALID')) | frozenset(CERTIFICATION_CODES)


class MigrationFailure(ValueError):
    def __init__(self,stage,code):
        if stage not in STAGES or code not in FAILURE_CODES:raise ValueError('allowlisted migration failure required')
        self.stage=stage;self.code=code
        super().__init__(code)


class Progress:
    def __init__(self,backup,head,old,mode):
        self.backup=backup;self.events=[];self.stage='PREFLIGHT_VERIFIED'
        self.identity=dict(schema='scout-system-migration-progress-1',attempt_id=uuid.uuid4().hex,source_target_sha=head,old_boundary_sha=old,start_mode=mode)

    def record(self,stage,result,started,code=None):
        if stage not in STAGES or result not in {'STARTED','PASS','FAIL'} or code is not None and code not in FAILURE_CODES:raise ValueError('allowlisted progress required')
        self.stage=stage
        row=dict(stage=stage,stage_started_at=started,stage_completed_at=None if result=='STARTED' else time.time(),result=result,sanitized_failure_code=code)
        self.events.append(row)
        if len(self.events)>128:raise ValueError('bounded progress required')
        temp=self.backup/'progress.next';target=self.backup/'progress.json'
        if temp.exists() or temp.is_symlink() or target.is_symlink():raise ValueError('progress path collision')
        u.write(temp,r.encoded(dict(self.identity,stages=self.events)),0o600,r.ROOT_UID,os.getgid())
        os.replace(temp,target);u.sync(self.backup)

    def run(self,stage,code,action):
        started=time.time();self.record(stage,'STARTED',started)
        try:value=action()
        except Exception as error:
            failure=error if isinstance(error,MigrationFailure) else MigrationFailure(stage,code)
            self.record(stage,'FAIL',started,failure.code)
            raise failure from None
        self.record(stage,'PASS',started)
        return value


def require(condition,stage,code):
    if not condition:raise MigrationFailure(stage,code)


def activation_window(plan):
    stage='ACTIVATION_WINDOW_VERIFIED'
    try:slot=first_activation_slot()
    except Exception:raise MigrationFailure(stage,'ACTIVATION_WINDOW_EXPIRED') from None
    require(slot==plan['slot'],stage,'ACTIVATION_WINDOW_EXPIRED')
    require(not (STAMP.exists() or STAMP.is_symlink()),stage,'PERSISTENT_TIMER_STAMP_PRESENT')


def _migrate(root,head,old,*,apply=False,invoke=subprocess.run):
    preflight_started=time.time()
    base=dict(status='PREFLIGHT_FAILED_NOT_READY',changes_applied=False,accepted_runs=0,grants_implementation=False)
    try:
        # Do not echo invalid caller arguments into failure evidence.
        source_require(isinstance(head,str) and re.fullmatch('[a-f0-9]{40}',head) is not None,'DEPLOYED_SOURCE_SHA_INVALID')
        source_require(isinstance(old,str) and re.fullmatch('[a-f0-9]{40}',old) is not None,'OLD_BOUNDARY_INVALID')
        base.update(source_head=head,expected_old_head=old)
        plan=inspect(root,head,old,invoke)
    except Exception as error:
        code=error.code if isinstance(error,MigrationFailure) else 'UNCLASSIFIED_MIGRATION_FAILURE'
        return dict(base,failure_stage='PREFLIGHT_VERIFIED',failure_code=code)
    summary=dict(base,status='PLAN_ONLY',start_mode=plan['start_mode'],scout_manager='system',untracked_source_influence=plan['influence'],old_boundary={k:plan['current'][k] for k in ('observer_digest','unit_digest','timer_digest')},new_boundary={k:plan['desired'][k] for k in ('observer_digest','unit_digest','timer_digest')},changed_files=[str(p) for p,_,_ in plan['targets']])
    if not apply:return summary
    backup=None;progress=None;installed=[];units_changed=False;backup_complete=False
    lock=r.CONFIG.parent/'scout-system-migration.lock'
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as handle:
        r.protected(lock);fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            require(inspect(root,head,old,invoke)==plan,'PREFLIGHT_VERIFIED','OBSERVER_BOUNDARY_INVALID')
            activation_window(plan)
            candidate=r.CONFIG.parent/('scout-system-migration-backup-'+head)
            if candidate.exists() or candidate.is_symlink():raise MigrationFailure('PREFLIGHT_VERIFIED','UNCLASSIFIED_MIGRATION_FAILURE')
            candidate.mkdir(mode=0o700);backup=candidate;u.sync(backup.parent)
            progress=Progress(backup,head,old,plan['start_mode'])
            progress.record('PREFLIGHT_VERIFIED','PASS',preflight_started)
            def backups():
                for i,item in enumerate(plan['oldfiles']):u.write(backup/str(i),item['data'],item['mode'],item['uid'],item['gid'])
                u.write(backup/'manifest.json',r.encoded(dict(old=old,head=head,start_mode=plan['start_mode'],attempt_id=progress.identity['attempt_id'],old_files=[{k:str(v) if k=='path' else v for k,v in f.items() if k!='data'}|{'sha256':r.sha(f['data'])} for f in plan['oldfiles']],new_paths=[str(p) for p,_,_ in plan['targets'][2:]],evidence={name:r.sha(data) for name,data in plan['evidence'].items()},old_user_timer_enabled=plan['start_mode']=='NORMAL_ACTIVE')),0o600,r.ROOT_UID,os.getgid())
                for name,data in plan['evidence'].items():u.write(backup/('evidence-'+name),data,0o600,r.ROOT_UID,os.getgid())
            progress.run('BACKUP_CREATED','UNCLASSIFIED_MIGRATION_FAILURE',backups)
            backup_complete=True
            progress.run('OLD_SCOUT_QUIESCENT','OBSERVER_BOUNDARY_INVALID',lambda:quiescent(invoke,True))
            # Reauthorize immediately before any old-boundary transition.
            activation_window(plan)
            def disable_old():
                if plan['start_mode']=='NORMAL_ACTIVE':u.user(invoke,['disable','--now','development-scout.timer'])
                timer_state(invoke,True,False);quiescent(invoke,True)
            progress.run('OLD_USER_TIMER_DISABLED','OLD_USER_TIMER_STATE_INVALID',disable_old)
            progress.run('OLD_OBSERVER_STOPPED','OBSERVER_BOUNDARY_INVALID',lambda:r.stop_verified(invoke) if plan['start_mode']=='NORMAL_ACTIVE' else stopped_observer(plan['current'],invoke))
            def install():
                nonlocal units_changed
                for path,data,mode in plan['targets']:
                    if path in {r.SOURCE,r.CONFIG}:
                        original=next(f for f in plan['oldfiles'] if f['path']==path);u.replace(path,data,mode,original['uid'],original['gid'])
                    else:
                        install_new(path,data,mode,installed)
                        if path.parent==SYSTEM:units_changed=True
            progress.run('SYSTEM_BOUNDARY_INSTALLED','SYSTEM_BOUNDARY_CHANGED',install)
            progress.run('SYSTEM_DAEMON_RELOADED','SYSTEM_BOUNDARY_CHANGED',lambda:system(invoke,'daemon-reload'))
            def boundary():timer_state(invoke,False,False);system_boundary(invoke,plan['desired'])
            progress.run('SYSTEM_BOUNDARY_VERIFIED','SYSTEM_BOUNDARY_CHANGED',boundary)
            cert_started=time.time()
            progress.run('SANDBOX_CERTIFICATION_STARTED','SANDBOX_CERTIFICATION_FAILED',lambda:None)
            cert=progress.run('SANDBOX_CERTIFICATION_PASSED','SANDBOX_CERTIFICATION_FAILED',lambda:certify(invoke,cert_started,progress))
            progress.run('POST_CERT_LEDGER_VERIFIED','LEDGER_CONTINUITY_CHANGED',lambda:ledger_unchanged(plan['ledger']))
            progress.run('POST_CERT_ACCEPTANCE_STATE_VERIFIED','ACCEPTANCE_STATE_CHANGED',lambda:require(u.state()==plan['evidence'],'POST_CERT_ACCEPTANCE_STATE_VERIFIED','ACCEPTANCE_STATE_CHANGED'))
            progress.run('POST_CERT_PROTECTED_STATE_VERIFIED','PROTECTED_STATE_CHANGED',lambda:require(u.protected_state()==plan['fingerprints'],'POST_CERT_PROTECTED_STATE_VERIFIED','PROTECTED_STATE_CHANGED'))
            progress.run('OLD_USER_TIMER_DISABLED_VERIFIED','OLD_USER_TIMER_STATE_INVALID',lambda:timer_state(invoke,True,False))
            progress.run('ACTIVATION_WINDOW_VERIFIED','ACTIVATION_WINDOW_EXPIRED',lambda:activation_window(plan))
            progress.run('SYSTEM_TIMER_ENABLED','SYSTEM_TIMER_ENABLE_FAILED',lambda:system(invoke,'enable','--now','development-scout.timer'))
            def timer_states():
                timer_state(invoke,False,True)
                try:timer_state(invoke,True,False)
                except Exception:raise MigrationFailure('SYSTEM_TIMER_STATE_VERIFIED','OLD_USER_TIMER_STATE_INVALID') from None
            progress.run('SYSTEM_TIMER_STATE_VERIFIED','SYSTEM_TIMER_STATE_INVALID',timer_states)
            def elapse():
                nxt=next_timer(invoke,False)
                require(plan['slot']<=nxt<=plan['slot']+120,'NEXT_ELAPSE_VERIFIED','NEXT_ELAPSE_INVALID');quiescent(invoke,False)
                return nxt
            nxt=progress.run('NEXT_ELAPSE_VERIFIED','NEXT_ELAPSE_INVALID',elapse)
            def start_observer():r.service(invoke,'start');r.wait_socket(plan['observed']['socket'])
            progress.run('NEW_OBSERVER_STARTED','OBSERVER_START_FAILED',start_observer)
            def final():
                seen=r.boundary(plan['desired'],invoke)
                require(seen['invocation']!=plan['observed']['invocation'] and seen['socket']!=plan['observed']['socket'] and seen['runtime_sha256']==plan['observed']['runtime_sha256'],'FINAL_BOUNDARY_VERIFIED','OBSERVER_BOUNDARY_INVALID')
                try:ledger_unchanged(plan['ledger'])
                except Exception:raise MigrationFailure('FINAL_BOUNDARY_VERIFIED','LEDGER_CONTINUITY_CHANGED') from None
                r.manifest_matches(root,plan['desired']['files'])
                require(u.state()==plan['evidence'],'FINAL_BOUNDARY_VERIFIED','ACCEPTANCE_STATE_CHANGED')
                require(u.protected_state()==plan['fingerprints'],'FINAL_BOUNDARY_VERIFIED','PROTECTED_STATE_CHANGED')
                require(audit(root,head)['untracked_source_influence']=='PASS','FINAL_BOUNDARY_VERIFIED','SYSTEM_BOUNDARY_CHANGED')
                for path,data,_ in plan['targets']:require(path.read_bytes()==data,'FINAL_BOUNDARY_VERIFIED','SYSTEM_BOUNDARY_CHANGED')
                timer_states();system_boundary(invoke,plan['desired'])
                return seen
            seen=progress.run('FINAL_BOUNDARY_VERIFIED','OBSERVER_BOUNDARY_INVALID',final)
            result=dict(summary,status='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS',changes_applied=True,backup=str(backup),progress=str(backup/'progress.json'),certification=cert,observer=seen,next_elapse=nxt)
            progress.run('MIGRATION_COMPLETE','UNCLASSIFIED_MIGRATION_FAILURE',lambda:u.write(backup/'result.json',r.encoded(result),0o600,r.ROOT_UID,os.getgid()))
            return result
        except Exception as error:
            failure=error if isinstance(error,MigrationFailure) else MigrationFailure(progress.stage if progress else 'PREFLIGHT_VERIFIED','UNCLASSIFIED_MIGRATION_FAILURE')
            if backup is None:
                return dict(summary,status='PREFLIGHT_FAILED_NOT_READY',failure_stage=failure.stage,failure_code=failure.code)
            restored=False;stopped=False
            try:
                if progress:progress.run('ROLLBACK_STARTED','ROLLBACK_FAILED',lambda:None)
                def rollback():
                    nonlocal stopped,restored
                    system(invoke,'disable','--now','development-scout.timer',check=False);u.user(invoke,['disable','--now','development-scout.timer'])
                    r.stop_verified(invoke);stopped=True
                    if backup_complete:
                        for i,item in enumerate(plan['oldfiles']):
                            if (backup/str(i)).read_bytes()!=item['data']:raise ValueError('backup integrity invalid')
                            u.replace(item['path'],item['data'],item['mode'],item['uid'],item['gid'])
                    else:
                        # No boundary transition is allowed before backup PASS.
                        require(not installed and all(f['path'].read_bytes()==f['data'] for f in plan['oldfiles']),'ROLLBACK_COMPLETE','ROLLBACK_FAILED')
                    for path in reversed(installed):path.unlink();u.sync(path.parent)
                    if units_changed:system(invoke,'daemon-reload')
                    timer_state(invoke,True,False);quiescent(invoke,True)
                    require(not any(path.exists() or path.is_symlink() for path,_,_ in plan['targets'][2:]),'ROLLBACK_COMPLETE','ROLLBACK_FAILED')
                    require(all(f['path'].read_bytes()==f['data'] and stat.S_IMODE(f['path'].stat().st_mode)==f['mode'] and f['path'].stat().st_uid==f['uid'] and f['path'].stat().st_gid==f['gid'] for f in plan['oldfiles']),'ROLLBACK_COMPLETE','ROLLBACK_FAILED')
                    stopped_observer(plan['current'],invoke);restored=True
                progress.run('ROLLBACK_COMPLETE','ROLLBACK_FAILED',rollback)
            except Exception:
                for stop in (lambda:system(invoke,'disable','--now','development-scout.timer',check=False),lambda:u.user(invoke,['disable','--now','development-scout.timer'])):
                    try:stop()
                    except Exception:pass
                try:r.stop_verified(invoke);stopped=True
                except Exception:pass
            result=dict(summary,status='ROLLED_BACK_STOPPED_NOT_READY' if restored else 'FAILED_STOPPED_NOT_READY' if stopped else 'FAILED_STOP_UNCONFIRMED_NOT_READY',changes_applied=False,backup=str(backup),progress=str(backup/'progress.json'),old_files_restored=restored,observer_stopped=stopped,failure_stage=failure.stage if restored else 'ROLLBACK_COMPLETE',failure_code=failure.code if restored else 'ROLLBACK_FAILED')
            if not restored:result.update(initial_failure_stage=failure.stage,initial_failure_code=failure.code)
        try:
            if (backup/'result.json').exists():u.replace(backup/'result.json',r.encoded(result),0o600,r.ROOT_UID,os.getgid())
            else:u.write(backup/'result.json',r.encoded(result),0o600,r.ROOT_UID,os.getgid())
        except Exception:
            result.update(result_receipt_persisted=False)
        return result


def migrate(root,head,old,*,apply=False,invoke=subprocess.run):
    try:return _migrate(root,head,old,apply=apply,invoke=invoke)
    except Exception:
        # Includes malformed locks/arguments before an inspectable transaction.
        # Never return arbitrary exception text or unsafe caller strings.
        return dict(status='PREFLIGHT_FAILED_NOT_READY',changes_applied=False,accepted_runs=0,grants_implementation=False,failure_stage='PREFLIGHT_VERIFIED',failure_code='UNCLASSIFIED_MIGRATION_FAILURE')
