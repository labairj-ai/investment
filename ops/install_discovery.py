#!/usr/bin/env python3
"""Pinned read-only discovery bootstrap; never installs the supervised loop.

Default is plan-only. The reviewed release operator uses --apply after owner Go.
Credentials must be independently provisioned read-only, never copied from an owner
CLI login. Existing installation files are preserved/refused, not overwritten.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.validator.install import prepare as reviewed_source,git
from dev_agent.github import GitHub
from dev_agent.signals import load_spool
from dev_agent.store import Store
from ops.validator.install import protected_parents

SERVICES=('development-scout','development-scheduler-observer','development-signal-collector')
UNITS=tuple(name+suffix for name in SERVICES for suffix in ('.service','.timer'))


def prepare(root,head,repository):
    plan=reviewed_source(root,head,repository)
    config=json.loads(git(root,'show',head+':config/development_agent.json'))
    if any(config.get(k) is not False for k in ('autonomous_implementation','supervised_loop_enabled','supervised_publish_pr','auto_merge')) or config.get('required_human_merge') is not True:
        raise ValueError('discovery bootstrap requires implementation/publication/auto-merge disabled')
    plan['files']={name:git(root,'show',head+':systemd/'+name) for name in UNITS}
    if any(b'supervised-cycle' in data or b'--command' in data for data in plan['files'].values()):raise ValueError('only fixed read-only discovery units may be installed')
    return plan


def verify_reader(client):
    repo=client.read('repos/'+client.repository);permissions=repo.get('permissions',{})
    if repo.get('full_name')!=client.repository or permissions.get('pull') is not True or any(permissions.get(k) is not False for k in ('push','admin','maintain')):
        raise ValueError('independently verified read-only GitHub identity required')


def apply(plan,*,invoke=subprocess.run):
    account=pwd.getpwuid(os.getuid());home=Path(account.pw_dir)
    if sys.platform!='linux' or account.pw_name!='optiplex' or Path(plan['root'])!=home/'investment':raise ValueError('reviewed OptiPlex user installation required')
    unit_dir=home/'.config/systemd/user';settings=home/'.config/investment-development'
    state=home/'.local/share/investment-development'
    for directory in [unit_dir,settings,state]:
        if directory.is_symlink():raise ValueError('private installation paths required')
        if directory.exists() and (directory.stat().st_uid!=os.getuid() or directory.stat().st_mode&0o022):raise ValueError('operator-owned installation paths required')
    token=settings/'github-read.token'
    if not token.is_file() or token.is_symlink():raise ValueError('dedicated read-only GitHub credential unavailable')
    observer=Path('/etc/investment-discovery-observer/config.json')
    protected_parents(observer)
    if json.loads(observer.read_text()).get('head')!=plan['head']:raise ValueError('current trusted discovery observer is required')
    invoke(['/bin/systemctl','is-active','--quiet','investment-discovery-observer.service'],check=True)
    old_token=os.environ.get('DEV_AGENT_GITHUB_READ_TOKEN_FILE')
    try:
        os.environ['DEV_AGENT_GITHUB_READ_TOKEN_FILE']=str(token)
        verify_reader(GitHub(plan['repository']))
    finally:
        if old_token is None:os.environ.pop('DEV_AGENT_GITHUB_READ_TOKEN_FILE',None)
        else:os.environ['DEV_AGENT_GITHUB_READ_TOKEN_FILE']=old_token
    envs={'discovery.env':f'DEVELOPMENT_CONTROL_DB={state}/development-control.sqlite3\nDEVELOPMENT_SIGNAL_SPOOL={state}/operational-signals.json\n',
          'collector.env':f'DEV_AGENT_GITHUB_READ_TOKEN_FILE={token}\n'}
    targets={**{unit_dir/name:data for name,data in plan['files'].items()},**{settings/name:data.encode() for name,data in envs.items()}}
    if any(p.exists() or p.is_symlink() for p in targets):raise ValueError('existing discovery installation requires reviewed upgrade, not bootstrap')
    created=[];enabled=[];old=os.umask(0o077)
    try:
        for directory in [unit_dir,settings,state]:directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        for path,data in targets.items():
            with path.open('xb') as f:f.write(data)
            path.chmod(0o600 if path.suffix=='.env' else 0o644);created.append(path)
        invoke(['systemctl','--user','daemon-reload'],check=True)
        Store(state/'development-control.sqlite3').migrate()
        # Collect real read-only metadata synchronously before any timer can fire.
        # A successful command alone is insufficient: validate the actual spool.
        priming_started=time.time()
        invoke(['systemctl','--user','start','development-signal-collector.service'],check=True)
        spool=state/'operational-signals.json'
        _,sources=load_spool(spool)
        payload=json.loads(spool.read_text())
        if not {'ci','telemetry','performance'}<=set(sources) or payload.get('unavailable')!=[] or not priming_started<=payload.get('created',0)<=time.time():
            raise ValueError('required read-only signal sources unavailable during priming')
        # No manual scout invocation; real timers determine accepted schedule slots.
        for name in ('development-signal-collector','development-scheduler-observer','development-scout'):
            enabled.append(name);invoke(['systemctl','--user','enable','--now',name+'.timer'],check=True)
        return dict(status='INSTALLED_AWAITING_THREE_REAL_RUNS',source_head=plan['head'],implementation_enabled=False,accepted_runs=0)
    except Exception:
        for name in reversed(enabled):invoke(['systemctl','--user','disable','--now',name+'.timer'],check=False)
        for path in created:path.unlink()
        invoke(['systemctl','--user','daemon-reload'],check=False)
        raise
    finally:os.umask(old)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--head',required=True);p.add_argument('--repository',default='labairj-ai/investment');p.add_argument('--apply',action='store_true');a=p.parse_args()
    plan=prepare(a.root,a.head,a.repository)
    result=apply(plan) if a.apply else dict(status='PLAN_ONLY',source_head=plan['head'],units=list(UNITS),starts_services=False,implementation_enabled=False)
    print(json.dumps(result,indent=2))
