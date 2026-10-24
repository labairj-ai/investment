#!/usr/bin/env python3
"""Plan-only by default, fixed root-owned discovery observer bootstrap."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import stat
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.validator.install import prepare as reviewed_source,git,protected_parents

SOURCE=Path('/opt/investment-discovery-observer')
CONFIG=Path('/etc/investment-discovery-observer')
UNIT=Path('/etc/systemd/system/investment-discovery-observer.service')


def prepare(root,head,repository):
    plan=reviewed_source(root,head,repository)
    names=['ops/discovery/observer.py','ops/discovery/investment-discovery-observer.service','systemd/development-scout.service']
    plan['files']={n:git(root,'show',head+':'+n) for n in names}
    tracked=git(root,'ls-tree','-rz','--full-tree',head).split(b'\0');manifest={}
    for row in filter(None,tracked):
        meta,name=row.split(b'\t',1);mode,kind,oid=meta.decode().split();name=name.decode()
        if kind!='blob' or mode not in {'100644','100755'}:raise ValueError('regular pinned source required')
        manifest[name]=hashlib.sha256(git(root,'cat-file','blob',oid)).hexdigest()
    plan['manifest']=manifest
    return plan


def apply(plan,*,invoke=subprocess.run):
    if sys.platform!='linux' or os.geteuid()!=0 or plan['root']!='/home/optiplex/investment':raise ValueError('fixed reviewed OptiPlex root bootstrap required')
    for path in (SOURCE,CONFIG,UNIT):
        protected_parents(path.parent)
        if path.exists() or path.is_symlink():raise ValueError('existing observer requires reviewed upgrade')
    created=[];started=False
    try:
        for directory in (SOURCE,CONFIG):directory.mkdir(mode=0o755);created.append(directory)
        source=SOURCE/'observer.py';source.write_bytes(plan['files']['ops/discovery/observer.py']);source.chmod(0o644)
        config=dict(head=plan['head'],observer_digest=hashlib.sha256(source.read_bytes()).hexdigest(),unit_digest=hashlib.sha256(plan['files']['systemd/development-scout.service']).hexdigest(),timer_digest=plan['manifest']['systemd/development-scout.timer'],files=plan['manifest'])
        (CONFIG/'config.json').write_text(json.dumps(config,sort_keys=True)+'\n');(CONFIG/'config.json').chmod(0o644)
        with UNIT.open('xb') as f:f.write(plan['files']['ops/discovery/investment-discovery-observer.service'])
        created.append(UNIT);UNIT.chmod(0o644)
        invoke(['/bin/systemctl','daemon-reload'],check=True);started=True
        invoke(['/bin/systemctl','start','investment-discovery-observer.service'],check=True)
        invoke(['/bin/systemctl','is-active','--quiet','investment-discovery-observer.service'],check=True)
        socket=Path('/run/investment-discovery-observer/observer.sock');deadline=time.monotonic()+5
        while not socket.exists() and time.monotonic()<deadline:time.sleep(0.05)
        info=socket.lstat()
        if socket.is_symlink() or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=0 or info.st_mode&0o007:raise ValueError('trusted observer socket unavailable')
        return dict(status='INSTALLED_AWAITING_REAL_TIMER_RUNS',source_head=plan['head'],grants_implementation=False)
    except Exception:
        if not started or invoke(['/bin/systemctl','stop','investment-discovery-observer.service'],check=False).returncode==0:
            import shutil
            for path in reversed(created):
                if path==UNIT:path.unlink(missing_ok=True)
                else:shutil.rmtree(path)
            invoke(['/bin/systemctl','daemon-reload'],check=False)
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--head',required=True);p.add_argument('--repository',default='labairj-ai/investment');p.add_argument('--apply',action='store_true');a=p.parse_args()
    plan=prepare(a.root,a.head,a.repository)
    print(json.dumps(apply(plan) if a.apply else dict(status='PLAN_ONLY',source_head=plan['head'],starts_services=False,grants_implementation=False),indent=2))
