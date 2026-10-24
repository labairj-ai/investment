"""Fixed local deployment operations. No arbitrary model/user shell strings."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request


class Executor:
    def __init__(self,root,receipts,ledger,*,invoke=subprocess.run):
        self.root=Path(root).resolve();self.receipts=Path(receipts).resolve();self.ledger=Path(ledger).resolve();self.invoke=invoke
        if self.root==Path('/') or self.receipts.is_relative_to(self.root) or self.ledger.is_relative_to(self.root):raise ValueError('isolated runtime receipt/ledger paths required')
        self.env=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',LANG='C.UTF-8',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_TERMINAL_PROMPT='0')

    def git(self,*args):
        import re
        from dev_agent.git_exec import OPTIONS
        shape=(args in {('remote','get-url','origin'),('status','--porcelain','--untracked-files=no'),('rev-parse','HEAD'),('ls-files','--others','--exclude-standard')})
        shape=shape or len(args)==4 and args[:2]==('fetch','--no-tags') and args[3]=='main' and bool(re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git',args[2]))
        shape=shape or len(args)==4 and args[:2]==('merge-base','--is-ancestor') and bool(re.fullmatch(r'[a-f0-9]{40}',args[2])) and args[3]=='FETCH_HEAD'
        shape=shape or len(args)==3 and args[:2]==('checkout','--detach') and bool(re.fullmatch(r'[a-f0-9]{40}',args[2]))
        if not shape:raise ValueError('fixed read/fetch/exact-checkout Git operation required; push denied')
        options=dict(OPTIONS,**{'core.sshCommand':'/bin/false','protocol.ssh.allow':'never','submodule.recurse':'false','safe.directory':str(self.root)})
        prefix=['/usr/bin/git','-C',str(self.root)]
        for key,value in options.items():prefix+=['-c',key+'='+value]
        filters=self.invoke(prefix+['config','--local','--get-regexp',r'^filter\..*\.(clean|smudge|process)$'],capture_output=True,timeout=30,env=self.env)
        if filters.returncode==0 and filters.stdout.strip() or filters.returncode not in (0,1):raise ValueError('ambient executable Git filters denied')
        process=self.invoke(prefix+list(args),check=True,capture_output=True,text=True,timeout=120,env=self.env)
        return process.stdout.strip()

    def service(self,verb):
        if verb not in {'is-active','stop','start','restart'}:raise ValueError('fixed service operation required')
        process=self.invoke(['/bin/systemctl','--no-ask-password',verb,'investment.service'],check=True,capture_output=True,text=True,timeout=90,env=self.env)
        return process.stdout.strip()

    def config_hash(self):
        result=self.invoke(['/bin/systemctl','show','investment.service','--property=FragmentPath,DropInPaths,ExecStart,User,EnvironmentFiles'],capture_output=True,text=True,check=True,timeout=15,env=self.env)
        return hashlib.sha256(result.stdout.encode()).hexdigest()

    @staticmethod
    def hash_file(path):
        path=Path(path)
        if path.is_symlink() or not path.is_file():raise ValueError('regular protected file required')
        h=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        return h.hexdigest()

    def ledger_snapshot(self,*,event_limit=None,candidate_limit=None):
        # Logical, transactional identity avoids false mutation alarms from WAL
        # readers while still detecting updates/deletes/schema changes.
        if self.ledger.is_symlink() or self.ledger.name!='development-control.sqlite3':raise ValueError('dedicated read-only development ledger required')
        with sqlite3.connect(self.ledger.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('BEGIN')
            schema=db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            events=db.execute('SELECT coalesce(max(seq),0) FROM dev_events').fetchone()[0] if event_limit is None else event_limit
            candidates=db.execute('SELECT coalesce(max(rowid),0) FROM dev_candidates').fetchone()[0] if candidate_limit is None else candidate_limit
            def hash_rows(query,limit):
                h=hashlib.sha256()
                for row in db.execute(query,(limit,)):h.update(json.dumps(row,separators=(',',':'),sort_keys=True).encode()+b'\n')
                return h.hexdigest()
            return dict(schema=hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),events=events,candidates=candidates,event_hash=hash_rows('SELECT seq,event_id,candidate,kind,created,payload FROM dev_events WHERE seq<=? ORDER BY seq',events),candidate_hash=hash_rows('SELECT rowid,id,identity,created,payload FROM dev_candidates WHERE rowid<=? ORDER BY rowid',candidates))

    def investment_identity(self,name="investment.db"):
        # Deployment role only; return a digest, never database contents.
        if name not in {'investment.db','buffett.db'}:raise ValueError('fixed protected database required')
        path=self.root/'out'/name
        if path.is_symlink() or not path.is_file():raise ValueError('authoritative database must be a regular existing file')
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('BEGIN');h=hashlib.sha256()
            encode=lambda row:json.dumps([{'blob':v.hex()} if isinstance(v,bytes) else v for v in row],sort_keys=True,separators=(',',':'))
            for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'):h.update(encode(row).encode())
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                h.update(name.encode())
                for row in sorted(encode(r) for r in db.execute('SELECT * FROM "'+name.replace('"','""')+'"')):h.update(row.encode()+b'\n')
            return h.hexdigest()

    def protected(self):
        return dict(holdings_sha256=self.hash_file(self.root/'holdings.csv'),ledger=self.ledger_snapshot(),investment=self.investment_identity(),auxiliary=dict(buffett=self.investment_identity('buffett.db') if (self.root/'out/buffett.db').exists() or (self.root/'out/buffett.db').is_symlink() else None))

    def protected_unchanged(self,before,after):
        if before['holdings_sha256']!=after['holdings_sha256'] or before['investment']!=after['investment'] or before.get('auxiliary')!=after.get('auxiliary'):return False
        old=before['ledger'];new=after['ledger']
        if new['events']<old['events'] or new['candidates']<old['candidates']:return False
        prefix=self.ledger_snapshot(event_limit=old['events'],candidate_limit=old['candidates'])
        if any(prefix[k]!=old[k] for k in ('schema','event_hash','candidate_hash')):return False
        allowed={'STATIC_VALIDATION','OWNER_MERGE','STATE','PLAN','TODO_RESERVATION','APPROVAL','OWNER_REVIEW','HUMAN_REVIEW','BUILD_POLICY','POLICY_ADMISSION','START_AUTHORIZATION','WORKTREE','RUN','ITERATION','VALIDATION','VALIDATION_BATCH','SUPPLEMENTAL_VALIDATION','RECEIPT','PR','MERGE','DEPLOYMENT','OPERATIONAL_SUCCESS','EFFECTIVENESS','SCORE','SIGNAL_OBSERVATION','SCHEDULE','SCHEDULE_ATTEMPT','SCHEDULE_FAILURE','SCHEDULE_DUPLICATE','SCHEDULER_OBSERVATION','PROTECTION','PIPELINE','OWNER_NOTIFICATION','TECHNICAL_CERTIFICATION','STAGE_OBSERVATION','AUTONOMY_PAUSE','AUTONOMY_RESUME','GIT_INTENT','AUTHORIZATION'}
        with sqlite3.connect(self.ledger.as_uri()+'?mode=ro',uri=True) as db:
            kinds={r[0] for r in db.execute('SELECT DISTINCT kind FROM dev_events WHERE seq>? AND seq<=?',(old['events'],new['events']))}
        # Only append-only development/control activity is expected. Existing
        # rows, schema, holdings and unknown event types may never change.
        return kinds<=allowed and self.ledger_snapshot(event_limit=new['events'],candidate_limit=new['candidates'])==new

    def preflight(self,origin):
        if self.git('remote','get-url','origin')!=origin or not origin.startswith('https://github.com/'):raise ValueError('reviewed read-only origin required')
        if self.git('status','--porcelain','--untracked-files=no'):raise ValueError('dirty tracked production worktree')
        if shutil.disk_usage(self.root).free<2_000_000_000:raise ValueError('insufficient rollback/backup disk space')
        if self.service('is-active')!='active':raise ValueError('pre-deployment service not healthy')
        return dict(prior_sha=self.git('rev-parse','HEAD'),untracked=self.git('ls-files','--others','--exclude-standard').splitlines(),service='active',service_configuration_hash=self.config_hash(),protected=self.protected())

    def backup(self,directory):
        directory=Path(directory);directory.mkdir(mode=0o700,parents=True,exist_ok=False)
        source=self.root/'out/investment.db';target=directory/'investment-backup.sqlite3'
        backups={}
        for name in ('investment.db','buffett.db'):
            source=self.root/'out'/name
            if source.is_symlink():raise ValueError('protected backup symlink denied')
            if name=='buffett.db' and not source.exists():continue
            if source.is_symlink() or not source.is_file():raise ValueError('regular protected backup source required')
            target=directory/(name+'.sqlite3')
            with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as live,sqlite3.connect(target) as copy:
                live.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('backup integrity failure')
            backups[name]=dict(path=str(target),sha256=self.hash_file(target),integrity='ok')
        return dict(**backups['investment.db'],mechanism='sqlite-online-backup-1',databases=backups)

    def checkout(self,sha,origin):
        if len(sha)!=40 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('exact SHA required')
        self.git('fetch','--no-tags',origin,'main')
        self.git('merge-base','--is-ancestor',sha,'FETCH_HEAD')
        self.git('checkout','--detach',sha)

    def health(self):
        def http(path,expected):
            try:
                with urllib.request.urlopen('http://127.0.0.1:5001'+path,timeout=10) as response:code=response.status
            except urllib.error.HTTPError as error:code=error.code
            return code==expected
        process=self.invoke([str(self.root/'venv/bin/python'),str(self.root/'scripts/canary_advisor_decision.py'),'--db',str(self.root/'out/investment.db')],capture_output=True,text=True,check=True,timeout=180,env=self.env)
        raw=json.loads(process.stdout)
        canary={k:raw.get(k) for k in ('health','mutation_safety','functional_contract','production_state_unchanged')}
        cfg=json.loads((self.root/'config/development_agent.json').read_text())
        checks=dict(service=self.service('is-active')=='active',dashboard=http('/out/dashboard.html',200),development_dashboard=http('/development-agent',200),unauthorized_api_denied=http('/api/development-agent',403),advisor=all(canary.get(k)=='PASS' for k in ('health','mutation_safety','functional_contract')) and canary.get('production_state_unchanged') is True,auto_merge_disabled=cfg.get('auto_merge') is False)
        # Authenticated API must be exercised with a separately provisioned local
        # credential by the operator service; no fallback to unauthenticated PASS.
        token_file=os.environ.get('INVESTMENT_DEPLOY_API_CREDENTIAL_FILE')
        checks['authenticated_api']=False
        if token_file:
            credential_path=Path(token_file)
            if credential_path.is_symlink() or credential_path.stat().st_mode&0o077:raise ValueError('private local API credential required')
            request=urllib.request.Request('http://127.0.0.1:5001/api/development-agent',headers={'X-Development-Agent-Token':credential_path.read_text().strip()})
            with urllib.request.urlopen(request,timeout=10) as response:checks['authenticated_api']=response.status==200
        return dict(checks=checks,canary=canary,activation={k:cfg.get(k) for k in ('autonomous_implementation','supervised_loop_enabled','supervised_publish_pr','auto_merge')},autonomous_implementation=cfg.get('autonomous_implementation'))
