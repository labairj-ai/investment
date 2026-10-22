"""Trusted container bootstrap, copied by the controller, never the candidate.

Executed using python -I before adding source paths. No host environment survives.
The entire assembled application/test tree is an OS read-only mount.
"""
import os
import runpy
import sys
import json

os.environ.clear()
os.environ.update(PATH='/usr/local/bin:/usr/bin:/bin', HOME='/tmp', TMPDIR='/tmp',
                  PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1',
                  GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/tmp/gitconfig')
with open('/tmp/gitconfig','w') as stream:
    stream.write('[safe]\n\tdirectory = /source\n[core]\n\thooksPath = /dev/null\n')
command=sys.argv[1:]
collection=bool(command and command[0]=='--collect-base')
if collection:command=command[1:]
if command[:3]==['python','-m','pytest']:
    import pytest
    # Candidate root conftest/config cannot enter mandatory runs: the controller
    # has replaced every test/config surface with the exact approved-base bytes.
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
                with open('/artifacts/inventory.json','w') as stream:json.dump(sorted(rows),stream)
        plugins=[Inventory()]
    raise SystemExit(pytest.main(command[3:]+['-p','no:cacheprovider'],plugins=plugins))
if len(command)<2 or command[0]!='python' or not command[1].startswith('scripts/check_'):
    raise SystemExit('unsupported sandbox command')
sys.path.insert(0,'/source')
sys.argv=command[1:]
runpy.run_path('/source/'+command[1],run_name='__main__')
