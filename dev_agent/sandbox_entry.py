"""Trusted container bootstrap. Imported safely by tests; executed only with python -I."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys


def check_plugin(name, oracle, root='/source'):
    """A candidate module cannot shadow an installed or approved pytest plugin."""
    root=Path(root)
    parts=name.split('.')
    if not all(part.isidentifier() for part in parts):raise ValueError('unrecognized pytest plugin name')
    for count in range(1,len(parts)+1):
        prefix='/'.join(parts[:count])
        for relative in (prefix+'.py',prefix+'/__init__.py'):
            path=root/relative
            if path.is_file():
                if path.is_symlink() or oracle.get(relative)!=hashlib.sha256(path.read_bytes()).hexdigest():
                    raise ValueError('pytest plugin outside immutable approved test oracle')


def main():
    # No host environment, startup files or credentials survive. The entire source
    # tree is an OS read-only mount; only bounded artifacts/tmp are writable.
    os.environ.clear()
    os.environ.update(PATH='/usr/local/bin:/usr/bin:/bin',HOME='/tmp',TMPDIR='/tmp',
                      PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',
                      GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/tmp/gitconfig')
    Path('/tmp/gitconfig').write_text('[safe]\n\tdirectory = /source\n[core]\n\thooksPath = /dev/null\n')
    command=sys.argv[1:]
    collection=bool(command and command[0]=='--collect-base')
    if collection:command=command[1:]
    if command[:3]==['python','-m','pytest']:
        # Load installed pytest before exposing application import paths.
        import pytest
        from _pytest.config import PytestPluginManager,builtin_plugins
        oracle_file=Path('/authority/oracle-files.json')
        if oracle_file.exists():
            oracle=json.loads(oracle_file.read_text())
            original=PytestPluginManager.import_plugin
            def trusted_plugin(self,name,consider_entry_points=False):
                if name not in builtin_plugins:check_plugin(name,oracle)
                return original(self,name,consider_entry_points=consider_entry_points)
            PytestPluginManager.import_plugin=trusted_plugin
        sys.path[:0]=['/source/tests','/source']
        plugins=[]
        if collection:
            from _pytest.junitxml import mangle_test_address
            class Inventory:
                def pytest_collection_finish(self,session):
                    rows=[]
                    for item in session.items:
                        parts=mangle_test_address(item.nodeid)
                        rows.append('.'.join(parts[:-1])+'::'+parts[-1])
                    Path('/artifacts/inventory.json').write_text(json.dumps(sorted(rows)))
            plugins=[Inventory()]
        return pytest.main(command[3:]+['-p','no:cacheprovider'],plugins=plugins)
    if len(command)<2 or command[0]!='python' or not command[1].startswith('scripts/check_'):
        raise ValueError('unsupported sandbox command')
    sys.path.insert(0,'/source');sys.argv=command[1:]
    runpy.run_path('/source/'+command[1],run_name='__main__')
    return 0


if __name__=='__main__':raise SystemExit(main())
