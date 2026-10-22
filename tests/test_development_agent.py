"""Governance integration tests use disposable repositories and dedicated stores."""
import io
import json
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dev_agent import certification, dashboard, discovery, evidence, github, outcomes, policy, scheduler
from dev_agent.guard import WorkspaceGuard
from dev_agent.providers import ReplayProvider, OllamaProvider
from dev_agent.runner import ContainerValidator, Runner, review
from dev_agent.store import Store, digest
from dev_agent.worktrees import Worktrees

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    subprocess.run(["git", "init", "-b", "fixture", str(root)], check=True, capture_output=True)
    for key, val in [("user.name", "Fixture"), ("user.email", "fixture@example.invalid")]:
        subprocess.run(["git", "-C", str(root), "config", key, val], check=True)
    (root / "AGENTS.md").write_text((ROOT / "AGENTS.md").read_text())
    (root / "docs").mkdir(); (root / "docs/note.md").write_text("Before\n")
    commit(root)
    return root


def commit(root):
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, capture_output=True)
    return discovery.git(root, "rev-parse", "HEAD")


@pytest.fixture
def store(tmp_path):
    obj = Store(tmp_path / "control/development-control.sqlite3"); obj.migrate(); return obj


def proposal(**extra):
    return dict(dict(source="user", title="Document missing instructions", problem="The instructions omit a required detail", outcome="Document the required detail", evidence=["docs/note.md:1"], files=["docs/note.md"], category="DOCUMENT", validation="focused documentation assertions"), **extra)


def approved(repo, store):
    cid = store.discover(proposal())
    discovery.plan(repo, store, cid, ["The missing detail is visible in the documentation."])
    commit(repo)
    context = discovery.refresh_plan(repo, store, cid)
    store.decide(cid, "approve", "human", context, "nonce")
    return cid, context


def test_dedicated_store_and_migration(tmp_path, store):
    with pytest.raises(ValueError): Store(tmp_path / "investment.db")
    store.migrate(); cid = store.discover(proposal()); assert store.discover(proposal()) == cid
    assert store.get(cid)["state"] == "DISCOVERED"
    with store.connect(True) as db:
        for sql in ["DELETE FROM dev_candidates", "UPDATE dev_events SET kind='erased'"]:
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)


def test_foreign_schema_not_modified(tmp_path):
    path = tmp_path / "development-control.sqlite3"
    with sqlite3.connect(path) as db: db.execute("CREATE TABLE holdings(x)")
    before = path.read_bytes()
    with pytest.raises(ValueError): Store(path).migrate()
    assert path.read_bytes() == before


@pytest.mark.parametrize("changes", [{"evidence": []}, {"source":"unknown"}, {"category":"TRADE"}, {"problem":"api_key=secretvalue"}, {"outcome":"x"*40000}, {"extra":{"api_key":"value"}}])
def test_invalid_candidates(store, changes):
    with pytest.raises(ValueError): store.discover(proposal(**changes))


def test_immutable_runs_and_idempotency(store):
    cid = store.discover(proposal())
    store.event(cid, "NOTE", {"value":1}, "once"); store.event(cid, "NOTE", {"value":1}, "once")
    with pytest.raises(ValueError): store.event(cid, "NOTE", {"value":2}, "once")
    with pytest.raises(ValueError): store.event(cid, "STATE", {"state":"APPROVED"})
    store.run_event(cid, "run", "builder", "RUNNING", {})
    store.run_event(cid, "run", "builder", "PASS", {})
    store.run_event(cid, "run", "builder", "PASS", {})
    with pytest.raises(ValueError): store.run_event(cid, "run", "builder", "FAIL", {})
    with pytest.raises(ValueError): store.transition(cid, "BUILDING")


def test_approval_staleness_replay_and_consumption(repo, store):
    cid, context = approved(repo, store)
    with pytest.raises(ValueError): store.decide(cid, "approve", "human", context, "nonce")
    with pytest.raises(ValueError): store.begin(cid, dict(context, head="a"*40), "run")
    store.begin(cid, context, "run")
    with pytest.raises(ValueError): store.begin(cid, context, "another")
    assert store.get(cid)["state"] == "BUILDING"


@pytest.mark.parametrize("decision,state", [("reject","REJECTED"),("defer","DEFERRED")])
def test_decisions(repo, store, decision, state):
    cid = store.discover(proposal()); ctx=discovery.plan(repo,store,cid,["The detail is visible in the rendered documentation."])
    store.decide(cid, decision, "human", ctx, decision)
    assert store.get(cid)["state"] == state


def test_high_risk_requires_rationale(repo, store):
    cid = store.discover(proposal(files=["trade_engine/risk.py"]))
    ctx = discovery.plan(repo,store,cid,["The deterministic risk regression fixture passes unchanged."])
    with pytest.raises(ValueError): store.decide(cid,"approve","human",ctx,"x")
    store.decide(cid,"approve","human",ctx,"x","Reviewed protected scope")


def test_plan_ids_concurrent_and_bind(repo, store):
    ids = [store.discover(proposal(problem=f"Required detail {i} is absent")) for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        contexts = list(pool.map(lambda cid: discovery.plan(repo,store,cid,["The missing detail appears in the documentation."]),ids))
    assert len({c["todo"] for c in contexts}) == 4
    with pytest.raises(ValueError): discovery.refresh_plan(repo,store,ids[0])
    commit(repo); context=discovery.refresh_plan(repo,store,ids[0]); assert context["head"] == discovery.git(repo,"rev-parse","HEAD")


def test_dependency_cycles_and_duplicates(repo):
    td=repo/".todos";td.mkdir()
    (td/"0001-one.md").write_text("- **ID:** 0001\n- **Status:** backlog\n- **Depends:** 0002\n")
    (td/"0002-two.md").write_text("- **ID:** 0002\n- **Status:** backlog\n- **Depends:** 0001\n")
    with pytest.raises(ValueError,match="cycle"): discovery.task_index(repo)
    (td/"0002-two.md").write_text("- **ID:** 0001\n- **Status:** backlog\n")
    with pytest.raises(ValueError,match="duplicate"): discovery.task_index(repo)


@pytest.mark.parametrize("path,level", [("docs/readme.md","L0"),("tests/test_x.py","L1"),("static/style.css","L2"),("scripts/helper.py","L3"),("covered_call_rec.py","L4"),("trade_engine/fill.py","L5"),("unknown.data","L5"),("AGENTS.md","L5"),(".github/workflows/test.yml","L5")])
def test_risk_levels(path,level):
    assert policy.classify([path])["risk"] == level


def test_reachability_and_whole_diff(repo):
    (repo/"covered_call_math.py").write_text("from helpers import value\n")
    (repo/"helpers.py").write_text("from common import value\n")
    (repo/"common.py").write_text("value=2\n")
    base = policy.protected_graph(repo)
    (repo/"covered_call_math.py").write_text("value=3\n")
    assert policy.classify(["common.py"],graphs=[base,policy.protected_graph(repo)])["risk"] == "L4"
    assert policy.classify(["docs/readme.md","common.py"],graphs=[base])["risk"] == "L4"
    assert policy.classify(["docs/readme.md"],diff="+ sqlite3.connect(path)")["risk"] == "L5"
    assert policy.classify(["docs/readme.md"],model=5)["risk"] == "L5"


def test_test_weakening_and_principle_changes():
    checks=policy.engineering_checks({"tests/test_x.py":("def test_x(): assert True", "# deleted"), "AGENTS.md":("old","new")})
    assert {c["id"] for c in checks} == {"test-integrity:tests/test_x.py","protected:AGENTS.md"}
    assert all(c["principle"] == "P6" for c in checks)


@pytest.mark.parametrize("name", ["../outside","/tmp/file","docs/../../file","docs/./file",".env","out/investment.db","credentials.json",".git/config","docs\\file","docs/.env"])
def test_write_guard(repo,name):
    guard=WorkspaceGuard(repo,["docs/note.md"])
    with pytest.raises(ValueError): guard.write(name,"bad")


def test_symlinks_hardlinks_and_no_shell(repo,tmp_path):
    outside=tmp_path/"outside";outside.write_text("protected")
    (repo/"docs/link").symlink_to(outside)
    guard=WorkspaceGuard(repo,["docs/link","docs/note.md","docs/hard"])
    with pytest.raises(ValueError): guard.write("docs/link","bad")
    import os
    os.link(outside,repo/"docs/hard")
    with pytest.raises(ValueError): guard.write("docs/hard","bad")
    for op in ["shell","read","network","sqlite"]:
        with pytest.raises(ValueError): guard.apply(dict(type=op,path="docs/note.md",content="bad"))
    assert outside.read_text() == "protected"
    with pytest.raises(ValueError): Store(tmp_path/"link"/"investment.db")


def test_score_deterministic_risk_separate():
    candidate=proposal(category="SIMPLIFY",dimensions={"impact":5,"reliability":5,"maintainability":5})
    high=policy.classify(["trade_engine/risk.py"])
    result=discovery.score(candidate,high)
    assert result==discovery.score(candidate,high) and result["risk"]["risk"]=="L5" and result["disposition"]=="HUMAN_REVIEW"
    assert discovery.score(proposal(evidence=[]),high)["disposition"]=="REJECT"
    with pytest.raises(ValueError): discovery.score(proposal(dimensions={"impact":99}),high)


def test_scout_read_only_dedup_diversity(repo,store):
    (repo/"example.py").write_text("# FIXME: Handle malformed metadata explicitly\n")
    commit(repo); before=evidence.source_hash(repo)
    signals=[proposal(source=s,problem="Signal "+s) for s in ["user","ci","telemetry","error","performance","accessibility","git","test"]]
    found=discovery.scout(repo,signals,cap=3)
    assert len(found["proposals"])<=3 and evidence.source_hash(repo)==before
    assert discovery.scout(repo,signals,cap=0)["proposals"]==[]
    a=store.discover(found["proposals"][0]); assert store.discover(found["proposals"][0])==a


def test_architecture_cycles_no_size_only(repo):
    (repo/"a.py").write_text("import b\n");(repo/"b.py").write_text("import a\n")
    (repo/"large.py").write_text("# intentional line\n"*1600)
    found=discovery.architecture_signals(repo)
    assert len(found)==1 and found[0]["category"]=="CONSOLIDATE"


@pytest.mark.parametrize("clock,expected",[("2026-03-08T04:59:00+00:00","2026-03-07"),("2026-03-08T07:01:00+00:00","2026-03-08"),("2026-11-01T05:30:00+00:00","2026-11-01"),("2026-11-01T06:30:00+00:00","2026-11-01")])
def test_scheduler_dst(clock,expected):
    assert scheduler.slot(datetime.fromisoformat(clock))==expected


def test_scheduled_discovery_idempotency_and_backlog(repo,store):
    now=datetime(2026,10,21,12,tzinfo=timezone.utc)
    first=scheduler.discover_daily(repo,store,now=now,signals=[proposal()])
    assert first["created"]==1
    assert scheduler.discover_daily(repo,store,now=now)["status"]=="DUPLICATE"
    assert scheduler.discover_daily(repo,store,now=datetime(2026,10,22,12,tzinfo=timezone.utc),backlog_limit=1)["status"]=="BACKLOG_FULL"


def test_worktree_isolation_recovery_and_cleanup(repo,tmp_path):
    manager=Worktrees(repo,tmp_path/"trees");base=discovery.git(repo,"rev-parse","HEAD")
    record=manager.create("0001",base);path=manager.verify(record)
    assert path!=repo and manager.recover()[0]["observed"]=="PRESENT"
    (path/"dirty").write_text("keep")
    with pytest.raises(ValueError): manager.cleanup(record)
    (path/"dirty").unlink();manager.cleanup(record)
    assert not path.exists() and manager.recover()[0]["status"]=="RETIRED"
    (repo/"dirty").write_text("keep")
    with pytest.raises(ValueError): manager.create("0002",base)


class Validator:
    def __init__(self,status="PASS"): self.status=status
    def run(self,root,name,command):return dict(name=name,command=command,status=self.status,exit_code=0 if self.status=="PASS" else 1)


def run_fixture(repo,store,tmp_path,builder,replies,**kwargs):
    cid,context=approved(repo,store);manager=Worktrees(repo,tmp_path/"trees");record=manager.create(context["todo"],context["head"])
    runner=Runner(store,ReplayProvider(builder),ReplayProvider(replies),kwargs.pop("validator",Validator()),**kwargs)
    result=runner.run(cid,context,manager,record,[("focused_tests",["fixture"])],certification=lambda:True,protections={"status":"PASS"},fixture=True)
    return result,cid,Path(record["path"])


def write_action(text):return dict(actions=[dict(type="write",path="docs/note.md",content=text)],done=True)


def finding(identity="missing",severity="MEDIUM"):
    return dict(id=identity,severity=severity,file="docs/note.md",requirement="Required detail",evidence="missing detail",principle="P3")


def test_runner_one_pass(repo,store,tmp_path):
    result,cid,path=run_fixture(repo,store,tmp_path,[write_action("After\n")],[dict(disposition="PASS",findings=[])])
    assert result["status"]=="REVIEW_PASS" and path.joinpath("docs/note.md").read_text()=="After\n"
    assert store.get(cid)["state"]=="BUILDING" # no PR/deploy success implied


def test_successful_correction(repo,store,tmp_path):
    result,_,_=run_fixture(repo,store,tmp_path,[write_action("First\n"),write_action("Corrected\n")],[dict(disposition="REQUEST_CHANGES",findings=[finding()]),dict(disposition="PASS",findings=[],resolved=[dict(id="missing",file="docs/note.md",evidence="Corrected detail now visible")])])
    assert result["status"]=="REVIEW_PASS" and result["iterations"]==2


@pytest.mark.parametrize("variant",["repeat","budget","validation","forbidden","provider","reviewer"])
def test_runner_fail_closed(repo,store,tmp_path,variant):
    builder=[write_action("After\n")]*3; reviews=[dict(disposition="REQUEST_CHANGES",findings=[finding(severity="HIGH")])]*3;kwargs={}
    if variant=="budget":kwargs["max_lines"]=1;builder=[write_action("two\nlines\n")]
    if variant=="validation":kwargs["validator"]=Validator("FAIL")
    if variant=="forbidden":builder=[dict(actions=[dict(type="shell",path="docs/note.md",content="bad")])]
    if variant=="provider":builder=[]
    if variant=="reviewer":reviews=[]
    result,cid,_=run_fixture(repo,store,tmp_path,builder,reviews,**kwargs)
    assert result["status"]=="NEEDS_HUMAN" and store.get(cid)["state"]=="NEEDS_HUMAN"


def test_runner_disabled_without_certification(repo,store,tmp_path):
    cid,context=approved(repo,store);manager=Worktrees(repo,tmp_path/"trees");record=manager.create(context["todo"],context["head"])
    runner=Runner(store,ReplayProvider([]),ReplayProvider([]),Validator())
    assert runner.run(cid,context,manager,record,[],certification=lambda:False,protections={"status":"PASS"},fixture=True)["status"]=="NEEDS_HUMAN"
    assert store.get(cid)["state"]=="APPROVED"


def test_sandbox_missing_and_command_restrictions(repo,monkeypatch):
    with pytest.raises(ValueError):ContainerValidator("image:latest")
    validator=ContainerValidator("fixture@sha256:"+"a"*64)
    monkeypatch.setattr("dev_agent.runner.shutil.which",lambda x:None)
    assert validator.run(repo,"focused_tests",["python","-m","pytest","tests/"])["status"]=="UNAVAILABLE"
    with pytest.raises(ValueError):validator.run(repo,"bad",["sh","-c","ssh production"])
    with pytest.raises(ValueError):OllamaProvider("model","https://untrusted.invalid")


def test_evidence_hashes_counts_and_tampering(repo,tmp_path):
    vals=[dict(name=n,command=["fixture",n],exit_code=0,status="PASS",inventory=dict(total=1,passed=1,failures=[],skipped=[])) for n in evidence.REQUIRED]
    data=evidence.receipt(repo,"candidate","0001",discovery.git(repo,"rev-parse","HEAD"),1,vals,{"disposition":"PASS"},{"risk":"L0"},{"provider":"fixture"},{"contract":"1"})
    assert data["status"]=="PARTIAL" and not data["trusted_validation"] and evidence.verify(repo,data)
    path=evidence.persist(tmp_path/"receipts",data);assert evidence.persist(path.parent,data)==path
    tampered=dict(data,status="FAIL");assert not evidence.verify(repo,tampered)
    (repo/"docs/note.md").write_text("tampered");assert not evidence.verify(repo,data)
    xml=tmp_path/"tests.xml";xml.write_text('<testsuites><testsuite><testcase name="ok"/><testcase name="bad"><failure/></testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuites>')
    assert evidence.junit(xml)==dict(total=3,passed=1,failures=["::bad"],skipped=["::skip"])
    partial=evidence.receipt(repo,"candidate","0001",data["base"],1,vals[:-1],{"disposition":"PASS"},{"risk":"L0"},{},{})
    assert partial["status"]=="PARTIAL"


def protection():
    return dict(required_status_checks=dict(strict=True,contexts=["test"]),required_pull_request_reviews=dict(required_approving_review_count=1,dismiss_stale_reviews=True,require_last_push_approval=True),enforce_admins=dict(enabled=True),required_conversation_resolution=dict(enabled=True),allow_force_pushes=dict(enabled=False),allow_deletions=dict(enabled=False),restrictions=dict(users=[]),agent_identity_no_bypass_verified=True)


def test_github_protection_variants():
    assert github.verify_protections(protection())["status"]=="PASS"
    for key in ["required_status_checks","required_pull_request_reviews","enforce_admins","restrictions","agent_identity_no_bypass_verified"]:
        data=protection();data.pop(key);assert github.verify_protections(data)["status"]=="FAIL"
    data=protection();data["allow_force_pushes"]["enabled"]=True;assert github.verify_protections(data)["status"]=="FAIL"


def test_dashboard_read_only_auth_and_escaping(store):
    cid=store.discover(proposal(title='<img src=x onerror="alert(1)">'))
    before=store.path.read_bytes();result=dashboard.summary(store)
    assert result["candidates"][0]["id"]==cid and store.path.read_bytes()==before
    assert "innerHTML" not in dashboard.HTML and "textContent" in dashboard.HTML
    headers={"X-Development-Agent-Token":"fixture","Origin":"https://host.test","Host":"host.test","Content-Type":"application/json"}
    assert dashboard.authorized(headers,"fixture",True)
    assert not dashboard.authorized(dict(headers,Origin="https://other.test"),"fixture",True)
    assert not dashboard.authorized(headers,"",True)
    assert not dashboard.authorized(headers,"other",True)


def test_effectiveness_insufficient_and_no_governance():
    assert outcomes.effectiveness(proposal(),{"status":"INSUFFICIENT_DATA"},{})["score"] is None
    dims=dict(acceptance=1,recurrence=0,review_findings=0,health=1,user_acceptance=1,maintenance=1)
    good=outcomes.effectiveness(proposal(category="SIMPLIFY"),{"status":"HEALTHY"},dims)
    assert good["score"]==100 and good["governance_effect"]=="NONE"
    assert outcomes.effectiveness(proposal(),{"status":"ROLLED_BACK"},dims)["score"]==0
    assert outcomes.aggregate([good])["status"]=="INSUFFICIENT_DATA"
    assert outcomes.aggregate([good]*5)["governance_effect"]=="NONE"


def test_certification_canary_and_disabled_default():
    data=certification.canary(ROOT)
    assert data["status"]=="PARTIAL" and data["external_mutation"] is False
    assert all(data["components"][key]=="PASS" for key in ["workspace_isolation","evidence_binding","human_gate","audit_lineage","financial_detection"])
    assert not certification.current(ROOT,[dict(data,status="PASS",supervised=True)])


def test_renumbered_tasks_unique():
    records=discovery.task_index(ROOT)
    assert all(f"{n:04d}" in records for n in range(760,785))
    for n in range(760,785):
        path=records[f"{n:04d}"]["path"]
        assert f"Renumbered from coding-agent task {n-15:04d} to {n:04d}" in path.read_text()


def test_whole_diff_includes_removed_dependency(repo):
    (repo/"covered_call_probe.py").write_text("from support import RATE\n")
    (repo/"support.py").write_text("RATE=1\n")
    base=commit(repo)
    (repo/"covered_call_probe.py").write_text("# import removed\n")
    (repo/"support.py").write_text("RATE=2\n")
    assert policy.whole_diff(repo,base)["risk"] in {"L4","L5"}


def test_raise_risk_inherits_financial_gates():
    raised=policy.human_override(policy.classify(["docs/note.md"]),"L5","human","Indirect account effects")
    assert "financial_human_review" in raised["gates"]
    with pytest.raises(ValueError):policy.human_override(raised,"L0","human","Want fewer gates")


def test_weaker_threshold_requires_human():
    checks=policy.engineering_checks({"tests/test_policy.py":("def test_limit():\n assert limit < 5\n","def test_limit():\n assert limit < 5000\n")})
    assert checks[0]["id"].startswith("test-semantics:")


def test_provider_wall_time_and_no_late_actions(repo):
    from dev_agent.providers import respond_bounded
    class Slow:
        def respond(self,context): time.sleep(.1);return write_action("Late")
    before=evidence.source_hash(repo)
    with pytest.raises(ValueError,match="timeout"):respond_bounded(Slow(),{},.01)
    time.sleep(.12)
    assert evidence.source_hash(repo)==before


def test_crash_recovery_preserves_lineage(repo,store):
    cid,ctx=approved(repo,store);store.begin(cid,ctx,"interrupted")
    store.run_event(cid,"interrupted","builder","RUNNING",dict(base=ctx["head"]))
    store.event(cid,"ITERATION",dict(iteration=1),"interrupted:1")
    runner=Runner(store,ReplayProvider([]),ReplayProvider([]),Validator())
    assert runner.recover(cid)["recovered"]==["interrupted"]
    assert runner.recover(cid)["recovered"]==[]
    assert store.get(cid)["state"]=="NEEDS_HUMAN"
    assert len([e for e in store.get(cid)["events"] if e["kind"]=="ITERATION"])==1


def test_worktree_partial_creation_recovered(repo,tmp_path):
    manager=Worktrees(repo,tmp_path/"trees");record=manager.create("0001",discovery.git(repo,"rev-parse","HEAD"))
    path=manager.directory/(record["run"]+".json")
    path.write_text(json.dumps(dict(record,status="CREATING")))
    assert manager.recover()[0]["status"]=="READY"
    assert manager.verify(record).exists()
    with pytest.raises(ValueError):manager.verify(dict(record,run="../../bad"))


def test_dashboard_http_decision_and_replay(repo,store,monkeypatch):
    cid=store.discover(proposal());ctx=discovery.plan(repo,store,cid,["The missing detail appears in the help document."])
    monkeypatch.setattr(dashboard,"configured_store",lambda:store);monkeypatch.setenv("DEV_AGENT_API_TOKEN","fixture")
    class Handler:
        def __init__(self,body,origin="https://host.test"):
            raw=json.dumps(body).encode();self.rfile=io.BytesIO(raw);self.wfile=io.BytesIO();self.code=None
            self.headers={"X-Development-Agent-Token":"fixture","Content-Type":"application/json","Host":"host.test","Origin":origin,"Content-Length":str(len(raw))}
        def send_response(self,code):self.code=code
        def send_header(self,*args):pass
        def end_headers(self):pass
    body=dict(candidate=cid,decision="approve",context=ctx,nonce="http-once")
    denied=Handler(body,"https://attacker.test");dashboard.handle(denied,"/api/development-agent/decision",True);assert denied.code==403
    good=Handler(body);dashboard.handle(good,"/api/development-agent/decision",True);assert good.code==200
    replay=Handler(body);dashboard.handle(replay,"/api/development-agent/decision",True);assert replay.code==409
    before=store.path.read_bytes();read=Handler({});dashboard.handle(read,"/api/development-agent");assert read.code==200 and store.path.read_bytes()==before


def test_pr_handoff_duplicate_draft_and_failure(tmp_path,monkeypatch):
    commands=[]
    def fake(command,**kwargs):
        commands.append(command)
        if command[1:3]==["pr","list"]:return subprocess.CompletedProcess(command,0,stdout=json.dumps([dict(number=42,url="https://github.com/o/r/pull/42",isDraft=False)]))
        if "--body-file" in command:assert "human merge" in Path(command[command.index("--body-file")+1]).read_text()
        return subprocess.CompletedProcess(command,0,stdout="")
    monkeypatch.setattr(github.subprocess,"run",fake)
    item=github.GitHub("o/r").handoff("agent/0001/x","title","human merge approval",True)
    assert item["number"]==42 and any("--undo" in c for c in commands)
    assert not any("merge" in c for c in commands)
    def fail(*args,**kwargs):raise subprocess.CalledProcessError(1,args[0])
    monkeypatch.setattr(github.subprocess,"run",fail)
    with pytest.raises(subprocess.CalledProcessError):github.GitHub("o/r").handoff("agent/0001/x","title","body",True)


def test_deployment_observations_and_mutation_safety(repo,store):
    cid,ctx=approved(repo,store)
    store.event(cid,"PR",dict(result=dict(url="https://github.com/o/r/pull/1"),head=ctx["head"]))
    store.event(cid,"MERGE",dict(merge_sha="a"*40,pr="https://github.com/o/r/pull/1",actor="operator"))
    now=time.time();record=dict(merge_sha="a"*40,deployed_sha="a"*40,environment="fixture",deployed_at=now-100,observed_at=now,window_seconds=60,metrics=dict(errors=0),evidence=["fixture-canary"],status="HEALTHY")
    assert outcomes.observe(store,cid,record)["status"]=="HEALTHY"
    assert outcomes.observe(store,cid,dict(record,deployed_sha="b"*40))["status"]=="INSUFFICIENT_DATA"
    assert outcomes.observe(store,cid,dict(record,window_seconds=1000))["status"]=="INSUFFICIENT_DATA"
    with pytest.raises(ValueError):outcomes.observe(store,cid,dict(record,status="ROLLED_BACK"))
    with pytest.raises(ValueError):outcomes.observe(store,cid,dict(record,metrics=dict(portfolio_return=10)))
    assert outcomes.observe(store,cid,dict(record,status="ROLLED_BACK",rollback_cause="regression",rollback_target="b"*40))["status"]=="ROLLED_BACK"


def test_pr_ready_binds_committed_candidate_and_recovers(repo,store,tmp_path):
    result,cid,path=run_fixture(repo,store,tmp_path,[write_action("After\n")],[dict(disposition="PASS",findings=[])])
    commit(path)
    context=[e["payload"]["context"] for e in store.get(cid)["events"] if e["kind"]=="PLAN"][-1]
    vals=[dict(name=n,command=["fixture",n],exit_code=0,status="PASS",inventory=dict(total=1,passed=1,failures=[],skipped=[])) for n in evidence.REQUIRED]
    # Operator-supplied results cannot authorize PR handoff, even if all claim PASS.
    proof=evidence.receipt(path,cid,context["todo"],context["head"],1,vals,result["review"],result["review"]["risk"],{}, {})
    from test_development_agent_hardening import make_trusted_proof
    proof=make_trusted_proof(path,store,cid)
    class Client:
        repository='o/r'
        def protections(self):return dict(status="PASS")
        def pr_identity(self,number):
            return dict(number=number,headRefName=discovery.git(path,'branch','--show-current'),headRefOid=proof['head'],baseRefName='main',headRepository={'nameWithOwner':'o/r'},isDraft=False)
        def handoff(self,branch,title,body,draft):
            assert branch.startswith("agent/") and cid in body and "human merge" in body and not draft
            return dict(url="https://github.com/o/r/pull/1",number=1)
    assert github.prepare_pr(path,store,cid,proof,Client())["number"]==1
    assert store.get(cid)["state"]=="PR_OPEN"
    assert github.prepare_pr(path,store,cid,proof,Client())["number"]==1
    assert len([e for e in store.get(cid)["events"] if e["kind"]=="PR"])==1
    with pytest.raises(ValueError):github.prepare_pr(path,store,"different",proof,Client())
    (path/"docs/note.md").write_text("Changed after evidence")
    with pytest.raises(ValueError):github.prepare_pr(path,store,cid,proof,Client())


def test_snapshot_is_read_only(tmp_path):
    from dev_agent.snapshot import check_snapshot
    snapshot=tmp_path/"snapshot.db"
    with sqlite3.connect(snapshot) as db:
        db.execute("CREATE TABLE holdings(ticker,shares)");db.execute("INSERT INTO holdings VALUES ('TEST',100)")
    workspace=tmp_path/"workspace";workspace.mkdir();before=snapshot.read_bytes()
    from dev_agent.snapshot import REQUIRED_TABLES, sign_backup
    with sqlite3.connect(snapshot) as db:
        for name in REQUIRED_TABLES: db.execute('CREATE TABLE '+name+'(x)')
    before=snapshot.read_bytes()
    key=b'fixture-backup-key-never-production-1234'
    provenance=sign_backup(snapshot,key=key,source_sha='a'*40)
    assert check_snapshot(snapshot,workspace,provenance,key=key)["status"]=="PASS"
    assert snapshot.read_bytes()==before


def test_principles_mutation_detected(tmp_path):
    import importlib.util
    import shutil
    spec=importlib.util.spec_from_file_location("development_guard",ROOT/"scripts/check_development_agent.py")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert mod.check(ROOT)["status"]=="PASS"
    (tmp_path/"config").mkdir();(tmp_path/"docs").mkdir();(tmp_path/"dev_agent").mkdir()
    shutil.copy2(ROOT/"config/development_agent.json",tmp_path/"config/development_agent.json")
    text=(ROOT/"docs/development-agent.md").read_text().replace("P6: Fail closed", "P6: Skip checks")
    (tmp_path/"docs/development-agent.md").write_text(text)
    assert "principle missing: P6" in mod.check(tmp_path)["findings"]


def test_human_review_cannot_grant_merge_or_override_stale_scope(repo,store):
    cid,ctx=approved(repo,store)
    store.review_decision(cid,"REVIEW_OVERRIDE","accept","human",ctx,"review-once","Reviewed the evidence")
    event=store.get(cid)["events"][-1]["payload"]
    assert event["grants_merge"] is False and event["grants_deployment"] is False
    with pytest.raises(ValueError):store.review_decision(cid,"REVIEW_OVERRIDE","accept","human",ctx,"review-once","Replay")
    with pytest.raises(ValueError):store.review_decision(cid,"PR_DISPOSITION","accept","human",dict(ctx,head="b"*40),"fresh","Stale SHA")
    assert store.get(cid)["state"]=="APPROVED"


def test_reviewer_cannot_drop_prior_findings(repo,store,tmp_path):
    result,_,_=run_fixture(repo,store,tmp_path,[write_action("First\n"),write_action("Second\n")],[dict(disposition="REQUEST_CHANGES",findings=[finding()]),dict(disposition="PASS",findings=[])])
    assert result["status"]=="NEEDS_HUMAN"


def test_discovery_retry_budget_and_duplicate_suppression(repo,store,monkeypatch):
    now=datetime(2026,10,21,12,tzinfo=timezone.utc)
    def fail(*args,**kwargs): raise RuntimeError("source unavailable")
    monkeypatch.setattr(scheduler,"scout",fail)
    assert scheduler.discover_daily(repo,store,now=now)["status"]=="FAILED"
    assert scheduler.discover_daily(repo,store,now=now)["status"]=="FAILED"
    assert scheduler.discover_daily(repo,store,now=now)["status"]=="NEEDS_HUMAN"


def test_principle_code_removal_detected(monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location("development_guard_mutation",ROOT/"scripts/check_development_agent.py")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    monkeypatch.setattr(mod,"PRINCIPLES",{k:v for k,v in policy.PRINCIPLES.items() if k!="P6"})
    assert "reviewed principle contract changed" in mod.check(ROOT)["findings"]


def test_todo_reservations_span_worktrees(repo,store,tmp_path):
    manager=Worktrees(repo,tmp_path/"trees");base=discovery.git(repo,"rev-parse","HEAD")
    first=manager.create("0001",base);second=manager.create("0002",base)
    ids=[store.discover(proposal(problem="Distinct missing detail "+str(i))) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        contexts=list(pool.map(lambda pair:discovery.plan(pair[0],store,pair[1],["The required detail is present in the instructions."]),[(Path(first["path"]),ids[0]),(Path(second["path"]),ids[1])]))
    assert len({ctx["todo"] for ctx in contexts})==2


def test_large_function_scan_does_not_apply_metadata_payload_limit(repo):
    (repo/"large_function.py").write_text("def build():\n"+"".join(f"    value_{i} = {i}\n" for i in range(1500)))
    assert discovery.architecture_signals(repo)==[]


def test_supervised_certification_cannot_promote_missing_external_gates(tmp_path):
    snapshot=tmp_path/"snapshot.db"
    with sqlite3.connect(snapshot) as db:db.execute("CREATE TABLE holdings(x)")
    class Client:
        def protections(self):return dict(status="FAIL",failures=["unprotected main"])
    with pytest.raises(ValueError,match='trusted sandbox'):
        certification.certify(ROOT,Validator("UNAVAILABLE"),Client(),snapshot,"supervising-human")
    # A free-form human name or a fake validator cannot establish supervision.
    assert not certification.current(ROOT,[])


def test_committed_worktree_cleanup_preserves_branch_and_evidence(repo,tmp_path):
    manager=Worktrees(repo,tmp_path/"trees");record=manager.create("0001",discovery.git(repo,"rev-parse","HEAD"))
    path=Path(record["path"]);(path/"docs/note.md").write_text("Completed change")
    head=commit(path)
    with pytest.raises(ValueError):manager.verify(record) # cannot reuse stale base for a new run
    manager.cleanup(record)
    assert discovery.git(repo,"rev-parse",record["branch"])==head
    retired=manager.recover()[0]
    assert retired["status"]=="RETIRED" and retired["final_head"]==head and retired["observed"]=="ABSENT"


def test_candidate_closure_requires_observed_outcome(repo,store):
    cid,ctx=approved(repo,store)
    with pytest.raises(ValueError):store.review_decision(cid,"OUTCOME_ACCEPTANCE","accept","human",ctx,"early","No observation yet")
    # Fixture explicitly seeds the specialized PR/deploy history; a general
    # transition call still cannot manufacture deployment/closure.
    with store.connect(True) as db:
        store._append(db,cid,"STATE",{"state":"DEPLOYED"},"fixture-deploy")
        store._append(db,cid,"DEPLOYMENT",{"status":"HEALTHY","deployed_sha":ctx["head"]},"fixture-observed")
    store.review_decision(cid,"OUTCOME_ACCEPTANCE","accept","human",ctx,"accepted","Verified observation window and accepted outcome")
    assert store.get(cid)["state"]=="CLOSED"
