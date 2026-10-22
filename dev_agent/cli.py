"""Operator CLI. Discovery never invokes implementation or deployment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .certification import canary, current, certify
from .dashboard import configured_store
from .discovery import plan, refresh_plan
from .evidence import persist, verify, receipt
from .github import GitHub, prepare_pr
from .providers import OllamaProvider
from .runner import ContainerValidator, Runner
from .scheduler import discover_daily
from .worktrees import Worktrees
from .outcomes import observe, effectiveness
from .snapshot import check_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "list", "show", "scout", "plan", "bind-plan", "decide", "worktree", "build", "recover", "seal", "observe", "effectiveness", "snapshot", "verify-receipt", "pr", "protections", "canary", "certify"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--decision", choices=["approve", "reject", "defer"])
    parser.add_argument("--rationale", default="")
    parser.add_argument("--nonce")
    parser.add_argument("--model")
    parser.add_argument("--review-model")
    parser.add_argument("--image")
    parser.add_argument("--repository", default="labairj-ai/investment")
    args = parser.parse_args(argv)
    store = configured_store(); root = args.root.resolve()
    data = json.loads(args.input.read_text()) if args.input else {}
    if args.command == "init": store.migrate(); result = dict(status="INITIALIZED")
    elif args.command == "list": result = store.list()
    elif args.command == "show": result = store.get(args.candidate)
    elif args.command == "scout": result = discover_daily(root, store, signals=data.get("signals", []))
    elif args.command == "plan": result = plan(root, store, args.candidate, data["criteria"], data.get("dependencies", []))
    elif args.command == "bind-plan": result = refresh_plan(root, store, args.candidate)
    elif args.command == "decide":
        if not args.decision or not args.nonce: parser.error("explicit decision and nonce required")
        store.decide(args.candidate, args.decision, os.environ.get("USER", "operator"), data, args.nonce, args.rationale); result = dict(status="RECORDED")
    elif args.command == "worktree":
        context = [e["payload"]["context"] for e in store.get(args.candidate)["events"] if e["kind"] == "PLAN"][-1]
        result = Worktrees(root, store.path.parent / "worktrees").create(context["todo"], context["head"])
        store.event(args.candidate, "WORKTREE", result)
    elif args.command == "protections": result = GitHub(args.repository).protections()
    elif args.command == "verify-receipt": result = dict(valid=verify(root, data))
    elif args.command == "snapshot": result = check_snapshot(data["snapshot"], root)
    elif args.command == "observe": result = observe(store, args.candidate, data)
    elif args.command == "effectiveness":
        result = effectiveness(store.get(args.candidate), data["observation"], data["dimensions"])
        store.event(args.candidate, "EFFECTIVENESS", result)
    elif args.command == "recover":
        result = Runner(store, OllamaProvider("unused"), OllamaProvider("unused"), ContainerValidator("unused@sha256:"+"0"*64)).recover(args.candidate)
    elif args.command == "seal":
        candidate = store.get(args.candidate)
        iteration = [e["payload"] for e in candidate["events"] if e["kind"] == "ITERATION"][-1]
        from .evidence import source_hash
        if iteration["source_hash"] != source_hash(root): raise ValueError("source changed since independent review")
        context = [e["payload"]["context"] for e in candidate["events"] if e["kind"] == "PLAN"][-1]
        result = receipt(root, args.candidate, context["todo"], context["head"], iteration["iteration"], data["validations"], iteration["review"], iteration["review"]["risk"], data["provider"], data["contracts"])
        path = persist(store.path.parent / "receipts", result)
        store.event(args.candidate, "RECEIPT", dict(path=str(path), receipt=result))
    elif args.command == "pr": result = prepare_pr(root, store, args.candidate, data, GitHub(args.repository))
    elif args.command == "canary":
        result = canary(root); persist(store.path.parent / "certificates", result)
    elif args.command == "certify":
        if not args.image or not args.input: parser.error("digest-pinned sandbox image and explicit snapshot/actor input required")
        result = certify(root, ContainerValidator(args.image), GitHub(args.repository), data["snapshot"], data["actor"])
        persist(store.path.parent / "certificates", result)
    elif args.command == "build":
        if not all((args.model, args.review_model, args.image)): parser.error("builder/reviewer model and digest-pinned image required")
        candidate = store.get(args.candidate)
        context = [e["payload"]["context"] for e in candidate["events"] if e["kind"] == "PLAN"][-1]
        record = [e["payload"] for e in candidate["events"] if e["kind"] == "WORKTREE"][-1]
        certificates = [json.loads(p.read_text()) for p in (store.path.parent / "certificates").glob("*.json")]
        runner = Runner(store, OllamaProvider(args.model), OllamaProvider(args.review_model), ContainerValidator(args.image))
        result = runner.run(args.candidate, context, Worktrees(root, store.path.parent / "worktrees"), record, [("focused_tests", ["python", "-m", "pytest", "tests/", "-q"])], certification=lambda: current(root, certificates), protections=GitHub(args.repository).protections())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
