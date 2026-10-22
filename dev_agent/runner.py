"""Bounded builder/reviewer orchestration with no arbitrary host execution."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .discovery import git
from .evidence import source_hash, junit
from .guard import WorkspaceGuard
from .policy import PRINCIPLES, classify, engineering_checks, protected_graph
from .store import bounded, digest
from .providers import respond_bounded


class ContainerValidator:
    """Validation executes only in a disposable networkless Linux container.

    The image must be preinstalled by an operator and pinned by digest. No pulls,
    host shell, sockets, credentials or writable host source mounts are provided.
    """
    def __init__(self, image, timeout=120):
        if not re.fullmatch(r"[a-zA-Z0-9_./:-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("operator-provisioned digest-pinned image required")
        self.image, self.timeout = image, min(1800, max(1, timeout))
        self._full_junit = None

    def run(self, root, name, command, *, _base_collection=False):
        test_command = command[:3] == ["python", "-m", "pytest"]
        scripts = {"release_baseline": "scripts/check_release_baseline.py", "cc_contract": "scripts/check_cc_contract.py", "agent_contract": "scripts/check_agent_contract.py", "todo_consistency": "scripts/check_todo_status.py", "development_governance": "scripts/check_development_agent.py"}
        script_command = len(command) >= 2 and command[:2] == ["python", scripts.get(name)]
        if not command or not (test_command or script_command) or any(not re.fullmatch(r"[A-Za-z0-9_./:=+-]+", x) for x in command):
            raise ValueError("only structured canonical validation supported")
        if script_command:
            suffix = command[2:]
            if name == 'release_baseline' and suffix != ['test-results.xml']: raise ValueError('release command')
            if name == 'cc_contract' and (len(suffix)!=2 or suffix[0]!='--trusted-prior-file' or suffix[1]!='/authority/prior-cc-baseline.json'): raise ValueError('CC authority command')
            if name not in {'release_baseline','cc_contract'} and suffix: raise ValueError('script arguments denied')
        if test_command and any(x.startswith(('--junitxml','--override-ini','-o','--confcutdir','--ignore')) for x in command[3:]):
            raise ValueError('validation inventory/gate overrides denied')
        if name == 'full_suite': self._full_junit = None
        if not shutil.which("docker"):
            return dict(name=name, command=command, exit_code=None, status="UNAVAILABLE", reason="sandbox runtime unavailable")
        root = Path(root)
        test_root=Path(getattr(self,'trusted_test_root',root))
        test_base=getattr(self,'trusted_test_base',None) or getattr(self,'prior_base',None)
        if test_command and name!='supplemental_tests' and not _base_collection:
            from .test_oracle import files
            trusted_paths=files(test_root,test_base)
            paths=[arg for arg in command[3:] if arg.startswith('tests/') and arg!='tests/']
            if any(arg.split('::')[0] not in trusted_paths for arg in paths):
                command=command[:3]+['tests/']+[arg for arg in command[3:] if arg.startswith('-')]
        expected=None
        if test_command and name!='supplemental_tests' and not _base_collection:
            key=(str(test_root),test_base,tuple(command))
            cache=getattr(self,'_oracle_inventories',{})
            if key not in cache:
                collection=self.run(root,'regression_inventory',command+['--collect-only'],_base_collection=True)
                if collection.get('status')!='PASS':return dict(name=name,status='UNAVAILABLE',exit_code=None,reason='trusted base inventory unavailable',image=self.image)
                cache[key]=collection['test_ids'];self._oracle_inventories=cache
            expected=cache[key]
        # Build a separate source copy. Container writes never touch source or host.
        with tempfile.TemporaryDirectory(prefix="dev-validation-") as temp:
            snapshot = Path(temp) / "source"; snapshot.mkdir()
            artifacts = Path(temp) / "artifacts"; artifacts.mkdir(); artifacts.chmod(0o777)
            guard = WorkspaceGuard(root, [])
            for rel in git(root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines():
                try: path = guard.resolve(rel)
                except ValueError: continue
                if not path.is_file(): continue
                if path.stat().st_size > 2_000_000: raise ValueError("source copy incomplete: oversized file")
                target = snapshot / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
            if _base_collection:
                from .test_oracle import application_files
                shutil.rmtree(snapshot);snapshot.mkdir()
                for rel,data in application_files(test_root,test_base).items():
                    target=snapshot/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            # Mandatory tests/configuration come only from the exact approved base.
            from .test_oracle import materialize, files, CONFIG
            authority=Path(temp)/'authority';authority.mkdir()
            trusted_hash=None
            if name != 'supplemental_tests':
                prior=test_base
                if not prior: raise ValueError('approved prior base required')
                trusted=Path(temp)/'trusted';trusted.mkdir()
                trusted_hash=materialize(test_root,prior,trusted)
                (authority/'oracle-files.json').write_text(json.dumps({p:hashlib.sha256(data).hexdigest() for p,data in files(test_root,prior).items()}))
                if (snapshot/'tests').exists(): shutil.rmtree(snapshot/'tests')
                for path in list(snapshot.rglob('*')):
                    if path.is_file() and path.name in CONFIG: path.unlink()
                for rel,data in files(test_root,prior).items():
                    target=snapshot/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                # Trusted release orchestration also comes from the approved base.
                for script in scripts.values():
                    try: data=git_output(test_root,'show',prior+':'+script,text=False)
                    except subprocess.CalledProcessError: raise ValueError('trusted release gate unavailable') from None
                    target=snapshot/script;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            if name == 'release_baseline':
                if self._full_junit is None:
                    return dict(name=name, command=command, exit_code=None, status='NOT_RUN', reason='full-suite JUnit unavailable', image=self.image)
                (snapshot/'test-results.xml').write_bytes(self._full_junit)
            if name=='cc_contract':
                (authority/'prior-cc-baseline.json').write_bytes(git_output(root,'show',self.prior_base+':.cc_contract_baseline.json',text=False))
            # Create fresh Git metadata; no host history, hooks or credentials enter.
            git_run(snapshot,'init','-b','validation')
            git_run(snapshot,'add','.')
            git_run(snapshot,'commit','-m','isolated validation source')
            bootstrap=Path(__file__).with_name('sandbox_entry.py').read_bytes()
            (authority/'entry.py').write_bytes(bootstrap)
            container = "dev-validation-" + uuid.uuid4().hex
            self.last_container=container
            uid=os.getuid() if os.getuid()!=0 else 65534
            gid=os.getgid() if os.getuid()!=0 else 65534
            args = ["docker", "run", "--pull=never", "--rm", "--name", container, "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=128", "--memory=1g", "--cpus=1", f"--user={uid}:{gid}", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--mount", f"type=bind,src={snapshot},dst=/source,readonly", "--mount", f"type=bind,src={artifacts},dst=/artifacts", "--mount", f"type=bind,src={authority},dst=/authority,readonly", "--workdir=/source", self.image,
                    "python", "-I", "/authority/entry.py", *(['--collect-base'] if _base_collection else []), *command, *(["--junitxml=/artifacts/results.xml"] if test_command else [])]
            try:
                # Discard untrusted logs; pytest XML/count receipts may be exported
                # through a separately reviewed artifact protocol, never stdout claims.
                result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=self.timeout)
                if _base_collection:
                    path=artifacts/'inventory.json'
                    if not path.is_file() or path.is_symlink() or path.stat().st_size>2_000_000:raise ValueError('trusted inventory unavailable')
                    identities=json.loads(path.read_text())
                    if result.returncode or not identities or len(set(identities))!=len(identities) or any(not isinstance(x,str) for x in identities):raise ValueError('invalid trusted inventory')
                    return dict(status='PASS',exit_code=0,test_ids=identities)
                if not test_command:
                    return dict(name=name, command=command, exit_code=result.returncode, status='PASS' if result.returncode==0 else 'FAIL', image=self.image)
                xml = artifacts / "results.xml"
                if not xml.is_file() or xml.is_symlink() or xml.stat().st_size > 2_000_000:
                    return dict(name=name, command=command, exit_code=result.returncode, status="PARTIAL", reason="missing or oversized test inventory", image=self.image)
                inventory = junit(xml)
                if expected is not None:
                    import xml.etree.ElementTree as ET
                    actual=sorted(c.get('classname','')+'::'+c.get('name','') for c in ET.parse(xml).getroot().iter('testcase'))
                    if actual!=expected:raise ValueError('trusted regression inventory changed')
                if name == 'full_suite': self._full_junit = xml.read_bytes()
                return dict(name=name, command=command + ["--junitxml=/artifacts/results.xml"], exit_code=result.returncode, status="PASS" if result.returncode == 0 and inventory["total"] > 0 and not inventory["failures"] else "FAIL", inventory=inventory, artifact_hash=hashlib.sha256(xml.read_bytes()).hexdigest(), trusted_test_tree_hash=trusted_hash, candidate_source_tree_hash=source_hash(root), image=self.image)
            except (subprocess.TimeoutExpired, ValueError, OSError) as error:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
                reason='timeout' if isinstance(error,subprocess.TimeoutExpired) else 'sandbox artifact/protocol validation failed'
                return dict(name=name, command=command, exit_code=None, status="FAIL", reason=reason)


def review(root, original, base_files, provider, validation, declared_risk, timeout=60, prior_findings=()):
    guard = WorkspaceGuard(root, [])
    changed = {}
    for path, old in sorted(base_files.items()):
        try: new = guard.read(path)
        except FileNotFoundError: new = ""
        if old != new: changed[path] = (old, new)
    deterministic = engineering_checks(changed)
    risk = classify(changed, graphs=[protected_graph(root)], declared=int(declared_risk[1:]),content=changed)
    if int(risk['risk'][1:])>int(declared_risk[1:]):
        deterministic.append(dict(id='risk-increased',severity='HIGH',file='',principle='P6',evidence='whole content exceeds approved risk; fresh human scope approval required'))
    before = source_hash(root)
    if deterministic:
        return dict(disposition="NEEDS_HUMAN", findings=deterministic, risk=risk, provider=provider.identity)
    if not validation or any(v["status"] != "PASS" or v["exit_code"] != 0 for v in validation):
        return dict(disposition="NEEDS_HUMAN", findings=[dict(id="validation", severity="HIGH", file="", requirement="fresh validation", evidence="missing or failed validation", principle="P3")], risk=risk, provider=provider.identity)
    try:
        response = respond_bounded(provider, dict(role="reviewer", todo=original, changes=changed, validation=validation, prior_findings=list(prior_findings), resolution_contract="Every prior finding requires either its same open ID or an explicit resolved entry with id, file and concrete evidence; conflicting findings require NEEDS_HUMAN.", principles=PRINCIPLES, principle_version="engineering-principles-1", contract=guard.read("AGENTS.md")), timeout)
        if response.get("disposition") not in {"PASS", "REQUEST_CHANGES", "NEEDS_HUMAN"} or not isinstance(response.get("findings"), list):
            raise ValueError("invalid reviewer output")
        for finding in response["findings"]:
            if not {"id", "severity", "file", "requirement", "evidence", "principle"} <= finding.keys() or finding["principle"] not in PRINCIPLES or finding["severity"] not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} or not finding["evidence"] or not finding["requirement"]:
                raise ValueError("untraceable finding")
        if len({f["id"] for f in response["findings"]}) != len(response["findings"]): raise ValueError("duplicate finding IDs")
        resolutions = response.get("resolved", [])
        if not isinstance(resolutions, list) or any(not all(r.get(k) for k in ("id", "file", "evidence")) for r in resolutions):
            raise ValueError("explicit resolution evidence required")
        prior_ids = {f["id"] for f in prior_findings}
        open_ids = {f["id"] for f in response["findings"]}
        resolved_ids = {r["id"] for r in resolutions}
        if prior_ids - open_ids - resolved_ids or open_ids & resolved_ids or response.get("conflicts"):
            raise ValueError("lost or conflicting review findings")
        if response["disposition"] == "PASS" and response["findings"]:
            raise ValueError("PASS with unresolved findings")
        if source_hash(root) != before: raise ValueError("reviewer changed workspace")
        return dict(response, risk=risk, provider=provider.identity, independent_context=uuid.uuid4().hex)
    except Exception:
        return dict(disposition="NEEDS_HUMAN", findings=[dict(id="review-unavailable", severity="HIGH", file="", requirement="independent review", evidence="review failed or workspace changed", principle="P3")], risk=risk, provider=provider.identity)


class Runner:
    def __init__(self, store, builder, reviewer, validator, max_iterations=3, max_seconds=300, max_lines=400):
        if builder is reviewer: raise ValueError("independent reviewer context required")
        self.store, self.builder, self.reviewer, self.validator = store, builder, reviewer, validator
        self.iterations = min(5, max(1, max_iterations)); self.seconds = min(600, max(1, max_seconds)); self.lines = min(1000, max(1, max_lines))

    def recover(self, cid):
        """Crash recovery preserves iterations; requires replan/approval to retry."""
        interrupted = self.store.query_runs(candidate=cid, status="RUNNING")
        for run in interrupted:
            self.store.run_event(cid, run["run_id"], run["role"], "NEEDS_HUMAN", dict(reason="interrupted process; prior iterations retained"), run["parent"])
        if interrupted and self.store.get(cid)["state"] == "BUILDING":
            self.store.transition(cid, "NEEDS_HUMAN", dict(reason="interrupted run"))
        return dict(recovered=[r["run_id"] for r in interrupted], status="NEEDS_HUMAN" if interrupted else "UNCHANGED")

    def run(self, cid, context, worktrees, record, validation_commands, *, certification, protections, mode="SUPERVISED", fixture=False):
        # Certification cannot be replaced by a boolean/model assertion. A verifier
        # supplied by the trusted application must check exact harness source hash.
        if certification() is not True or protections.get("status") != "PASS":
            return dict(status="NEEDS_HUMAN", reason="current certification and protections required")
        root = worktrees.verify(record)
        if git(root, "status", "--porcelain") or context["head"] != record["base"]:
            raise ValueError("dirty/unapproved worktree")
        candidate = self.store.get(cid)
        if mode not in {'SUPERVISED','AUTONOMOUS'} or context.get('mode','SUPERVISED')!=mode: raise ValueError('execution mode changed after approval')
        if not fixture:
            starts=[e['payload'] for e in candidate['events'] if e['kind']=='START_AUTHORIZATION']
            if not starts or starts[-1]['context']!=context or starts[-1]['mode']!=mode: raise ValueError('trusted start authorization required')
            if any(e['kind']=='RUN' and e['payload']['data'].get('start_nonce')==starts[-1]['nonce'] for e in candidate['events']): raise ValueError('start authorization already consumed')
        plans = [e["payload"] for e in candidate["events"] if e["kind"] == "PLAN"]
        if not plans or plans[-1]["context"] != context: raise ValueError("stale plan")
        todo_path = plans[-1]["path"]
        original = (root / todo_path).read_text()
        if digest(original) != context["acceptance_hash"]: raise ValueError("acceptance changed")
        allowed = candidate["files"]
        if todo_path in allowed or "AGENTS.md" in allowed:
            raise ValueError("requirements and authority are immutable to builder")
        risk = classify(allowed, graphs=[protected_graph(root)])
        if int(risk["risk"][1:]) > int(context["risk"][1:]): raise ValueError("risk increased; fresh approval required")
        if int(risk["risk"][1:]) >= 4:
            return dict(status="NEEDS_HUMAN", reason="protected financial/governance work requires supervised human workflow")
        guard = WorkspaceGuard(root, allowed)
        base_files = {name: guard.read(name) if (root / name).exists() else "" for name in allowed}
        run_id = str(uuid.uuid4()); self.store.begin(cid, context, run_id)
        self.store.run_event(cid, run_id, "builder", "RUNNING", dict(base=record["base"], worktree=record, provider=self.builder.identity, mode=mode, fixture_only=fixture, start_nonce=None if fixture else starts[-1]["nonce"]))
        start = time.monotonic(); unresolved = set(); seen = set(); final = {}; cumulative = 0
        try:
            for iteration in range(1, self.iterations + 1):
                if mode=='AUTONOMOUS':
                    from .operations import policy
                    config=policy(worktrees.repo)
                    if not config.get('autonomous_implementation') or config.get('emergency_stop') or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'} or certification() is not True:
                        raise ValueError('autonomous operation disabled or certification stale')
                if time.monotonic() - start >= self.seconds: raise ValueError("wall-time budget exhausted")
                response = respond_bounded(self.builder, dict(role="builder", todo=original, files={name: guard.read(name) if (root / name).exists() else "" for name in allowed}, contract=guard.read("AGENTS.md"), principles=PRINCIPLES, principle_version="engineering-principles-1", findings=final.get("findings", [])), self.seconds - (time.monotonic()-start))
                actions = response.get("actions")
                if not isinstance(actions, list) or len(actions) > 20: raise ValueError("invalid/action budget")
                for action in actions:
                    cumulative += len(action.get("content", "").splitlines())
                    if cumulative > self.lines: raise ValueError("cumulative diff budget exhausted")
                    guard.apply(action)
                if time.monotonic() - start >= self.seconds: raise ValueError("wall-time budget exhausted")
                actual = git(root, "status", "--porcelain", "--untracked-files=all")
                changed = {line[3:] for line in actual.splitlines()}
                if changed - set(allowed): raise ValueError("scope expanded")
                validations = []
                for name, cmd in validation_commands:
                    remaining = self.seconds - (time.monotonic()-start)
                    if remaining <= 0: raise ValueError("wall-time budget exhausted")
                    if isinstance(self.validator, ContainerValidator):
                        self.validator.timeout = min(self.validator.timeout, remaining)
                        self.validator.prior_base=record['base']
                        self.validator.trusted_test_base=record['base']
                        self.validator.trusted_test_root=root
                    validations.append(self.validator.run(root, name, cmd))
                final = review(root, original, base_files, self.reviewer, validations, context["risk"], self.seconds - (time.monotonic()-start), final.get("findings", []))
                current = {f["id"] for f in final["findings"]}
                event = dict(mode=mode, fixture_only=fixture, provider=self.builder.identity, iteration=iteration, source_hash=source_hash(root), changed_files=sorted(changed), actions_summary=["write:"+a["path"] for a in actions], validations=validations, review=final, resolved=sorted(unresolved-current), new=sorted(current-unresolved), cumulative_lines=cumulative)
                self.store.event(cid, "ITERATION", event, f"{run_id}:{iteration}")
                if final["disposition"] == "PASS":
                    self.store.run_event(cid, run_id, "builder", "PASS", dict(head=git(root, "rev-parse", "HEAD"), evidence=event))
                    return dict(status="REVIEW_PASS", mode=mode, run_id=run_id, validation=validations, review=final, iterations=iteration)
                fingerprint = digest(final["findings"])
                high = {f["id"] for f in final["findings"] if f["severity"] in {"HIGH", "CRITICAL"}}
                if final["disposition"] == "NEEDS_HUMAN" or fingerprint in seen or high & unresolved:
                    raise ValueError("review unresolved or repeated high-severity findings")
                seen.add(fingerprint); unresolved = current
            raise ValueError("iteration budget exhausted")
        except Exception as error:
            reason = str(error)[:200] if isinstance(error, ValueError) else type(error).__name__
            self.store.run_event(cid, run_id, "builder", "NEEDS_HUMAN", dict(reason=reason))
            self.store.transition(cid, "NEEDS_HUMAN", dict(reason=reason))
            return dict(status="NEEDS_HUMAN", reason=reason, run_id=run_id)
