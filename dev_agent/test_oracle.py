"""0803: immutable approved-base tests and configuration, separate from candidate code."""
from __future__ import annotations

import hashlib
import re
import subprocess
import io
import tarfile
from pathlib import Path

from .git_exec import output
from .policy import safe_relative
from .policy import matches, FORBIDDEN, TEST_RUNNER_FILES
from .store import digest

CONFIG = TEST_RUNNER_FILES


def application_files(root,base):
    """Exact approved-base source for independent collection; never candidate code."""
    expected={}
    for row in filter(None,output(root,'ls-tree','-rz','--full-tree',base,text=False).split(b'\0')):
        metadata,name=row.split(b'\t',1);name=name.decode();safe_relative(name)
        if matches(name,FORBIDDEN):continue
        if metadata.split()[0] not in {b'100644',b'100755'}:raise ValueError('unsafe base source')
        expected[name]=metadata.split()[2].decode()
    result={}
    with tarfile.open(fileobj=io.BytesIO(output(root,'archive',base,text=False))) as archive:
        for item in archive:
            if item.name not in expected:continue
            if not item.isfile() or item.size>2_000_000:raise ValueError('incomplete base source')
            data=archive.extractfile(item).read()
            if hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()!=expected[item.name]:
                raise ValueError('base source transformed by archive attributes')
            result[item.name]=data
    if set(result)!=set(expected):raise ValueError('base source omitted by archive attributes')
    return result


def files(root, base):
    if not re.fullmatch(r'[a-f0-9]{40}',base): raise ValueError('exact approved base required')
    try:
        if output(root,'rev-parse',base+'^{commit}').strip()!=base: raise ValueError('base cannot be reconstructed')
    except subprocess.CalledProcessError:
        raise ValueError('base cannot be reconstructed') from None
    result = {}
    # Read exact Git blobs: git archive can silently omit export-ignore paths.
    entries=output(root,'ls-tree','-rz','--full-tree',base,text=False).split(b'\0')
    for entry in filter(None,entries):
        metadata,name=entry.split(b'\t',1);name=name.decode();safe_relative(name)
        protected=(name.startswith('tests/') or Path(name).name in CONFIG or name=='config/release_baseline_failures.json')
        if not protected: continue
        mode,kind,oid=metadata.decode().split()
        if kind!='blob' or mode not in {'100644','100755'}:raise ValueError('unsafe trusted test tree')
        data=output(root,'cat-file','blob',oid,text=False)
        if len(data)>2_000_000:raise ValueError('incomplete trusted test tree')
        result[name]=data
    if not any(p.startswith('tests/test') and p.endswith('.py') for p in result):
        raise ValueError('approved-base regression tests unavailable')
    return result


def tree_hash(files):
    return digest({p:hashlib.sha256(data).hexdigest() for p,data in sorted(files.items())})


def materialize(root, base, destination):
    trusted=files(root,base)
    destination=Path(destination)
    for name,data in trusted.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return tree_hash(trusted)


def overlay(candidate, trusted):
    """A disposable workspace receives the oracle; candidate test code is excluded."""
    import shutil
    candidate, trusted=Path(candidate),Path(trusted)
    if (candidate/'tests').exists(): shutil.rmtree(candidate/'tests')
    for p in list(candidate.rglob('*')):
        if p.is_file() and p.name in CONFIG: p.unlink()
    for p in trusted.rglob('*'):
        if not p.is_file(): continue
        rel=p.relative_to(trusted)
        target=candidate/rel;target.parent.mkdir(parents=True,exist_ok=True)
        # Symlinks point to an OS read-only mount; candidate cannot replace tests
        # before collection. The container workspace itself is then read-only.
        target.symlink_to(p)
