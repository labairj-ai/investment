"""GitHub handoff; never changes rulesets, merges or enables auto-merge."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .discovery import git
from .evidence import REQUIRED, verify, trusted_receipt
from .store import bounded, digest
from .policy import whole_diff


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository): raise ValueError("repository")
        self.repository = repository

    def read(self, endpoint):
        result = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    def read_all(self, endpoint):
        rows=[]
        for page in range(1,101):
            batch=self.read(endpoint+('&' if '?' in endpoint else '?')+f'per_page=100&page={page}')
            if not isinstance(batch,list): raise ValueError('API inventory unavailable')
            rows.extend(batch)
            if len(batch)<100: return rows
        raise ValueError('API pagination incomplete')

    def protections(self):
        raw={}
        try:
            # A 404 on classic protection alone is legitimate for ruleset-only repos.
            try: classic=self.read(f'repos/{self.repository}/branches/main/protection')
            except subprocess.CalledProcessError as exc:
                if '404' not in str(exc.stderr): raise
                classic=None
            raw['classic']=classic
            user=self.read('user');raw['identity']={k:user[k] for k in ('login','id') if k in user}
            repo=self.read(f'repos/{self.repository}');raw['repository']={k:repo[k] for k in ('id','full_name','permissions','default_branch') if k in repo}
            raw['permission']=self.read(f"repos/{self.repository}/collaborators/{raw['identity']['login']}/permission")
            active=self.read_all(f'repos/{self.repository}/rules/branches/main')
            inventory=self.read_all(f'repos/{self.repository}/rulesets?includes_parents=true')
            details=[]
            for item in inventory:
                # Include inherited details; absence of visibility is UNAVAILABLE.
                detail=self.read(f"repos/{self.repository}/rulesets/{item['id']}?includes_parents=true")
                if not {'rules','bypass_actors','enforcement'}<=detail.keys(): raise ValueError('incomplete ruleset detail')
                details.append(detail)
            raw.update(active_rules=active,rulesets=details)
            result=effective_protections(classic,active,details,raw['identity'],raw['repository'],visibility=True)
            result.update(created=time.time(),repository=self.repository,evidence_hash=digest(raw),evidence=raw)
            return result
        except Exception:
            return dict(status='UNAVAILABLE',failures=['GitHub identity/protection visibility incomplete'],auto_merge=False,created=time.time(),evidence_hash=digest(raw))

    def pr_identity(self, number):
        result=subprocess.run(['gh','pr','view',str(number),'--repo',self.repository,'--json','number,url,headRefName,headRefOid,headRepository,headRepositoryOwner,baseRefName,isDraft,state,reviewDecision,mergeCommit'],check=True,capture_output=True,text=True,timeout=30)
        return json.loads(result.stdout)

    def publish(self,root,branch,head,*,store,cid):
        if not branch.startswith('agent/') or git(root,'branch','--show-current')!=branch or git(root,'rev-parse','HEAD')!=head or git(root,'status','--porcelain'):
            raise ValueError('clean exact-head isolated branch required')
        remote=git(root,'remote','get-url','origin')
        allowed={f'git@github.com:{self.repository}.git',f'https://github.com/{self.repository}.git'}
        if remote not in allowed:raise ValueError('unexpected publishing repository')
        if git(root,'remote','get-url','--push','--all','origin').splitlines() not in [[value] for value in allowed]:
            raise ValueError('unexpected push repository')
        from .protection import require
        authority=require(store,cid,self,'publish',root=root)
        store.event(cid,'GIT_INTENT',dict(operation='publish',status='REQUESTED',head=head,branch=branch,repository=self.repository,hooks_disabled=True,ambient_config_disabled=True))
        git_run(root,'push','origin',head+':refs/heads/'+branch,timeout=60)
        store.event(cid,'GIT_INTENT',dict(operation='publish',head=head,branch=branch,protection=authority['raw_evidence_hash'],hooks_disabled=True))

    def handoff(self, branch, title, body, draft):
        query = subprocess.run(["gh", "pr", "list", "--repo", self.repository, "--head", branch, "--state", "open", "--json", "number,url,isDraft"], check=True, capture_output=True, text=True, timeout=30)
        existing = json.loads(query.stdout)
        with tempfile.TemporaryDirectory(prefix="dev-pr-") as temp:
            path = Path(temp) / "body.md"; path.write_text(body)
            if existing:
                item = existing[0]
                subprocess.run(["gh", "pr", "edit", str(item["number"]), "--repo", self.repository, "--title", title, "--body-file", str(path)], check=True, capture_output=True, timeout=30)
                if draft and not item["isDraft"]:
                    subprocess.run(["gh", "pr", "ready", str(item["number"]), "--repo", self.repository, "--undo"], check=True, capture_output=True, timeout=30)
                    item = dict(item, isDraft=True)
                return item
            command = ["gh", "pr", "create", "--repo", self.repository, "--head", branch, "--base", "main", "--title", title, "--body-file", str(path)]
            if draft: command.append("--draft")
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            url = result.stdout.strip()
            return dict(url=url, number=int(url.rstrip("/").rsplit("/",1)[1]), isDraft=draft)


def verify_protections(data):
    checks = data.get("required_status_checks") or {}
    contexts = set(checks.get("contexts", [])) | {c["context"] for c in checks.get("checks", [])}
    reviews = data.get("required_pull_request_reviews") or {}
    restrictions = data.get("restrictions")
    failures = []
    if not checks.get("strict") or "test" not in contexts: failures.append("current-head required test check")
    if reviews.get("required_approving_review_count", 0) < 1 or not reviews.get("dismiss_stale_reviews") or not reviews.get("require_last_push_approval"):
        failures.append("fresh independent review")
    if (reviews.get("bypass_pull_request_allowances") or {}).get("users") or (reviews.get("bypass_pull_request_allowances") or {}).get("apps") or (reviews.get("bypass_pull_request_allowances") or {}).get("teams"):
        failures.append("review bypass identity")
    for key in ("enforce_admins", "required_conversation_resolution"):
        if not (data.get(key) or {}).get("enabled"): failures.append(key)
    for key in ("allow_force_pushes", "allow_deletions"):
        if (data.get(key) or {}).get("enabled"): failures.append(key)
    if restrictions is None: failures.append("restricted direct push")
    # This verifies branch protection. Identity membership in bypass rulesets is
    # a separate operator gate, never inferred from a successful API response.
    if not data.get("agent_identity_no_bypass_verified", False): failures.append("agent ruleset/identity bypass audit")
    return dict(status="PASS" if not failures else "FAIL", failures=failures, auto_merge=False, required_checks=sorted(contexts))


def prepare_pr(root, store, cid, data, client):
    if data.get("candidate") != cid: raise ValueError("receipt belongs to another candidate")
    if not trusted_receipt(root, store, cid, data): raise ValueError("stale, untrusted or tampered receipt")
    if git(root, "status", "--porcelain"): raise ValueError("commit candidate before PR")
    branch = git(root, "branch", "--show-current")
    if not branch.startswith("agent/") or git(root, "rev-parse", "HEAD") == data["base"]: raise ValueError("isolated committed branch required")
    from .protection import require
    require(store,cid,client,'pr_handoff',root=root)
    records = data["validations"]
    mandatory = {r["name"] for r in records if r["status"] == "PASS" and r["exit_code"] == 0}
    if not REQUIRED <= mandatory or data["review"].get("disposition") != "PASS": raise ValueError("mandatory PR gates failed")
    for record in records:
        if record["name"] in {"focused_tests", "full_suite"} and (record.get("inventory",{}).get("total",0)<=0 or record["inventory"].get("failures") or "skipped" not in record["inventory"]):
            raise ValueError("mandatory test inventory missing or failing")
    candidate = store.get(cid)
    if candidate["state"] not in {"BUILDING", "PR_OPEN"}: raise ValueError("candidate not eligible for PR handoff")
    actual_risk = whole_diff(root, data["base"])
    if int(actual_risk["risk"][1:]) > int(data["risk"]["risk"][1:]): raise ValueError("complete diff risk increased")
    latest_plan = [e["payload"] for e in candidate["events"] if e["kind"] == "PLAN"][-1]
    if data["todo"] != latest_plan["context"]["todo"] or data["base"] != latest_plan["context"]["head"]: raise ValueError("receipt does not match original approved scope")
    body = f"Candidate {cid}; TODO {data['todo']}\n\n{candidate['problem']}\n\nScope: {candidate['outcome']}\n\nRisk: {data['risk']['risk']}; human merge approval required. No auto-merge.\n\nChanged files: {', '.join(candidate['files'])}\n\nAcceptance: see original TODO and immutable PLAN event.\n\nTests and review: {json.dumps(records)}; {data['review']['disposition']}\n\nEvidence: {data['id']}; tested head {data['head']}; approved base {data['base']}; execution mode {data.get('mode', 'UNKNOWN')}\n\nLimitations: no production deployment authorized.\n\nRollback: revert implementation through the reviewed deployment workflow.\n"
    bounded(body)
    result = client.handoff(branch, f"[agent][{data['risk']['risk']}] TODO {data['todo']}: {candidate['title']}", body, data["status"] != "PASS")
    remote=client.pr_identity(result['number'])
    verified=verify_remote_pr(remote,repository=client.repository,branch=branch,head=data['head'])
    if remote['isDraft'] != (data['status']!='PASS'): raise ValueError('remote draft/readiness mismatch')
    with store.connect(True) as db:
        prior = store._state(db, cid)
        if prior not in {"BUILDING", "PR_OPEN"}: raise ValueError("candidate state changed during handoff")
        event = dict(result=result, verified=verified, mode=data.get("mode"), head=data["head"], receipt=data["id"])
        store._append(db, cid, "PR", event, "pr:" + digest(event))
        if prior == "BUILDING": store._append(db, cid, "STATE", {"state": "PR_OPEN"}, "pr-state:" + data["head"])
    return result


def verify_remote_pr(remote, *, repository, branch, head):
    owner=remote.get('headRepositoryOwner') or {}
    repo=remote.get('headRepository') or {}
    identity=repo.get('nameWithOwner') or (owner.get('login','')+'/'+repo.get('name',''))
    if remote.get('headRefOid')!=head or remote.get('headRefName')!=branch or remote.get('baseRefName')!='main' or identity.lower()!=repository.lower():
        raise ValueError('NEEDS_HUMAN: remote PR identity differs from sealed evidence')
    if not isinstance(remote.get('isDraft'),bool) or not isinstance(remote.get('number'),int): raise ValueError('remote PR metadata unavailable')
    return {k:remote[k] for k in ('number','headRefName','headRefOid','baseRefName','isDraft')} | {'headRepository':identity}


def recheck_pr(store,cid,client):
    from .protection import require
    require(store,cid,client,'pr_disposition')
    candidate=store.get(cid)
    pr=[e['payload'] for e in candidate['events'] if e['kind']=='PR'][-1]
    try:
        result=verify_remote_pr(client.pr_identity(pr['result']['number']),repository=client.repository,branch=pr['verified']['headRefName'],head=pr['head'])
        return dict(status='PASS',identity=result)
    except (ValueError,KeyError):
        if candidate['state']=='PR_OPEN': store.transition(cid,'NEEDS_HUMAN',dict(reason='remote head changed; fresh validation and review required'))
        return dict(status='NEEDS_HUMAN',reason='remote head changed; fresh validation and review required')


def effective_protections(classic, active_rules, rulesets, identity, repository, *, visibility):
    failures=[]
    if not visibility or not identity.get('login') or not isinstance(repository.get('permissions'),dict):
        return dict(status='UNAVAILABLE',failures=['incomplete authenticated policy visibility'],auto_merge=False)
    required=dict(pr=False,checks=False,review=False,stale=False,last_push=False,conversation=False,no_force=False,no_delete=False,admin=False)
    contexts=set()
    if classic is not None:
        checked=verify_protections(dict(classic,agent_identity_no_bypass_verified=True))
        checks=classic.get('required_status_checks') or {}
        contexts.update(checks.get('contexts',[]));contexts.update(c['context'] for c in checks.get('checks',[]))
        review=classic.get('required_pull_request_reviews') or {}
        required.update(pr=bool(review),checks=bool(checks.get('strict') and 'test' in contexts),review=review.get('required_approving_review_count',0)>=1,stale=bool(review.get('dismiss_stale_reviews')),last_push=bool(review.get('require_last_push_approval')),conversation=bool((classic.get('required_conversation_resolution') or {}).get('enabled')),no_force=not (classic.get('allow_force_pushes') or {}).get('enabled',False),no_delete=not (classic.get('allow_deletions') or {}).get('enabled',False),admin=bool((classic.get('enforce_admins') or {}).get('enabled')))
        bypass=review.get('bypass_pull_request_allowances') or {}
        if any(bypass.get(k) for k in ('users','teams','apps')): failures.append('classic review bypass actors require independent audit')
        restrictions=classic.get('restrictions') or {}
        if any(u.get('login')==identity['login'] for u in restrictions.get('users',[])): failures.append('agent directly allowed on protected branch')
    ids={r.get('ruleset_id') for r in active_rules}
    visible={r.get('id') for r in rulesets if r.get('enforcement')=='active'}
    if ids-visible: return dict(status='UNAVAILABLE',failures=['inherited ruleset details inaccessible'],auto_merge=False)
    for rule in rulesets:
        if rule.get('enforcement')=='active' and rule.get('id') in ids:
            if 'bypass_actors' not in rule: return dict(status='UNAVAILABLE',failures=['bypass actors not visible'],auto_merge=False)
            if rule['bypass_actors']: failures.append('active ruleset bypass actor: '+str(rule['id']))
            required['admin']=True
    for rule in active_rules:
        kind=rule['type'];p=rule.get('parameters') or {}
        if kind=='pull_request':
            required['pr']=True
            required['review'] |= p.get('required_approving_review_count',0)>=1
            required['stale'] |= bool(p.get('dismiss_stale_reviews_on_push'))
            required['last_push'] |= bool(p.get('require_last_push_approval'))
            required['conversation'] |= bool(p.get('required_review_thread_resolution'))
        elif kind=='required_status_checks':
            names={c['context'] for c in p.get('required_status_checks',[])};contexts|=names
            required['checks'] |= bool(p.get('strict_required_status_checks_policy') and not p.get('do_not_enforce_on_create',False) and 'test' in names)
        elif kind=='non_fast_forward': required['no_force']=True
        elif kind=='deletion': required['no_delete']=True
    if repository['permissions'].get('admin'): failures.append('coding-agent identity has administrative authority')
    failures += ['missing effective protection: '+k for k,v in required.items() if not v]
    return dict(status='PASS' if not failures else 'FAIL',failures=failures,auto_merge=False,identity=identity['login'],required_checks=sorted(contexts),effective=required,agent_capabilities={k:False if not failures else 'UNVERIFIED' for k in ('direct_push','bypass_review','bypass_checks','force_push','delete_ref','bypass_conversations','self_approve')})


def record_merge(store,cid,client):
    """Read GitHub's completed human merge; never perform a merge."""
    from .protection import require
    authority=require(store,cid,client,'merge')
    candidate=store.get(cid)
    pr=[e['payload'] for e in candidate['events'] if e['kind']=='PR'][-1]
    remote=client.pr_identity(pr['result']['number'])
    verify_remote_pr(remote,repository=client.repository,branch=pr['verified']['headRefName'],head=pr['head'])
    sha=(remote.get('mergeCommit') or {}).get('oid','')
    if remote.get('state')!='MERGED' or remote.get('reviewDecision')!='APPROVED' or not re.fullmatch(r'[a-f0-9]{40}',sha):
        raise ValueError('independently approved completed GitHub merge required')
    payload=dict(merge_sha=sha,head=pr['head'],pr=remote.get('url',pr['result']['url']),source='github-verified-merge',number=remote['number'],protection_policy=authority['policy_hash'],protection_identity=authority['identity'])
    with store.connect(True) as db:
        store._append(db,cid,'MERGE',payload,'github-merge:'+sha)
    return payload
