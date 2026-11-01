"""One separately authorized source/observer transaction; never controls Scout/timer.

Default PLAN_ONLY. Root release-controller authorization is a verified solo-owner
receipt, not a caller bool or a model claim. Existing zero-history tools stay shut.
An incomplete transition cannot authorize Scout; rollback uses the durable journal.
"""
import argparse
import sqlite3
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit, parse_qsl
from dev_agent.github import GitHub
from ops.discovery import observer as o, pin_refresh as r, upgrade as u, migrate as m
from ops.discovery.influence import audit, git_boundary, git as reviewed_git, isolated

OLD='a27bed1ebd3a69df5723212784842df456e153b3'
REPAIRED='47e9236d605a6153bbc538b8dd5ceabd4c3b81ac'
AUTH=r.CONFIG.parent/'scout-epoch-authorization.json'
STAMP=Path('/var/lib/systemd/timers/stamp-development-scout.timer')
ALLOWED={'.github/workflows/test.yml','ops/discovery/observer.py','ops/discovery/epoch_upgrade.py','ops/discovery/influence.py','ops/discovery/pin_refresh.py','.todos/0852-enable-read-only-discovery-and-prove-three-runs.md','dev_agent/scheduler.py','dev_agent/scheduler_health.py'}
SCOPE='scout-source-epoch-transition-once'
AUTH_FIELDS={'version','repository','scope','old_head','target_head','reviewed_head','merge_sha','risk','decision','nonce','created','financial_ack','execution_ack','authentication_source','owner_object','owner_verified','ci_head','ci_status','historical_receipt_sha256','historical_runs'}


def authorization_path(host):
    # Keep the consumed bootstrap authorization intact. A later exact-source
    # correction receives its own exclusive capability under the same policy.
    return AUTH if host.old==OLD else AUTH.with_name('scout-epoch-authorization-'+host.head+'.json')


def require(ok,message):
    if not ok:raise ValueError(message)


def authorization(path,old,head):
    r.protected(path)
    require(path.stat().st_size<=16000,'bounded authorization required')
    raw=path.read_bytes();a=r.loads(raw)
    require(set(a)==AUTH_FIELDS,'exact release authorization schema required')
    require(a['version']=='scout-epoch-authorization-1' and a['repository']=='labairj-ai/investment' and a['scope']==SCOPE,'fixed authorization scope required')
    require(a['old_head']==old and a['target_head']==a['merge_sha']==a['ci_head']==head and a['ci_status']=='PASS','exact merged target and CI required')
    require(re.fullmatch('[a-f0-9]{40}',str(a['reviewed_head'])) is not None,'reviewed PR head required')
    require(a['risk']=='L5' and a['decision']=='APPROVE' and a['financial_ack'] is True and a['execution_ack'] is True,'explicit L5 domain acknowledgments required')
    require(a['authentication_source']=='solo-owner-1' and a['owner_verified'] is True and re.fullmatch(r'https://github.com/labairj-ai/investment/pull/[1-9][0-9]*#issuecomment-[1-9][0-9]*',str(a['owner_object'])) is not None,'verified authenticated owner object required')
    require(type(a['created']) in (int,float) and 0<=time.time()-a['created']<=3600 and re.fullmatch('[A-Za-z0-9-]{16,128}',str(a['nonce'])) is not None,'fresh single-use authorization required')
    require(re.fullmatch('[a-f0-9]{64}',str(a['historical_receipt_sha256'])) is not None and type(a['historical_runs']) is int and 1<=a['historical_runs']<=30,'exact historical acceptance binding required')
    require(path.read_bytes()==raw,'authorization changed')
    return a


class PublicGitHub(GitHub):
    """Fixed public GET transport; never consults CLI login, tokens or proxies.

    GitHub's HTTPS response authenticates public evidence. Owner/app policy and
    all object/source/CI checks remain in the existing verifier above this layer.
    """
    def __init__(self,repository):
        require(repository=='labairj-ai/investment','fixed public repository required')
        super().__init__(repository)

    def read(self,endpoint,**kwargs):
        require(isinstance(endpoint,str) and len(endpoint)<=2048,'bounded public endpoint required')
        parts=urlsplit(endpoint)
        prefix='repos/'+self.repository
        require(not parts.scheme and not parts.netloc and not parts.fragment and not parts.path.startswith('/'),'relative public endpoint required')
        pairs=parse_qsl(parts.query,keep_blank_values=True,strict_parsing=True)
        query=dict(pairs)
        require(len(query)==len(pairs),'duplicate public query field')
        path=parts.path
        if path==prefix:
            require(not query,'repository query denied')
        elif re.fullmatch(re.escape(prefix)+r'/pulls/[1-9][0-9]*',path) or re.fullmatch(re.escape(prefix)+r'/issues/comments/[1-9][0-9]*',path):
            require(not query,'identity query denied')
        elif re.fullmatch(re.escape(prefix)+r'/pulls/[1-9][0-9]*/files',path):
            require(set(query)=={'per_page','page'} and query['per_page']=='100' and re.fullmatch(r'[1-9][0-9]{0,2}',query['page']) is not None,'bounded files inventory required')
        elif re.fullmatch(re.escape(prefix)+r'/issues/[1-9][0-9]*/comments',path):
            require(set(query)=={'since','per_page','page'} and query['per_page']=='30' and query['page'] in {'1','2','3','4'} and len(query['since'])<=64,'bounded decision inventory required')
        elif path==prefix+'/actions/runs':
            require(set(query)=={'head_sha','event','per_page'} and re.fullmatch('[a-f0-9]{40}',query['head_sha']) is not None and query['event']=='push' and query['per_page']=='10','exact merged CI query required')
        elif re.fullmatch(re.escape(prefix)+r'/actions/runs/[1-9][0-9]*/jobs',path):
            require(query=={'per_page':'100'},'bounded job inventory required')
        else:
            raise ValueError('public epoch endpoint denied')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                raise ValueError('public evidence redirect denied')
        request=urllib.request.Request('https://api.github.com/'+endpoint,method='GET',headers={
            'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',
            'User-Agent':'investment-scout-epoch-verifier'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(request,timeout=30) as response:
            require(response.status==200 and response.geturl()==request.full_url,'canonical successful public response required')
            require(response.headers.get_content_type()=='application/json','public JSON response required')
            raw=response.read(20_000_001)
        require(len(raw)<=20_000_000,'bounded public evidence required')
        value=r.loads(raw)
        require(type(value) in (dict,list),'public object or inventory required')
        return value


def live_authorization(a,client=None):
    # Fresh read-only GitHub verification; a root JSON boolean is insufficient.
    from dev_agent.github_owner import verified_object,latest_object
    if client is None:
        client=PublicGitHub(a['repository'])
    object_id=int(a['owner_object'].rsplit('-',1)[1])
    data,current,origin=verified_object(client,object_id)
    require(origin['url']==a['owner_object'] and current['head']==a['reviewed_head'],'owner source binding changed')
    require(data['decision']=='APPROVE' and data['risk']=='L5' and data['financial_ack'] is True and data['execution_ack'] is True and data['nonce']==a['nonce'],'fresh L5 owner decision required')
    require(data['rationale']==SCOPE+':'+a['old_head']+':'+a['target_head'],'explicit exact upgrade scope required')
    require(latest_object(client,data['pr'],current['head'],origin['created_at'])==object_id,'owner decision superseded')
    identity=client.pr_identity(data['pr'])
    require(identity['state']=='MERGED' and identity['mergeCommit']['oid']==a['target_head'],'exact approved merged source required')
    endpoint='repos/'+a['repository']+'/actions/runs?head_sha='+a['target_head']+'&event=push&per_page=10'
    runs=client.read(endpoint)
    require(type(runs.get('total_count')) is int and 0<runs['total_count']<=10,'bounded merged-main CI inventory required')
    matches=[x for x in runs.get('workflow_runs',[]) if x.get('path')=='.github/workflows/test.yml' and x.get('head_branch')=='main' and x.get('head_sha')==a['target_head'] and x.get('event')=='push']
    require(matches,'merged-main release CI required')
    run=max(matches,key=lambda x:x['id'])
    require(run.get('status')=='completed' and run.get('conclusion')=='success','latest merged-main CI must pass')
    jobs=client.read('repos/'+a['repository']+'/actions/runs/'+str(run['id'])+'/jobs?per_page=100')
    require(type(jobs.get('total_count')) is int and jobs['total_count']==len(jobs.get('jobs',[])) and 0<jobs['total_count']<=100,'complete release jobs required')
    for name in ('native-systemd255','test'):
        matching=[j for j in jobs['jobs'] if j.get('name')==name]
        require(len(matching)==1 and matching[0].get('conclusion')=='success','native proof and all eight release gates required')
    # No token, comment body or financial content is persisted by this verifier.
    return dict(owner_object_id=object_id,ci_run_id=run['id'],head=a['target_head'])

def issue_authorization(host,object_id,client=None):
    """Future root operator entrypoint; only an actual scoped owner object can mint."""
    plan=host.inspect() # All fixed root/staging/production protections still apply.
    from dev_agent.github_owner import verified_object
    if client is None:
        client=PublicGitHub('labairj-ai/investment')
    data,current,origin=verified_object(client,object_id)
    a=dict(version='scout-epoch-authorization-1',repository='labairj-ai/investment',scope=SCOPE,
        old_head=host.old,target_head=host.head,reviewed_head=current['head'],merge_sha=host.head,
        risk=data['risk'],decision=data['decision'],nonce=data['nonce'],created=time.time(),
        financial_ack=data['financial_ack'],execution_ack=data['execution_ack'],
        authentication_source='solo-owner-1',owner_object=origin['url'],owner_verified=True,
        ci_head=host.head,ci_status='PASS',historical_receipt_sha256=r.sha(plan['receipt']),
        historical_runs=len(r.loads(plan['receipt'])['runs']))
    live_authorization(a,client)
    require(encode_plan(host.inspect())==encode_plan(plan),'preflight changed during authentication')
    r.protected(AUTH.parent,directory=True)
    path=authorization_path(host)
    u.write(path,r.encoded(a),0o600,0,os.getgid()) # Exclusive, never replace old approval.
    authorization(path,host.old,host.head)
    return dict(status='AUTHORIZATION_RECORDED',changes_applied=False,nonce=a['nonce'],owner_object=a['owner_object'],target_head=host.head,risk='L5')



def retire_unused_authorization(host,expected_sha256):
    """Preserve one exact unused receipt, including expired receipts, as evidence.

    This reduces authority; it never approves a replacement or changes source.
    The root caller supplies the reviewed old receipt hash. The existing APPLY
    lock prevents a concurrent transaction from consuming the retiring nonce.
    """
    require(re.fullmatch('[a-f0-9]{64}',str(expected_sha256)) is not None,'exact old receipt hash required')
    plan=host.inspect()
    require(r.protected(AUTH).st_size<=16000,'bounded old receipt required')
    raw=AUTH.read_bytes()
    require(len(raw)<=16000 and r.sha(raw)==expected_sha256 and AUTH.read_bytes()==raw,'exact unchanged old receipt required')
    a=r.loads(raw)
    require(set(a)==AUTH_FIELDS and a['version']=='scout-epoch-authorization-1' and a['repository']=='labairj-ai/investment' and a['scope']==SCOPE,'reviewed epoch receipt required')
    require(a['old_head']==host.old==OLD and re.fullmatch('[a-f0-9]{40}',str(a['target_head'])) is not None and a['target_head']==a['merge_sha']==a['ci_head'] and a['target_head']!=host.head,'different exact previous target required')
    require(a['decision']=='APPROVE' and a['risk']=='L5' and a['financial_ack'] is True and a['execution_ack'] is True and a['owner_verified'] is True and a['authentication_source']=='solo-owner-1','previous authenticated L5 receipt required')
    require(re.fullmatch('[A-Za-z0-9-]{16,128}',str(a['nonce'])) is not None,'bounded previous nonce required')
    require(a['historical_receipt_sha256']==r.sha(plan['receipt']) and a['historical_runs']==len(r.loads(plan['receipt'])['runs']),'historical acceptance binding required')
    base=r.CONFIG.parent/'epoch-transitions';r.protected(base.parent,directory=True)
    if not base.exists():base.mkdir(mode=0o700);u.sync(base.parent)
    r.protected(base,directory=True)
    fd=os.open(base/'lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as stream:
        r.protected(base/'lock');fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(set(p.name for p in base.iterdir())=={'lock'},'no consumed nonce or previous transition attempt permitted')
        epoch=r.STATE/'epochs'/a['target_head']
        require(not epoch.exists() and not epoch.is_symlink(),'previous epoch must not exist')
        require(encode_plan(host.inspect())==encode_plan(plan),'preflight changed before retirement')
        r.protected(AUTH);require(AUTH.read_bytes()==raw,'receipt changed before retirement')
        # Reserve the retired nonce in the existing exclusive attempt namespace.
        # This is a retirement record, not an APPLY journal or acceptance credit.
        entry=base/a['nonce']
        entry.mkdir(mode=0o700);u.sync(base)
        destination=entry/'retired-authorization.json'
        # Same filesystem, locked root-only private destination. Rename preserves
        # the original inode/bytes; no receipt is overwritten or discarded.
        os.rename(AUTH,destination);u.sync(entry);u.sync(AUTH.parent)
        r.protected(destination);require(destination.read_bytes()==raw,'archived receipt hash mismatch')
        destination.chmod(0o400)
        with destination.open('rb') as receipt_stream:os.fsync(receipt_stream.fileno())
        require(encode_plan(host.inspect())==encode_plan(plan),'protected state changed during retirement')
        record=dict(version='scout-unused-receipt-retirement-1',status='RETIRED_UNUSED',receipt_sha256=expected_sha256,nonce=a['nonce'],old_target=a['target_head'],proposed_target=host.head,owner_object=a['owner_object'],retired_at=time.time(),grants_implementation=False)
        u.write(entry/'retirement.json',r.encoded(record),0o400,0,os.getgid())
        entry.chmod(0o500);u.sync(entry);u.sync(base)
        require(not AUTH.exists() and not AUTH.is_symlink() and r.sha(destination.read_bytes())==expected_sha256,'retirement verification failed')
        return dict(status='UNUSED_AUTHORIZATION_RETIRED',changes_applied=False,receipt_sha256=expected_sha256,archive=str(entry),nonce=a['nonce'],previous_target=a['target_head'],proposed_target=host.head,grants_implementation=False)


def candidate_snapshot():
    path=o.LEDGER
    for suffix in ('-wal','-journal'):
        require(not path.with_name(path.name+suffix).exists(),'stable candidate snapshot required')
    raw=path.read_bytes();require(len(raw)<=32_000_000 and raw==path.read_bytes(),'stable bounded candidates required')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(raw);db.execute('PRAGMA query_only=ON')
        rows=db.execute('SELECT * FROM dev_candidates ORDER BY id').fetchall()
    require(raw==path.read_bytes() and not any(path.with_name(path.name+suffix).exists() for suffix in ('-wal','-journal')),'candidate snapshot raced')
    require(len(rows)<=100000,'bounded candidates required')
    return rows


def archive_history(plan,nonce):
    # Exclusive publication, content address and read-only sealing. No archive
    # writer ever replaces/deletes an existing history member or directory.
    if 'previous_epoch' in plan:
        history=r.loads(plan['previous_epoch'])['history'];o.verify_history(history)
        return history
    receipt=r.loads(plan['receipt']);slots=sorted(x['slot'] for x in receipt['runs'])
    files={'discovery.json':plan['receipt'],'timer-fires.json':plan['fires'],'october30-failure.json':plan['failure'],'ledger-history.json':plan['ledger_history'],'candidates.json':plan['candidates']}
    manifest=dict(schema='scout-history-archive-1',source_head=plan['old'],accepted_slots=slots,accepted_count=len(slots),files={name:dict(sha256=r.sha(raw),size=len(raw)) for name,raw in files.items()})
    encoded=r.encoded(manifest);identity=r.sha(encoded)
    meta=dict(source_head=plan['old'],accepted_slots=slots,accepted_count=len(slots),manifest_sha256=identity)
    base=r.STATE/'history'
    if not base.exists():base.mkdir(mode=0o700);u.sync(r.STATE)
    r.protected(base,directory=True)
    stage=base/('.staging-'+nonce);stage.mkdir(mode=0o700);u.sync(base)
    for name,raw in files.items():u.write(stage/name,raw,0o400,0,os.getgid())
    u.write(stage/'manifest.json',encoded,0o400,0,os.getgid());stage.chmod(0o500);u.sync(stage)
    dest=base/(plan['old']+'-'+identity)
    require(not dest.exists() and not dest.is_symlink(),'historical archive already exists; no overwrite permitted')
    os.rename(stage,dest);u.sync(base)
    o.verify_history(meta)
    return meta


def legacy_configuration(current,manifest):
    expected=r.configuration(OLD,manifest);expected['scout_manager']='system'
    require(current==expected,'exact reviewed legacy observer configuration required')


def zero_epoch_configuration(current,manifest):
    expected=r.configuration(REPAIRED,manifest);expected.update(scout_manager='system',acceptance_epoch=REPAIRED)
    require(current==expected,'exact reviewed committed observer configuration required')
    o.epoch_ready(current)
    directory=r.STATE/'epochs'/REPAIRED;r.protected(directory,directory=True)
    require({p.name for p in directory.iterdir()}=={'transition.json'},'only an uncredited committed epoch may be corrected')
    marker=directory/'transition.json';r.protected(marker)
    raw=marker.read_bytes();data=r.loads(raw)
    require(data['old_head']==OLD and data['history']['source_head']==OLD,'original historical source must remain unchanged')
    archive=o.verify_history(data['history'])
    require((r.STATE/'discovery.json').read_bytes()==(archive/'discovery.json').read_bytes(),'historical receipt changed after epoch commit')
    return raw


def no_scout_processes(proc):
    paths=list(proc.iterdir())
    require(len(paths)<=65536,'bounded Scout process inventory required')
    for path in paths:
        if not path.name.isdecimal():continue
        try:
            with (path/'cmdline').open('rb') as stream:raw=stream.read(8193)
        except (FileNotFoundError,ProcessLookupError):continue
        require(len(raw)<=8192,'bounded process arguments required')
        args=raw.split(b'\0')
        for i,arg in enumerate(args[:-1]):
            following=args[i+1]
            wrapper=arg==str(r.SOURCE).encode() and following in {b'begin',b'scout',b'end'}
            cli=following==b'scout' and (arg in {b'dev_agent.cli',b'-mdev_agent.cli',b'dev_agent/cli.py'} or arg.endswith(b'/dev_agent/cli.py'))
            require(not (wrapper or cli),'no Scout process outside or inside the unit permitted')


class Host:
    """Fixed privileged release adapter. No Scout/timer control method exists."""
    def __init__(self,head,old=OLD,invoke=subprocess.run):self.head=head;self.old=old;self.invoke=invoke
    def git(self,*args):return reviewed_git(r.ROOT,*args)
    def quiet(self):
        no_scout_processes(r.PROC)
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
            if (name in {'ops','dev_agent'} or name.startswith(('ops.','dev_agent.'))) and getattr(module,'__file__',None):
                path=Path(module.__file__);r.protected(path)
                rel=str(path.relative_to(stage))
                require(rel in target and r.sha(path.read_bytes())==target[rel],'exact staged release module required')
    def inspect(self):
        require(sys.platform=='linux' and os.geteuid()==0 and str(r.ROOT)=='/home/optiplex/investment' and isolated(),'fixed isolated Linux root release path required')
        require(self.old in {OLD,REPAIRED} and re.fullmatch('[a-f0-9]{40}',self.head) is not None and self.head!=self.old,'exact reviewed transition required')
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
        previous_epoch=None
        if self.old==OLD:
            legacy_configuration(current,r.source_manifest(r.ROOT,self.old))
            require('acceptance_epoch' not in current,'exact legacy SYSTEM boundary required')
        else:previous_epoch=zero_epoch_configuration(current,r.source_manifest(r.ROOT,self.old))
        require(current.get('head')==self.old and current.get('scout_manager')=='system','exact SYSTEM source boundary required')
        r.boundary(current,self.invoke,query_only=True);self.unit_boundary(current)
        r.manifest_matches(r.ROOT,current['files'])
        ledger,rows=o.ledger_snapshot();candidates=candidate_snapshot();before=dict(ledger=ledger,protected=u.protected_state(),candidate_count=len(candidates),candidates_sha256=o.digest(candidates))
        require(not list(r.STATE.glob('*.pending')) and not (r.CONTROL/'worktrees').is_symlink() and not ((r.CONTROL/'worktrees').exists() and any((r.CONTROL/'worktrees').iterdir())),'no pending bookends/worktrees permitted')
        receipt=r.STATE/'discovery.json';r.protected(receipt)
        data=r.loads(receipt.read_bytes())
        require(data.get('source_head')==OLD and data.get('fixture_only') is False and data.get('os_boundary_verified') is True and data.get('grants_implementation') is False,'historical source authority required')
        require(type(data.get('runs')) is list and 1<=len(data['runs'])<=30,'bounded nonempty historical acceptance required')
        require(len({x['slot'] for x in data['runs']})==len(data['runs'])==len({x['invocation'] for x in data['runs']}),'distinct historical records required')
        require(any(x['slot']=='scout:2026-10-29' and x['invocation']=='8608a7c10e9b4c23b96cf91bcc8fa51f' for x in data['runs']),'October 29 history required')
        for x in data['runs']:
            matched=[r.loads(row[5]) for row in rows if row[3]=='SCHEDULE' and r.loads(row[5]).get('slot')==x['slot']]
            require(len(matched)==1 and matched[0].get('head')==OLD and matched[0].get('status')=='COLLECTED' and matched[0].get('trigger')==dict(source='systemd-observed-timer',invocation=x['invocation']),'historical receipt must join original collection')
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
        plan=dict(old=self.old,head=self.head,current=current,desired=desired,before=before,timer=self.timer_identity(),receipt=receipt.read_bytes(),fires=(r.STATE/'timer-fires.json').read_bytes(),failure=r.encoded(failure),ledger_history=r.encoded(rows),candidates=r.encoded(candidates),source=r.SOURCE.read_bytes(),config=r.CONFIG.read_bytes(),new_source=self.git('show',self.head+':ops/discovery/observer.py'),new_config=r.encoded(desired))
        if previous_epoch is not None:
            plan['previous_epoch']=previous_epoch
            raw=r.command(self.invoke,['/usr/bin/journalctl','--no-pager','-o','json','_SYSTEMD_INVOCATION_ID=ec64de828d304e608b8113e3fc3d7e59'],check=True).stdout
            require(0<len(raw)<=2_000_000,'retained November 1 failure journal required')
            fields=('_SYSTEMD_UNIT','_SYSTEMD_INVOCATION_ID','_BOOT_ID','_PID','_UID','__REALTIME_TIMESTAMP','__MONOTONIC_TIMESTAMP')
            service=[{k:v for k,v in r.loads(line).items() if k in fields} for line in raw.splitlines()]
            raw=r.command(self.invoke,['/usr/bin/journalctl','--no-pager','-o','json','_SYSTEMD_UNIT=investment-discovery-observer.service','--since','2026-11-01 21:01:00 UTC','--until','2026-11-01 21:02:00 UTC'],check=True).stdout
            require(len(raw)<=2_000_000,'bounded November 1 observer failure journal required')
            codes=[]
            for line in raw.splitlines():
                record=r.loads(line)
                if record.get('_UID')=='0':
                    for code in re.findall(r'DISCOVERY_OBSERVER_FAILURE (SOURCE_SNAPSHOT_INVALID|BOOKEND_INVALID)',record.get('MESSAGE','')):
                        codes.append(dict(code=code,boot=record.get('_BOOT_ID'),at=record.get('__REALTIME_TIMESTAMP')))
            require({c['code'] for c in codes}=={'SOURCE_SNAPSHOT_INVALID','BOOKEND_INVALID'},'retained November 1 rejected bookends required')
            plan['previous_failure']=r.encoded(dict(service=service,observer=codes))
        return plan
    def recovery_guard(self,plan):
        require(sys.platform=='linux' and os.geteuid()==0 and isolated() and str(r.ROOT)=='/home/optiplex/investment','fixed isolated root recovery required')
        require(plan['old']==self.old and plan['head']==self.head and self.old in {OLD,REPAIRED},'exact recovery source required')
        require(not git_boundary(r.ROOT),'reviewed Git recovery boundary required')
        self.staged_boundary(r.source_manifest(r.ROOT,self.head))
    def authorize(self):
        a=authorization(authorization_path(self),self.old,self.head)
        # The protected release-controller attestation cannot substitute a different
        # PR head into a target: reviewed head must be in this merged source.
        self.git('merge-base','--is-ancestor',a['reviewed_head'],self.head)
        live_authorization(a)
        return a
    def guard(self,plan):
        self.quiet();require(self.timer_identity()==plan['timer'],'persistent timer history changed')
        require((r.STATE/'discovery.json').read_bytes()==plan['receipt'] and (r.STATE/'timer-fires.json').read_bytes()==plan['fires'],'historical evidence changed')
        if 'previous_epoch' in plan:
            require(zero_epoch_configuration(plan['current'],plan['current']['files'])==plan['previous_epoch'],'previous zero-credit epoch changed')
        m.ledger_unchanged(plan['before']['ledger']);r.flags_disabled(r.ROOT)
        require(o.digest(candidate_snapshot())==plan['before']['candidates_sha256'],'existing candidates changed')
    def stop(self):
        try:
            prior=r.SOCKET.lstat();self.previous_socket=(prior.st_dev,prior.st_ino,prior.st_ctime_ns)
        except FileNotFoundError:self.previous_socket=None
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
        r.wait_socket(self.previous_socket)
        r.boundary(plan['desired'] if new else plan['current'],self.invoke,query_only=True)
    def restore(self,plan):
        self.checkout(self.old)
        u.replace(r.SOURCE,plan['source'],0o644,0,os.getgid());u.replace(r.CONFIG,plan['config'],0o644,0,os.getgid())


def encode_plan(plan):return {k:(dict(bytes_hex=v.hex()) if isinstance(v,bytes) else v) for k,v in plan.items()}
def decode_plan(plan):return {k:(bytes.fromhex(v['bytes_hex']) if isinstance(v,dict) and set(v)=={'bytes_hex'} else v) for k,v in plan.items()}


def transaction(host,*,apply=False):
    try:plan=host.inspect()
    except Exception as error:
        if apply:raise
        return dict(status='PLAN_ONLY_BLOCKED',changes_applied=False,old_head=host.old,source_head=host.head,readiness_failures=[str(error)],grants_implementation=False)
    summary=dict(old_head=host.old,source_head=host.head,historical_runs=len(r.loads(plan['receipt'])['runs']),current_epoch_runs=0,grants_implementation=False)
    if not apply:
        return dict(summary,status='PLAN_ONLY',changes_applied=False,readiness_failures=[],
            production_head=plan['old'],proposed_target_head=plan['head'],
            historical_slots=sorted(x['slot'] for x in r.loads(plan['receipt'])['runs']),
            existing_candidate_count=plan['before']['candidate_count'],
            protected_state_fingerprints=plan['before'],timer=plan.get('timer'),
            observer=dict(state='ACTIVE',source_head=plan['old']),
            epoch_transition=dict(historical_source=r.loads(plan['receipt'])['source_head'],new_source=plan['head'],new_accepted_runs=0,historical_credit_transferred=False),
            intended_changes=['detached exact target source','installed observer source','protected source/epoch selector','sealed content-addressed historical archive','new epoch COMMITTED marker'],
            unchanged=['SYSTEM service and timer bytes','timer schedule and persistent history','legacy acceptance receipts','candidates','ledger history','financial state'],
            archive_requirements=['root-owned 0500 directory and 0400 files','exclusive content-addressed publication','SHA256 manifest verified before commit'],
            rollback_requirements=['durable exact old source/config/observer backup','one consumed nonce','exclusive lock','observer stopped on unverified rollback','never restore financial data'])
    a=host.authorize()
    require(a['historical_receipt_sha256']==r.sha(plan['receipt']) and a['historical_runs']==summary['historical_runs'],'owner authorization historical state changed')
    base=r.CONFIG.parent/'epoch-transitions';r.protected(base.parent,directory=True)
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
            o.verify_history(history)
            r.protected(epoch,directory=True)
            require(not (epoch/'discovery.json').exists() and not (epoch/'discovery.json').is_symlink(),'new epoch must have zero runs before genuine timer')
        operation='QUIET_WINDOW'
        try:
            host.guard(plan);operation='STOP_OBSERVER';host.stop();stage('OBSERVER_STOPPED');host.guard(plan)
            operation='ARCHIVE_HISTORY'
            # Archives and epochs are created once, never rewritten or cleaned up.
            history=archive_history(plan,a['nonce'])
            epochs=r.STATE/'epochs'
            if not epochs.exists():epochs.mkdir(mode=0o755);u.sync(r.STATE)
            r.protected(epochs,directory=True)
            epoch=epochs/host.head;epoch.mkdir(mode=0o755);u.sync(epochs)
            stage('HISTORY_ARCHIVED');preserved();host.guard(plan);operation='INSTALL_SOURCE';host.install(plan);stage('SOURCE_COMMITTED')
            operation='VERIFY_SOURCE';host.verify(plan,True);preserved();stage('NEW_BOUNDARY_VERIFIED');operation='START_OBSERVER';host.start(plan,True);operation='VERIFY_STARTED_OBSERVER';host.verify(plan,True);preserved()
            operation='COMMIT_EPOCH'
            u.write(epoch/'transition.json',r.encoded(dict(status='COMMITTED',source_head=host.head,old_head=history['source_head'],nonce=a['nonce'],history=history)),0o644,0,os.getgid())
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
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--head',required=True);parser.add_argument('--old-head',choices=(OLD,REPAIRED),default=OLD);parser.add_argument('--apply',action='store_true');parser.add_argument('--rollback');parser.add_argument('--authorize-owner-object',type=int);parser.add_argument('--retire-unused-authorization',metavar='EXPECTED_RECEIPT_SHA256')
    args=parser.parse_args();require(sum(bool(x) for x in (args.apply,args.rollback,args.authorize_owner_object,args.retire_unused_authorization))<=1,'choose one transition mode')
    host=Host(args.head,old=args.old_head)
    result=retire_unused_authorization(host,args.retire_unused_authorization) if args.retire_unused_authorization else issue_authorization(host,args.authorize_owner_object) if args.authorize_owner_object else rollback(host,args.rollback) if args.rollback else transaction(host,apply=args.apply)
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['status'] in {'PLAN_ONLY','AUTHORIZATION_RECORDED','UNUSED_AUTHORIZATION_RETIRED','NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'} else 1)
