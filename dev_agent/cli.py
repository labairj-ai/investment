"""Operator CLI. Discovery never invokes implementation or deployment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .certification import canary, current, certify
from .dashboard import configured_store
from .discovery import plan, refresh_plan
from .evidence import persist, verify, seal
from .github import GitHub, prepare_pr
from .providers import OllamaProvider
from .runner import ContainerValidator, Runner
from .scheduler import discover_daily
from .worktrees import Worktrees
from .outcomes import observe, effectiveness
from .snapshot import check_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["owner-context", "owner-review", "owner-state", "init", "list", "show", "scout", "plan", "bind-plan", "decide", "worktree", "build", "recover", "seal", "validate", "pilot-success", "review-decision", "sync-merge", "autonomous-cycle", "readiness", "observe", "effectiveness", "snapshot", "verify-receipt", "pr", "protections", "canary", "certify"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--decision", choices=["approve", "reject", "defer"])
    parser.add_argument("--rationale", default="")
    parser.add_argument("--nonce")
    parser.add_argument("--risk",choices=["L0","L1","L2","L3","L4","L5"],default="L5")
    parser.add_argument("--model")
    parser.add_argument("--review-model")
    parser.add_argument("--image")
    parser.add_argument("--mode", choices=["SUPERVISED","AUTONOMOUS"], default="SUPERVISED")
    parser.add_argument("--repository", default="labairj-ai/investment")
    args = parser.parse_args(argv)
    store = configured_store(); root = args.root.resolve()
    data = json.loads(args.input.read_text()) if args.input else {}
    if args.command in {'owner-context','owner-review','owner-state'}:
        from . import owner_review
        client=GitHub(args.repository)
        if args.command=='owner-context': result=owner_review.context(client,data['pr'],risk=args.risk)
        elif args.command=='owner-state': result=owner_review.state(store,client,data['pr'])
        else:
            human=owner_review.owner_identity()
            # Deliberate terminal confirmation is separate from JSON and authorship.
            expected=data['context']; challenge=f"{data['decision']} {args.repository}#{expected['pr']} {expected['head']}"
            if input('Review complete? Type '+challenge+'\n')!=challenge: raise ValueError('explicit owner confirmation required')
            result=owner_review.attest(store,client,expected,data['decision'],args.nonce,args.rationale,human=human,financial_ack=data.get('financial_ack'),execution_ack=data.get('execution_ack'))
    elif args.command == "init": store.migrate(); result = dict(status="INITIALIZED")
    elif args.command == "list": result = store.list()
    elif args.command == "show": result = store.get(args.candidate)
    elif args.command == "scout": result = discover_daily(root, store, signals=data.get("signals", []))
    elif args.command == "plan": result = plan(root, store, args.candidate, data["criteria"], data.get("dependencies", []), mode=args.mode, focused_tests=data.get("focused_tests"))
    elif args.command == "bind-plan": result = refresh_plan(root, store, args.candidate)
    elif args.command == "decide":
        if not args.decision or not args.nonce: parser.error("explicit decision and nonce required")
        from .identity import cli_identity
        human=cli_identity()
        store.decide(args.candidate, args.decision, human.actor, data, args.nonce, args.rationale, identity=human); result = dict(status="RECORDED")
    elif args.command == "worktree":
        context = [e["payload"]["context"] for e in store.get(args.candidate)["events"] if e["kind"] == "PLAN"][-1]
        result = Worktrees(root, store.path.parent / "worktrees").create(context["todo"], context["head"])
        store.event(args.candidate, "WORKTREE", result)
    elif args.command == "protections": result = GitHub(args.repository).protections()
    elif args.command == "verify-receipt": result = dict(valid=verify(root, data))
    elif args.command == "snapshot":
        config=json.loads((root/'config/development_agent.json').read_text())
        result = check_snapshot(data["snapshot"], root, data.get("provenance"),max_age_hours=config.get('snapshot_max_age_hours',24))
    elif args.command == "observe": result = observe(store, args.candidate, data)
    elif args.command == "effectiveness":
        result = effectiveness(store.get(args.candidate), data["observation"], data["dimensions"])
        store.event(args.candidate, "EFFECTIVENESS", result)
    elif args.command == "recover":
        result = Runner(store, OllamaProvider("unused"), OllamaProvider("unused"), ContainerValidator("unused@sha256:"+"0"*64)).recover(args.candidate)
    elif args.command == "seal":
        if data: raise ValueError('seal accepts no operator-supplied validation/provider claims')
        result=seal(root,store,args.candidate)
    elif args.command == 'readiness':
        from .readiness import readiness
        result=readiness(root,store)
    elif args.command == 'sync-merge':
        from .github import record_merge
        result=record_merge(store,args.candidate,GitHub(args.repository))
    elif args.command == 'review-decision':
        from .identity import cli_identity
        from .github import recheck_pr
        human=cli_identity()
        if data['stage']=='PR_DISPOSITION' and recheck_pr(store,args.candidate,GitHub(args.repository))['status']!='PASS': raise ValueError('remote PR head changed')
        store.review_decision(args.candidate,data['stage'],data['decision'],human.actor,data['context'],args.nonce,args.rationale,identity=human)
        result=dict(status='RECORDED')
    elif args.command == 'pilot-success':
        from .operations import record_success
        from .identity import cli_identity
        result=record_success(root,store,args.candidate,GitHub(args.repository),human=cli_identity())
    elif args.command == 'validate':
        if not args.image or not args.review_model: parser.error('digest-pinned image and independent review model required')
        from .validation import validate_and_review
        result=validate_and_review(root,store,args.candidate,ContainerValidator(args.image,timeout=1800),OllamaProvider(args.review_model))
    elif args.command == 'autonomous-cycle':
        if not all((args.model,args.review_model,args.image)):parser.error('builder/reviewer and digest-pinned image required')
        from .autonomy import progress
        result=progress(root,store,args.candidate,OllamaProvider(args.model),OllamaProvider(args.review_model),ContainerValidator(args.image,timeout=1800),GitHub(args.repository))
    elif args.command == "pr": result = prepare_pr(root, store, args.candidate, data, GitHub(args.repository))
    elif args.command == "canary":
        result = canary(root); persist(store.path.parent / "certificates", result)
    elif args.command == "certify":
        if not args.image or not args.input: parser.error("digest-pinned sandbox image and authenticated snapshot provenance required")
        result = certify(root, ContainerValidator(args.image), GitHub(args.repository), data["snapshot"], provenance=data.get("provenance"), store=store)
        persist(store.path.parent / "certificates", result)
    elif args.command == "build":
        if not all((args.model, args.review_model, args.image)): parser.error("builder/reviewer model and digest-pinned image required")
        candidate = store.get(args.candidate)
        context = [e["payload"]["context"] for e in candidate["events"] if e["kind"] == "PLAN"][-1]
        record = [e["payload"] for e in candidate["events"] if e["kind"] == "WORKTREE"][-1]
        from .operations import certificates as load_certificates, authorize_start
        from .certification import technical_current
        from .identity import cli_identity
        certificates=load_certificates(store)
        protections=GitHub(args.repository).protections()
        human=cli_identity() if args.mode=='SUPERVISED' else None
        Worktrees(root,store.path.parent/'worktrees').verify(record)
        authorize_start(root,store,args.candidate,args.mode,certificates,protections,human=human)
        runner = Runner(store, OllamaProvider(args.model), OllamaProvider(args.review_model), ContainerValidator(args.image))
        result = runner.run(args.candidate, context, Worktrees(root, store.path.parent / "worktrees"), record, [("focused_tests", ["python", "-m", "pytest", "tests/", "-q"])], certification=lambda: technical_current(root, load_certificates(store)) if args.mode=='SUPERVISED' else current(root,load_certificates(store),store=store) and GitHub(args.repository).protections().get('status')=='PASS', protections=protections, mode=args.mode)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
