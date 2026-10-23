"""Disposable deterministic canary; technical certification is never merge authority."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from .discovery import git, plan, refresh_plan
from .evidence import REQUIRED, receipt, verify
from .guard import WorkspaceGuard
from .policy import classify, protected_graph
from .providers import ReplayProvider
from .runner import Runner
from .store import Store, digest
from .worktrees import Worktrees
from .github import prepare_pr


def harness_hash(root):
    root = Path(root)
    files = [root / p for p in ("AGENTS.md", "config/development_agent.json", "docs/development-agent.md", "serve.py", "generate_dashboard.py", "scripts/check_development_agent.py", "scripts/check_agent_contract.py", "tests/test_development_agent.py", ".github/workflows/test.yml")]
    files += sorted((root / "dev_agent").glob("*.py"))
    files += sorted((root / "tests").glob("test_development_agent*.py"))
    files += [root/'tests'/n for n in ('test_continuous_improvement.py','test_deployment_agent.py','test_owner_gateway.py') if (root/'tests'/n).is_file()]
    files += [root/"scripts/backup_provenance.py", root/"backup_data.sh"]
    files += sorted((root / "scripts").glob("check_development_agent*"))
    files += sorted((root / "systemd").glob("development-*"))
    files += [root/'scripts/run_contained_ci.py',root/'scripts/check_validation_containment.py']
    files += sorted(p for p in (root/'ops/validator').glob('*') if p.is_file())
    files += sorted(p for p in (root/'ops/deployment-agent').glob('*') if p.is_file())
    files += sorted((root/'deployment_agent').glob('*.py'))
    files += sorted((root/'owner_gateway').glob('*.py'))
    files += [root/p for p in ('scripts/aggregate_release_validation.py','scripts/collect_development_signals.py','scripts/check_owner_review.py','scripts/run_supervised_cycle.py') if (root/p).is_file()]
    payload={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    # Activation state is a separately owner-reviewed control, not a new harness.
    # Without this fixed, explicit normalization, flipping the enable bit would
    # invalidate the very prospective evidence required to flip it. Every risk,
    # authority, freshness, budget, image and implementation change remains bound.
    config=json.loads((root/'config/development_agent.json').read_text())
    for key,value in {'autonomous_implementation':False,'autonomy_stage':'SHADOW','supervised_loop_enabled':False,'supervised_publish_pr':False}.items():config[key]=value
    payload['config/development_agent.json']=digest(config)
    return digest(payload)


TECHNICAL_COMPONENTS = {"workspace_isolation", "reviewer_independence", "evidence_binding", "production_mutation_denial", "financial_detection", "human_gate", "audit_lineage", "fixture_pr_handoff", "os_validation_sandbox", "github_protection", "production_snapshot", "authority_adversarial", "artifact_integrity"}


def technical_current(root, certificates, now=None):
    now = time.time() if now is None else now
    bound = harness_hash(root)
    config=json.loads((Path(root)/"config/development_agent.json").read_text())
    age=min(24,max(1,config.get('technical_certificate_max_age_hours',24)))*3600
    if not certificates: return False
    c=certificates[-1]
    return bool(c.get('version')=='harness-canary-2' and c.get('kind')=='TECHNICAL' and c.get('status')=='PASS' and c.get('harness_hash')==bound and 0<=now-c.get('created',0)<=age and TECHNICAL_COMPONENTS<=c.get('components',{}).keys() and all(c['components'][k]=='PASS' for k in TECHNICAL_COMPONENTS) and c.get('id')==digest({k:v for k,v in c.items() if k!='id'}))


def current(root, certificates, now=None, *, store=None, protections=None):
    from .operations import eligibility, policy
    import os
    config=policy(root)
    from .stage_control import report as stage_report
    return bool(store is not None and config.get('autonomous_implementation') and not config.get('emergency_stop') and os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() in {'','0','false'} and technical_current(root,certificates,now) and eligibility(root,store,now)['eligible'] and stage_report(root,store,now,protections=protections,technical=certificates)['eligible'])


def canary(root):
    """Fixture-only certification components. External/sandbox gates stay explicit."""
    components = {}
    with tempfile.TemporaryDirectory(prefix="development-canary-") as temp:
        temp = Path(temp); repo = temp / "repo"; repo.mkdir(); (repo / "docs").mkdir()
        git_run(repo, "init", "-b", "fixture")
        for key, value in [("user.email", "fixture@example.invalid"), ("user.name", "Fixture")]:
            git_run(repo, "config", key, value)
        (repo / "AGENTS.md").write_text((Path(root) / "AGENTS.md").read_text())
        (repo / "docs/note.md").write_text("Before\n")
        git_run(repo, "add", ".")
        git_run(repo, "commit", "-m", "fixture")
        store = Store(temp / "control/development-control.sqlite3"); store.migrate()
        proposal = dict(source="user", title="Improve fixture documentation", problem="Fixture instructions omit a needed detail", evidence=["docs/note.md:1"], outcome="Document the missing detail", files=["docs/note.md"], category="DOCUMENT")
        cid = store.discover(proposal)
        plan(repo, store, cid, ["The fixture documentation includes the missing detail."])
        git_run(repo, "add", ".todos")
        git_run(repo, "commit", "-m", "plan")
        context = refresh_plan(repo, store, cid)
        store.decide(cid, "approve", "supervised-fixture", context, "fixture-approval")
        manager = Worktrees(repo, temp / "trees"); record = manager.create(context["todo"], context["head"])
        work = Path(record["path"])
        components["workspace_isolation"] = "PASS" if work != repo and git(work, "branch", "--show-current").startswith("agent/") else "FAIL"
        class Validator:
            def run(self, root, name, cmd):
                return dict(name=name, command=cmd, exit_code=0, status="PASS", fixture_only=True)
        builder = ReplayProvider([dict(actions=[dict(type="write", path="docs/note.md", content="After: missing detail\n")], done=True)])
        reviewer = ReplayProvider([dict(disposition="PASS", findings=[])])
        runner = Runner(store, builder, reviewer, Validator())
        result = runner.run(cid, context, manager, record, [("focused_tests", ["fixture-check"])], certification=lambda: True, protections={"status":"PASS"}, fixture=True)
        components["reviewer_independence"] = "PASS" if result["status"] == "REVIEW_PASS" and (repo / "docs/note.md").read_text() == "Before\n" else "FAIL"
        validations = [dict(name=n, command=["fixture-check", n], exit_code=0, status="PASS", fixture_only=True, inventory=dict(total=1,passed=1,failures=[],skipped=[])) for n in sorted(REQUIRED)]
        proof = receipt(work, cid, context["todo"], context["head"], 1, validations, result["review"], result["review"]["risk"], builder.identity, {"contract":"fixture"})
        intact = verify(work, proof); (work / "docs/note.md").write_text("tampered\n")
        components["evidence_binding"] = "PASS" if intact and not verify(work, proof) else "FAIL"
        (work / "docs/note.md").write_text("After: missing detail\n")
        git_run(work, "add", "docs/note.md")
        git_run(work, "commit", "-m", "fixture reviewed change")
        proof = receipt(work, cid, context["todo"], context["head"], 1, validations, result["review"], result["review"]["risk"], builder.identity, {"contract":"fixture"})
        # Fixture-only receipts cannot enter operational PR handoff.
        components["fixture_pr_handoff"] = "PASS" if proof['status']=='PARTIAL' and not proof.get('trusted_validation') else "FAIL"
        guard = WorkspaceGuard(work, ["docs/note.md"])
        denied = 0
        for action in [dict(type="shell", path="docs/note.md", content="ssh production"), dict(type="write", path="../outside", content="bad"), dict(type="write", path=".env", content="bad"), dict(type="write", path="out/investment.db", content="bad")]:
            try: guard.apply(action)
            except ValueError: denied += 1
        components["production_mutation_denial"] = "PASS" if denied == 4 else "FAIL"
        helper = repo / "helper.py"; helper.write_text("VALUE=2\n")
        (repo / "covered_call_probe.py").write_text("from helper import VALUE\n")
        components["financial_detection"] = "PASS" if classify(["helper.py"], graphs=[protected_graph(repo)])["risk"] in {"L4","L5"} else "FAIL"
        replay = False
        try: store.decide(cid, "approve", "supervised-fixture", context, "fixture-approval")
        except ValueError: replay = True
        components["human_gate"] = "PASS" if replay else "FAIL"
        components["audit_lineage"] = "PASS" if all(any(e["kind"]==kind for e in store.get(cid)["events"]) for kind in ("PLAN","APPROVAL","ITERATION")) else "FAIL"
    # Passing the replay canary is not proof of OS confinement, GitHub settings or
    # successful supervised operation. Those are separate mandatory components.
    components.update(os_validation_sandbox="NOT_RUN", github_protection="NOT_RUN", production_snapshot="NOT_RUN", artifact_integrity="NOT_RUN")
    from .adversarial import probe
    adversarial=probe(root)
    components['authority_adversarial']=adversarial['status']
    data = dict(adversarial=adversarial, version="harness-canary-2", kind="TECHNICAL", runtime_policy_hash=digest(json.loads((Path(root)/"config/development_agent.json").read_text())), harness_hash=harness_hash(root), created=time.time(), components=components, status="PASS" if all(v == "PASS" for v in components.values()) else "PARTIAL", supervised=False, external_mutation=False)
    data["id"] = digest(data)
    return data


def certify(root, validator, github_client, snapshot, actor=None, *, provenance=None, store=None):
    """Technical checks only; actor strings never establish supervised success."""
    from .snapshot import check_snapshot
    from .runner import ContainerValidator
    if type(validator) is not ContainerValidator: raise ValueError('trusted sandbox validator required')
    if git(root,'status','--porcelain'):raise ValueError('clean approved harness commit required')
    validator.prior_base=git(root,'rev-parse','HEAD')
    validator.trusted_test_base=validator.prior_base
    validator.trusted_test_root=root
    data=canary(root)
    from .containment import probe
    confinement=probe(validator.image)
    focused=sorted('tests/'+p.name for p in (Path(root)/'tests').glob('test_development_agent*.py'))
    focused+=['tests/'+n for n in ('test_continuous_improvement.py','test_deployment_agent.py','test_owner_gateway.py') if (Path(root)/'tests'/n).is_file()]
    if not focused:raise ValueError('complete development-agent regression scope unavailable')
    sandbox=validator.run(root,'focused_tests',['python','-m','pytest',*focused,'-q'])
    protections=github_client.protections()
    with tempfile.TemporaryDirectory(prefix='development-snapshot-guard-') as workspace:
        observation=check_snapshot(snapshot,workspace,provenance,max_age_hours=json.loads((Path(root)/'config/development_agent.json').read_text()).get('snapshot_max_age_hours',24))
    data['components']['os_validation_sandbox']='PASS' if sandbox.get('status')=='PASS' and sandbox.get('exit_code')==0 and sandbox.get('inventory',{}).get('total',0)>0 and not sandbox.get('inventory',{}).get('failures') else sandbox.get('status','UNAVAILABLE')
    if confinement['status']!='PASS':data['components']['os_validation_sandbox']=confinement['status']
    data['components']['artifact_integrity']=sandbox.get('artifact_integrity',{}).get('status','UNAVAILABLE')
    data['components']['github_protection']=protections['status']
    data['components']['production_snapshot']=observation['status']
    data.update(supervised=False,evidence=dict(sandbox=sandbox,containment=confinement,github=protections,snapshot=observation))
    data['status']='PASS' if TECHNICAL_COMPONENTS<=data['components'].keys() and all(data['components'][k]=='PASS' for k in TECHNICAL_COMPONENTS) else 'PARTIAL'
    data['id']=digest({k:v for k,v in data.items() if k!='id'})
    if store is not None:
        with store.connect(True) as db:
            store._append(db,None,'TECHNICAL_CERTIFICATION',data,'technical:'+data['id'])
    return data
