"""Read-only genuine timer-run report. No run creation or activation API."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.discovery import git
from dev_agent.scheduler_health import acceptance
from dev_agent.store import Store

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True);a=p.parse_args()
    result=acceptance(Store(a.ledger),git(a.root,'rev-parse','HEAD'))
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['status']=='READY' else 1)
