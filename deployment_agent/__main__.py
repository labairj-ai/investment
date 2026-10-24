"""Operator-installed entry point. The coding agent never invokes this service."""
import argparse
import json
import os
from pathlib import Path
import stat
import time
from dev_agent.github import GitHub
from dev_agent.store import Store
from dev_agent.result_collector import write_final
from .admission import authorize
from .executor import Executor
from .service import deploy,recover,exit_code


def configuration():
    path=Path('/etc/investment-deploy/config.json');info=path.lstat()
    if path.is_symlink() or info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:raise ValueError('root-owned non-writable deployment configuration required')
    cfg=json.loads(path.read_text())
    required={'repository','root','receipts','ledger','origin','emergency_stop'}
    if set(cfg)!=required or cfg['origin']!=f'https://github.com/{cfg["repository"]}.git' or type(cfg['emergency_stop']) is not bool:raise ValueError('fixed deployment configuration schema/origin required')
    return cfg


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--authorization-id',type=int);p.add_argument('--recover',action='store_true');a=p.parse_args(argv)
    executor=None
    try:
        cfg=configuration();executor=Executor(cfg['root'],cfg['receipts'],cfg['ledger'])
        if a.recover:result=recover(executor,cfg['origin'])
        else:
            if not a.authorization_id or a.authorization_id<=0:raise ValueError('original exact-head owner Go object required')
            store=Store(Path(cfg['receipts'])/'authority'/'development-control.sqlite3');store.migrate();client=GitHub(cfg['repository'])
            def admit():
                current=configuration()
                if current!=cfg:raise ValueError('deployment operator configuration changed during transaction')
                stopped=current['emergency_stop'] or os.environ.get('INVESTMENT_DEPLOY_KILL_SWITCH','').lower() not in {'','0','false'}
                return authorize(store,client,a.authorization_id,emergency_stop=stopped,mirror_owner=True)
            result=deploy(executor,admit(),origin=cfg['origin'],admit_again=admit)
    except Exception as error:
        result=dict(status='FAILED_PRECHECK',authorization_id=a.authorization_id,failure=type(error).__name__,created=time.time())
        if executor is not None:
            try:write_final(executor.receipts,'deploy-'+str(a.authorization_id) if a.authorization_id else 'rejected-'+str(time.time_ns()),result)
            except (OSError,ValueError):result['receipt_unavailable']=True
        else:result['receipt_unavailable']=True
    print(json.dumps(result,indent=2))
    return exit_code(result,recovery=a.recover)


if __name__=='__main__':raise SystemExit(main())
