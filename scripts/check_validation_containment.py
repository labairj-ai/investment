"""Operator check; missing runtime exits nonzero and never grants certification."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.containment import probe
p=argparse.ArgumentParser();p.add_argument('--image',required=True);args=p.parse_args()
result=probe(args.image);print(json.dumps(result,indent=2));raise SystemExit(0 if result['status']=='PASS' else 1)
