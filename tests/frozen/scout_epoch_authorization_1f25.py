def live_authorization(a,client=None):
    # Fresh read-only GitHub verification; a root JSON boolean is insufficient.
    from dev_agent.github import GitHub
    from dev_agent.github_owner import verified_object,latest_object
    if client is None:
        class ReadOnly(GitHub):
            def read(self,endpoint,**kwargs):return super().read(endpoint,require_token=True)
        client=ReadOnly(a['repository'])
    object_id=int(a['owner_object'].rsplit('-',1)[1])
    data,current,origin=verified_object(client,object_id)
    require(origin['url']==a['owner_object'] and current['head']==a['reviewed_head'],'owner source binding changed')
    require(data['decision']=='APPROVE' and data['risk']=='L5' and data['financial_ack'] is True and data['execution_ack'] is True and data['nonce']==a['nonce'],'fresh L5 owner decision required')
    require(data['rationale']==SCOPE+':'+a['old_head']+':'+a['target_head'],'explicit exact upgrade scope required')
    require(latest_object(client,data['pr'],current['head'],origin['created_at'])==object_id,'owner decision superseded')
    identity=client.pr_identity(data['pr'])
    require(identity['state']=='MERGED' and identity['mergeCommit']['oid']==a['target_head'],'exact approved merged source required')
    endpoint='repos/'+a['repository']+'/actions/runs?head_sha='+a['target_head']+'&event=push&per_page=10'
    runs=client.read(endpoint)
    require(type(runs.get('total_count')) is int and 0<runs['total_count']<=10,'bounded merged-main CI inventory required')
    matches=[x for x in runs.get('workflow_runs',[]) if x.get('path')=='.github/workflows/test.yml' and x.get('head_branch')=='main' and x.get('head_sha')==a['target_head'] and x.get('event')=='push']
    require(matches,'merged-main release CI required')
    run=max(matches,key=lambda x:x['id'])
    require(run.get('status')=='completed' and run.get('conclusion')=='success','latest merged-main CI must pass')
    jobs=client.read('repos/'+a['repository']+'/actions/runs/'+str(run['id'])+'/jobs?per_page=100')
    require(type(jobs.get('total_count')) is int and jobs['total_count']==len(jobs.get('jobs',[])) and 0<jobs['total_count']<=100,'complete release jobs required')
    for name in ('native-systemd255','test'):
        matching=[j for j in jobs['jobs'] if j.get('name')==name]
        require(len(matching)==1 and matching[0].get('conclusion')=='success','native proof and all eight release gates required')
    # No token, comment body or financial content is persisted by this verifier.
    return dict(owner_object_id=object_id,ci_run_id=run['id'],head=a['target_head'])
