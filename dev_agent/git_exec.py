"""0808: process-local Git authority; no hooks, signing or ambient helpers."""
from __future__ import annotations

import os
import subprocess


OPTIONS = {
    'core.hooksPath': '/dev/null', 'core.fsmonitor': 'false',
    'core.attributesFile': '/dev/null', 'core.pager': 'cat',
    'core.alternateRefsCommand': '', 'pack.packObjectsHook': '',
    'init.templateDir': '/dev/null',
    'commit.gpgsign': 'false', 'tag.gpgsign': 'false',
    'credential.helper': '', 'core.gitProxy': '',
    'core.sshCommand': '/usr/bin/ssh -F /dev/null -oBatchMode=yes',
    'protocol.allow': 'never', 'protocol.ssh.allow': 'always',
    'protocol.https.allow': 'always', 'protocol.ext.allow': 'never',
    'protocol.file.allow': 'never', 'diff.external': '',
    'user.name': 'Development Agent', 'user.email': 'development-agent@example.invalid',
}


def environment():
    env = {k: os.environ[k] for k in ('HOME', 'SSH_AUTH_SOCK', 'TMPDIR', 'LANG') if k in os.environ}
    env.update(PATH=os.defpath, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_ATTR_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0', GIT_PAGER='cat')
    return env


def run(root, *args, timeout=30, text=True, check=True):
    """Only trusted orchestration supplies arguments. Output never contains env values."""
    # Reject caller overrides and executable local clean/smudge filters. Normal
    # human Git configuration remains untouched outside this process.
    if any(a == '-c' or a.startswith('--config-env') for a in args):
        raise ValueError('Git configuration overrides denied')
    prefix = ['/usr/bin/git', '-C', str(root)]
    prefix += ['-c', 'safe.directory='+str(root)]
    for key, value in OPTIONS.items(): prefix += ['-c', key + '=' + value]
    config = subprocess.run(prefix + ['config', '--local', '--get-regexp', r'^filter\..*\.(clean|smudge|process)$'],
                            env=environment(), capture_output=True, timeout=timeout)
    if config.returncode == 0 and config.stdout.strip():
        raise ValueError('executable repository Git filters denied')
    if config.returncode not in (0, 1) and (not args or args[0] != 'init'):
        raise ValueError('repository Git configuration unavailable')
    return subprocess.run(prefix + list(args), env=environment(), check=check,
                          capture_output=True, text=text, timeout=timeout)


def output(root, *args, **kwargs):
    return run(root, *args, **kwargs).stdout


def intent(*args):
    """Audit allowlisted intent rather than URLs, credentials or arbitrary output."""
    return {'operation': args[0], 'hooks_disabled': True, 'ambient_config_disabled': True}
