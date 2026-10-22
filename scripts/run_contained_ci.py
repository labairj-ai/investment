"""0804: trusted orchestration only; candidate Python never executes on the runner."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.runner import ContainerValidator
from dev_agent.validation import manifest
from dev_agent.git_exec import output
from dev_agent.evidence import junit
from dev_agent.test_oracle import files,tree_hash
from dev_agent.containment import probe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','base','head','image','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    if not all(re.fullmatch(r'[a-f0-9]{40}',s) for s in (args.base,args.head)):
        raise ValueError('exact GitHub event SHAs required')
    root=Path(args.root).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if output(root,'rev-parse','HEAD').strip()!=args.head:raise ValueError('event head differs from candidate')
    containment=probe(args.image)
    if containment['status']!='PASS':raise ValueError('OS containment '+containment['status'])
    validator=ContainerValidator(args.image,timeout=1800);validator.prior_base=args.base
    oracle_hash=tree_hash(files(root,args.base));records=[]
    for name,command in manifest(['tests/test_agent_contract.py'],args.base):
        result=validator.run(root,name,command);records.append(result)
    # Only one approved, bounded, parsed artifact crosses the execution boundary.
    if validator._full_junit is None:raise ValueError('mandatory JUnit unavailable')
    destination=out/'test-results.xml';destination.write_bytes(validator._full_junit)
    inventory=junit(destination)
    report=dict(head=args.head,base=args.base,image=args.image,trusted_test_tree_hash=oracle_hash,containment=containment,
                inventory=inventory,gates=records,status='PASS' if all(r['status']=='PASS' and r['exit_code']==0 for r in records) else 'FAIL')
    # Candidate tests execute in a fresh sandbox and cannot overwrite mandatory XML.
    supplemental=validator.run(root,'supplemental_tests',['python','-m','pytest','tests/','-v','--tb=short'])
    report['supplemental_status']=supplemental.get('status')
    if supplemental.get('status')!='PASS' or supplemental.get('exit_code')!=0:
        report['status']='FAIL'
    (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'supplemental.json').write_text(json.dumps(supplemental,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],head=args.head,total=inventory['total'])))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
