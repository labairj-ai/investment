#!/usr/bin/python3
"""Fixed installed L0 host matrix. Generated hostile inputs, never candidate code.

Runs only under the acceptance service's oracle identity/sandbox. Its receipt is
host acceptance, not a pytest certificate or a genuine discovered improvement.
"""
import copy
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

SOURCE=Path('/opt/investment-static-oracle/static_oracle.py')
SELF=Path('/opt/investment-static-oracle/live_acceptance.py')
CONFIG=Path('/etc/investment-static-oracle')
RUNTIME=Path('/run/investment-static-oracle')
OUTPUT=Path('/var/lib/investment-static-oracle-acceptance/live-acceptance.json')
UNIT=Path('/etc/systemd/system/investment-static-oracle.service')
ACCEPTANCE_UNIT=Path('/etc/systemd/system/investment-static-oracle-acceptance.service')
MATRIX=('valid-document','active-markup','executable','test-delete','test-rewrite','fake-pass','fake-junit','symlink',
        'worker-timeout','worker-crash','worker-duplicate','worker-truncated','runtime-mismatch','source-mismatch',
        'key-permissions','socket-permissions','candidate-access-denied','network-denied','production-db-denied',
        'credentials-denied','docker-denied','installed-socket')


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def protected(path):
    for p in [path,*path.parents]:
        info=p.lstat()
        if p.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('protected installed acceptance source required')


def private(path,socket_kind=False):
    s=path.lstat()
    if path.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077 or not (stat.S_ISSOCK(s.st_mode) if socket_kind else stat.S_ISREG(s.st_mode)):raise ValueError('private service material required')
    for p in path.parents:
        if p.is_symlink() or p.stat().st_mode&0o022:raise ValueError('protected material ancestry required')
    return s


def candidate_probe():
    # Invoked by the root bootstrap as fixed nobody, never as the oracle identity.
    if os.geteuid()!=pwd.getpwnam('nobody').pw_uid:raise ValueError('unprivileged candidate probe required')
    for path in [CONFIG/'signing.key',CONFIG/'config.json']:
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK);os.close(fd)
        except PermissionError:pass
        else:raise ValueError('candidate can access oracle material')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
        channel.settimeout(1)
        try:channel.connect(str(RUNTIME/'oracle.sock'))
        except PermissionError:pass
        else:raise ValueError('candidate can access oracle socket')
    print('DENIED')


def service_context():
    if sys.platform!='linux' or pwd.getpwuid(os.getuid()).pw_name!='investment-oracle':raise ValueError('installed oracle identity required')
    invocation=os.environ.get('INVOCATION_ID','')
    if not re.fullmatch('[a-f0-9]{32}',invocation) or 'investment-static-oracle-acceptance.service' not in Path('/proc/self/cgroup').read_text():raise ValueError('actual acceptance service required')
    return invocation


def identity():
    invocation=service_context()
    for p in [SOURCE,SELF,UNIT,ACCEPTANCE_UNIT,CONFIG/'installation.json',CONFIG/'candidate-denial.json']:protected(p)
    pins=json.loads((CONFIG/'installation.json').read_bytes())
    observed=dict(validator_source_digest=sha(SOURCE),harness_source_digest=sha(SELF),unit_digest=sha(UNIT),acceptance_unit_digest=sha(ACCEPTANCE_UNIT),runtime_identity='python@sha256:'+sha(Path(sys.executable).resolve()))
    if any(pins.get(k)!=v for k,v in observed.items()):raise ValueError('installed source/runtime/unit pin mismatch')
    if not os.statvfs(SOURCE).f_flag&os.ST_RDONLY:raise ValueError('acceptance source is writable')
    status=Path('/proc/self/status').read_text()
    if not re.search(r'^NoNewPrivs:\s+1$',status,re.M):raise ValueError('acceptance privilege boundary missing')
    socket_info=private(RUNTIME/'oracle.sock',True);key_info=private(CONFIG/'signing.key');private(CONFIG/'config.json')
    denial=json.loads((CONFIG/'candidate-denial.json').read_bytes())
    if (denial.get('status')!='DENIED' or denial.get('source_digest')!=observed['harness_source_digest'] or denial.get('socket_inode')!=socket_info.st_ino
        or denial.get('key_inode')!=key_info.st_ino or not 0<=time.time()-denial.get('observed_at',0)<=120):raise ValueError('fresh independent candidate denial required')
    return dict(pins,candidate_denial_verified=True),invocation


def exchange(path,request):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
        channel.settimeout(10);channel.connect(str(path));channel.sendall(encoded(request)+b'\n');channel.shutdown(socket.SHUT_WR)
        raw=bytearray()
        while True:
            block=channel.recv(65536)
            if not block:break
            raw.extend(block)
            if len(raw)>2_000_000:raise ValueError('bounded acceptance response required')
    return json.loads(raw)


def signature(envelope,key,request,pins):
    receipt=envelope['receipt'];binding=receipt['binding']
    if not hmac.compare_digest(envelope['signature'],hmac.new(key,encoded(receipt),hashlib.sha256).hexdigest()):raise ValueError('signature mismatch')
    for k in ('base','head','repository'):
        if binding[k]!=request[k]:raise ValueError('request binding mismatch')
    if binding['validator_source_digest']!=pins['validator_source_digest'] or binding['runtime_identity']!=pins['runtime_identity']:raise ValueError('installed identity mismatch')
    if receipt['status']!='PASS' or receipt['process_exit']!=0 or receipt['timed_out'] is not False or receipt['fixture_only'] is not False or receipt['grants_pytest_authority'] is not False:raise ValueError('actual static PASS required')


def denied(path):
    try:fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK);os.close(fd)
    except (PermissionError,FileNotFoundError):return True
    return False


def fault(kind):
    if kind=='timeout':time.sleep(5)
    elif kind=='crash':raise SystemExit(7)
    else:
        rows=[dict(id=i,status='PASS') for i in ('bounded-regular-text','no-active-markup','safe-document-path','utf8-no-control')]
        print(json.dumps(dict(results=rows+[rows[0]] if kind=='duplicate' else rows[:-1])))


def matrix(oracle,directory,pins):
    """Run real installed processes; no source edits, imports or commands from inputs."""
    repo=directory/'r';repo.mkdir()
    env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_AUTHOR_NAME':'L0 acceptance','GIT_AUTHOR_EMAIL':'acceptance@invalid','GIT_COMMITTER_NAME':'L0 acceptance','GIT_COMMITTER_EMAIL':'acceptance@invalid'}
    def git(*args):return subprocess.check_output(['/usr/bin/git','-C',str(repo),'-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*args],env=env,stderr=subprocess.DEVNULL,timeout=15).decode().strip()
    git('-c','init.templateDir=/dev/null','init','-q')
    (repo/'tests').mkdir();(repo/'tests/test_trusted.py').write_text('def test_trusted(): assert True\n')
    (repo/'docs/help').mkdir(parents=True);(repo/'docs/help/guide.md').write_text('Original guide\n')
    git('add','.');git('commit','-qm','fixed acceptance base');base=git('rev-parse','HEAD')
    config=dict(repository='acceptance/static-only',approved_base=base,authority_git_dir=str(repo/'.git'),allowed_prefixes=['docs/help/'],runtime_identity=pins['runtime_identity'])
    def candidate(name='docs/help/guide.md',text='Updated guide\n',delete=False,symlink=False):
        git('reset','--hard',base);git('clean','-fdq');p=repo/name;p.parent.mkdir(parents=True,exist_ok=True)
        if delete:p.unlink()
        elif symlink:p.symlink_to('/etc/passwd')
        else:p.write_text(text)
        git('add','.');git('commit','-qm','fixed adversarial input')
        return dict(protocol=oracle.PROTOCOL,repository=config['repository'],base=base,head=git('rev-parse','HEAD'))
    rows=[]
    def check(name,action):
        try:ok=action() is True
        except Exception:ok=False
        rows.append(dict(id=name,status='PASS' if ok else 'FAIL'))
    valid=candidate();result=oracle.evaluate(config,valid)
    check('valid-document',lambda:result['status']=='PASS')
    scenarios=[('active-markup','docs/help/guide.md','<script>alert(1)</script>'),('executable','app.py','raise SystemExit(0)'),('test-delete','tests/test_trusted.py',''),('test-rewrite','tests/test_trusted.py','assert True'),('fake-pass','PASS','PASS'),('fake-junit','results.xml','<testsuite/>'),('symlink','docs/help/link.md','')]
    for label,name,text in scenarios:
        request=candidate(name,text,delete=label=='test-delete',symlink=label=='symlink')
        try:rejected=oracle.evaluate(config,request)['status']!='PASS'
        except ValueError:rejected=True
        check(label,lambda:rejected)
    # Real timeout/crash/malformed workers through the installed evaluator's
    # process boundary. This injection exists only in this trusted harness.
    real=oracle.subprocess.run
    for kind in ('timeout','crash','duplicate','truncated'):
        def run(args,**kwargs):
            if args[-1:]!=['--worker']:return real(args,**kwargs)
            kwargs['timeout']=0.05 if kind=='timeout' else 5
            return real([sys.executable,'-I','-S',str(SELF),'--fault',kind],**kwargs)
        oracle.subprocess.run=run
        try:failed=oracle.evaluate(config,valid)['status']=='FAIL'
        finally:oracle.subprocess.run=real
        check('worker-'+kind,lambda:failed)
    altered=dict(config,runtime_identity='python@sha256:'+'0'*64)
    try:oracle.evaluate(altered,valid);rejected=False
    except ValueError:rejected=True
    check('runtime-mismatch',lambda:rejected)
    # Exercise actual installed oracle process over a private socket, not a mock.
    key=b'fixed-adversarial-harness-key-32bytes'
    cfg=directory/'config.json';cfg.write_text(json.dumps(dict(config,signing_key=str(directory/'key'),socket=str(directory/'s'))));cfg.chmod(0o600)
    (directory/'key').write_bytes(key);(directory/'key').chmod(0o600)
    process=subprocess.Popen([sys.executable,'-I','-S',str(SOURCE),str(cfg)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+5
        while not (directory/'s').exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(0.02)
        envelope=exchange(directory/'s',valid);signature(envelope,key,valid,pins)
        wrong=dict(pins,validator_source_digest='0'*64)
        try:signature(envelope,key,valid,wrong);rejected=False
        except ValueError:rejected=True
        check('source-mismatch',lambda:rejected)
        private(directory/'s',True);(directory/'s').chmod(0o666)
        try:oracle.clear_stale_socket(directory/'s');rejected=False
        except ValueError:rejected=True
        finally:(directory/'s').chmod(0o600)
        check('socket-permissions',lambda:rejected)
        (directory/'key').chmod(0o644)
        try:oracle.private_file(directory/'key');rejected=False
        except ValueError:rejected=True
        finally:(directory/'key').chmod(0o600)
        check('key-permissions',lambda:rejected)
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
    check('candidate-access-denied',lambda:pins.get('candidate_denial_verified') is True)  # identity() verified root's actual nobody probe.
    def no_network():
        if Path('/proc/net/route').read_text().splitlines()[1:]:return False
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
                s.settimeout(0.1);s.connect(('192.0.2.1',443))
        except OSError:return True
        return False
    check('network-denied',no_network)
    check('production-db-denied',lambda:denied(Path('/home/optiplex/investment/out/investment.db')))
    check('credentials-denied',lambda:all(denied(Path(p)) for p in ('/home/optiplex/.ssh','/home/optiplex/.aws','/home/optiplex/investment/.env')))
    check('docker-denied',lambda:all(denied(Path(p)) for p in ('/run/docker.sock','/var/run/docker.sock')))
    def primary():
        config=json.loads((CONFIG/'config.json').read_bytes())
        if config.get('approved_base')!=pins.get('application_sha') or config.get('repository')!=pins.get('repository') or config.get('allowed_prefixes')!=['docs/help/'] or config.get('authority_git_dir')!='/var/lib/investment-static-oracle/authority.git':return False
        request=dict(protocol=oracle.PROTOCOL,repository=pins['repository'],base=pins['application_sha'],head=pins['acceptance_head'])
        signature(exchange(RUNTIME/'oracle.sock',request),(CONFIG/'signing.key').read_bytes(),request,pins)
        return True
    check('installed-socket',primary)
    if sorted(r['id'] for r in rows)!=sorted(MATRIX):raise ValueError('incomplete acceptance inventory')
    return rows


def main():
    # A development invocation cannot create a live receipt, even on failure.
    service_context();started=time.time()
    info=OUTPUT.parent.lstat()
    if OUTPUT.parent.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('private receipt directory required')
    try:
        pins,invocation=identity()
        spec=importlib.util.spec_from_file_location('installed_l0_oracle',SOURCE);oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
        with tempfile.TemporaryDirectory(prefix='accept-',dir=RUNTIME) as directory:rows=matrix(oracle,Path(directory),pins)
        result=dict(status='PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL',application_sha=pins['application_sha'],acceptance_head=pins['acceptance_head'],validator_source_digest=pins['validator_source_digest'],
                    runtime_identity=pins['runtime_identity'],harness_source_digest=pins['harness_source_digest'],service_identity='investment-oracle',invocation=invocation,
                    created_at=started,observed_at=time.time(),scope='L0_STATIC_TEXT',fixture_only=False,generated_adversarial_inputs=True,matrix=rows,
                    grants_pytest_authority=False,grants_activation=False,grants_implementation=False)
    except Exception as error:
        result=dict(status='FAIL',reason='installed L0 acceptance did not complete',diagnostic=type(error).__name__,created_at=started,observed_at=time.time(),
                    scope='L0_STATIC_TEXT',fixture_only=False,grants_pytest_authority=False,grants_activation=False,grants_implementation=False)
    temp=OUTPUT.with_suffix('.new');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(encoded(result)+b'\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,OUTPUT);print(encoded(result).decode());return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    if sys.argv[1:]==['--candidate-probe']:candidate_probe()
    elif len(sys.argv)==3 and sys.argv[1]=='--fault' and sys.argv[2] in {'timeout','crash','duplicate','truncated'}:fault(sys.argv[2])
    elif len(sys.argv)==1:raise SystemExit(main())
    else:raise SystemExit('fixed acceptance mode required')
