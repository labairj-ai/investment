#!/usr/bin/env python3
"""Fixed first installation of the reviewed L0 oracle; no model/application changes.

Default is a read-only plan. The reviewed release operator invokes --apply after
owner Go. The owner never needs to run this tooling or manage keys/certificates.
Existing installations are refused rather than silently overwritten.
"""
from __future__ import annotations
import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys

IDENTITY='investment-oracle'
SOURCE=Path('/opt/investment-static-oracle')
CONFIG=Path('/etc/investment-static-oracle')
STATE=Path('/var/lib/investment-static-oracle')
UNIT=Path('/etc/systemd/system/investment-static-oracle.service')
RUNTIME=Path('/usr/bin/python3')


def git(root,*args):
    env=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_NO_REPLACE_OBJECTS='1',GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(['/usr/bin/git','-C',str(root),'-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','pack.packObjectsHook=','-c','safe.directory='+str(root),*args],env=env,timeout=120)


def prepare(root,expected_head,repository):
    root=Path(root).resolve(strict=True)
    if not re.fullmatch('[a-f0-9]{40}',expected_head) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('exact reviewed source and repository required')
    if git(root,'rev-parse','HEAD').decode().strip()!=expected_head or git(root,'status','--porcelain','--untracked-files=no').strip():raise ValueError('clean exact reviewed installation source required')
    remote=git(root,'remote','get-url','origin').decode().strip()
    if remote not in {f'https://github.com/{repository}.git',f'git@github.com:{repository}.git'}:raise ValueError('source repository mismatch')
    if git(root,'rev-parse','origin/main').decode().strip()!=expected_head:raise ValueError('installation requires exact merged main')
    paths=['ops/validator/static_oracle.py','ops/validator/investment-static-oracle.service']
    files={p:git(root,'show',expected_head+':'+p) for p in paths}
    if any(not data or len(data)>65536 for data in files.values()):raise ValueError('bounded reviewed installation files required')
    return dict(root=str(root),head=expected_head,repository=repository,files=files)


def protected_parents(path):
    for parent in [path,*path.parents]:
        if parent.exists() and (parent.is_symlink() or parent.stat().st_uid!=0 or parent.stat().st_mode&0o022):
            raise ValueError('root-controlled installation ancestry required')


def apply(plan,*,invoke=subprocess.run):
    if sys.platform!='linux' or os.geteuid()!=0:raise ValueError('reviewed Linux root installation required')
    # Bootstrap only. Never overwrite or stop an existing service/installation.
    for path in [SOURCE,CONFIG,STATE,UNIT]:
        protected_parents(path.parent)
        if path.exists() or path.is_symlink():raise ValueError('existing installation requires reviewed upgrade, not bootstrap')
    # A pre-existing account must have no login or supplementary authority.
    try:account=pwd.getpwnam(IDENTITY)
    except KeyError:
        invoke(['/usr/sbin/useradd','--system','--user-group','--home-dir','/nonexistent','--shell','/usr/sbin/nologin',IDENTITY],check=True)
        account=pwd.getpwnam(IDENTITY)
    if account.pw_dir!='/nonexistent' or account.pw_shell!='/usr/sbin/nologin' or set(os.getgrouplist(IDENTITY,account.pw_gid))!={account.pw_gid}:
        raise ValueError('dedicated unprivileged oracle identity required')
    gid=grp.getgrnam(IDENTITY).gr_gid
    if gid!=account.pw_gid:raise ValueError('dedicated oracle group required')
    old=os.umask(0o077);created=[];start_attempted=False
    try:
        SOURCE.mkdir(mode=0o755);created.append(SOURCE);SOURCE.chmod(0o755)
        for path in [CONFIG,STATE]:
            path.mkdir(mode=0o750);created.append(path);os.chown(path,0,gid);path.chmod(0o750)
        # Bundle uses Git blobs/objects only; no worktree files, credentials,
        # source Python imports, Git hooks, model runtimes or production DBs.
        bundle=STATE/'bootstrap.bundle'
        git(plan['root'],'bundle','create',str(bundle),'HEAD')
        heads=git(plan['root'],'bundle','list-heads',str(bundle)).decode().splitlines()
        if heads!=[plan['head']+' HEAD'] or bundle.stat().st_size>2_000_000_000:raise ValueError('installation source moved or bundle is excessive')
        authority=STATE/'authority.git'
        invoke(['/usr/bin/git','-c','init.templateDir=/dev/null','init','--bare',str(authority)],check=True,capture_output=True)
        invoke(['/usr/bin/git','--git-dir='+str(authority),'bundle','unbundle',str(bundle)],check=True,capture_output=True)
        invoke(['/usr/bin/git','--git-dir='+str(authority),'update-ref','refs/heads/approved-base',plan['head']],check=True)
        for path in [authority,*authority.rglob('*')]:
            if path.is_symlink():raise ValueError('authority store symlink denied')
            os.chown(path,0,gid);path.chmod(0o750 if path.is_dir() else 0o640)
        bundle.unlink()
        source=SOURCE/'static_oracle.py';source.write_bytes(plan['files']['ops/validator/static_oracle.py']);source.chmod(0o644)
        UNIT.write_bytes(plan['files']['ops/validator/investment-static-oracle.service']);created.append(UNIT);UNIT.chmod(0o644)
        key=CONFIG/'signing.key';key.write_bytes(os.urandom(32));os.chown(key,account.pw_uid,gid);key.chmod(0o600)
        runtime='python@sha256:'+hashlib.sha256(RUNTIME.resolve().read_bytes()).hexdigest()
        config=dict(repository=plan['repository'],approved_base=plan['head'],authority_git_dir=str(authority),allowed_prefixes=['docs/help/'],runtime_identity=runtime,signing_key=str(key),socket='/run/investment-static-oracle/oracle.sock')
        path=CONFIG/'config.json';path.write_text(json.dumps(config,indent=2)+'\n');os.chown(path,account.pw_uid,gid);path.chmod(0o600)
        # Non-secret supervisor pins are operator-only, separate from candidates.
        pins=dict(application_sha=plan['head'],validator_source_digest=hashlib.sha256(source.read_bytes()).hexdigest(),runtime_identity=runtime,scope='L0_STATIC_TEXT',live_acceptance='NOT_RUN',grants_pytest_authority=False)
        path=CONFIG/'installation.json';path.write_text(json.dumps(pins,indent=2)+'\n');path.chmod(0o600)
        invoke(['/bin/systemctl','daemon-reload'],check=True)
        start_attempted=True
        invoke(['/bin/systemctl','start','investment-static-oracle.service'],check=True)
        invoke(['/bin/systemctl','is-active','--quiet','investment-static-oracle.service'],check=True)
        return dict(status='INSTALLED_AWAITING_ACCEPTANCE',**pins)
    except Exception:
        stopped=not start_attempted
        if start_attempted:
            stopped=invoke(['/bin/systemctl','stop','investment-static-oracle.service'],check=False).returncode==0
        if stopped:
            # Remove only paths created by this bootstrap; never existing state.
            for path in reversed(created):
                if path==UNIT:path.unlink(missing_ok=True)
                else:shutil.rmtree(path)
            invoke(['/bin/systemctl','daemon-reload'],check=False)
        raise
    finally:os.umask(old)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--head',required=True);p.add_argument('--repository',default='labairj-ai/investment');p.add_argument('--apply',action='store_true');a=p.parse_args()
    plan=prepare(a.root,a.head,a.repository)
    if a.apply:result=apply(plan)
    else:result=dict(status='PLAN_ONLY',head=plan['head'],repository=plan['repository'],scope='L0_STATIC_TEXT',service=IDENTITY,files={p:hashlib.sha256(b).hexdigest() for p,b in plan['files'].items()},starts_services=False,live_acceptance='NOT_RUN')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
