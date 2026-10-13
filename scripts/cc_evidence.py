"""Covered-call evidence operator commands; promotion and certification are explicit."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from strategy_config import CC_V3_CONFIG
from covered_call_ledger import connect,migrate,promotion_evidence,transition
from covered_call_evidence import migrate_legacy
from covered_call_validation import run_validation,certify

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['migrate','validate','certify','promotion','promote','rollback'])
    parser.add_argument('--db');parser.add_argument('--run-id')
    args=parser.parse_args()
    if args.command=='migrate':
        db=connect(args.db);migrate(db)
        with db:result=migrate_legacy(db)
        db.close()
    elif args.command=='validate':result=run_validation(CC_V3_CONFIG,args.db)
    elif args.command=='certify':result=certify(args.run_id,CC_V3_CONFIG,args.db)
    elif args.command=='promotion':result=promotion_evidence(CC_V3_CONFIG,args.db)
    else:result=transition('v3' if args.command=='promote' else 'v2',CC_V3_CONFIG,args.db)
    print(json.dumps(result,indent=2))
