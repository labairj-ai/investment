#!/usr/bin/python3
"""External L0 oracle. Install reviewed file outside every candidate checkout.

This protocol attests static text checks only, NEVER pytest or executable safety.
Fixed authority repository/base/path policy is private operator configuration.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import errno
import socketserver
import stat
import subprocess
import sys
import time

PROTOCOL='bounded-static-oracle-1'
INVENTORY=['bounded-regular-text','no-active-markup','safe-document-path','utf8-no-control']
MAX=2_000_000


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def unique(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError('duplicate field')
        out[k]=v
    return out


def loads(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def private_file(path):
    path=Path(path)
    info=path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>16384:
        raise ValueError('private bounded controller-owned regular file required')
    # All ancestors must resist candidate-controlled replacement.
    for parent in path.absolute().parents:
        info=parent.lstat()
        if parent.is_symlink() or info.st_mode&0o022:raise ValueError('protected controller path required')
    return path.read_bytes()


def git(authority,*args):
    env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_NO_REPLACE_OBJECTS':'1','GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0'}
    return subprocess.run(['/usr/bin/git','--git-dir='+authority,'-c','core.hooksPath=/dev/null','-c','core.attributesFile=/dev/null','-c','core.fsmonitor=false','-c','safe.directory='+authority,*args],env=env,cwd='/',capture_output=True,check=True,timeout=20).stdout


def tree(authority,sha):
    result={}
    raw=git(authority,'ls-tree','-rz','--full-tree',sha)
    if len(raw)>MAX:raise ValueError('tree too large')
    for row in filter(None,raw.split(b'\0')):
        meta,name=row.split(b'\t',1);mode,kind,oid=meta.decode().split();name=name.decode('utf8')
        if name in result or not name or name.startswith('/') or '..' in PurePosixPath(name).parts:
            raise ValueError('invalid source tree path')
        if kind!='blob' or mode not in {'100644','100755'}:raise ValueError('symlink/submodule denied')
        result[name]=dict(mode=mode,oid=oid)
    return result


def check_text(files):
    status={k:True for k in INVENTORY}
    if not files:raise ValueError('nonempty change required')
    for name,text in files.items():
        status['safe-document-path'] &= bool(re.fullmatch(r'[A-Za-z0-9_./-]+\.(md|txt)',name)) and '..' not in PurePosixPath(name).parts
        status['bounded-regular-text'] &= len(text.encode())<=65536
        status['utf8-no-control'] &= all(ord(c)>=32 or c in '\n\r\t' for c in text)
        status['no-active-markup'] &= not bool(re.search(r'(?i)<\s*(script|iframe|object|embed|svg|style|link|meta)|javascript\s*:|data\s*:|on[a-z]+\s*=',text))
    return dict(results=[dict(id=k,status='PASS' if status[k] else 'FAIL') for k in INVENTORY])


def evaluate(config,request,*,timeout=5):
    if not isinstance(request,dict) or set(request)!={'protocol','repository','base','head'} or request['protocol']!=PROTOCOL:
        raise ValueError('exact bounded static request required')
    if request['repository']!=config['repository'] or request['base']!=config['approved_base']:
        raise ValueError('repository/approved base mismatch')
    for field in ('base','head'):
        if not isinstance(request[field],str) or not re.fullmatch('[a-f0-9]{40}',request[field]):raise ValueError('exact SHA required')
    authority=config['authority_git_dir']
    if not Path(authority).is_absolute() or Path(authority).is_symlink():raise ValueError('fixed absolute authority required')
    runtime_identity='python@sha256:'+hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
    if config['runtime_identity']!=runtime_identity:raise ValueError('pinned runtime identity mismatch')
    git(authority,'merge-base','--is-ancestor',request['base'],request['head'])
    base=tree(authority,request['base']);head=tree(authority,request['head'])
    changed=sorted(k for k in base.keys()|head.keys() if base.get(k)!=head.get(k))
    if not changed or len(changed)>50:raise ValueError('bounded changed inventory required')
    prefixes=config['allowed_prefixes']
    if not prefixes or any(not re.fullmatch(r'docs/[a-z0-9-]+/',p) or p in {'docs/plans/','docs/evidence/'} for p in prefixes):
        raise ValueError('reviewed user-document prefixes required')
    files={}
    for name in changed:
        if not any(name.startswith(p) for p in prefixes) or not name.endswith(('.md','.txt')) or name not in head or head[name]['mode']!='100644':
            raise ValueError('outside L0 additive/editable document scope')
        blob=git(authority,'cat-file','blob',head[name]['oid'])
        if len(blob)>65536:raise ValueError('oversized candidate text')
        files[name]=blob.decode('utf8')
    trusted={k:v for k,v in base.items() if k.startswith('tests/')}
    if not trusted:raise ValueError('trusted base test inventory missing')
    runtime=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    binding=dict(repository=config['repository'],base=request['base'],head=request['head'],candidate_source_tree_digest=digest(head),
                 trusted_test_tree_digest=digest(trusted),trusted_inventory_digest=digest(INVENTORY),command_class='L0_STATIC_TEXT',
                 runtime_identity=config['runtime_identity'],validator_source_digest=runtime,oracle_protocol=PROTOCOL)
    # This child executes only this installed trusted file. Candidate bytes are JSON data.
    started=time.time();timed_out=False;exit_code=None;results=[]
    try:
        child=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).resolve()),'--worker'],input=canonical(files),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                             env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'},cwd='/',timeout=timeout)
        exit_code=child.returncode
        if exit_code==0 and len(child.stdout)<=MAX:
            data=loads(child.stdout)
            if set(data)=={'results'}:results=data['results']
    except subprocess.TimeoutExpired:timed_out=True
    expected=[dict(id=k,status='PASS') for k in INVENTORY]
    ok=not timed_out and exit_code==0 and results==expected
    return dict(protocol=PROTOCOL,binding=binding,expected=INVENTORY,results=results,status='PASS' if ok else 'FAIL',
                process_exit=exit_code,timed_out=timed_out,started=started,ended=time.time(),
                containment='no-candidate-code-execution',fixture_only=False,grants_pytest_authority=False)


def clear_stale_socket(path):
    """Recover only our private, refused socket. Never unlink a live listener."""
    if not path.exists() and not path.is_symlink():return
    before=path.lstat()
    if path.is_symlink() or not stat.S_ISSOCK(before.st_mode) or before.st_uid!=os.getuid() or before.st_mode&0o077:
        raise ValueError('unsafe existing socket path')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(1)
        try:client.connect(str(path))
        except OSError as error:
            if error.errno!=errno.ECONNREFUSED:raise ValueError('existing socket availability unknown') from None
        else:raise ValueError('oracle socket already active')
    after=path.lstat()
    if (after.st_dev,after.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('socket changed during recovery')
    path.unlink()


def serve(config_path):
    config=loads(private_file(config_path));key=private_file(config['signing_key'])
    if len(key)<32:raise ValueError('private signing material required')
    socket_path=Path(config['socket'])
    parent=socket_path.parent
    if not parent.is_dir() or parent.is_symlink() or parent.stat().st_uid!=os.getuid() or parent.stat().st_mode&0o077:
        raise ValueError('private owned socket directory required')
    clear_stale_socket(socket_path)
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(30)
            try:
                raw=self.rfile.readline(MAX+1)
                if len(raw)>MAX or not raw.endswith(b'\n'):raise ValueError('bounded request required')
                receipt=evaluate(config,loads(raw))
                result=dict(receipt=receipt,signature=hmac.new(key,canonical(receipt),hashlib.sha256).hexdigest())
            except Exception as error:result=dict(status='FAIL',reason=type(error).__name__)
            self.wfile.write(canonical(result)+b'\n')
    old=os.umask(0o077)
    try:
        with socketserver.UnixStreamServer(str(socket_path),Handler) as server:
            owned_socket=socket_path.lstat()
            server.serve_forever()
    finally:
        os.umask(old)
        if socket_path.is_socket() and 'owned_socket' in locals():
            current=socket_path.lstat()
            if (current.st_dev,current.st_ino)==(owned_socket.st_dev,owned_socket.st_ino):socket_path.unlink()


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--worker':
        raw=sys.stdin.buffer.read(MAX+1)
        if len(raw)>MAX:raise ValueError('bounded worker input required')
        sys.stdout.buffer.write(canonical(check_text(loads(raw))))
    elif len(sys.argv)==2:serve(sys.argv[1])
    else:raise SystemExit('usage: static_oracle.py /private/controller-config.json')
