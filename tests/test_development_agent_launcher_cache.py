"""Launcher trust attacks and stopped-recovery entry point; synthetic host only."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.discovery import influence as a, migrate as m
from test_development_agent_stopped_recovery import stopped
from test_development_agent_scout_migration import migration
from test_development_agent_observer_refresh import host

PREFIX='/var/cache/investment-discovery-reviewed-pycache'


def interpreter(monkeypatch, **changes):
    values=dict(flags=SimpleNamespace(isolated=1,no_site=1),pycache_prefix=PREFIX,
                dont_write_bytecode=True,executable='/usr/bin/python3')
    values.update(changes)
    for key,value in values.items():monkeypatch.setattr(sys,key,value)


def ancestry(monkeypatch, attack=None, final=False):
    """Model Linux root ancestry without changing any host directories."""
    real=Path
    class CachePath(type(Path())):
        def lstat(self):
            if str(self).startswith('/var') or str(self)=='/':
                mode=0o40755
                if str(self)=='/var/cache' and attack=='group':mode|=0o020
                if str(self)=='/var/cache' and attack=='world':mode|=0o002
                return SimpleNamespace(st_uid=1000 if str(self)=='/var/cache' and attack=='owner' else 0,st_mode=mode)
            return real(self).lstat()
        def stat(self, **kw):
            return self.lstat() if str(self).startswith('/var') or str(self)=='/' else real(self).stat(**kw)
        def is_symlink(self):return (str(self)=='/var/cache' and attack=='symlink') or (str(self)==PREFIX and attack=='final_symlink')
        def exists(self):
            if str(self)==PREFIX:return final
            if str(self)=='/run/investment-discovery-observer':return False
            return super().exists()
    monkeypatch.setattr(a,'Path',CachePath)


@pytest.mark.parametrize('attack',['symlink','group','world','owner','final_symlink'])
def test_cache_ancestry_rejected(monkeypatch,attack):
    interpreter(monkeypatch);ancestry(monkeypatch,attack)
    with pytest.raises(SystemExit,match='protected cache'):a.protected_cache()


@pytest.mark.parametrize('change',[
    dict(executable='/unexpected/python3'),dict(flags=SimpleNamespace(isolated=0,no_site=1)),
    dict(flags=SimpleNamespace(isolated=1,no_site=0)),dict(pycache_prefix='/wrong'),
    dict(dont_write_bytecode=False),
])
def test_cache_interpreter_rejected(monkeypatch,change):
    interpreter(monkeypatch,**change)
    with pytest.raises(SystemExit,match='fixed isolated system Python'):a.protected_cache()


def test_stopped_launcher_enters_real_migration_without_observer_runtime(stopped,monkeypatch,capsys):
    h=stopped;before=h.snapshot();config=h.CONFIG.read_bytes();names=set(h.CONFIG.parent.iterdir())
    assert not h.active and not h.user_active and not h.user_enabled and not h.system_active
    assert not list(h.STATE.iterdir()) and not h.SOCKET.exists()
    # Audit reviewed repository source for real; redirect only the synthetic host
    # transaction arguments/transport. All launcher validation runs before import.
    source=Path(__file__).resolve().parents[1]
    root=h.base/'audited-source'
    subprocess.run(['git','clone','--no-local','--quiet',str(source),str(root)],check=True)
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    audit=a.audit(root,head)
    assert audit['untracked_source_influence']=='PASS' and not audit['rejected_paths']
    run=m.migrate
    monkeypatch.setattr(m,'migrate',lambda *args,**kw:run(h.ROOT,h.head,h.old,invoke=h.invoke,**kw))
    if os.environ.get('SCOUT_ISOLATED_FIXTURE')!='1':
        interpreter(monkeypatch);ancestry(monkeypatch)
    monkeypatch.setattr(m,'isolated',a.isolated)
    monkeypatch.setattr(sys,'argv',['influence.py','--root',str(root),'--head',head,'--expected-old-head',h.old,'--migrate-scout'])
    with pytest.raises(SystemExit) as result:a.main()
    assert result.value.code==0
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='PLAN_ONLY' and output['start_mode']=='STOPPED_ROLLBACK'
    assert not output['changes_applied'] and output['accepted_runs']==0
    assert h.snapshot()==before and h.CONFIG.read_bytes()==config and set(h.CONFIG.parent.iterdir())==names
    assert h.starts==h.stops==0 and not h.user_active and not h.system_active and not list(h.STATE.iterdir())
    assert a.CACHE_PREFIX==PREFIX


def test_real_isolated_system_python_stopped_launch():
    # Linux CI exercises real /var/cache ancestry and real -I -S flags. macOS
    # runs the same portable host fixture; /var is a symlink on that platform.
    script="import sys,os; sys.path.extend("+repr([str(p) for p in sys.path if p])+ "); import pytest; raise SystemExit(pytest.main(["+repr(str(Path(__file__).resolve()))+"+'::test_stopped_launcher_enters_real_migration_without_observer_runtime','-q','--tb=short']))"
    env=dict(os.environ,SCOUT_ISOLATED_FIXTURE='1' if sys.platform=='linux' else 'portable')
    executable='/usr/bin/python3' if sys.platform=='linux' else sys.executable
    result=subprocess.run([executable,'-I','-S','-c',script],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr
