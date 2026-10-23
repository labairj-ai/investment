"""Owner-delegated supervised progression. No owner approval/merge/deploy APIs."""
from __future__ import annotations
import json
import time
from pathlib import Path
from .store import digest

NEXT={'DISCOVERED':{'PLANNED'},'PLANNED':{'APPROVED_FOR_BUILD'},'APPROVED_FOR_BUILD':{'BUILDING'},'BUILDING':{'REVIEWING'},'REVIEWING':{'VALIDATING'},'VALIDATING':{'PR_READY'},'PR_READY':{'AWAITING_OWNER'},'AWAITING_OWNER':{'MERGED'},'MERGED':{'DEPLOYMENT_PENDING'},'DEPLOYMENT_PENDING':{'DEPLOYED'},'DEPLOYED':{'OBSERVING'},'OBSERVING':{'CLOSED'}}


def record(store,cid,stage,**evidence):
    with store.connect(True) as db:
        old=db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='PIPELINE' ORDER BY seq DESC LIMIT 1",(cid,)).fetchone()
        prior=json.loads(old[0])['stage'] if old else None
        if stage not in {'NEEDS_HUMAN','FAILED'} and stage not in (NEXT.get(prior,set()) if prior else {'DISCOVERED'}):raise ValueError('invalid pipeline stage transition')
        payload=dict(stage=stage,created=time.time(),evidence=evidence)
        store._append(db,cid,'PIPELINE',payload,'pipeline:'+str(time.time_ns()))
    return payload


def require_completed(root):
    from .discovery import task_index
    tasks=task_index(root)
    if any(tasks.get(f'{n:04d}',{}).get('status') not in {'done','completed','resolved'} for n in range(816,822)):raise ValueError('supervised foundation TODOs 0816-0821 require operational acceptance')


def cycle(root,store,builder,reviewer,validator,client):
    from .certification import technical_current,harness_hash as technical_hash
    from .operations import certificates,authorize_start
    from .build_policy import current,admit
    from .discovery import plan,refresh_plan,git
    from .policy import classify,protected_graph
    from .git_exec import run as git_run
    from .worktrees import Worktrees
    from .runner import Runner
    from .validation import validate_and_review
    from .evidence import seal
    from .github import prepare_pr
    root=Path(root);config=json.loads((root/'config/development_agent.json').read_text())
    candidates=[c for c in store.list(500) if c['state']=='DISCOVERED']
    if type(config.get('supervised_loop_enabled',False)) is not bool or type(config.get('supervised_publish_pr',False)) is not bool:raise ValueError('boolean supervised runtime policy required')
    if not config.get('supervised_loop_enabled',False):
        previews=[]
        for c in candidates[:5]:
            classification=classify(c['files'],graphs=[protected_graph(root)])
            if int(classification['risk'][1:])<=2:previews.append(dict(candidate=c['id'],files=c['files'],risk=classification['risk'],acceptance=c['outcome'],focused_tests=c.get('focused_tests',['tests/']),problem=c['problem']))
        with store.connect(True) as db:
            store._append(db,None,'STAGE_OBSERVATION',dict(stage='SHADOW',cycle=str(time.time_ns()),harness_hash=technical_hash(root),created=time.time(),fixture_only=False),'shadow-cycle:'+str(time.time_ns()))
        return dict(status='SHADOW',plans=previews,eligible_candidates=len(previews),implementation_started=False)
    if config.get('emergency_stop') or config.get('auto_merge') or not config.get('required_human_merge'):raise ValueError('owner authority policy violation')
    require_completed(root)
    current(root,store)
    if not technical_current(root,certificates(store)):raise ValueError('current technical certification including artifact integrity required')
    graph=protected_graph(root)
    for candidate in candidates:
        cid=candidate['id'];risk=classify(candidate['files'],graphs=[graph])
        if int(risk['risk'][1:])>2:continue
        # Dependencies remain hard gates, never model estimates.
        from .discovery import task_index
        tasks=task_index(root);deps=candidate.get('dependencies',[])
        if any(dep not in tasks or tasks[dep]['status'] not in {'done','completed','resolved'} for dep in deps):continue
        record(store,cid,'DISCOVERED',signal=candidate.get('signal_id'),risk=risk['risk'])
        try:
            manager=Worktrees(root,store.path.parent/'worktrees')
            # Reservation uses the repository TODO index; worktree branch ID is a
            # provisional number, and the allocated frozen plan is separately bound.
            next_id=f"{max([int(t) for t in tasks]+[0])+1:04d}"
            tree=manager.create(next_id,git(root,'rev-parse','HEAD'));work=Path(tree['path'])
            criteria=[candidate['outcome']+'; verify through '+candidate.get('validation','focused and full regression tests')]
            plan(work,store,cid,criteria,deps,mode='SUPERVISED',focused_tests=candidate.get('focused_tests',['tests/']))
            pending=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='PLAN'][-1]
            git_run(work,'add','--',pending['path']);git_run(work,'commit','-m','Freeze candidate acceptance plan')
            tree=manager.freeze_plan(tree,pending['path']);context=refresh_plan(work,store,cid)
            if context['todo']!=tree['todo']:raise ValueError('concurrent TODO allocation requires replanning')
            store.event(cid,'WORKTREE',tree);record(store,cid,'PLANNED',head=context['head'],context_hash=digest(context))
            admission=admit(root,store,cid);record(store,cid,'APPROVED_FOR_BUILD',authority='owner-delegated-build-policy')
            authorize_start(root,store,cid,'SUPERVISED',certificates(store),client.protections())
            record(store,cid,'BUILDING')
            def ready():
                import os
                live=json.loads((root/'config/development_agent.json').read_text())
                return (live.get('supervised_loop_enabled') is True and not live.get('emergency_stop') and os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() in {'','0','false'}
                        and digest(current(root,store))==admission['policy_hash'] and technical_current(root,certificates(store)) and client.protections().get('status')=='PASS')
            result=Runner(store,builder,reviewer,validator).run(cid,context,manager,tree,[('focused_tests',['python','-m','pytest',*pending['focused_tests'],'-q'])],certification=ready,protections=client.protections(),mode='SUPERVISED')
            record(store,cid,'REVIEWING',disposition=result['status'])
            if result['status']!='REVIEW_PASS':raise ValueError('bounded builder/reviewer did not pass')
            git_run(work,'add','--',*candidate['files']);git_run(work,'commit','-m',f"[agent] TODO {context['todo']}: {candidate['title']}")
            record(store,cid,'VALIDATING',head=git(work,'rev-parse','HEAD'))
            review=validate_and_review(work,store,cid,validator,reviewer)
            if review['disposition']!='PASS':raise ValueError('trusted mandatory validation/review failed')
            proof=seal(work,store,cid)
            if proof['status']!='PASS' or not ready():raise ValueError('fresh complete evidence required')
            record(store,cid,'PR_READY',head=proof['head'],receipt=proof['id'])
            from .stage_control import observe as observe_stage
            from .certification import harness_hash
            if not config.get('supervised_publish_pr',False):
                observe_stage(store,'BUILD_ONLY',candidate=cid,head=proof['head'],harness=harness_hash(root),receipt=proof['id'],fixture=builder.identity.get('provider')=='replay' or builder.identity.get('fixture_only',False))
                return dict(status='VALIDATED_NOT_PUBLISHED',candidate=cid,head=proof['head'],grants_merge=False,grants_deployment=False)
            client.publish(work,tree['branch'],proof['head'],store=store,cid=cid)
            pr=prepare_pr(work,store,cid,proof,client)
            record(store,cid,'AWAITING_OWNER',pr=pr,head=proof['head'])
            if config.get('autonomous_implementation') is True:observe_stage(store,'PR',candidate=cid,head=proof['head'],harness=harness_hash(root),receipt=proof['id'],fixture=builder.identity.get('provider')=='replay' or builder.identity.get('fixture_only',False))
            store.event(cid,'OWNER_NOTIFICATION',dict(pr=pr,head=proof['head'],channel='development-dashboard',decision_required='OK/NO'))
            return dict(status='AWAITING_OWNER',candidate=cid,pr=pr,grants_merge=False,grants_deployment=False)
        except Exception as error:
            record(store,cid,'NEEDS_HUMAN',reason=type(error).__name__)
            if store.get(cid)['state'] in {'APPROVED','BUILDING','PR_OPEN'}:store.transition(cid,'NEEDS_HUMAN',dict(reason='supervised pipeline stopped; inspect preserved evidence'))
            return dict(status='NEEDS_HUMAN',candidate=cid,reason=type(error).__name__)
    return dict(status='NO_ELIGIBLE_CANDIDATE')


def reconcile_prs(root,store,client):
    """Read GitHub owner decisions and actual merges; never perform a merge."""
    from .github import recheck_pr,record_merge
    from .github_owner import newest_review,ingest
    from .owner_review import require as owner_approval
    results=[]
    for candidate in store.list(50):
        phases=[e['payload'] for e in candidate['events'] if e['kind']=='PIPELINE']
        prs=[e['payload'] for e in candidate['events'] if e['kind']=='PR']
        if not phases or phases[-1]['stage']!='AWAITING_OWNER' or not prs:continue
        cid=candidate['id'];pr=prs[-1]
        try:
            if recheck_pr(store,cid,client)['status']!='PASS':raise ValueError('remote head/protection changed')
            obj=newest_review(client,pr['result']['number'],pr['head'])
            decision=ingest(store,client,obj)
            if decision['decision']!='APPROVE':
                record(store,cid,'NEEDS_HUMAN',owner_decision=decision['decision'],origin=decision['origin'])
                if store.get(cid)['state']=='PR_OPEN':store.transition(cid,'NEEDS_HUMAN',dict(reason='owner requested changes or deferred'))
                results.append(dict(candidate=cid,status='NEEDS_HUMAN'));continue
            owner_approval(store,client,pr['result']['number'])
            if client.pr_identity(pr['result']['number']).get('state')!='MERGED':results.append(dict(candidate=cid,status='AWAITING_OWNER_MERGE'));continue
            merge=record_merge(store,cid,client)
            record(store,cid,'MERGED',merge_sha=merge['merge_sha'],owner_review_hash=merge['owner_review_hash'])
            record(store,cid,'DEPLOYMENT_PENDING',merge_sha=merge['merge_sha'],owner_deployment_authorization_required=True)
            results.append(dict(candidate=cid,status='DEPLOYMENT_PENDING',merge_sha=merge['merge_sha']))
        except ValueError as error:
            # Missing owner decision is a normal wait, not a synthetic approval.
            results.append(dict(candidate=cid,status='WAITING_OR_BLOCKED',reason=str(error)[:200]))
    return results


def accept_observation(root,store,cid,client,signed,*,key):
    """Consume the separate deployment observer's signed exact-SHA software facts."""
    import hashlib,hmac
    from .result_collector import canonical
    from .github_owner import newest_review,authenticated_identity,ingest
    from .outcomes import observe
    from .operations import record_success
    if not isinstance(key,bytes) or len(key)<32 or not isinstance(signed,dict) or set(signed)!={'observation','signature'}:raise ValueError('signed deployment observation required')
    body=signed['observation']
    if not hmac.compare_digest(hmac.new(key,canonical(body),hashlib.sha256).hexdigest(),str(signed['signature'])):raise ValueError('deployment observer signature mismatch')
    if body.get('protocol')!='software-observation-1' or not 0<=time.time()-body.get('observed_at',0)<=3600:raise ValueError('fresh deployment observation required')
    candidate=store.get(cid);pr=[e['payload'] for e in candidate['events'] if e['kind']=='PR'][-1]
    if body.get('repository')!=client.repository or body.get('pr')!=pr['result']['number'] or body.get('head')!=pr['head']:raise ValueError('deployment observation belongs to another PR/head')
    merge=[e['payload'] for e in candidate['events'] if e['kind']=='MERGE'][-1]
    if body['merge_sha']!=merge['merge_sha']:raise ValueError('observation refers to another merge')
    prior=[e['payload'] for e in candidate['events'] if e['kind']=='DEPLOYMENT']
    if prior and body['observed_at']<=max(p.get('observed_at',0) for p in prior):return dict(status='OBSERVATION_ALREADY_RECORDED',idempotent=True)
    if body['status']!='HEALTHY' or body['deployed_sha']!=merge['merge_sha']:
        with store.connect(True) as db:store._append(db,cid,'AUTONOMY_PAUSE',dict(created=time.time(),reason='signed deployment outcome abnormal',observation_hash=hashlib.sha256(canonical(body)).hexdigest()),'outcome-pause:'+hashlib.sha256(canonical(body)).hexdigest())
        record(store,cid,'NEEDS_HUMAN',reason='signed deployment observation not healthy')
        return dict(status='NEEDS_HUMAN')
    result=observe(store,cid,body,client=client)
    if result['status']!='HEALTHY':
        record(store,cid,'NEEDS_HUMAN',reason='post-deployment outcome not healthy')
        return dict(status='NEEDS_HUMAN')
    phases=[e['payload']['stage'] for e in store.get(cid)['events'] if e['kind']=='PIPELINE']
    if phases and phases[-1]=='CLOSED':return dict(status='CLOSED',idempotent=True)
    if not phases or phases[-1]!='DEPLOYMENT_PENDING':raise ValueError('deployment-pending lineage required')
    record(store,cid,'DEPLOYED',deployed_sha=body['deployed_sha'])
    record(store,cid,'OBSERVING',window_seconds=body['window_seconds'],observation_signature=signed['signature'])
    obj=newest_review(client,body['pr'],body['head']);ingest(store,client,obj);human=authenticated_identity(client,obj)
    success=record_success(root,store,cid,client,human=human)
    with store.connect(True) as db:
        if store._state(db,cid)=='DEPLOYED':store._append(db,cid,'STATE',dict(state='CLOSED',actor='trusted-software-observer',operational_success=success['run_id']),'observed-close:'+success['run_id'])
    record(store,cid,'CLOSED',operational_success=success['run_id'])
    return dict(status='CLOSED',operational_success=success['run_id'])


def reconcile_observations(root,store,client,directory,key):
    """Read bounded signed software exports; never opens the production database."""
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir():raise ValueError('operator observation export directory required')
    files=list(directory.glob('observation-*.json'))
    if len(files)>1000:raise ValueError('observation inbox exceeds bounded inventory; archive reviewed evidence')
    decoded=[]
    for path in files:
        if path.is_symlink() or path.stat().st_size>16000:raise ValueError('bounded regular software observation required')
        value=json.loads(path.read_text());decoded.append(value)
    decoded.sort(key=lambda item:item.get('observation',{}).get('observed_at',0))
    results=[]
    for signed in decoded[-50:]:
        body=signed.get('observation',{})
        for candidate in store.list(100):
            prs=[e['payload'] for e in candidate['events'] if e['kind']=='PR']
            if prs and prs[-1]['result']['number']==body.get('pr') and prs[-1]['head']==body.get('head'):
                results.append(accept_observation(root,store,candidate['id'],client,signed,key=key))
    return results
