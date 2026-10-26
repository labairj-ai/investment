#!/usr/bin/python3
"""Fixed TEST EVIDENCE ONLY. No application imports, writes, ledger or acceptance."""
import json
import os
from pathlib import Path
import pwd
import re
import time
import subprocess
import sys

ROOT=Path('/home/optiplex/investment')
CONTROL=Path('/home/optiplex/.local/share/investment-development')

def denied(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK);os.close(fd);return False
    except (PermissionError,FileNotFoundError):return True


def active_record():
    env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'}
    inv=os.environ.get('INVOCATION_ID','')
    if not re.fullmatch('[a-f0-9]{32}',inv):return False
    unit='development-scout-sandbox-certification.service'
    observed=subprocess.check_output(['/usr/bin/systemctl','--system','show',unit,'--property=InvocationID'],env=env,timeout=10).decode().strip()
    if observed!='InvocationID='+inv:return False
    for name in ('ExecStartPre','ExecStart','ExecStopPost'):
        raw=subprocess.check_output(['/usr/bin/busctl','--system','--json=short','get-property','org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/development_2dscout_2dsandbox_2dcertification_2eservice','org.freedesktop.systemd1.Service',name],env=env,timeout=10)
        if len(raw)>8192:return False
        value=json.loads(raw)
        if set(value)!={'type','data'} or value['type']!='a(sasbttttuii)' or not isinstance(value['data'],list) or len(value['data'])!=1:return False
        row=value['data'][0]
        if not isinstance(row,list) or len(row)!=10:return False
        if row[7]==os.getpid():
            return row[:3]==['/usr/bin/python3',['/usr/bin/python3','-I','-S','/opt/investment-discovery-observer/sandbox_certify.py'],False] and all(type(x) is int for x in row[3:]) and row[3]>0 and 0<=time.monotonic()-row[4]/1e6<=60 and row[5:7]==[0,0] and row[8:]==[0,0]
    return False


def checks():
    credentials=[ROOT/'.env',ROOT.parent/'.ssh',ROOT.parent/'.aws',ROOT.parent/'.config/gh',ROOT.parent/'.netrc',ROOT.parent/'.git-credentials',ROOT.parent/'.gnupg',ROOT.parent/'.config/investment-development/github-read.token',CONTROL/'service.env']
    network=not Path('/proc/net/route').read_text().splitlines()[1:] and set(os.listdir('/sys/class/net'))=={'lo'} and all(line.split()[-1]=='lo' for line in Path('/proc/net/ipv6_route').read_text().splitlines())
    try:
        raw=subprocess.check_output(['/usr/bin/busctl','--system','--json=short','get-property','org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/development_2dscout_2eservice','org.freedesktop.systemd1.Service','MainPID'],timeout=10,env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'})
        value=json.loads(raw);manager=set(value)=={'type','data'} and value['type']=='u' and type(value['data']) is int and value['data']==0
    except Exception:manager=False
    return dict(network_namespace_isolated=network,repository_read_only=bool(os.statvfs(ROOT).f_flag&os.ST_RDONLY),protected_state_inaccessible=all(denied(p) for p in [ROOT/'out',ROOT/'holdings.csv']),credentials_inaccessible=all(denied(p) for p in credentials),process_uid_expected=os.getuid()==pwd.getpwnam('optiplex').pw_uid,system_manager_readable=manager,execution_record_current=active_record(),test_evidence_only=True,accepted_scout_run=False)


def main():
    try:result=checks()
    except Exception:result={k:False for k in ('network_namespace_isolated','repository_read_only','protected_state_inaccessible','credentials_inaccessible','process_uid_expected','system_manager_readable','execution_record_current')};result.update(execution_record_current=active_record(),test_evidence_only=True,accepted_scout_run=False)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 0 if all(v for k,v in result.items() if k!='accepted_scout_run') and result['accepted_scout_run'] is False else 1

if __name__=='__main__':raise SystemExit(main())
