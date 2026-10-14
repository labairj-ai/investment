"""Presentation-only CC income summary; embedded in the generated dashboard."""


def income_assets():
    return r'''
<style>
.cc-tracker-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.cc-tracker-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cc-position-detail-heading { font-size: 14px; font-weight: 650; color: #334155; margin: 24px 0 12px; }
#cc-income-overview { margin: 4px 0 24px; color: #263449; }
.cc-income-kpis { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; margin-bottom: 22px; }
.cc-income-kpi { background: #f8fafc; border: 1px solid #e5eaf0; border-radius: 10px; padding: 16px; min-width: 0; }
.cc-income-kpi-label { font-size: 12px; font-weight: 600; color: #637083; margin-bottom: 9px; }
.cc-income-kpi-value { font-size: clamp(20px,2.2vw,28px); font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; letter-spacing: -.035em; }
.cc-income-kpi-note { font-size: 11px; color: #6b7789; line-height: 1.5; margin-top: 8px; }
.cc-income-gain { color: #167352; }
.cc-income-loss { color: #bd3e44; }
.cc-income-zero { color: #7a8697; }
.cc-income-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 10px; }
#cc-income-overview h3 { margin: 0; font-size: 15px; color: #263449; font-weight: 650; }
.cc-income-subtitle { margin-top: 4px; font-size: 12px; color: #6b7789; }
.cc-income-ranges { display: flex; gap: 3px; padding: 3px; background: #eef2f6; border-radius: 7px; }
.cc-income-range { font: inherit; font-size: 11px; color: #5c687b; background: transparent; border: 0; border-radius: 5px; padding: 7px 10px; cursor: pointer; }
.cc-income-range[aria-pressed="true"] { background: #fff; color: #23354b; font-weight: 650; box-shadow: 0 1px 3px #26344918; }
.cc-income-range:focus-visible { outline: 2px solid #4676b9; outline-offset: 2px; }
.cc-income-months { table-layout: fixed; width: 100%; border-collapse: collapse; }
.cc-income-months .cc-income-month { width: 22%; }
.cc-income-months .cc-income-realized { width: 24%; text-align: right; }
.cc-income-months .cc-income-trend { width: 32%; padding-left: 24px; padding-right: 24px; }
.cc-income-months .cc-income-open { width: 22%; text-align: right; }
.cc-income-months th { background: transparent; font-size: 10px; letter-spacing: .035em; color: #788497; padding-top: 12px; padding-bottom: 10px; border-bottom: 1px solid #dfe6ee; }
.cc-income-months td { padding-top: 13px; padding-bottom: 13px; border-bottom: 1px solid #edf1f5; font-variant-numeric: tabular-nums; }
.cc-income-months tbody th { font-size: 12px; letter-spacing: 0; text-transform: none; color: #334155; font-weight: 500; border-bottom: 1px solid #edf1f5; }
.cc-income-months .cc-income-realized { font-weight: 650; white-space: nowrap; }
.cc-income-months td.cc-income-open { color: #66768c; white-space: nowrap; }
.cc-income-current { background: #f8fafc; }
.cc-income-current-tag { display: block; font-size: 10px; font-weight: 400; color: #7b8798; margin-top: 3px; }
.cc-income-track { position: relative; height: 18px; background: linear-gradient(to right,#f5f7fa,#f5f7fa); border-radius: 3px; }
.cc-income-track::after { content: ''; position: absolute; left: 50%; top: -3px; bottom: -3px; width: 1px; background: #bdc8d5; }
.cc-income-bar { position: absolute; top: 3px; height: 12px; border-radius: 2px; }
.cc-income-bar-positive { left: 50%; background: #3c9b79; }
.cc-income-bar-negative { right: 50%; background: #d27479; }
.cc-income-footnote { color: #7b8798; font-size: 11px; line-height: 1.6; margin-top: 12px; }
.cc-income-empty { padding: 16px; margin: 12px 0; background: #f8fafc; border: 1px dashed #dbe3ed; border-radius: 8px; font-size: 12px; color: #66768c; }
@media (max-width: 900px) { .cc-income-kpis { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 560px) {
  .cc-income-kpis { gap: 8px; }
  .cc-income-kpi { padding: 12px; }
  .cc-income-kpi-value { font-size: 20px; }
  .cc-income-months .cc-income-trend { display: none; }
  .cc-income-months .cc-income-month { width: 32%; }
  .cc-income-months .cc-income-realized, .cc-income-months .cc-income-open { width: 34%; }
  .cc-income-months th, .cc-income-months td { padding-left: 5px; padding-right: 5px; }
  .cc-income-months thead th { white-space: normal; line-height: 1.4; }
}
</style>
<script>
let _ccIncomeRange = '6';

function ccIncomeMonth(raw) {
  if (typeof raw !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  const [y,m,d] = raw.split('-').map(Number);
  const date = new Date(Date.UTC(y,m-1,d));
  if (y < 1900 || date.getUTCFullYear() !== y || date.getUTCMonth() !== m-1 || date.getUTCDate() !== d) return null;
  return raw.slice(0,7);
}

function ccIncomeCurrentMonth(now) {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York',year:'numeric',month:'2-digit'}).formatToParts(now);
  return parts.find(p=>p.type==='year').value + '-' + parts.find(p=>p.type==='month').value;
}

function ccIncomeAmount(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function ccIncomeData(positions, now = new Date()) {
  const current = ccIncomeCurrentMonth(now);
  const months = {};
  let ytd = 0, historicalYtd = 0, openPremium = 0, openPnl = 0, marked = 0, openCount = 0;
  let skippedDates = 0, missingAmounts = 0, historical = 0;
  const bucket = key => months[key] || (months[key] = {realized:0, openPremium:0, closedCount:0});
  positions.forEach(p => {
    if (p.status === 'open') {
      openCount++;
      const premium = ccIncomeAmount(p.premium_per_contract), contracts = ccIncomeAmount(p.contracts);
      const gross = premium !== null && contracts !== null ? premium * contracts * 100 : null;
      if (gross !== null) openPremium += gross;
      else missingAmounts++;
      const pnl = ccIncomeAmount(p.pnl_total);
      if (pnl !== null) { openPnl += pnl; marked++; }
      const key = ccIncomeMonth(p.opened_date);
      if (key) { if (gross !== null) bucket(key).openPremium += gross; }
      else skippedDates++;
      return;
    }
    const amount = ccIncomeAmount(p.net_premium);
    const key = ccIncomeMonth(p.closed_date) || ccIncomeMonth(p.expiry);
    const legacy = p.notes === 'pre-system income entry';
    if (amount === null) missingAmounts++;
    if (key && key.slice(0,4) === current.slice(0,4) && key <= current && amount !== null) {
      ytd += amount;
      if (legacy) historicalYtd += amount;
    }
    if (legacy) { historical++; return; }
    if (!key) { skippedDates++; return; }
    const month = bucket(key);
    if (amount !== null) { month.realized += amount; month.closedCount++; }
  });
  return {current, months, ytd, historicalYtd, historical, openPremium, openPnl, marked, openCount, skippedDates, missingAmounts};
}

function ccIncomeMonths(data, range) {
  const recorded = Object.keys(data.months).filter(k=>k<=data.current).sort();
  const earliest = range === 'all' ? (recorded[0] || data.current) : null;
  const [year, month] = data.current.split('-').map(Number);
  const end = year*12 + month-1;
  const start = earliest ? Number(earliest.slice(0,4))*12 + Number(earliest.slice(5,7))-1 : end-Number(range)+1;
  const result = [];
  for (let index=end; index>=start; index--) result.push(Math.floor(index/12)+'-'+String(index%12+1).padStart(2,'0'));
  return result;
}

function ccIncomeMoney(amount) {
  // Avoid displaying negative zero after rounding to cents.
  const rounded = Math.round((amount + Number.EPSILON)*100)/100;
  return (rounded < 0 ? '−$' : '$') + Math.abs(rounded).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}

function renderCCIncome(positions, now = new Date()) {
  const data = ccIncomeData(positions, now);
  const months = ccIncomeMonths(data, _ccIncomeRange);
  const get = key => data.months[key] || {realized:0,openPremium:0,closedCount:0};
  const tone = value => value > 0 ? 'cc-income-gain' : value < 0 ? 'cc-income-loss' : 'cc-income-zero';
  const monthName = key => new Date(key+'-01T12:00:00Z').toLocaleDateString('en-US',{month:'short',year:'numeric',timeZone:'UTC'});
  const max = Math.max(1,...months.map(key=>Math.abs(get(key).realized)));
  const kpi = (label,value,note,cls='') => `<div class="cc-income-kpi"><div class="cc-income-kpi-label">${label}</div><div class="cc-income-kpi-value ${cls}">${value}</div><div class="cc-income-kpi-note">${note}</div></div>`;
  const currentNet = get(data.current).realized;
  const rangeButtons = [['6','6 months'],['12','12 months'],['all','All history']].map(([value,label])=>`<button type="button" class="cc-income-range" id="cc-income-range-${value}" aria-pressed="${_ccIncomeRange===value}" onclick="setCCIncomeRange('${value}')">${label}</button>`).join('');
  const rows = months.map(key=>{
    const item = get(key);
    const width = (Math.abs(item.realized)/max*48).toFixed(2);
    const bar = item.realized ? `<span class="cc-income-bar cc-income-bar-${item.realized<0?'negative':'positive'}" style="width:${width}%"></span>` : '';
    return `<tr class="${key===data.current?'cc-income-current':''}"><th scope="row" class="cc-income-month">${monthName(key)}${key===data.current?'<span class="cc-income-current-tag">Month to date</span>':''}</th><td class="cc-income-realized ${tone(item.realized)}">${ccIncomeMoney(item.realized)}</td><td class="cc-income-trend" aria-hidden="true"><div class="cc-income-track">${bar}</div></td><td class="cc-income-open">${item.openPremium ? ccIncomeMoney(item.openPremium) : '—'}</td></tr>`;
  }).join('');
  const hasRealized = months.some(key=>get(key).closedCount);
  const caveats = [
    data.historical ? `${data.historical} historical income entries are excluded from this monthly view.` : '',
    data.skippedDates ? `${data.skippedDates} positions lack a valid reporting date.` : '',
    data.missingAmounts ? `${data.missingAmounts} positions have unavailable premium amounts; totals are partial.` : ''
  ].filter(Boolean).join(' ');
  return `<div class="cc-income-kpis">
    ${kpi('Realized · '+monthName(data.current),ccIncomeMoney(currentNet),'Closed and expired positions · month to date',tone(currentNet))}
    ${kpi('Realized · '+data.current.slice(0,4),ccIncomeMoney(data.ytd),data.historicalYtd?'Includes '+ccIncomeMoney(data.historicalYtd)+' historical income':'Closed and expired positions · year to date',tone(data.ytd))}
    ${kpi('Open premium collected',ccIncomeMoney(data.openPremium),data.openCount+' open positions · not realized profit')}
    ${kpi('Open option P&L',data.marked?ccIncomeMoney(data.openPnl):'—',data.marked?'Marks available for '+data.marked+' of '+data.openCount+' open positions':'Current option marks unavailable',data.marked?tone(data.openPnl):'cc-income-zero')}
  </div><div class="cc-income-heading"><div><h3>Monthly realized income</h3><div class="cc-income-subtitle">Net premium after buybacks. Open premium shown separately.</div></div><div class="cc-income-ranges" role="group" aria-label="Income history range">${rangeButtons}</div></div>
  ${hasRealized?'':'<div class="cc-income-empty">No realized income recorded in this period. Open premium is shown separately until positions close.</div>'}
  <table class="cc-income-months" aria-label="Monthly covered call income"><thead><tr><th scope="col" class="cc-income-month">Month</th><th scope="col" class="cc-income-realized">Net realized</th><th scope="col" class="cc-income-trend">Loss ← 0 → Gain</th><th scope="col" class="cc-income-open">Open premium</th></tr></thead><tbody>${rows}</tbody></table>
  <p class="cc-income-footnote">Realized income is grouped by closing month (expiry if no close date). Open premium covers currently open positions, grouped by opening month; it is not added to realized income. Bars share the same scale within the selected period. ${caveats}</p>`;
}

function setCCIncomeRange(range) {
  if (!['6','12','all'].includes(String(range))) return;
  _ccIncomeRange = String(range);
  const overview = document.getElementById('cc-income-overview');
  if (!overview) return;
  overview.innerHTML = renderCCIncome(_allCCPositions);
  const button = document.getElementById('cc-income-range-'+_ccIncomeRange);
  if (button) button.focus({preventScroll:true});
}
</script>
'''
