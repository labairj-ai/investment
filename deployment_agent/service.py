"""Serialized fixed deployment transaction; never restores financial databases."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from dev_agent.result_collector import write_final


def deploy(executor,authorization,*,origin,admit_again):
    require_deployment_scope(authorization)
    if admit_again()!=authorization:raise ValueError('independent current deployment admission required')
    directory=executor.receipts
    if directory.is_symlink():raise ValueError('symlink deployment receipt directory')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if directory.stat().st_mode&0o077:raise ValueError('private deployment receipt directory required')
    with (directory/'.deployment.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        name='deploy-'+str(authorization['authorization_id'])
        completed=directory/(name+'.json')
        if completed.exists():
            previous=json.loads(completed.read_text())
            if previous.get('merge_sha')!=authorization['merge_sha']:raise ValueError('authorization replay with different target')
            if previous.get('status')=='DEPLOYED_VERIFIED' and executor.git('rev-parse','HEAD')==authorization['merge_sha'] and executor.service('is-active')=='active':return dict(previous,idempotent=True)
            raise ValueError('used release requires technical failure recovery before retry')
        nonce_name='nonce-'+hashlib.sha256(authorization['nonce'].encode()).hexdigest()
        if (directory/(nonce_name+'.json')).exists():raise ValueError('deployment nonce already consumed')
        pending=directory/'pending.json'
        if pending.exists():raise ValueError('interrupted deployment must be recovered before new admission')
        receipt=dict(repository=authorization['repository'],deployment_service_uid=os.getuid(),authorization_id=authorization['authorization_id'],authorization_url=authorization['authorization_url'],authorization_nonce=authorization['nonce'],pr=authorization['pr'],head=authorization['head'],merge_sha=authorization['merge_sha'],deployed_sha=None,created=time.time(),main_sha=authorization['main_sha'],head_ci=authorization['head_ci'],merge_ci=authorization['merge_ci'],deployment_actor=authorization['deployment_actor'],ci_url=authorization.get('ci_url'),status='FAILED_PRECHECK')
        write_final(directory,nonce_name,dict(authorization_id=authorization['authorization_id'],created=time.time()))
        before=None;stopped=False
        try:
            before=executor.preflight(origin);receipt.update(prior_sha=before['prior_sha'],before=before,rollback_target=before['prior_sha'])
            cfg=json.loads((executor.root/'config/development_agent.json').read_text())
            if cfg.get('auto_merge') or not cfg.get('required_human_merge'):raise ValueError('human merge policy invalid')
            if admit_again()!=authorization:raise ValueError('deployment admission changed before transaction')
            write_final(directory,'pending',dict(prior_sha=before['prior_sha'],target=authorization['merge_sha'],authorization_id=authorization['authorization_id'],protected=before['protected']))
            require_deployment_scope(authorization)
            executor.service('stop');stopped=True
            receipt['backup']=executor.backup(directory/(name+'-rollback'))
            receipt['holdings_before']=executor.protected()
            require_deployment_scope(authorization)
            executor.checkout(authorization['merge_sha'],origin)
            if executor.git('rev-parse','HEAD')!=authorization['merge_sha'] or executor.git('status','--porcelain','--untracked-files=no'):raise ValueError('deployed files differ from approved merge SHA')
            executor.service('start')
            health=executor.health();receipt['health']=health
            receipt['holdings_after']=executor.protected()
            if not all(health['checks'].values()) or health['autonomous_implementation']!=cfg.get('autonomous_implementation') or not protected_matches(executor,receipt['holdings_before'],receipt['holdings_after']) or executor.config_hash()!=before['service_configuration_hash']:raise ValueError('post-deployment health, authority, config or protected state failed')
            if admit_again()!=authorization:raise ValueError('owner/main/CI admission changed during deployment')
            receipt.update(status='DEPLOYED_VERIFIED',deployed_sha=authorization['merge_sha'],finished=time.time(),protected_state_verified=True)
            from .evidence import normalize
            receipt['deployment_evidence']=normalize(receipt)
        except Exception as error:
            receipt.update(failure=type(error).__name__,finished=time.time())
            if stopped and before:
                try:
                    executor.service('stop');executor.checkout(before['prior_sha'],origin);executor.service('start')
                    rollback=executor.health();receipt['rollback_health']=rollback
                    receipt['protected_after_rollback']=executor.protected()
                    receipt.update(status='ROLLED_BACK' if all(rollback['checks'].values()) and protected_matches(executor,before['protected'],receipt['protected_after_rollback']) else 'DEPLOYED_DEGRADED',deployed_sha=executor.git('rev-parse','HEAD'))
                except Exception as rollback_error:receipt.update(status='DEPLOYED_DEGRADED',rollback_failure=type(rollback_error).__name__)
        write_final(directory,name,receipt)
        if receipt['status'] in {'DEPLOYED_VERIFIED','ROLLED_BACK','FAILED_PRECHECK'}:pending.unlink(missing_ok=True)
        return receipt


def recover(executor,origin):
    directory=executor.receipts;pending=directory/'pending.json'
    if not pending.exists():return dict(status='NO_INTERRUPTED_DEPLOYMENT')
    if pending.is_symlink() or pending.stat().st_mode&0o077:raise ValueError('private interrupted deployment receipt required')
    with (directory/'.deployment.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads(pending.read_text());executor.service('stop');executor.checkout(state['prior_sha'],origin);executor.service('start');health=executor.health()
        result=dict(status='ROLLED_BACK' if all(health['checks'].values()) and protected_matches(executor,state.get('protected'),executor.protected()) else 'DEPLOYED_DEGRADED',authorization_id=state['authorization_id'],prior_sha=state['prior_sha'],deployed_sha=executor.git('rev-parse','HEAD'),health=health,created=time.time())
        write_final(directory,'recovery-'+str(time.time_ns()),result)
        if result['status']=='ROLLED_BACK':pending.unlink()
        return result


def exit_code(receipt,*,recovery=False):
    # A safe code rollback is not a successful deployment/promotion.
    return 0 if receipt.get('status')=='DEPLOYED_VERIFIED' or recovery and receipt.get('status') in {'NO_INTERRUPTED_DEPLOYMENT','ROLLED_BACK'} else 1


def protected_matches(executor,before,after):
    compare=getattr(executor,'protected_unchanged',None)
    return compare(before,after) if compare is not None else before==after


def require_deployment_scope(authorization):
    """Transaction boundary independently denies generic or merge-only admission."""
    from dev_agent.github_owner import validate_action
    data=authorization.get('action_authorization')
    validate_action(data,'DEPLOY')
    if authorization.get('authorization_contract')!='solo-owner-3' or authorization.get('action')!='MERGE_AND_DEPLOY':
        raise ValueError('explicit deployment action required before mutations')
    if data['decision']!='APPROVE' or any(authorization.get(k)!=data[k] for k in ('repository','pr','head','nonce')):
        raise ValueError('deployment scope and admitted identity differ')
