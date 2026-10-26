"""Deployment checkout -> real migration PLAN with synthetic host transport/state."""
import json
import subprocess
from pathlib import Path
import pytest
from ops.discovery import migrate as m,pin_refresh as r,influence as a
from test_development_agent_observer_refresh import host
from test_development_agent_scout_migration import migration,executor_checkout
from test_development_agent_stopped_recovery import stopped


@pytest.mark.parametrize('cached_ref',['stale','absent'])
def test_executor_detached_checkout_enters_stopped_plan(stopped,monkeypatch,cached_ref):
 h=stopped;source=Path(__file__).resolve().parents[1]
 target=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
 old='43d4fda5d7c032290d51574a6d2f283d09127ee4';remote=h.base/'integration-remote.git'
 subprocess.run(['git','init','--bare','--quiet','--initial-branch=main',str(remote)],check=True)
 subprocess.run(['git','-C',str(source),'push','--quiet',str(remote),old+':refs/heads/main'],check=True)
 root=h.base/'deployed-source'
 subprocess.run(['git','clone','--no-local','--quiet',str(remote),str(root)],check=True)
 h.ROOT=root;monkeypatch.setattr(r,'ROOT',root)
 assert h.git('rev-parse','HEAD')==old and h.git('rev-parse','origin/main')==old
 h.git('remote','set-url','origin','https://github.com/labairj-ai/investment.git')
 subprocess.run(['git','-C',str(source),'push','--quiet',str(remote),target+':refs/heads/main'],check=True)
 executor_checkout(h,target,remote)
 assert h.git('rev-parse','HEAD')==target and h.git('branch','--show-current')==''
 assert h.git('rev-parse','origin/main')==old!=target
 if cached_ref=='absent':h.git('update-ref','-d','refs/remotes/origin/main')
 # PR26's unchanged generic helper rejects this legitimate deployed checkout.
 with pytest.raises((ValueError,subprocess.CalledProcessError)):r.prepare(root,target,'labairj-ai/investment')
 h.old=old;h.head=target;h.old_config=r.configuration(old,r.source_manifest(root,old))
 for name,key in [('OLD_HEAD',old),('OLD_OBSERVER',h.old_config['observer_digest']),('OLD_UNIT',h.old_config['files'][r.IDENTITIES[1]]),('OLD_SERVICE',h.old_config['unit_digest']),('OLD_TIMER',h.old_config['timer_digest'])]:monkeypatch.setattr(m,name,key)
 h.CONFIG.write_bytes(r.encoded(h.old_config));h.SOURCE.write_bytes(r.git(root,'show',old+':'+r.IDENTITIES[0]));h.UNIT.write_bytes(r.git(root,'show',old+':'+r.IDENTITIES[1]))
 for name in r.IDENTITIES[2:]:(h.USER_UNITS/Path(name).name).write_bytes(r.git(root,'show',old+':'+name))
 assert not h.git('ls-files','holdings.csv','out/investment.db','out/buffett.db')
 (root/'holdings.csv').write_text('synthetic holdings');(root/'out').mkdir(exist_ok=True)
 for name in ['investment.db','buffett.db']:(root/'out'/name).write_bytes(b'synthetic protected financial state')
 monkeypatch.setattr(m,'audit',a.audit)
 before=h.snapshot();config=h.CONFIG.read_bytes();inventory=set(h.CONFIG.parent.iterdir());ledger=(h.CONTROL/'development-control.sqlite3').read_bytes()
 result=h.migrate()
 assert result['status']=='PLAN_ONLY' and result['start_mode']=='STOPPED_ROLLBACK' and result['changes_applied'] is False and result['accepted_runs']==0
 assert result['untracked_source_influence']['untracked_source_influence']=='PASS' and not result['untracked_source_influence']['rejected_paths']
 assert h.snapshot()==before and h.CONFIG.read_bytes()==config and set(h.CONFIG.parent.iterdir())==inventory and (h.CONTROL/'development-control.sqlite3').read_bytes()==ledger
 assert not h.active and not h.user_active and not h.user_enabled and not h.system_active and h.starts==h.stops==0 and not list(h.STATE.iterdir())
 assert any('fetch' in c for c in h.checkout_calls) and any('merge-base' in c for c in h.checkout_calls) and any('checkout' in c and '--detach' in c for c in h.checkout_calls)


@pytest.mark.parametrize('attack,code',[
 ('head','DEPLOYED_SOURCE_SHA_INVALID'),('main_branch','DEPLOYED_SOURCE_SHA_INVALID'),('missing','DEPLOYED_SOURCE_SHA_INVALID'),
 ('dirty','DEPLOYED_SOURCE_DIRTY'),('origin','REPOSITORY_ORIGIN_INVALID'),('ancestor','OLD_BOUNDARY_INVALID'),
 ('manifest','DEPLOYED_SOURCE_AUTHORITY_INVALID'),('hook','DEPLOYED_SOURCE_AUTHORITY_INVALID'),
 ('filter','DEPLOYED_SOURCE_AUTHORITY_INVALID'),('replace','DEPLOYED_SOURCE_AUTHORITY_INVALID'),
])
def test_deployed_source_attacks_fail_closed(stopped,monkeypatch,attack,code):
 h=stopped
 if attack=='head':h.git('checkout','--detach',h.old)
 elif attack=='main_branch':h.git('checkout','-B','main',h.old)
 elif attack=='missing':h.head='b'*40
 elif attack=='dirty':(h.ROOT/'docs/help.md').write_text('dirty tracked source')
 elif attack=='origin':h.git('remote','set-url','origin','https://github.com/untrusted/other.git')
 elif attack=='ancestor':
  tree=h.git('rev-parse','HEAD^{tree}')
  unrelated=subprocess.check_output(['git','-C',str(h.ROOT),'commit-tree',tree],input=b'unrelated fixture root\n').decode().strip()
  h.old=unrelated;monkeypatch.setattr(m,'OLD_HEAD',unrelated)
 elif attack=='manifest':
  h.git('update-index','--assume-unchanged','docs/help.md');(h.ROOT/'docs/help.md').write_text('hidden manifest mismatch')
  assert not h.git('status','--porcelain','--untracked-files=no')
 elif attack=='hook':(h.ROOT/'.git/hooks/pre-commit').write_text('untrusted executable hook')
 elif attack=='filter':h.git('config','filter.untrusted.clean','untrusted-command')
 elif attack=='replace':h.git('replace',h.old,h.head)
 result=h.migrate()
 assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and result['failure_stage']=='PREFLIGHT_VERIFIED' and result['failure_code']==code and result['changes_applied'] is False
 assert h.starts==h.stops==0 and not h.active and not h.user_active and not h.system_active and not list(h.STATE.iterdir())


@pytest.mark.parametrize('attack,code',[
 ('old_bytes','OLD_BOUNDARY_INVALID'),('socket','STOPPED_OBSERVER_INVALID'),('user_unit','OLD_USER_SCOUT_BOUNDARY_INVALID'),
 ('acceptance','ACCEPTANCE_PRECONDITION_INVALID'),('signals','OPERATIONAL_SIGNALS_MISSING'),
 ('collision','SYSTEM_BOUNDARY_COLLISION'),('loaded','SYSTEM_UNIT_STATE_INVALID'),
])
def test_precise_host_preflight_failures(stopped,monkeypatch,attack,code):
 h=stopped
 if attack=='old_bytes':h.SOURCE.write_text('wrong old bytes')
 elif attack=='socket':h.SOCKET.write_text('stale socket')
 elif attack=='user_unit':(h.USER_UNITS/'development-scout.service').write_text('wrong user unit')
 elif attack=='acceptance':(h.STATE/'discovery.json').write_text('{"runs":[]}')
 elif attack=='signals':(h.CONTROL/'operational-signals.json').unlink()
 elif attack=='collision':(m.SYSTEM/'development-scout.timer').write_text('collision')
 elif attack=='loaded':
  original=m.properties
  def properties(invoke,name,user=False):
   result=original(invoke,name,user)
   if not user:result['LoadState']='loaded'
   return result
  monkeypatch.setattr(m,'properties',properties)
 result=h.migrate()
 assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and result['failure_code']==code and result['failure_stage']=='PREFLIGHT_VERIFIED'
 assert h.starts==h.stops==0 and not h.active and not h.user_active and not h.system_active
 assert code in m.FAILURE_CODES


def test_source_exception_text_is_sanitized(stopped,monkeypatch):
 def fail(*args):raise RuntimeError('credentials holdings SQL /private/untrusted')
 monkeypatch.setattr(m,'deployed_source',fail);result=stopped.migrate()
 assert result['failure_code']=='DEPLOYED_SOURCE_AUTHORITY_INVALID'
 assert all(value not in json.dumps(result) for value in ['credentials','holdings SQL','/private/untrusted','RuntimeError'])
