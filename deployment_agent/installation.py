"""Read-only deployment-role preflight. No permissions are granted or repaired."""
from pathlib import Path
import os
import pwd
import stat
from dev_agent.github import GitHub


def permission_findings(root,*,writable=None,readable=None):
    writable=writable or (lambda p:os.access(p,os.W_OK,effective_ids=True))
    readable=readable or (lambda p:os.access(p,os.R_OK,effective_ids=True))
    root=Path(root);findings=[]
    protected=[root/'holdings.csv',root/'out',root/'out/investment.db',root/'out/buffett.db']
    for path in protected:
        if path.is_symlink():findings.append('protected state must not be a symlink')
        if path.exists() and writable(path):findings.append('deployment identity can write protected investment state')
    # Parent write permits replacement even when an existing file is read-only.
    if writable(root):findings.append('deployment identity can replace protected state through the application directory')
    for path in [root/'.env',root.parent/'.ssh',root.parent/'.aws',root.parent/'.config/gh',root.parent/'.local/share/investment-development/service.env']:
        if path.exists() and readable(path):findings.append('deployment identity can access owner or application credentials')
    return list(dict.fromkeys(findings))


def preflight(config,*,client=None):
    findings=[]
    account=pwd.getpwuid(os.getuid())
    if account.pw_name!='investment-deploy' or os.geteuid()==0:findings.append('dedicated deployment identity is unavailable')
    if account.pw_name=='investment-deploy' and len(set(os.getgrouplist(account.pw_name,account.pw_gid)))!=1:findings.append('deployment identity has unexpected supplementary privileges')
    root=Path(config['root']);findings+=permission_findings(root)
    controller=Path(__file__).resolve().parents[1]
    if controller==root or root in controller.parents or os.access(controller,os.W_OK,effective_ids=True):findings.append('installed controller must be protected outside application source')
    if config.get('emergency_stop') is not False:findings.append('deployment safety stop is active')
    try:
        repo=(client or GitHub(config['repository'])).read('repos/'+config['repository']);p=repo.get('permissions',{})
        if repo.get('full_name')!=config['repository'] or p.get('pull') is not True or any(p.get(k) is not False for k in ('push','admin','maintain')):
            findings.append('read-only GitHub deployment identity is not verified')
    except Exception:findings.append('GitHub deployment authorization is unavailable')
    # Do not suggest broad ACLs, owner tokens or sudo as a way to turn this green.
    return dict(status='NOT READY' if findings else 'READY',reason=findings[0] if findings else 'deployment role boundaries verified',blockers=findings,
                grants_deployment=False,source_checkout_acceptance='fixed checkout privilege must be accepted separately')
