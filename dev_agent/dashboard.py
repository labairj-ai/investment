"""Separate development review UI. No investment imports or database connections."""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from .store import Store


def configured_store():
    path = os.environ.get("DEVELOPMENT_CONTROL_DB", str(Path.home() / ".local/share/investment-development/development-control.sqlite3"))
    return Store(path)


def summary(store, root=None):
    rows = []
    for candidate in store.list(100):
        latest = {}
        for event in candidate["events"]: latest[event["kind"]] = event["payload"]
        rows.append(dict(candidate, latest=latest))
    from .readiness import readiness
    state=readiness(root or Path(__file__).resolve().parents[1],store)
    owner_reviews=[]
    if store.path.exists():
        with store.connect() as db:
            owner_reviews=[json.loads(r[0]) for r in db.execute("SELECT payload FROM dev_events WHERE kind='OWNER_REVIEW' ORDER BY seq DESC LIMIT 100")]
    from .software_metrics import summary as software_metrics
    return dict(ok=True, software_metrics=software_metrics(store), owner_reviews=owner_reviews, candidates=rows, readiness=state, certification=state['technical_certification'], autonomous_implementation=state['autonomous_implementation'], investment_data_access=False)


def authorized(headers, token, mutation=False):
    provided = headers.get("X-Development-Agent-Token", "")
    if not token or not hmac.compare_digest(provided.encode(), token.encode()): return False
    if mutation:
        origin = urlparse(headers.get("Origin", ""))
        if origin.scheme not in {"http", "https"} or origin.netloc != headers.get("Host", "") or origin.path not in {"", "/"}: return False
        if headers.get("Content-Type", "").split(";")[0] != "application/json": return False
    return True


def handle(handler, path, mutation=False):
    if path == "/development-agent" and not mutation:
        raw = HTML.encode()
        handler.send_response(200); handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Cache-Control", "no-store"); handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        handler.send_header("Content-Length", str(len(raw))); handler.end_headers(); handler.wfile.write(raw); return
    def send(payload, code=200):
        raw = json.dumps(payload).encode(); handler.send_response(code)
        handler.send_header("Content-Type", "application/json"); handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(raw))); handler.end_headers(); handler.wfile.write(raw)
    if not authorized(handler.headers, os.environ.get("DEV_AGENT_API_TOKEN", ""), mutation):
        return send(dict(ok=False, error="unauthorized or invalid origin"), 403)
    try:
        store = configured_store()
        from .identity import dashboard_identity
        if not mutation: return send(summary(store))
        human=dashboard_identity(handler)
        if path not in {"/api/development-agent/decision", "/api/development-agent/review", "/api/development-agent/owner-review"}: return send(dict(ok=False, error="unknown operation"), 404)
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 < length <= 16384: raise ValueError("bounded request required")
        payload = json.loads(handler.rfile.read(length))
        # Existing ledger must already be initialized by operator tooling.
        if path.endswith('/owner-review'):
            from . import owner_review
            from .github import GitHub
            human=owner_review.owner_identity(handler)
            owner_review.attest(store,GitHub(os.environ.get('DEV_AGENT_REPOSITORY','labairj-ai/investment')),payload['context'],payload['decision'],payload['nonce'],payload.get('rationale',''),human=human,financial_ack=payload.get('financial_ack'),execution_ack=payload.get('execution_ack'))
        elif path.endswith("/review"):
            if payload['stage']=='PR_DISPOSITION':
                from .github import GitHub,recheck_pr
                if recheck_pr(store,payload['candidate'],GitHub(os.environ.get('DEV_AGENT_REPOSITORY','labairj-ai/investment')))['status']!='PASS': raise ValueError('remote PR head changed')
            store.review_decision(payload["candidate"], payload["stage"], payload["decision"], human.actor, payload["context"], payload["nonce"], payload.get("rationale", ""), identity=human)
        else:
            store.decide(payload["candidate"], payload["decision"], human.actor, payload["context"], payload["nonce"], payload.get("rationale", ""), identity=human)
        return send(dict(ok=True))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return send(dict(ok=False, error="invalid, stale or replayed decision"), 409)
    except Exception:
        return send(dict(ok=False, error="development ledger unavailable"), 503)


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Development Agent</title>
<style>
[hidden]{display:none!important}*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#243246;font:16px system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:20px}a{color:#2159aa}h1{font-size:1.8rem}.notice{border-left:4px solid #b77500;padding:12px;background:#fff3d4}.controls{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}input,select,button{min-height:44px;max-width:100%;font:inherit;padding:8px;border:1px solid #9aa8ba;border-radius:6px}button{cursor:pointer;background:#fff}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #2159aa}label{display:flex;flex-direction:column;gap:5px;min-width:0}#queue{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px}article{background:white;border:1px solid #d3dbe7;border-radius:10px;padding:16px;min-width:0;overflow-wrap:anywhere}article h2{font-size:1.1rem}.badge{display:inline-block;border:1px solid #77879b;padding:4px 7px;margin:0 5px 6px 0;border-radius:5px;font-weight:600}.warning{background:#fff3d4;border-color:#b77500}.failed{background:#ffe5e5;border-color:#b52b2b}details{margin:12px 0}summary{cursor:pointer;min-height:44px;padding:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}dialog{max-width:min(95vw,500px);border:1px solid #77879b;border-radius:10px}dialog::backdrop{background:#0008}.actions{display:flex;flex-wrap:wrap;gap:8px}#message{min-height:24px} @media(max-width:430px){main{padding:12px}.controls>*{width:100%}article{padding:12px}}
</style></head><body><main><a href="/out/dashboard.html">Back to Investment Dashboard</a><h1>Development Agent</h1>
<p>Software improvement proposals and evidence</p><p class="notice">Readiness is loaded from current evidence. Review approval does not authorize merge, deployment or investment actions.</p>
<section id="readiness" aria-label="Development agent readiness"><h2>Readiness</h2><p>Not loaded. No operational readiness established.</p></section>
<div class="controls"><label>Review access token<input id="access" type="password" autocomplete="off"></label><button id="load">Load queue</button><label>Status<select id="status"><option value="">All statuses</option></select></label><label>Risk<select id="risk"><option value="">All risks</option></select></label><label>Category<select id="category"><option value="">All categories</option></select></label><label>Source<select id="source"><option value="">All sources</option></select></label><label>Sort<select id="sort"><option value="newest">Newest</option><option value="risk">Highest risk</option><option value="value">Highest value</option></select></label></div>
<p id="message" role="status" aria-live="polite">Enter the configured review token to load development evidence.</p><div id="queue"></div>
<dialog id="confirmation"><h2>Confirm development decision</h2><p id="decision-context"></p><label id="review-choice" hidden>Review disposition<select id="review-decision"><option value="escalate">Escalate</option><option value="accept">Accept review evidence</option><option value="reject">Reject</option><option value="defer">Defer</option></select></label><label>Rationale<input id="rationale" maxlength="1000"></label><p>This decision grants no merge or deployment authority. Technical safety gates remain mandatory.</p><div class="actions"><button id="confirm">Confirm decision</button><button id="cancel">Cancel</button></div></dialog>
<script>
'use strict';let records=[],pending=null;const el=id=>document.getElementById(id);const node=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n};
async function request(path,body){const response=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Development-Agent-Token':el('access').value},body:body?JSON.stringify(body):undefined});const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data}
function riskOf(c){return c.latest.PLAN?.context?.risk||'UNKNOWN'}
function render(){const queue=el('queue');queue.replaceChildren();const rows=records.filter(c=>(!el('status').value||c.state===el('status').value)&&(!el('risk').value||riskOf(c)===el('risk').value)&&(!el('category').value||c.category===el('category').value)&&(!el('source').value||c.source===el('source').value));rows.sort((a,b)=>el('sort').value==='risk'?riskOf(b).localeCompare(riskOf(a)):el('sort').value==='value'?(b.latest.SCORE?.score||0)-(a.latest.SCORE?.score||0):b.created-a.created);if(!rows.length)queue.append(node('p','No matching development candidates.'));
for(const c of rows){const card=node('article','');card.append(node('h2',c.title));for(const text of [c.state,riskOf(c),c.category,c.source])card.append(node('span',text,'badge'));if(c.state==='NEEDS_HUMAN'||['L4','L5'].includes(riskOf(c)))card.append(node('p','Human review required — protected or unresolved work','notice'));if(c.latest.ITERATION?.review?.disposition&&c.latest.ITERATION.review.disposition!=='PASS')card.append(node('p','Review gate: '+c.latest.ITERATION.review.disposition,'badge failed'));if(c.latest.SIGNAL_OBSERVATION){const s=c.latest.SIGNAL_OBSERVATION;card.append(node('p','Evidence source: '+s.source+' · Occurrences: '+s.recurrence+' · Confidence: '+s.confidence),node('p','Observed: '+new Date(s.observed_at*1000).toISOString()+' · '+s.evidence_location))}if(c.latest.ITERATION)card.append(node('p','Evidence freshness requires SHA verification before PR readiness.','notice'));card.append(node('p',c.problem),node('p','Proposed outcome: '+c.outcome));for(const [label,data]of [['Scope and evidence',{files:c.files,evidence:c.evidence,plan:c.latest.PLAN}],['Review and run history',c.events],['Deployment and effectiveness',{deployment:c.latest.DEPLOYMENT,effectiveness:c.latest.EFFECTIVENESS}]]){const detail=node('details','');detail.append(node('summary',label),node('pre',JSON.stringify(data,null,2)));card.append(detail)}const url=c.latest.PR?.result?.url;if(url){try{const u=new URL(url);if(u.origin==='https://github.com'){const a=node('a','View pull request');a.href=u.href;a.rel='noopener noreferrer';card.append(a)}}catch{}}
if(c.state==='PLANNED'&&c.latest.PLAN){const actions=node('div','','actions');for(const decision of ['approve','reject','defer']){const button=node('button',decision[0].toUpperCase()+decision.slice(1));button.onclick=()=>{pending={candidate:c.id,decision,context:c.latest.PLAN.context,nonce:crypto.randomUUID()};el('decision-context').textContent=c.title+' · '+riskOf(c)+' · '+decision;el('rationale').value='';el('review-choice').hidden=!pending.review;el('review-decision').value='escalate';el('confirmation').showModal()};actions.append(button)}card.append(actions)}
if(['NEEDS_HUMAN','PR_OPEN','DEPLOYED','ROLLED_BACK'].includes(c.state)&&c.latest.PLAN){const button=node('button','Record review / escalation');button.onclick=()=>{const context={...c.latest.PLAN.context};if(c.latest.RECEIPT?.receipt?.head)context.head=c.latest.RECEIPT.receipt.head;pending={candidate:c.id,decision:'escalate',stage:c.state==='PR_OPEN'?'PR_DISPOSITION':['DEPLOYED','ROLLED_BACK'].includes(c.state)?'OUTCOME_ACCEPTANCE':'REVIEW_OVERRIDE',context,nonce:crypto.randomUUID(),review:true};el('decision-context').textContent=c.title+' · '+riskOf(c)+' · record escalation (no merge authority)';el('rationale').value='';el('review-choice').hidden=!pending.review;el('review-decision').value='escalate';el('confirmation').showModal()};card.append(button)}queue.append(card)}}
el('load').onclick=async()=>{try{const data=await request('/api/development-agent');records=data.candidates;const ready=el('readiness');ready.replaceChildren(node('h2','Readiness: '+(data.readiness?.status||'UNAVAILABLE')));if(data.software_metrics){const m=node('details','');m.append(node('summary','Software improvement effectiveness'),node('pre',JSON.stringify(data.software_metrics,null,2)));ready.append(m)}if(data.readiness){const r=data.readiness;ready.append(node('p','Discovery scheduler: '+(r.scheduled_discovery?.status||'UNAVAILABLE')+' · Successful scheduled runs: '+(r.scheduled_discovery?.successful_runs||0)),node('p','Improvement stage: '+(r.improvement?.stage||'SHADOW')+' · Supervised loop: '+(r.improvement?.supervised_loop_enabled?'configured':'disabled')));if(data.owner_reviews?.length){const history=node('details','');history.append(node('summary','Owner review attestations (head must still match)'),node('pre',JSON.stringify(data.owner_reviews,null,2)));ready.append(history)}ready.append(node('p','Technical certification: '+r.technical_certification+' · Sandbox: '+r.sandbox_runtime),node('p','Supervised successes: '+r.supervised.completed+' / '+r.supervised.required+' · Observation days: '+r.supervised.observation_days+' / '+r.supervised.required_days),node('p','Autonomous implementation: '+(r.autonomous_implementation?'configured':'disabled')+' · Auto-merge: disabled'));if(r.certification_stale)ready.append(node('p','Certification stale: harness/config changed.','notice'));for(const blocker of r.blockers)ready.append(node('p',blocker,'notice'));const detail=node('details','');detail.append(node('summary','Readiness evidence and identities'),node('pre',JSON.stringify(r,null,2)));ready.append(detail)}for(const [field,fn]of [['status',c=>c.state],['risk',riskOf],['category',c=>c.category],['source',c=>c.source]]){const select=el(field);while(select.options.length>1)select.remove(1);for(const v of [...new Set(records.map(fn))].sort())select.append(new Option(v,v))}el('message').textContent=records.length+' development candidates. Certification: '+data.certification;render()}catch(error){el('message').textContent=error.message}};for(const id of ['status','risk','category','source','sort'])el(id).onchange=render;el('cancel').onclick=()=>{pending=null;el('confirmation').close()};el('confirm').onclick=async()=>{if(!pending)return;const body={...pending,rationale:el('rationale').value};if(body.review)body.decision=el('review-decision').value;pending=null;el('confirmation').close();try{await request(body.review?'/api/development-agent/review':'/api/development-agent/decision',body);el('load').click()}catch(error){el('message').textContent=error.message}};
</script></main></body></html>'''
