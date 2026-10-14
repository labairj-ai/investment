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
function renderAdvisorDecision(target, decision) {
  target.textContent='';
  const root=document.createElement('div');root.className='ad-decision';target.appendChild(root);
  const add=(tag,text,cls)=>{const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;root.appendChild(e);return e;};
  if (!decision.policy) {add('strong','REVIEW_REQUIRED · Decision unavailable');add('p',decision.error||'Required evidence is unavailable.');return;}
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
  sections.forEach(([title,data])=>{const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent=title;details.appendChild(summary);const pre=document.createElement('pre');pre.textContent=JSON.stringify(data,null,2);details.appendChild(pre);root.appendChild(details);});
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
