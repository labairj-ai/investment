"""Real isolated Git/event fixtures for CLI assertions under CI flags."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_checker(args, baseline_file, manifests_dir=None, ci_env=False):
    env = os.environ.copy()
    if ci_env:
        env['GITHUB_ACTIONS'] = 'true'
    command = [sys.executable, str(ROOT/'scripts/check_cc_contract.py'), '--json']
    if baseline_file:
        command += ['--baseline-file', str(baseline_file)]
    if manifests_dir:
        command += ['--manifests-dir', str(manifests_dir)]
    if env.get('GITHUB_ACTIONS') == 'true' or env.get('CI') == 'true':
        # Never remove CI flags or substitute offline authority in CI. Each
        # fixture has a genuine local prior Git commit and a push event payload.
        repo = baseline_file.parent / ('cli-'+baseline_file.stem)
        repo.mkdir(exist_ok=True)
        (repo/'scripts').mkdir(exist_ok=True)
        for name in ('covered_call_change_control.py', 'scripts/check_cc_contract.py'):
            shutil.copyfile(ROOT/name, repo/name)
        for source in ROOT.glob('*.py'):
            target=repo/source.name
            if not target.exists():
                target.symlink_to(source)
        if not (repo/'config').exists():
            (repo/'config').symlink_to(ROOT/'config', target_is_directory=True)
        if baseline_file.exists():
            shutil.copyfile(baseline_file, repo/'.cc_contract_baseline.json')
        subprocess.run(['git','init'],cwd=repo,check=True,capture_output=True)
        subprocess.run(['git','add','.'],cwd=repo,check=True,capture_output=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.com',
                        'commit','--allow-empty','-m','trusted fixture state'],cwd=repo,check=True,capture_output=True)
        sha=subprocess.run(['git','rev-parse','HEAD'],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
        event=repo/'event.json';event.write_text(json.dumps({'before':sha}))
        env.update(GITHUB_EVENT_PATH=str(event),GITHUB_EVENT_NAME='push')
        command[1]=str(repo/'scripts/check_cc_contract.py')
        cwd=repo
    else:
        if baseline_file:
            command += ['--trusted-prior-file', str(baseline_file)]
        cwd=ROOT
    return subprocess.run(command+args,cwd=cwd,env=env,capture_output=True,text=True)


def next_model_version(steps=1):
    """A future test release relative to the actual runtime, never a fixed baseline."""
    from covered_call_v3 import VERSION
    major, minor = VERSION.removeprefix('cc-v').split('.')
    return f'cc-v{major}.{int(minor) + steps}'


def next_simulator_contract_version(steps=1):
    """Future fixture version relative to the approved runtime contract."""
    from covered_call_virtual import SIMULATOR_CONTRACT_VERSION
    prefix,number=SIMULATOR_CONTRACT_VERSION.rsplit('-',1)
    return f'{prefix}-{int(number)+steps}'
