"""Read-only owner-controlled PR #6 handoff; never merges or deploys."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.github import GitHub
from dev_agent.store import Store
from scripts.check_owner_review import check


def handoff(store,client):
    remote=client.pr_identity(6)
    proof=check(store,client,6,remote['headRefOid'])
    if remote['baseRefName']!='main':raise ValueError('main target required')
    merged=remote.get('mergeCommit') or {}
    result=dict(repository=client.repository,pr=6,head=remote['headRefOid'],owner_gate=proof,auto_merge=False,required_human_merge=True,autonomous_implementation=False)
    if remote['state']=='OPEN':return dict(result,status='READY_FOR_HUMAN_MERGE',deployed=False)
    if remote['state']!='MERGED' or not merged.get('oid'):raise ValueError('human merge not observed')
    from dev_agent.owner_review import verify_merge_actor
    verify_merge_actor(client,6,remote['headRefOid'],merged['oid'])
    main=client.read(f'repos/{client.repository}/compare/{merged["oid"]}...main')
    if main.get('status') not in {'identical','ahead'}:raise ValueError('merge SHA not present on main')
    if proof['owner_review']['action_binding']['action']=='MERGE_ONLY':return dict(result,status='MERGED_ONLY',merge_sha=merged['oid'],deployed=False)
    return dict(result,status='MERGED_DEPLOYMENT_PENDING',merge_sha=merged['oid'],required_deploy_sha=merged['oid'],deployed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--ledger',type=Path,required=True);args=parser.parse_args()
    try:result=handoff(Store(args.ledger),GitHub('labairj-ai/investment'))
    except (ValueError,KeyError) as error:print(json.dumps(dict(status='BLOCKED',reason=str(error))));raise SystemExit(1)
    print(json.dumps(result,indent=2))
