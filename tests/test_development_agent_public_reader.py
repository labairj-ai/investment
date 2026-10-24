"""Public discovery is an explicit, credential-free GET-only capability."""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import urllib.error
import urllib.request
import pytest
from dev_agent.discovery_reader import DiscoveryReader,_PublicRedirect,verify_repository
from dev_agent.github import GitHub
from dev_agent.signals import load_spool
from scripts import collect_development_signals as collector
from test_development_agent_operational_producers import discovery_install
from test_development_agent import repo,store

REPO='owner/repo';META='repos/'+REPO;RUNS=META+'/actions/runs?per_page=10';BASE='https://api.github.com/'
PUBLIC=dict(full_name=REPO,private=False,visibility='public')
PRIVATE=dict(full_name=REPO,private=True,visibility='private',permissions=dict(pull=True,push=False,admin=False,maintain=False))


class Response:
    status=200
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,n):return json.dumps(self.data).encode()


def network(monkeypatch,replies):
    calls=[];handlers=[];queue=list(replies)
    def build(*args):
        handlers.extend(args)
        def open_(request,timeout):
            calls.append(request)
            assert timeout==30 and request.get_method()=='GET' and request.data is None
            assert not any(k.lower() in {'authorization','proxy-authorization'} for k,v in request.header_items())
            reply=queue.pop(0)
            if isinstance(reply,Exception):raise reply
            return Response(reply)
        return SimpleNamespace(open=open_)
    monkeypatch.setattr(urllib.request,'build_opener',build)
    return calls,handlers


def no_credentials(monkeypatch):
    monkeypatch.setenv('DEV_AGENT_GITHUB_READ_TOKEN_FILE','/must-not-read/owner-token')
    monkeypatch.setenv('GH_TOKEN','must-not-send-owner-token');monkeypatch.setenv('GITHUB_TOKEN','must-not-send-another-token')
    monkeypatch.setenv('HTTPS_PROXY','http://owner:secret@proxy.invalid')
    for name in ('read_text','read_bytes','lstat'):
        monkeypatch.setattr(Path,name,lambda *a,**k:pytest.fail('no credential/config file reads in public transport'))
    monkeypatch.setattr(GitHub,'read',lambda *a:pytest.fail('generic credential/gh reader forbidden'))
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('no CLI fallback'))
    real=os.environ.get
    def get(key,*args):
        if key in {'GH_TOKEN','GITHUB_TOKEN','DEV_AGENT_GITHUB_READ_TOKEN_FILE'}:pytest.fail('public mode must not inspect credential configuration')
        return real(key,*args)
    monkeypatch.setattr(os.environ,'get',get)


def test_public_mode_never_reads_or_sends_credentials_or_uses_cli(monkeypatch):
    calls,handlers=network(monkeypatch,[PUBLIC,dict(workflow_runs=[]),PUBLIC])
    no_credentials(monkeypatch)
    monkeypatch.setenv('DEV_AGENT_DISCOVERY_READER_MODE','public')
    assert DiscoveryReader(REPO).read(RUNS)==dict(workflow_runs=[])
    assert [r.full_url for r in calls]==[BASE+META,BASE+RUNS,BASE+META]
    assert all(h.proxies=={} for h in handlers if isinstance(h,urllib.request.ProxyHandler))
    assert not hasattr(DiscoveryReader(REPO),'write') and not hasattr(DiscoveryReader(REPO),'publish')


@pytest.mark.parametrize('endpoint',['user','repos/other/repo',META+'/pulls',META+'/pulls/1/merge',META+'/issues/1/comments',META+'/actions/runs/1/cancel',META+'/actions/runs/1/rerun',META+'/rulesets',RUNS+'&page=2',META+'?_method=PATCH','https://api.github.com/'+META,'//evil.invalid/'+META,META+'/../repo',META+'%2factions',META+'\r\nAuthorization: secret'])
def test_unreviewed_and_write_routes_rejected_before_network_or_credentials(monkeypatch,endpoint):
    no_credentials(monkeypatch)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:pytest.fail('unreviewed endpoint must not reach network'))
    with pytest.raises(ValueError):DiscoveryReader(REPO,'public').read(endpoint)


@pytest.mark.parametrize('url',['http://api.github.com/'+META,'https://evil.invalid/'+META,'https://api.github.com.evil.invalid/'+META,'https://owner@api.github.com/'+META,'https://api.github.com:443/'+META,BASE+META+'/issues',BASE+META+'/actions/runs/1/cancel',BASE+RUNS+'&page=2'])
def test_redirects_restricted_to_exact_reviewed_https_api_endpoints(url):
    handler=_PublicRedirect({BASE+META,BASE+RUNS});request=urllib.request.Request(BASE+META)
    with pytest.raises(ValueError):handler.redirect_request(request,None,302,'redirect',{},url)


def test_same_api_redirect_stays_get_without_authentication():
    handler=_PublicRedirect({BASE+META,BASE+RUNS});request=urllib.request.Request(BASE+META,headers={'Accept':'application/vnd.github+json'})
    redirected=handler.redirect_request(request,None,302,'redirect',{},BASE+RUNS)
    assert redirected.get_method()=='GET' and redirected.data is None
    assert not any(k.lower()=='authorization' for k,v in redirected.header_items())
    for method in ('POST','PATCH','PUT','DELETE'):
        with pytest.raises(ValueError):handler.redirect_request(urllib.request.Request(BASE+META,method=method),None,302,'',{},BASE+META)
    with pytest.raises(ValueError):handler.redirect_request(urllib.request.Request(BASE+META,headers={'Authorization':'owner'}),None,302,'',{},BASE+META)


@pytest.mark.parametrize('change',[dict(private=True,visibility='private'),dict(private=False,visibility='private'),dict(private=0),dict(full_name='other/repo'),dict(visibility=None)])
def test_initial_nonpublic_or_incomplete_identity_stops_before_workflow_read(monkeypatch,change):
    data=dict(PUBLIC,**change);calls,_=network(monkeypatch,[data]);no_credentials(monkeypatch)
    with pytest.raises(ValueError):DiscoveryReader(REPO,'public').read(RUNS)
    assert len(calls)==1


def test_no_cached_public_authority_if_repo_becomes_private(monkeypatch):
    replies=[PUBLIC,dict(workflow_runs=[]),PUBLIC,dict(PUBLIC,private=True,visibility='private')]
    calls,_=network(monkeypatch,replies);no_credentials(monkeypatch)
    reader=DiscoveryReader(REPO,'public');reader.read(RUNS)
    with pytest.raises(ValueError):reader.read(RUNS)
    assert len(calls)==4  # Second collection stops before workflow data.


def test_visibility_change_during_collection_never_returns_success(monkeypatch):
    calls,_=network(monkeypatch,[PUBLIC,dict(workflow_runs=[]),dict(PUBLIC,private=True,visibility='private')]);no_credentials(monkeypatch)
    with pytest.raises(ValueError):DiscoveryReader(REPO,'public').read(RUNS)
    assert len(calls)==3


@pytest.mark.parametrize('status',[403,404,429])
def test_http_failure_never_retries_or_falls_back(monkeypatch,status):
    calls,_=network(monkeypatch,[urllib.error.HTTPError(BASE+META,status,'unavailable',{'Retry-After':'60'},None)])
    no_credentials(monkeypatch)
    with pytest.raises(urllib.error.HTTPError):DiscoveryReader(REPO,'public').read(RUNS)
    assert len(calls)==1


def test_token_mode_preserves_private_reader_and_permissions(monkeypatch):
    monkeypatch.setenv('DEV_AGENT_GITHUB_READ_TOKEN_FILE','private-fixture-path');calls=[]
    def read(client,endpoint,**kwargs):
        assert kwargs==dict(require_token=True)
        calls.append(endpoint);return copy.deepcopy(PRIVATE) if endpoint==META else dict(workflow_runs=[])
    monkeypatch.setattr(GitHub,'read',read)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:pytest.fail('public transport not selected'))
    assert DiscoveryReader(REPO,'token').read(RUNS)==dict(workflow_runs=[])
    assert calls==[META,RUNS,META]
    bad=dict(PRIVATE,permissions=dict(pull=True,push=True,admin=False,maintain=False))
    with pytest.raises(ValueError):verify_repository(bad,REPO,'token')


def test_token_mode_missing_credential_does_not_borrow_cli_or_become_public(monkeypatch):
    monkeypatch.delenv('DEV_AGENT_GITHUB_READ_TOKEN_FILE',raising=False)
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('no CLI path'))
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:pytest.fail('no public fallback'))
    with pytest.raises(ValueError):DiscoveryReader(REPO,'token').read(META)
    monkeypatch.setenv('DEV_AGENT_DISCOVERY_READER_MODE','automatic')
    with pytest.raises(ValueError):DiscoveryReader(REPO)


@pytest.mark.parametrize('status',[403,429])
def test_rate_limited_collection_invalidates_cached_success_and_stops_scout(tmp_path,monkeypatch,repo,store,status):
    from dev_agent import scheduler
    path=tmp_path/'signals.json';path.write_text(json.dumps(dict(version='development-signals-1',created=time.time(),enabled_sources=['ci','telemetry','performance'],unavailable=[],observations=[])));path.chmod(0o600)
    def unavailable(self,endpoint):
        assert not path.exists(),'cached success must be invalidated before network access'
        raise urllib.error.HTTPError(BASE+META,status,'rate limited',{},None)
    monkeypatch.setattr(DiscoveryReader,'read',unavailable)
    # Let real collection report CI failure; other required observations succeed.
    real=collector.collect
    def collect(repository,**kwargs):
        class HTTP(Response):status=200
        return real(repository,**kwargs,invoke=lambda *a,**k:SimpleNamespace(stdout='ActiveState=active\nNRestarts=0'),open_url=lambda *a,**k:HTTP({}))
    monkeypatch.setattr(collector,'collect',collect)
    assert collector.main(['--out',str(path),'--repository',REPO,'--reader-mode','public'])==1
    assert json.loads(path.read_text())['unavailable']==['ci']
    with pytest.raises(ValueError):load_spool(path)
    monkeypatch.setenv('DEVELOPMENT_SIGNAL_SPOOL',str(path))
    monkeypatch.setattr(scheduler,'scout',lambda *a,**k:pytest.fail('must stop before candidate discovery'))
    assert scheduler.discover_daily(repo,store)['status']=='FAILED'
    assert not store.list(500)


def test_public_install_needs_no_token_and_persists_explicit_mode(discovery_install,monkeypatch):
    from ops import install_discovery
    home,plan,commands,invoke=discovery_install;token=home/'.config/investment-development/github-read.token';token.unlink()
    plan['reader_mode']='public';seen=[]
    monkeypatch.setattr(install_discovery,'verify_reader',lambda client:seen.append((client.mode,client.repository)))
    assert install_discovery.apply(plan,invoke=invoke)['accepted_runs']==0
    env=(home/'.config/investment-development/collector.env').read_text()
    assert 'DEV_AGENT_DISCOVERY_READER_MODE=public' in env and 'DEV_AGENT_DISCOVERY_REPOSITORY=owner/repo' in env
    assert 'TOKEN' not in env and not token.exists() and seen==[('public',REPO)]


def test_public_install_visibility_failure_cannot_enable_timers(discovery_install,monkeypatch):
    from ops import install_discovery
    home,plan,commands,invoke=discovery_install;plan['reader_mode']='public'
    monkeypatch.setattr(install_discovery,'verify_reader',lambda client:verify_repository(dict(PUBLIC,private=True),client.repository,'public'))
    with pytest.raises(ValueError):install_discovery.apply(plan,invoke=invoke)
    assert not any('enable' in c or 'development-signal-collector.service' in c for c in commands)


@pytest.mark.parametrize('position',[0,1,2])
@pytest.mark.parametrize('status',[403,429])
def test_rate_limit_at_any_collection_stage_cannot_return_partial_success(monkeypatch,position,status):
    replies=[PUBLIC,dict(workflow_runs=[]),PUBLIC]
    replies[position]=urllib.error.HTTPError(BASE+META,status,'rate limited',{},None)
    calls,_=network(monkeypatch,replies);no_credentials(monkeypatch)
    with pytest.raises(urllib.error.HTTPError):DiscoveryReader(REPO,'public').read(RUNS)
    assert len(calls)==position+1


@pytest.mark.parametrize('failure',['interrupt','publish'])
def test_interruption_or_spool_write_failure_cannot_leave_previous_success(tmp_path,monkeypatch,failure):
    path=tmp_path/'signals.json';path.write_text('previous successful spool')
    if failure=='interrupt':
        monkeypatch.setattr(collector,'collect',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('interrupted')))
    else:
        monkeypatch.setattr(collector,'collect',lambda *a,**k:dict(unavailable=[],enabled_sources=['ci','telemetry','performance']))
        monkeypatch.setattr(collector,'write_spool',lambda *a:(_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises((RuntimeError,OSError)):collector.main(['--out',str(path),'--repository',REPO,'--reader-mode','public'])
    assert not path.exists()


def test_public_selection_does_not_change_owner_or_protection_clients(monkeypatch):
    monkeypatch.setenv('DEV_AGENT_DISCOVERY_READER_MODE','public')
    monkeypatch.delenv('DEV_AGENT_GITHUB_READ_TOKEN_FILE',raising=False)
    calls=[]
    monkeypatch.setattr(subprocess,'run',lambda command,**kw:calls.append(command) or SimpleNamespace(stdout='{"login":"owner"}'))
    assert GitHub(REPO).read('user')==dict(login='owner')
    assert calls==[['gh','api','user']]


@pytest.mark.parametrize('repository',['../repo','owner/..','owner/repo/extra','owner/repo?token=secret','owner\\repo','owner/rep%6f'])
def test_public_repository_cannot_inject_paths_or_queries(repository):
    with pytest.raises(ValueError):DiscoveryReader(repository,'public')
