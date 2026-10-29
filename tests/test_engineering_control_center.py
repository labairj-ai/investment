"""Presentation security uses disposable development ledgers, never investment data."""
import base64
import hashlib
from http.client import HTTPMessage
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from dev_agent import control_center as cc
from dev_agent.store import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path/'control/development-control.sqlite3'); s.migrate(); return s


@pytest.fixture
def root(tmp_path):
    p = tmp_path/'repo'; p.mkdir()
    subprocess.run(['git','init','-b','fixture',str(p)], check=True, capture_output=True)
    (p/'config').mkdir(); (p/'config/development_agent.json').write_bytes((ROOT/'config/development_agent.json').read_bytes())
    subprocess.run(['git','-C',str(p),'add','.'], check=True)
    subprocess.run(['git','-C',str(p),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture'], check=True, capture_output=True)
    return p


@pytest.fixture
def center(root, store):
    return cc.ControlCenter(root, store, now=2_000_000_000)


def candidate(store, n=0):
    return store.discover(dict(source='user', title=f'Candidate {n}', problem=f'Document missing detail {n}', outcome='Clear instructions', evidence=[f'docs/note.md:{n}'], files=['docs/note.md'], category='DOCUMENT'))


def fingerprint(store):
    return hashlib.sha256(store.path.read_bytes()).hexdigest()


class Handler:
    def __init__(self, **headers):
        self.headers = HTTPMessage()
        for k,v in headers.items(): self.headers[k.replace('_','-')] = v
        self.wfile = io.BytesIO(); self.response_headers = {}; self.client_address = ('127.0.0.1',123)
        self.server = SimpleNamespace(server_address=('127.0.0.1',5001))
    def send_response(self, code): self.code = code
    def send_header(self, key, value): self.response_headers[key] = value
    def end_headers(self): pass
    def data(self): return json.loads(self.wfile.getvalue())


def test_route_off_by_default(monkeypatch):
    monkeypatch.delenv('DEV_AGENT_ECC_ENABLED', raising=False)
    h=Handler(); cc.handle(h,cc.API+'overview'); assert h.code==404
    assert h.response_headers['Cache-Control']=='no-store'


@pytest.mark.parametrize('headers', [{}, {'Host':'example.test','Origin':'https://evil.test','X_Development_Agent_Token':'fixture'}, {'Host':'example.test','Sec_Fetch_Site':'cross-site','X_Development_Agent_Token':'fixture'}, {'Host':'example.test','Origin':'null','X_Development_Agent_Token':'fixture'}, {'Host':'example.test','Origin':'https://example.test/?bad=1','X_Development_Agent_Token':'fixture'}])
def test_reader_denied(monkeypatch, headers):
    monkeypatch.setenv('DEV_AGENT_ECC_ENABLED','1'); monkeypatch.setenv('DEV_AGENT_API_TOKEN','fixture')
    h=Handler(**headers); cc.handle(h,cc.API+'candidates'); assert h.code==403
    assert 'fixture' not in h.wfile.getvalue().decode()


def test_authenticated_proxy_reader_has_no_browser_token(monkeypatch):
    monkeypatch.delenv('DEV_AGENT_API_TOKEN', raising=False)
    monkeypatch.setenv('DEV_AGENT_IDENTITY_SOURCE','tailscale-serve'); monkeypatch.setenv('DEV_AGENT_OPERATORS','owner@example.test')
    h=Handler(Host='example.test', Origin='https://example.test', Tailscale_User_Login='owner@example.test')
    assert cc.reader_authorized(h)
    h.client_address=('192.0.2.1',123); assert not cc.reader_authorized(h)
    h.client_address=('127.0.0.1',123); h.headers['Tailscale-User-Login']='owner@example.test'; assert not cc.reader_authorized(h)


def test_read_route_and_cross_project_denied(monkeypatch, store):
    from dev_agent import dashboard
    monkeypatch.setenv('DEV_AGENT_ECC_ENABLED','1'); monkeypatch.setenv('DEV_AGENT_API_TOKEN','fixture')
    monkeypatch.setattr(dashboard,'configured_store',lambda:store)
    before=fingerprint(store)
    h=Handler(Host='example.test',X_Development_Agent_Token='fixture'); cc.handle(h,cc.API+'candidates')
    assert h.code==200 and h.data()['items']==[] and fingerprint(store)==before
    assert h.response_headers['X-Frame-Options']=='DENY'
    assert 'unsafe-inline' not in h.response_headers['Content-Security-Policy']
    for path in ['/api/engineering/v1/projects/other/candidates',cc.API+'../other',cc.API+'owner-review']:
        h=Handler(X_Development_Agent_Token='fixture'); cc.handle(h,path); assert h.code==404
    h=Handler(X_Development_Agent_Token='fixture');cc.handle(h,cc.API+'decision',mutation=True);assert h.code==405 and fingerprint(store)==before


def test_readstore_refuses_writes(store):
    s=cc.ReadStore(store.path)
    with pytest.raises(ValueError):
        with s.connect(True): pass
    with s.connect() as db:
        with pytest.raises(Exception): db.execute('DELETE FROM dev_events')


@pytest.mark.parametrize('query',['limit=0','limit=51','limit=100','limit=-1','sort=random','risk=L7','state=INVENTED','source=broker','category=TRADE','search=a&search=b','unknown=x','search='+('a'*121),'cursor=!!','search=token&cursor=x'])
def test_bad_queries(center, query):
    with pytest.raises(ValueError): center.candidates(query)


def test_paging_stable_with_appends(center, store):
    ids={candidate(store,i) for i in range(121)}
    before=fingerprint(store)
    first=center.candidates('limit=17&sort=oldest')
    assert first['total']==121 and len(first['items'])==17
    assert fingerprint(store)==before
    inserted=candidate(store,200)
    store.event(next(iter(ids)),'SCORE',{'score':100},'new-score')
    found=[i['id'] for i in first['items']]; cursor=first['next_cursor']
    while cursor:
        page=center.candidates(urlencode(dict(limit=17,sort='oldest',cursor=cursor)))
        found.extend(i['id'] for i in page['items']);cursor=page['next_cursor']
    assert len(found)==len(set(found))==121 and set(found)==ids and inserted not in found
    with pytest.raises(ValueError): center.candidates(urlencode(dict(sort='risk',cursor=first['next_cursor'])))


def test_risk_value_filters_search_and_unknown(center, store):
    a=candidate(store,1);b=candidate(store,2)
    store.event(a,'PLAN',{'context':{'risk':'L5','head':'a'*40}},'plan-a')
    store.event(a,'SCORE',{'score':4,'version':'value-risk-1'},'score-a')
    store.event(b,'SCORE',{'score':8,'version':'value-risk-1'},'score-b')
    assert center.candidates('sort=value')['items'][0]['id']==b
    assert center.candidates('sort=risk')['items'][0]['id']==a
    assert center.candidates('risk=L5')['items'][0]['blocker'].startswith('Review financial')
    assert len(center.candidates('search=docs%2Fnote')['items'])==2
    assert center.candidates('risk=UNKNOWN')['items'][0]['id']==b
    assert center.candidates('search=%25')['items']==[]  # literal search, not LIKE wildcard


def test_snapshot_cursor_tamper(center, store):
    for n in range(3):candidate(store,n)
    c=center.candidates('limit=1')['next_cursor']
    obj=json.loads(base64.urlsafe_b64decode(c));obj['seq']=10**12
    forged=base64.urlsafe_b64encode(json.dumps(obj).encode()).decode()
    with pytest.raises(ValueError):center.candidates(urlencode(dict(limit=1,cursor=forged)))


def test_candidate_detail_bounded_redaction_and_history(center, store):
    cid=candidate(store)
    # Simulate a compromised historical payload without weakening Store.bounded.
    with store.connect(True) as db:
        db.execute('INSERT INTO dev_events(event_id,candidate,kind,created,payload) VALUES (?,?,?,?,?)', ('note',cid,'NOTE',center.now-1,json.dumps({'problem':'<img src=x onerror=alert(1)>','raw_prompt':'PRIVATE','holdings':{'secret':'PRIVATE'},'outcome':'Bearer fake-value'})))
    for n in range(101):store.event(cid,'NOTE',{'status':'FAIL','problem':f'Failure {n}'},f'note-{n}')
    before=fingerprint(store); d=center.candidate(cid)
    assert not d['timeline_complete'] and len(d['timeline'])==100 and d['actions']['build'] is False
    assert 'PRIVATE' not in json.dumps(d) and fingerprint(store)==before
    with pytest.raises(cc.NotFound):center.candidate('not-found')
    with pytest.raises(ValueError):center.candidate('../../out/investment.db')
    assert cc.safe_detail({'problem':'Bearer fake-value','raw_prompt':'PRIVATE'})=={'problem':'[redacted]'}


def test_audit_paging_and_csv_injection(center, store):
    cid=candidate(store)
    for n in range(8):store.event(cid,'NOTE',{'actor':'=HYPERLINK("evil")','raw_prompt':'PRIVATE','status':'FAIL'},f'=event-{n}')
    before=fingerprint(store); a=center.audit('kind=NOTE&limit=3&format=csv')
    candidate(store,100)
    b=center.audit(urlencode(dict(kind='NOTE',limit=3,format='csv',cursor=a['next_cursor'])))
    assert not set(e['seq'] for e in a['items']) & set(e['seq'] for e in b['items'])
    raw=cc.csv_export(a).decode()
    assert "'=event-" in raw and "'=HYPERLINK" in raw and 'PRIVATE' not in raw
    assert 'UNVERIFIED_LEDGER_CLAIM' in raw and 'exported_at_utc' in raw
    filtered=center.audit(urlencode(dict(candidate=cid,status='FAIL')))
    assert len(filtered['items'])==8
    assert before!=fingerprint(store) # only our explicit concurrent append changed it
    after=fingerprint(store);center.audit();assert fingerprint(store)==after


@pytest.mark.parametrize('query',['pr=0','pr=1 OR 1=1','since=nan','since=99999999999999','kind=bad%2Fpath','format=exe','cursor=bad'])
def test_bad_audit_queries(center,query):
    with pytest.raises(ValueError):center.audit(query)


def test_evidence_fails_closed(center):
    for observed in (None,center.now+1,center.now-301):
        d=center.judgment('PASS','TEST','Test',observed=observed,ttl=300,verifier='EXISTING_GATE')
        assert d['status'] in {'STALE','UNAVAILABLE'}
    assert center.judgment('PASS','TEST','Test',observed=center.now)['status']=='UNAVAILABLE'
    assert center.judgment('made-up','TEST','Test')['status']=='UNAVAILABLE'


def test_empty_overview_and_certification_do_not_manufacture_readiness(center,store):
    before=fingerprint(store)
    o=center.overview();c=center.certification()
    assert o['readiness']['status']!='READY' and o['metrics']['owner_decisions'] is None
    assert c['technical']['status']!='PASS' and c['autonomy']['eligible'] is False
    assert c['scout']['successful_runs'] in (None,0)
    assert fingerprint(store)==before
    assert o['autonomy_configuration']['source']=='committed-configuration-not-host-observation'


def test_real_projection_delegates_owner_readiness(center,store,monkeypatch):
    candidate(store)
    monkeypatch.setattr(center,'projections',lambda:dict(owner={'status':'NOT READY','reason':'Safety stop'},blockers=['Safety stop','Missing certificate'],scheduled_discovery={}))
    o=center.overview()
    assert o['readiness']['status']=='NOT READY' and o['blockers'][0]['reason']=='Safety stop'
    assert o['metrics']['candidate_backlog']==1
    monkeypatch.setattr(center,'projections',lambda:dict(owner={'status':'READY','reason':'Existing admission passed'},blockers=[]))
    assert center.overview()['readiness']['status']=='READY'


def test_validation_forged_pass_never_credited(center,store):
    cid=candidate(store)
    with store.connect(True) as db:
        store._append(db,cid,'RECEIPT',dict(receipt={'status':'PASS','trusted_validation':True,'head':center.head,'validations':[{'name':'full_suite','status':'PASS','exit_code':0}]}),'fake-receipt')
    before=fingerprint(store);v=center.validation(cid)
    from dev_agent.validation import GATES
    from scripts.aggregate_release_validation import GATES as CI_GATES
    assert [i['name'] for i in v['items']]==list(GATES)
    assert v['repository_ci_manifest']['gates']==list(CI_GATES)
    assert not v['all_required_pass'] and all(i['evidence']['status']=='UNAVAILABLE' for i in v['items'])
    assert all(i['inventory'] is None for i in v['items']) and fingerprint(store)==before


def test_validation_wrong_head_stale(center,store):
    cid=candidate(store)
    with store.connect(True) as db:store._append(db,cid,'RECEIPT',dict(receipt={'head':'a'*40,'status':'PASS'}),'stale-receipt')
    assert all(i['evidence']['status']=='STALE' for i in center.validation(cid)['items'])


def test_foreign_database_not_read_or_modified(root,tmp_path):
    import sqlite3
    path=tmp_path/'development-control.sqlite3'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE holdings(secret)')
    s=Store(path);before=path.read_bytes();c=cc.ControlCenter(root,s)
    with pytest.raises(ValueError):c.candidates()
    assert path.read_bytes()==before


def test_oversized_and_unknown_payloads(center,store):
    cid=candidate(store)
    with store.connect(True) as db:store._append(db,cid,'STATE',{'state':'INVENTED'},'unknown-state')
    with pytest.raises(ValueError):center.candidates()
    with pytest.raises(ValueError):cc.decode('{"x":"'+'a'*40000+'"}')
    with pytest.raises(ValueError):cc.decode('{"status":"PASS","status":"FAIL"}')


def test_all_engineering_write_routes_intercept_before_financial_routes():
    import ast
    tree=ast.parse((ROOT/'serve.py').read_text())
    handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
    for name in ('do_GET','do_POST','do_PUT','do_PATCH','do_DELETE'):
        fn=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name==name)
        early=ast.unparse(fn.body[1]);assert '/api/engineering/' in early and '/engineering/' in early
        if name!='do_GET':assert 'mutation=True' in early


def test_malformed_and_duplicate_origin_denied(monkeypatch):
    monkeypatch.setenv('DEV_AGENT_API_TOKEN','fixture')
    h=Handler(Host='example.test',Origin='https://[',X_Development_Agent_Token='fixture')
    assert not cc.reader_authorized(h)
    h=Handler(Host='example.test',X_Development_Agent_Token='fixture');h.headers['Host']='other.test'
    assert not cc.reader_authorized(h)


def test_verified_receipt_fields_and_freshness_delegate(center,store,monkeypatch):
    from dev_agent import evidence,validation
    cid=candidate(store)
    records=[dict(name=name,status='PASS',ended_at=center.now-20,base='b'*40,head=center.head,exit_code=0,source_hash='c'*64,trusted_test_tree_hash='d'*64,sandbox_image_digest='fixture@sha256:'+'e'*64,inventory={'total':4,'passed':3,'skipped':['fixture::skip'],'failures':[]}) for name in validation.GATES]
    with store.connect(True) as db:store._append(db,cid,'RECEIPT',dict(receipt=dict(id='f'*64,head=center.head,validations=records)),'verified-fixture-receipt')
    called=[]
    def verifier(root,readonly,candidate_id,receipt):
        assert isinstance(readonly,cc.ReadStore);called.append(candidate_id);return True
    monkeypatch.setattr(evidence,'trusted_receipt',verifier)
    result=center.validation(cid)
    assert called==[cid] and result['all_required_pass']
    assert result['items'][0]['inventory']['skip_count']==1
    center.now+=86401
    assert not center.validation(cid)['all_required_pass']


def test_pr_preview_uses_read_only_current_apis_and_never_enables_action(center,monkeypatch):
    from dev_agent import github,owner_review
    class Reader:
        repository=cc.REPOSITORY
        def read(self,path):
            if '/check-runs?' in path:return dict(total_count=1,check_runs=[dict(id=1,name='test',head_sha='a'*40,status='completed',conclusion='success')])
            return dict(head={'sha':'a'*40,'ref':'fixture'},base={'sha':'b'*40,'ref':'main'})
        def read_all(self,path):return [{'filename':'docs/note.md'}]
        def protections(self):raise ValueError('incomplete bypass visibility')
        def pr_identity(self,number):return dict(headRefOid='a'*40)
    monkeypatch.setattr(github,'GitHub',lambda repository:Reader())
    monkeypatch.setattr(owner_review,'context',lambda *a,**kw:dict(head='a'*40,risk='L5'))
    monkeypatch.setattr(owner_review,'state',lambda *a,**kw:dict(status='MISSING'))
    result=center.pr('31')
    assert result['ci']['status']=='PASS' and result['ci']['reason_code']=='REPOSITORY_CI_ONLY'
    assert result['protection']['status']=='UNAVAILABLE' and result['oracle']['status']=='UNAVAILABLE'
    assert not result['actions']['go'] and not result['actions']['no_go']
    assert result['deployment']['status']=='UNAVAILABLE' and result['owner_disposition']=='MISSING'
    assert result['url']=='https://github.com/labairj-ai/investment/pull/31'
    Reader.pr_identity=lambda self,number:dict(headRefOid='c'*40)
    with pytest.raises(ValueError):center.pr('31')


def test_assets_are_gated_no_tokens_or_inline_script(monkeypatch):
    for path in (cc.PAGE,'/engineering/assets/control-center.js','/engineering/assets/control-center.css'):
        monkeypatch.delenv('DEV_AGENT_ECC_ENABLED',raising=False)
        h=Handler();cc.handle(h,path);assert h.code==404
        monkeypatch.setenv('DEV_AGENT_ECC_ENABLED','1')
        h=Handler();cc.handle(h,path);assert h.code==403
        monkeypatch.setenv('DEV_AGENT_API_TOKEN','fixture-actual-service-value')
        h=Handler(X_Development_Agent_Token='fixture-actual-service-value');cc.handle(h,path)
        assert h.code==200 and b'fixture-actual-service-value' not in h.wfile.getvalue()
        assert 'unsafe-inline' not in h.response_headers['Content-Security-Policy']
    html=(ROOT/'dev_agent/control_center_assets/index.html').read_text()
    js=(ROOT/'dev_agent/control_center_assets/control-center.js').read_text()
    assert '<script src=' in html and 'type="password"' not in html
    assert 'innerHTML' not in js and 'X-Development-Agent-Token' not in js


@pytest.mark.parametrize('path',['/dev_agent/control_center_assets/index.html','/dev_agent/%63ontrol_center_assets/control-center.js','/foo/../dev_agent/control_center_assets/control-center.css','/%64ev_agent/control_center_assets/index.html'])
def test_static_fallback_cannot_bypass_flag(path):
    assert cc.source_asset_request(path)
    assert not cc.source_asset_request('/out/dashboard.html')


def test_head_response_has_no_body(monkeypatch):
    monkeypatch.setenv('DEV_AGENT_ECC_ENABLED','1')
    h=Handler();h.command='HEAD';cc.handle(h,cc.PAGE,mutation=True)
    assert h.code==405 and h.wfile.getvalue()==b''


def test_export_formats_share_the_exact_snapshot_page(center,store):
    cid=candidate(store)
    for n in range(8):store.event(cid,'NOTE',{'status':'FAIL'},f'note-{n}')
    original=center.audit('kind=NOTE&limit=3')
    store.event(cid,'NOTE',{'status':'FAIL'},'newer-note')
    csv_page=center.audit(urlencode(dict(kind='NOTE',limit=3,format='csv',cursor=original['page_cursor'])))
    assert [i['seq'] for i in original['items']]==[i['seq'] for i in csv_page['items']]
    second=center.audit(urlencode(dict(kind='NOTE',limit=3,cursor=original['next_cursor'])))
    csv_second=center.audit(urlencode(dict(kind='NOTE',limit=3,format='csv',cursor=second['page_cursor'])))
    assert [i['seq'] for i in second['items']]==[i['seq'] for i in csv_second['items']]


def test_scope_truncation_is_explicit():
    view=cc.safe_detail({'files':['docs/note.md']*80,'problem':'x'*2000})
    assert view['files']['complete'] is False and view['files']['total']==80
    assert 'truncated' in view['problem']


def test_committed_configuration_is_not_dirty_host_file(root,store):
    cfg=root/'config/development_agent.json'
    value=json.loads(cfg.read_text());value['autonomous_implementation']=True;cfg.write_text(json.dumps(value))
    current=cc.ControlCenter(root,store)
    assert not current.source_clean
    assert current.configuration()['values']['autonomous_implementation'] is False
    assert current.judgment('READY','TEST','Test',observed=current.now,verifier='EXISTING_GATE')['status']=='UNAVAILABLE'


def test_projection_cannot_outlive_underlying_proof(center):
    assert center.projection_deadline({'github_protection':{'created':center.now-299}})==center.now+1
    assert center.projection_deadline({})==center.now+60


def test_legacy_and_new_owner_gate_parity(center,store,root,monkeypatch):
    from dev_agent import dashboard,readiness,promotion,software_metrics
    state=dict(owner={'status':'NOT READY','reason':'Fixture supervised safety stop'},technical_certification='NOT_RUN',autonomous_implementation=False,blockers=['Fixture supervised safety stop'])
    monkeypatch.setattr(readiness,'readiness',lambda *a,**kw:state)
    monkeypatch.setattr(promotion,'report',lambda *a,**kw:{'fixture_only':True})
    monkeypatch.setattr(software_metrics,'summary',lambda *a,**kw:{'fixture_only':True})
    legacy=dashboard.summary(store,root)
    current=center.overview()
    assert current['readiness']['status']==legacy['readiness']['owner']['status']
    assert current['readiness']['reason_summary']==legacy['readiness']['owner']['reason']


def test_reads_never_open_financial_database_or_change_sentinels(center,store,root,monkeypatch):
    import sqlite3
    (root/'out').mkdir()
    protected=[root/'holdings.csv',root/'out/investment.db',root/'out/buffett.db']
    for p in protected:p.write_bytes(b'DISPOSABLE SYNTHETIC SENTINEL ONLY')
    before={p:p.read_bytes() for p in protected}; ledger=fingerprint(store)
    original=sqlite3.connect;opened=[]
    def connect(path,*a,**kw):
        opened.append(str(path));assert 'development-control.sqlite3' in str(path)
        return original(path,*a,**kw)
    monkeypatch.setattr(sqlite3,'connect',connect)
    cid=candidate(store)
    ledger=fingerprint(store)
    for endpoint in ('overview','certification','candidates','candidates/'+cid,'validations/'+cid,'audit','prs'):
        center.dispatch(endpoint)
    assert opened and fingerprint(store)==ledger and {p:p.read_bytes() for p in protected}==before


def test_overview_excludes_terminal_candidates_from_active_backlog(center,store,monkeypatch):
    closed=candidate(store,1);open_id=candidate(store,2)
    with store.connect(True) as db:store._append(db,closed,'STATE',{'state':'CLOSED'},'closed-fixture')
    monkeypatch.setattr(center,'projections',lambda:dict(owner={'status':'NOT READY','reason':'Fixture'},blockers=[]))
    d=center.overview()
    assert d['metrics']['candidate_backlog']==1 and [c['id'] for c in d['priority_queue']]==[open_id]
    assert center.candidates()['total']==2
    with pytest.raises(ValueError):center.candidates('active=bogus')


def test_old_frozen_plan_is_retained_beyond_timeline_page(center,store):
    cid=candidate(store)
    store.event(cid,'PLAN',{'context':{'risk':'L5','head':'a'*40},'criteria':['Measured acceptance']},'frozen-plan')
    for n in range(120):store.event(cid,'NOTE',{'status':'FAIL'},f'n-{n}')
    detail=center.candidate(cid)
    assert not detail['timeline_complete'] and detail['latest']['PLAN']['context']['head']=='a'*40
    assert detail['latest']['PLAN']['criteria']==['Measured acceptance']


def test_audit_owner_context_and_disposition_are_inspectable_claims(center,store):
    with store.connect(True) as db:
        store._append(db,None,'OWNER_REVIEW',dict(context={'pr':31,'head':'a'*40,'risk':'L5'},decision='REQUEST_CHANGES',actor='owner',authentication_source='github-owner-object',origin={'id':123}),'fixture-owner-no-go')
    d=center.audit('pr=31&status=REQUEST_CHANGES')
    assert len(d['items'])==1
    e=d['items'][0]
    assert e['pr']==31 and e['head_sha']=='a'*40 and e['risk']=='L5'
    assert e['details']['decision']=='REQUEST_CHANGES' and e['receipt_id']=='123'
    assert e['claimed_identity_source']=='github-owner-object' and e['actor_identity_source']=='UNVERIFIED_LEDGER_CLAIM'
    assert e['status']['status']=='UNAVAILABLE'


@pytest.mark.parametrize('head',[123,False,'',{'raw_prompt':'PRIVATE'},['PRIVATE']])
def test_untrusted_head_metadata_is_never_echoed_or_credited(center,head):
    d=center.judgment('PASS','TEST','Test',observed=center.now,head=head,verifier='EXISTING_GATE')
    assert d['head_sha'] is None and d['status']=='UNAVAILABLE' and 'PRIVATE' not in json.dumps(d)
