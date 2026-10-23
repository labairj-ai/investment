"""Ingest an existing owner-authored GitHub promotion; never issues an approval."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.promotion_github import ingest
from dev_agent.store import Store

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr',type=int,required=True)
    parser.add_argument('--ledger',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(ingest(Path(__file__).resolve().parents[1],Store(args.ledger),args.pr)))
