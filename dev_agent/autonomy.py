"""Bounded progression of a frozen human-approved L0–L2 candidate to PR only.

Discovery/plan proposals remain subject to explicit policy/scope approval. This
entry point cannot approve candidates, merge, deploy or modify GitHub protections.
"""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

from pathlib import Path
import subprocess

from .certification import current
from .discovery import git
from .evidence import seal
from .github import prepare_pr
from .operations import authorize_start,certificates
from .policy import whole_diff
from .runner import Runner
from .validation import validate_and_review
from .worktrees import Worktrees


def progress(root,store,cid,builder,reviewer,validator,client):
    candidate=store.get(cid)
    context=[e['payload']['context'] for e in candidate['events'] if e['kind']=='PLAN'][-1]
    record=[e['payload'] for e in candidate['events'] if e['kind']=='WORKTREE'][-1]
    manager=Worktrees(root,store.path.parent/'worktrees')
    work=manager.verify(record)
    def ready():
        return current(root,certificates(store),store=store) and client.protections().get('status')=='PASS'
    authorize_start(root,store,cid,'AUTONOMOUS',certificates(store),client.protections())
    runner=Runner(store,builder,reviewer,validator)
    result=runner.run(cid,context,manager,record,[('focused_tests',['python','-m','pytest',*[e['payload'] for e in candidate['events'] if e['kind']=='PLAN'][-1]['focused_tests'],'-q'])],certification=ready,protections=client.protections(),mode='AUTONOMOUS')
    if result['status']!='REVIEW_PASS': return result
    try:
        if not ready():raise ValueError('autonomy disabled or certification/protection changed')
        if int(whole_diff(work,context['head'])['risk'][1:])>2:raise ValueError('risk exceeds L2; human reauthorization required')
        git_run(work,'add','--',*candidate['files'])
        git_run(work,'commit','-m',f"[agent] TODO {context['todo']}: {candidate['title']}")
        store.event(cid,'GIT_INTENT',dict(operation='stage-and-commit',files=candidate['files'],head=git(work,'rev-parse','HEAD'),hooks_disabled=True,ambient_config_disabled=True))
        review=validate_and_review(work,store,cid,validator,reviewer)
        if review['disposition']!='PASS':raise ValueError('mandatory validation/review incomplete')
        proof=seal(work,store,cid)
        if proof['status']!='PASS' or not ready():raise ValueError('fresh mandatory evidence and current authority required')
        client.publish(work,record['branch'],proof['head'],store=store,cid=cid)
        pr=prepare_pr(work,store,cid,proof,client)
        return dict(status='PR_OPEN',candidate=cid,head=proof['head'],pr=pr,mode='AUTONOMOUS',grants_merge=False,grants_deployment=False)
    except Exception as exc:
        if store.get(cid)['state']=='BUILDING':store.transition(cid,'NEEDS_HUMAN',dict(reason=str(exc)[:200]))
        return dict(status='NEEDS_HUMAN',reason=type(exc).__name__)
