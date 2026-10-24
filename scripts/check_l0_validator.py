"""Operator-only live functional probe; static PASS is never a certificate."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.static_validation import installed
from dev_agent.discovery import git


def probe(root,base,head):
    result=installed(root,base,head)
    return dict(status='PROBE_PASS',application_sha=git(root,'rev-parse','HEAD'),observed_at=time.time(),scope='L0_STATIC_TEXT',result=result,
                installation_acceptance='PENDING_FULL_HOST_MATRIX',grants_certification=False,grants_implementation=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--base',required=True);p.add_argument('--head',required=True);a=p.parse_args()
    try:result=probe(a.root,a.base,a.head)
    except Exception as error:
        print(json.dumps(dict(status='NOT READY',reason='L0 validator is unavailable or rejected the probe',diagnostic=type(error).__name__,grants_certification=False)));raise SystemExit(1)
    print(json.dumps(result,indent=2))
