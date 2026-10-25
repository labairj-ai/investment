"""Source resolution attacks; all files are synthetic and never imported."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
from ops.discovery import influence as a


@pytest.fixture
def repo(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
    git('init','-q');git('config','user.name','fixture');git('config','user.email','fixture@invalid')
    files={'dev_agent/__init__.py':'','dev_agent/cli.py':'from .scheduler import trigger\nimport json\n',
           'dev_agent/scheduler.py':'import time\n',
           'ops/discovery/upgrade.py':'from ops.discovery import pin_refresh\n',
           'ops/discovery/pin_refresh.py':'import hashlib\n',
           'ops/discovery/observer.py':"from pathlib import Path\nROOT=Path('/fixture')\nx=ROOT/'out/investment.db'\ny=ROOT/'out/buffett.db'\n",
           'scripts/fixed.py':'import sys\n','systemd/development-scout.timer':'[Timer]\n',
           'config/development_agent.json':'{}','root_trusted.py':'import math\n'}
    for name,data in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
    git('add','.');git('commit','-qm','reviewed')
    head=git('rev-parse','HEAD')
    return root,head


def add(root,name,data=b'data',mode=None):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    if mode is not None:p.chmod(mode)
    return p


def test_runtime_data_backups_and_caches_are_not_source(repo):
    root,head=repo
    for name in ['out/investment.db','out/releases/old.sqlite3','out/cache/data.json','holdings.csv.bak','dev_agent/__pycache__/cli.cpython-312.pyc','out/old-tool.py']:
        add(root,name)
    add(root,'venv/pyvenv.cfg');add(root,'venv/lib/python3.12/site-packages/runtime.pth',b'import arbitrary_site_hook')
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='PASS' and result['scanned']==8
    assert result['allowed_categories']=={'non_authoritative_cache':1,'non_authoritative_backup':1,'non_authoritative_runtime':6}
    assert 'dev_agent.cli' in result['trusted_modules']


@pytest.mark.parametrize('name,data,mode',[
    ('dev_agent/evil.py',b'raise RuntimeError',None),
    ('dev_agent/extra/__init__.py',b'',None),
    ('ops/__init__.py',b'raise RuntimeError',None),
    ('ops.py',b'raise RuntimeError',None),
    ('ops/native.cpython-312-x86_64-linux-gnu.so',b'ELF',None),
    ('scripts/tool',b'#!/bin/sh\necho unsafe',0o755),
    ('ops/tool',b'not an extension',0o755),
    ('systemd/development-scout.service.d/extra.conf',b'[Service]',None),
    ('config/development_agent.local',b'override',None),
    ('json.py',b'raise RuntimeError',None),
    ('json/__init__.py',b'raise RuntimeError',None),
    ('sitecustomize.py',b'raise RuntimeError',None),
    ('custom.pth',b'import unsafe',None),
    ('dev_agent/cli.pyc',b'sourceless bytecode',None),
    ('native.so',b'ELF',None),
    ('mystery/settings',b'data',None),
])
def test_untracked_source_and_configuration_attacks_rejected(repo,name,data,mode):
    root,head=repo;add(root,name,data,mode)
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='FAIL'
    assert any(r['path']==name for r in result['rejected_paths'])


@pytest.mark.parametrize('name',['out/source-link','venv/source-link','dev_agent/alias'])
def test_symlink_into_trusted_source_rejected(repo,name):
    root,head=repo;p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    if name.startswith('venv/'):add(root,'venv/pyvenv.cfg')
    p.symlink_to(root/'dev_agent/cli.py')
    result=a.audit(root,head)
    assert any(r['path']==name and r['reason']=='SYMLINK_TRUSTED_COLLISION' for r in result['rejected_paths'])


def test_tracked_parent_symlink_and_exact_collision_rejected(repo):
    root,head=repo
    result=a.audit(root,head,untracked=['dev_agent/cli.py'])
    assert result['rejected_paths'][0]['reason']=='TRACKED_COLLISION'
    (root/'aliased').symlink_to(root/'dev_agent',target_is_directory=True)
    result=a.audit(root,head,untracked=['aliased/cli.py'])
    assert result['rejected_paths'][0]['reason']=='TRUSTED_PARENT_RESOLUTION'


@pytest.mark.parametrize('attack',['hook','config','attributes','alternates','replace'])
def test_git_interpretation_influence_rejected_before_plumbing(repo,attack):
    root,head=repo
    if attack=='hook':add(root,'.git/hooks/pre-commit',b'#!/bin/sh\n',0o755)
    if attack=='config':
        with (root/'.git/config').open('a') as f:f.write('[filter "unsafe"]\n clean = arbitrary-command\n')
    if attack=='attributes':add(root,'.git/info/attributes',b'* filter=unsafe')
    if attack=='alternates':add(root,'.git/objects/info/alternates',b'/untrusted/objects')
    if attack=='replace':add(root,'.git/refs/replace/'+'a'*40,b'b'*40)
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='FAIL' and result['rejected_paths']
    assert result['rejected_categories']=={'git_influence':1}


def test_large_realistic_runtime_inventory_does_not_block(repo):
    root,head=repo;add(root,'.venv/pyvenv.cfg')
    for i in range(9400):add(root,f'.venv/lib/python3.12/site-packages/pkg/file_{i}.py',b'# dependency excluded from isolated launch\n')
    for i in range(30):add(root,f'out/history/{i}.json')
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='PASS' and result['scanned']==9431
    assert result['allowed_categories']=={'non_authoritative_runtime':9431}


def test_ignored_attack_in_trusted_namespace_is_still_scanned(repo):
    root,head=repo;add(root,'.git/info/exclude',b'dev_agent/evil.py\n')
    add(root,'dev_agent/evil.py')
    result=a.audit(root,head)
    assert result['visible_untracked']==0 and result['scanned']==1
    assert result['untracked_source_influence']=='FAIL'


def test_standalone_audit_requires_isolated_no_site(repo):
    root,head=repo
    script=Path(a.__file__).resolve()
    unsafe=subprocess.run([sys.executable,str(script),'--root',str(root),'--head',head],capture_output=True,text=True)
    assert unsafe.returncode!=0 and 'system Python -I -S required' in unsafe.stderr
    safe=subprocess.run([sys.executable,'-I','-S',str(script),'--root',str(root),'--head',head],capture_output=True,text=True)
    assert safe.returncode==0 and json.loads(safe.stdout)['untracked_source_influence']=='PASS'


def test_reachable_dynamic_import_requires_review(repo):
    root,head=repo
    # A new reviewed implementation introducing dynamic imports must explicitly
    # revisit the closed import graph; runtime input never chooses a module.
    (root/'dev_agent/cli.py').write_text('__import__("dynamic_name")\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','changed graph'],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    result=a.audit(root,head)
    assert 'DYNAMIC_IMPORT_REVIEW_REQUIRED' in result['rejected_categories']


@pytest.mark.parametrize('name',['dev_agent','json'])
def test_cache_marker_cannot_disguise_trusted_namespace(repo,name):
    root,head=repo
    add(root,name+'/CACHEDIR.TAG',b'Signature: 8a477f597d28d172789f06886806bc55')
    attack=name+('/evil.py' if name=='dev_agent' else '/__init__.py')
    add(root,attack,b'raise RuntimeError')
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='FAIL'
    assert any(r['path']==attack for r in result['rejected_paths'])


def test_venv_marker_cannot_inject_importable_package(repo):
    root,head=repo;add(root,'venv/pyvenv.cfg');add(root,'venv/__init__.py',b'raise RuntimeError')
    result=a.audit(root,head)
    assert {'path':'venv/__init__.py','reason':'RUNTIME_PACKAGE_INJECTION'} in result['rejected_paths']


@pytest.mark.parametrize('name',['token.json','token.csv','token.txt','token.md','token.bak'])
def test_nonimportable_data_stem_is_not_an_import_shadow(repo,name):
    root,head=repo;add(root,name)
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='PASS'
    assert not result['rejected_paths']


@pytest.mark.parametrize('name',['token.py','token.pyc','token/__init__.py','token.so'])
def test_real_import_forms_still_fail(repo,name):
    root,head=repo;add(root,name)
    assert a.audit(root,head)['untracked_source_influence']=='FAIL'


@pytest.mark.parametrize('mode',[0o644,0o755])
def test_developer_metadata_is_narrow_and_not_executable(repo,mode):
    root,head=repo;add(root,'.claude/settings.local.json',b'{"metadata":"not production input"}',mode)
    result=a.audit(root,head)
    assert (result['untracked_source_influence']=='PASS')==(mode==0o644)
    if mode==0o644:assert result['allowed_categories']=={'non_authoritative_developer_tool_config':1}
    add(root,'.claude/other.json',b'{}')
    assert a.audit(root,head)['untracked_source_influence']=='FAIL'


def test_unreachable_legacy_source_requires_tracked_discovery_contract(repo,monkeypatch):
    root,head=repo;add(root,'legacy/orchestrator.py',b'import math\n')
    assert a.audit(root,head)['untracked_source_influence']=='FAIL'
    monkeypatch.setattr(a,'tracked_discovery_contract',lambda graph:True)
    result=a.audit(root,head)
    assert result['untracked_source_influence']=='PASS'
    assert result['allowed_categories']=={'non_authoritative_legacy_source':1}
    add(root,'dev_agent/reachable.py')
    assert a.audit(root,head)['untracked_source_influence']=='FAIL'


def test_inert_backup_in_package_is_not_executable_authority(repo):
    root,head=repo;add(root,'ops/old.py.bak',b'not imported',0o755)
    assert a.audit(root,head)['allowed_categories']=={'non_authoritative_backup':1}


def test_reviewed_unit_reference_blocks_even_nonimportable_backup(repo):
    root,head=repo
    (root/'systemd/tool.service').write_text('[Service]\nExecStart=/usr/bin/python3 ops/old.py.bak\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','reviewed unit'],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    add(root,'ops/old.py.bak',b'not imported')
    result=a.audit(root,head)
    assert {'path':'ops/old.py.bak','reason':'SYSTEMD_EXECUTION'} in result['rejected_paths']


def test_runtime_directory_cannot_hide_a_reviewed_execution_target(repo):
    root,head=repo
    (root/'systemd/tool.service').write_text('[Service]\nExecStart=/usr/bin/python3 out/unsafe.py\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','reviewed runtime target'],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    add(root,'out/unsafe.py',b'print("unsafe")')
    assert {'path':'out/unsafe.py','reason':'SYSTEMD_EXECUTION'} in a.audit(root,head)['rejected_paths']


def test_developer_metadata_read_by_reviewed_code_is_not_exempt(repo):
    root,head=repo
    (root/'dev_agent/cli.py').write_text('from pathlib import Path\nvalue=Path(".claude/settings.local.json").read_text()\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','explicit metadata reader'],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    add(root,'.claude/settings.local.json',b'{}')
    assert {'path':'.claude/settings.local.json','reason':'REVIEWED_SOURCE_REFERENCE'} in a.audit(root,head)['rejected_paths']


def test_noncode_package_data_requires_no_reviewed_reader(repo,monkeypatch):
    root,head=repo;monkeypatch.setattr(a,'tracked_discovery_contract',lambda graph:True)
    add(root,'dev_agent/unrelated.json',b'{}')
    assert a.audit(root,head)['allowed_categories']=={'non_authoritative_package_data':1}
    add(root,'dev_agent/unrelated.py',b'pass')
    assert a.audit(root,head)['untracked_source_influence']=='FAIL'


@pytest.mark.parametrize("shell",["/bin/sh","/usr/bin/env bash"])
def test_dynamic_unit_execution_fails_closed(repo,shell):
    root,head=repo
    (root/'systemd/tool.service').write_text('[Service]\nWorkingDirectory='+str(root)+'\nExecStart='+shell+' -c "python3 $SCRIPT"\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','ambiguous unit'],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    assert a.audit(root,head)['rejected_categories']=={'AMBIGUOUS_UNIT_EXECUTION':1}


def test_unit_module_execution_is_not_unreachable_legacy(repo,monkeypatch):
    root,head=repo;monkeypatch.setattr(a,'tracked_discovery_contract',lambda graph:True)
    (root/'systemd/tool.service').write_text('[Service]\nExecStart=/usr/bin/python3 -m legacy_module\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@invalid','commit','-qm','module unit'],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    add(root,'legacy_module.py',b'pass')
    assert {'path':'legacy_module.py','reason':'SYSTEMD_EXECUTION'} in a.audit(root,head)['rejected_paths']
