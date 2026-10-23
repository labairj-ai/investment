"""Read-only live acceptance/promotion report; does not install, build or activate."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.store import Store
from dev_agent.promotion import report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--ledger',type=Path,required=True);a=p.parse_args()
    result=report(a.root,Store(a.ledger));print(json.dumps(result,indent=2));raise SystemExit(0 if result['recommendation']=='GO_FOR_OWNER_STAGE_REVIEW' else 1)
