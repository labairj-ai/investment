"""Real OS containment probes. No Docker means UNAVAILABLE, never fixture PASS."""
from __future__ import annotations
import tempfile
import shutil
import subprocess
from pathlib import Path

from .runner import ContainerValidator
from .git_exec import run, output
from .evidence import source_hash

PROBES=r'''
import os,socket
from pathlib import Path
import pytest

def test_network_denied():
    with pytest.raises(OSError):socket.create_connection(('1.1.1.1',443),timeout=1)
    with pytest.raises(OSError):socket.create_connection(('api.github.com',443),timeout=1)

def test_no_host_credentials_or_interfaces():
    assert not any(k in os.environ for k in ('GITHUB_TOKEN','GH_TOKEN','ACTIONS_RUNTIME_TOKEN','AWS_SECRET_ACCESS_KEY'))
    assert not Path('/var/run/docker.sock').exists()
    assert not Path('/home/optiplex/investment/out/investment.db').exists()
    assert not Path('/root/.ssh').exists()
    assert not Path('/source/.env').exists()

def test_non_root_capabilities_and_read_only_oracle():
    assert os.geteuid()!=0
    status=Path('/proc/self/status').read_text()
    assert next(line.split()[1] for line in status.splitlines() if line.startswith('CapEff:'))=='0000000000000000'
    for name in ('/source/app.py','/source/tests/test_containment.py','/source/tests/conftest.py'):
        with pytest.raises(OSError):Path(name).write_text('compromised')
'''


def probe(image):
    if not shutil.which('docker'):return dict(status='UNAVAILABLE',reason='sandbox runtime unavailable',fixture_only=False)
    with tempfile.TemporaryDirectory(prefix='containment-') as temp:
        root=Path(temp);(root/'tests').mkdir();(root/'scripts').mkdir()
        (root/'app.py').write_text('VALUE=1\n')
        (root/'tests/test_containment.py').write_text(PROBES)
        for name in ('check_release_baseline','check_cc_contract','check_agent_contract','check_todo_status','check_development_agent'):
            (root/f'scripts/{name}.py').write_text('raise SystemExit(0)\n')
        run(root,'init','-b','containment');run(root,'add','.');run(root,'commit','-m','trusted containment probes')
        base=output(root,'rev-parse','HEAD').strip();before=source_hash(root)
        validator=ContainerValidator(image,timeout=120);validator.prior_base=base
        result=validator.run(root,'full_suite',['python','-m','pytest','tests/','-q'])
        if result.get('status')!='PASS':return dict(status=result['status'],confinement=result,fixture_only=False)
        first_unchanged=source_hash(root)==before
        (root/'tests/test_timeout.py').write_text('import time\ndef test_timeout(): time.sleep(30)\n')
        run(root,'add','.');run(root,'commit','-m','timeout cleanup probe')
        validator=ContainerValidator(image,timeout=1);validator.prior_base=output(root,'rev-parse','HEAD').strip()
        timeout_before=source_hash(root)
        timeout=validator.run(root,'full_suite',['python','-m','pytest','tests/test_timeout.py','-q'])
        # Source was intentionally extended before the timeout test. The guard
        # verifies identity across both real runs, independent of test claims.
        immutable=first_unchanged and source_hash(root)==timeout_before
        remaining=subprocess.run(['docker','ps','-a','--filter','name='+validator.last_container,'--format','{{.Names}}'],capture_output=True,text=True,check=True,timeout=15).stdout.strip()
        return dict(status='PASS' if immutable and not remaining and timeout.get('reason')=='timeout' else 'FAIL',
                    confinement=result,timeout=timeout,source_unchanged=immutable,cleanup_verified=not remaining,fixture_only=False)
