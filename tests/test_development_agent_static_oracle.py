"""Bounded L0 oracle attacks: all executable candidates rejected before execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'ops/validator/static_oracle.py'
spec=importlib.util.spec_from_file_location('static_oracle',SOURCE)
oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)


@pytest.fixture
def repo(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
    git('init','-q');git('config','user.name','fixture');git('config','user.email','fixture@example.invalid')
    (root/'tests').mkdir();(root/'tests/test_trusted.py').write_text('def test_trusted(): assert True\n')
    (root/'docs/help').mkdir(parents=True);(root/'docs/help/guide.md').write_text('Original guide\n')
    git('add','.');git('commit','-qm','approved base');base=git('rev-parse','HEAD')
    config=dict(repository='owner/repo',approved_base=base,authority_git_dir=str(root/'.git'),allowed_prefixes=['docs/help/'],
                runtime_identity='python@sha256:'+hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest())
    def commit(name='docs/help/guide.md',content='Updated guide\n'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        git('add','.');git('commit','-qm','candidate')
        return dict(protocol=oracle.PROTOCOL,repository='owner/repo',base=base,head=git('rev-parse','HEAD'))
    return root,config,git,commit


def test_genuine_static_pass_bound_to_observed_authority(repo):
    root,config,git,commit=repo;request=commit();result=oracle.evaluate(config,request)
    assert result['status']=='PASS' and result['process_exit']==0 and not result['timed_out']
    assert result['grants_pytest_authority'] is False
    assert result['binding']['head']==request['head']
    assert result['binding']['trusted_inventory_digest']==oracle.digest(oracle.INVENTORY)
    assert result['binding']['validator_source_digest']==hashlib.sha256(SOURCE.read_bytes()).hexdigest()


@pytest.mark.parametrize('name,content',[
    ('results.xml','<testsuite><testcase name="fake"/></testsuite>'),
    ('PASS','PASS'),('tests/test_trusted.py',''),('tests/results.xml','replacement'),
    ('tests/conftest.py','import pytest; pytest.main=lambda: 0'),
    ('conftest.py','pytest_plugins=["evil"]'),('sitecustomize.py','import os; os._exit(0)'),
    ('pytest.py','raise SystemExit(0)'),('tests/test_exit.py','import os; os._exit(0)'),
    ('tests/test_timeout.py','while True: pass'),('tests/test_crash.py','raise RuntimeError()'),
    ('tests/inventory.json','[]'),('tests/test_duplicates.py','def test_x(): pass\ndef test_x(): pass'),
    ('tests/test_network.py','import urllib.request; urllib.request.urlopen("https://example.com")'),
    ('tests/test_credentials.py','open("/home/optiplex/.ssh/id_ed25519").read()'),
    ('tests/test_db.py','open("/home/optiplex/investment/out/investment.db").read()'),
    ('docs/help/active.html','<script>alert(1)</script>'),
])
def test_candidate_code_and_forged_artifacts_rejected(repo,name,content):
    root,config,git,commit=repo;request=commit(name,content)
    with pytest.raises(ValueError):oracle.evaluate(config,request)


def test_trusted_test_deletion_rejected(repo):
    root,config,git,commit=repo;(root/'tests/test_trusted.py').unlink();request=commit()
    with pytest.raises(ValueError):oracle.evaluate(config,request)


def test_symlink_substitution_rejected(repo):
    root,config,git,commit=repo
    (root/'docs/help/link.md').symlink_to('/etc/passwd');request=commit()
    with pytest.raises(ValueError):oracle.evaluate(config,request)


def test_fake_pass_in_document_cannot_bypass_static_checks(repo):
    root,config,git,commit=repo;request=commit(content='PASS\n<script>forge()</script>')
    assert oracle.evaluate(config,request)['status']=='FAIL'


@pytest.mark.parametrize('failure',['timeout','crash','truncated','duplicate'])
def test_independently_observed_worker_failure_closed(repo,monkeypatch,failure):
    root,config,git,commit=repo;request=commit();real=subprocess.run
    def run(args,**kw):
        if len(args)>1 and args[1]=='-I':
            if failure=='timeout':raise subprocess.TimeoutExpired(args,1)
            if failure=='crash':return subprocess.CompletedProcess(args,7,b'{}')
            rows=[dict(id=i,status='PASS') for i in oracle.INVENTORY]
            rows=rows[:-1] if failure=='truncated' else rows+[rows[0]]
            return subprocess.CompletedProcess(args,0,json.dumps(dict(results=rows)).encode())
        return real(args,**kw)
    monkeypatch.setattr(subprocess,'run',run)
    result=oracle.evaluate(config,request)
    assert result['status']=='FAIL'
    assert result['timed_out']==(failure=='timeout')


@pytest.mark.parametrize('field,value',[('repository','other/repo'),('base','0'*40),('head','HEAD'),('protocol','isolated-oracle-1')])
def test_wrong_request_binding_denied(repo,field,value):
    root,config,git,commit=repo;request=commit();request[field]=value
    with pytest.raises(ValueError):oracle.evaluate(config,request)


def test_runtime_identity_drift_denied(repo):
    root,config,git,commit=repo;request=commit();config['runtime_identity']='python@sha256:'+'0'*64
    with pytest.raises(ValueError):oracle.evaluate(config,request)


def test_duplicate_json_rejected():
    with pytest.raises(ValueError):oracle.loads('{"head":"a","head":"b"}')


def test_static_signature_and_cross_binding(repo):
    from dev_agent.static_validation import verify
    import hmac
    root,config,git,commit=repo;request=commit();receipt=oracle.evaluate(config,request);key=b'fixture-only-signing-material-32-bytes'
    def sign(value):return dict(receipt=value,signature=hmac.new(key,oracle.canonical(value),hashlib.sha256).hexdigest())
    kwargs=dict(key=key,runtime_identity=config['runtime_identity'],validator_source_digest=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    result=verify(sign(receipt),request,**kwargs)
    assert result['status']=='PASS' and not result['grants_pytest_authority'] and not result['grants_activation']
    for field,value in [('fixture_only',True),('process_exit',1),('process_exit',False),('timed_out',True),('grants_pytest_authority',True),('expected',[])]:
        altered=copy.deepcopy(receipt);altered[field]=value
        with pytest.raises(ValueError):verify(sign(altered),request,**kwargs)
    for field,value in [('repository','other/repo'),('base','0'*40),('head','0'*40),('trusted_inventory_digest','0'*64),('command_class','L1'),('runtime_identity','different')]:
        altered=copy.deepcopy(receipt);altered['binding'][field]=value
        with pytest.raises(ValueError):verify(sign(altered),request,**kwargs)
    forged=sign(receipt);forged['signature']='0'*64
    with pytest.raises(ValueError):verify(forged,request,**kwargs)
