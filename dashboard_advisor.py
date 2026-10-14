"""Structured Decision rendering: all model/source text is escaped, never HTML."""


def advisor_assets():
    return r'''
<style>
.advisor-mode-controls { display:flex;gap:6px;padding:10px 14px 0;background:#fff; }
.advisor-mode-controls button { padding:6px 12px;border:1px solid #d9e1eb;border-radius:6px;background:#fff;color:#334155;cursor:pointer; }
.advisor-mode-controls button[aria-pressed="true"] { background:#eaf1fa;border-color:#5980b0;font-weight:600; }
#ad-mode-description { padding:8px 14px;font-size:11px;color:#64748b;background:#fff; }
.ad-decision { border:1px solid #dce4ef;border-radius:8px;padding:12px;background:#fff;font-size:12px;line-height:1.6; }
.ad-state { font-weight:700;display:inline-block;padding:3px 8px;border-radius:5px;background:#e9eef5;color:#334155; }
.ad-decision h4 { margin:12px 0 4px;font-size:12px; }
.ad-decision pre { white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;max-height:240px;overflow:auto;background:#f6f8fb;padding:8px;border-radius:5px; }
.ad-decision details { margin:8px 0;padding:8px;border:1px solid #e2e8f0;border-radius:6px; }
.ad-decision summary { cursor:pointer;font-weight:600; }
.ad-fields { display:grid;grid-template-columns:minmax(100px,1fr) minmax(0,2fr);gap:6px 12px;margin:10px 0; }
.ad-fields dt { color:#64748b; }.ad-fields dd { margin:0;overflow-wrap:anywhere; }
.ad-table-wrap { overflow-x:auto;margin:10px 0; }
.ad-table { width:100%;border-collapse:collapse;font-size:11px; }
.ad-table th,.ad-table td { text-align:left;padding:7px;border-bottom:1px solid #e2e8f0;vertical-align:top; }
.ad-table th { background:#f6f8fb;white-space:nowrap; }
.ad-decision li { margin:5px 0;overflow-wrap:anywhere; }
.ad-trade { padding:8px 0;border-bottom:1px solid #e9edf4;font-variant-numeric:tabular-nums; }
</style>
<script>
window.advisorMode='explore';
function setAdvisorMode(mode) {
  if (!['explore','decision'].includes(mode)) return;
  window.advisorMode=mode;
  document.getElementById('ad-account-label').style.display=mode==='decision'?'':'none';
  if (mode==='decision') loadAdvisorAccounts();
  document.querySelectorAll('[data-advisor-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.advisorMode===mode)));
  document.getElementById('ad-mode-description').textContent=mode==='decision'
    ? 'Decision: captured data, exact trade math, tax lots, Critic and risk preview. No orders are submitted.'
    : 'Explore: conversational analysis. Not a governed decision or execution approval.';
  document.getElementById('pc-input').placeholder=mode==='decision'?'e.g. Get IGV to 100 shares':'Ask about your portfolio…';
}
async function loadAdvisorAccounts() {
  const select=document.getElementById('ad-risk-account');
  if (select.dataset.loaded) return;
  try {
    const response=await fetch('/api/ai/advisor-health');
    if (!response.ok) return;
    const data=await response.json();
    (data.risk_accounts||[]).forEach(account=>{const option=document.createElement('option');option.value=account.account_id;option.textContent=account.name+' ('+account.mode+')';select.appendChild(option);});
    select.dataset.loaded='1';
  } catch(error) { /* Unspecified account stays review-only. */ }
}
function advisorLabel(key) {
  const names={st_gain_loss:'Short-term gain / loss',lt_gain_loss:'Long-term gain / loss',nav_before:'Portfolio value before',nav_after:'Portfolio value after',cc_contracts_before:'Covered-call capacity before',cc_contracts_after:'Covered-call capacity after',open_calls:'Open calls',st:'Short term',lt:'Long term'};
  return names[key]||String(key).replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
}
function advisorValue(value,key='') {
  if(value===null||value===undefined) return 'Unavailable';
  if(typeof value==='boolean') return value?'Yes':'No';
  if(typeof value==='number') {
    if(/price|notional|cash_effect|cash_before|cash_after|gain_loss|tax_drag|gross_buys|gross_sells|net_cash_requirement|position_value|nav_before|nav_after/.test(key)) return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value);
    if(/weight|pct/.test(key)) return new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value)+'%';
    return new Intl.NumberFormat('en-US',{maximumFractionDigits:8}).format(value);
  }
  return String(value).replace(/\b[A-Z][A-Z_]{2,}\b/g,s=>s.replaceAll('_',' '));
}
function renderAdvisorEvidence(parent,data,key='') {
  const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  if(data===null||data===undefined){parent.appendChild(make('p','Unavailable'));return;}
  if(Array.isArray(data)){
    if(!data.length){parent.appendChild(make('p',key==='tax_lots'?'No sale proposed; tax-lot disposition does not apply.':'None recorded.'));return;}
    if(data.every(row=>row&&typeof row==='object'&&!Array.isArray(row))){
      const columns=[...new Set(data.flatMap(row=>Object.keys(row)))];
      const wrap=make('div');wrap.className='ad-table-wrap';const table=make('table');table.className='ad-table';
      const head=make('thead'),header=make('tr');columns.forEach(column=>{const th=make('th',advisorLabel(column));th.setAttribute('scope','col');header.appendChild(th);});head.appendChild(header);table.appendChild(head);
      const body=make('tbody');data.forEach(row=>{const tr=make('tr');columns.forEach(column=>{const td=make('td');renderAdvisorEvidence(td,row[column],column);tr.appendChild(td);});body.appendChild(tr);});table.appendChild(body);wrap.appendChild(table);parent.appendChild(wrap);
    }else{const list=make('ul');data.forEach(item=>{const li=make('li');renderAdvisorEvidence(li,item,key);list.appendChild(li);});parent.appendChild(list);}
    return;
  }
  if(typeof data==='object'){
    const entries=Object.entries(data);if(!entries.length){parent.appendChild(make('p',key==='tax_lots'?'No sale proposed; tax-lot disposition does not apply.':'None recorded.'));return;}
    const fields=make('dl');fields.className='ad-fields';
    entries.filter(([,v])=>v===null||typeof v!=='object').forEach(([name,value])=>{fields.appendChild(make('dt',advisorLabel(name)));fields.appendChild(make('dd',advisorValue(value,name)));});
    if(fields.children.length)parent.appendChild(fields);
    entries.filter(([,v])=>v!==null&&typeof v==='object').forEach(([name,value])=>{const section=make('div');section.appendChild(make('h4',advisorLabel(name)));renderAdvisorEvidence(section,value,name);parent.appendChild(section);});return;
  }
  parent.appendChild(make('span',advisorValue(data,key)));
}
function renderAdvisorDecision(target, decision) {
  target.textContent='';
  const root=document.createElement('div');root.className='ad-decision';target.appendChild(root);
  const add=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;root.appendChild(e);return e;};
  if (!decision.policy) {add('strong','REVIEW_REQUIRED · Decision unavailable');add('p',decision.error||'Required evidence is unavailable.');return;}
  if(decision.request?.needs_clarification){
    add('span','Clarification needed','ad-state');
    add('p','Request: '+decision.request.raw_request);
    const raw=decision.request.raw_request||'';
    const match=raw.match(/^(?:buy|add)\s+([a-z][a-z0-9./-]*)$|^([a-z][a-z0-9./-]*)\s+(?:buy|add)$/i);
    const ticker=match?(match[1]||match[2]).toUpperCase():null;
    add('h4',ticker?'How many '+ticker+' shares would you like to buy?':'What exact trade would you like reviewed?');
    add('p','Enter an additional share quantity, or specify your final target holding. No trade has been evaluated yet.');
    add('p',ticker?'Use “Buy [quantity] '+ticker+'” or “Get '+ticker+' to [target] shares”.':'For example: “Buy 17 IGV” or “Get IGV to 100 shares”.');
    add('p','For an open question such as “Should I buy '+(ticker||'this stock')+'?”, use Explore to discuss the investment before choosing a trade size.');
    add('p','No order was submitted.');
    return;
  }
  add('span',decision.policy.decision_state,'ad-state');
  add('p','Decision-grade review only. Execution ready: no.');
  add('small','Decision '+decision.advisor_decision_id+' · '+(decision.lifecycle_status||'VALID')+' · expires '+decision.valid_until);
  add('h4','Exact trade preview');
  (decision.impact.legs||[]).forEach(leg=>{
    add('div',leg.side+' '+Math.abs(leg.delta_shares)+' '+leg.ticker+' · '+leg.before_shares+' → '+leg.after_shares+' shares · reference $'+leg.reference_price+' · notional $'+leg.notional,'ad-trade');
  });
  const technical = reason => /^(REFERENCE_PRICE_NOT_CURRENT|REQUIRED_SOURCE_|CANONICAL_BRIEF_UNAVAILABLE|THESIS_SOURCE_ERROR|EXECUTION_SOURCE_ERROR|RISK_PREVIEW_REQUIRED|CRITIC_REVIEW_REQUIRED|EXACT_TAX_LOTS_UNAVAILABLE)/.test(reason);
  const reasons=decision.policy.reasons||[];
  const readiness=reasons.filter(technical);
  const objections=reasons.filter(reason=>!technical(reason));
  const readable=reason=>{
    const [code,subject]=reason.split(':');
    if(code==='REFERENCE_PRICE_NOT_CURRENT') return subject+': a current reference price is unavailable.';
    if(code==='REQUIRED_SOURCE_NOT_CURRENT') return subject.replaceAll('_',' ')+': required evidence is stale or unavailable.';
    if(code==='RISK_PREVIEW_REQUIRED') return 'Account risk review is incomplete'+((decision.risk_preview.reasons||[]).includes('ACCOUNT_POSITION_MISMATCH')?' because the selected account positions do not match the portfolio.':'.');
    if(code==='CRITIC_REVIEW_REQUIRED') return 'Critic review is unavailable or requires further review.';
    return reason.replaceAll('_',' ');
  };
  if(readiness.length){
    add('h4','Review readiness · technical / evidence limitations');
    add('p','These limitations prevent a complete review; they are not investment reasons to avoid the trade.');
    readiness.forEach(reason=>add('p',readable(reason)));
  }
  add('h4','Proposal assessment');
  if(!objections.length) add('p',readiness.length?'No separate proposal rejection is recorded. The assessment remains incomplete.':'All decision-review gates passed.');
  objections.forEach(reason=>{
    if(reason==='CRITIC_VETO'){
      add('p','Critic veto · review gate. See the objection and missing evidence below; a veto is not necessarily an adverse investment finding.');
      (decision.critic.reviews||[]).filter(review=>review.verdict==='VETO').forEach(review=>{
        if(review.strongest_objection) add('p',(review.ticker?review.ticker+': ':'')+review.strongest_objection);
        if((review.missing_evidence||[]).length) add('p','Evidence requested: '+review.missing_evidence.join('; '));
      });
    } else add('p',readable(reason));
  });
  const sections=[['Portfolio / layer impact',decision.impact],['Tax-lot scenarios',decision.tax_lots],
    ['Thesis / candidate evidence',{theses:decision.context.theses,candidate_ranks:decision.context.candidate_ranks}],
    ['Critic',decision.critic],['Risk preview',decision.risk_preview],
    ['CC implications',(decision.impact.legs||[]).map(l=>({ticker:l.ticker,before:l.cc_contracts_before,after:l.cc_contracts_after,open_calls:l.open_call_contracts}))],
    ['Expiry / invalidation',decision.invalidating_conditions]];
  sections.forEach(([title,data])=>{const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=title;details.appendChild(summary);renderAdvisorEvidence(details,data,title==='Tax-lot scenarios'?'tax_lots':'');root.appendChild(details);});
  add('h4','Explanation · not authoritative');add('p',decision.explanation);
  const button=document.createElement('button');button.textContent='Convert to paper intent · unavailable';button.disabled=true;root.appendChild(button);
}
async function sendAdvisorDecision(text,target) {
  target.textContent='Checking context, trade math, tax lots, Critic and risk…';
  const response=await fetch('/api/ai/decision',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({request:text,advisor_decision_id:crypto.randomUUID(),account_id:document.getElementById('ad-risk-account').value||null})});
  const result=await response.json();
  if (!response.ok) throw new Error(result.error||'Decision unavailable');
  renderAdvisorDecision(target,result);
  return result;
}
</script>
'''
