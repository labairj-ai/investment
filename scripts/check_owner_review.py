"""Read-only exact-head owner gate for a separately trusted check publisher.

Run from reviewed controller source, never from candidate code. This script does
not publish statuses, approve, merge, deploy, or create human attestations.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.github import GitHub
from dev_agent.store import Store
from dev_agent.owner_review import require


def check(store,client,number,head):
    result=require(store,client,number)
    if result['context']['head']!=head:raise ValueError('check head differs from owner-approved PR head')
    runs=client.read(f'repos/{client.repository}/commits/{head}/check-runs?per_page=100')
    if runs.get('total_count',0)>100:raise ValueError('check inventory incomplete')
    tests=[r for r in runs.get('check_runs',[]) if r.get('name')=='test' and r.get('head_sha')==head]
    if not tests:raise ValueError('exact-head test check missing')
    latest=max(tests,key=lambda r:r['id'])
    if latest.get('status')!='completed' or latest.get('conclusion')!='success':raise ValueError('latest exact-head test CI must pass')
    return dict(status='PASS',head=head,owner_review=result['review'],ci_url=latest.get('html_url'),merge_authority='human-owner-only')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',type=Path,required=True);parser.add_argument('--repository',required=True)
    parser.add_argument('--pr',type=int,required=True);parser.add_argument('--head',required=True)
    args=parser.parse_args()
    try:result=check(Store(args.ledger),GitHub(args.repository),args.pr,args.head)
    except (ValueError,KeyError) as error:print(json.dumps(dict(status='FAIL',reason=str(error))));raise SystemExit(1)
    print(json.dumps(result,indent=2))
