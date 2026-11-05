// A generated snapshot must stop presenting a complete value when quotes age out.
function expirePortfolioValuation(data, now) {
  const report = data.valuation;
  if (!report || !report.complete || !report.valid_until) return false;
  const deadline = Date.parse(report.valid_until);
  if (!Number.isFinite(deadline) || now >= deadline) {
    report.complete = false;
    report.net_value = null;
    data.totalValue = null;
    const value = document.getElementById('kpi-net-value');
    const status = document.getElementById('kpi-net-status');
    if (value) value.textContent = 'Unavailable';
    if (status) status.textContent = 'Option quotes have expired. Waiting for a fresh pricing snapshot. Gross stocks remain a separate snapshot; cash and untracked instruments are excluded.';
    return true;
  }
  return false;
}

// Synchronize only the valuation components; leave forms and the rest of the page intact.
function applyPortfolioValuation(data, report, now) {
  if (!report || typeof report.complete !== 'boolean' ||
      (report.complete ? !Number.isFinite(report.net_value) : report.net_value !== null) ||
      (report.gross_stock_value !== null && !Number.isFinite(report.gross_stock_value)) ||
      !Number.isInteger(report.open_count) || !Number.isInteger(report.priced_count) ||
      report.open_count < 0 || report.priced_count < 0 || report.priced_count > report.open_count ||
      (report.complete && (!Number.isFinite(report.gross_stock_value) || report.priced_count !== report.open_count)) ||
      (report.complete && report.open_count > 0 && !Number.isFinite(Date.parse(report.valid_until))) ||
      (report.issues && (!Array.isArray(report.issues) || report.issues.some(v=>typeof v !== 'string'))) ||
      (report.observations && (!Array.isArray(report.observations) || report.observations.some(v=>typeof v !== 'string')))) return false;
  data.valuation = report;
  data.totalValue = report.net_value;
  data.grossStockValue = report.gross_stock_value;
  const value = document.getElementById('kpi-net-value');
  const gross = document.getElementById('kpi-gross-value');
  const status = document.getElementById('kpi-net-status');
  const money = n => n.toLocaleString('en-US',{style:'currency',currency:'USD'});
  if (value) value.textContent = report.complete ? money(report.net_value) : 'Unavailable';
  if (gross) gross.textContent = 'Gross stocks '+(Number.isFinite(report.gross_stock_value) ? money(report.gross_stock_value) : 'unavailable');
  if (status) {
    const notes = [report.priced_count+'/'+report.open_count+' open calls priced', 'session '+report.session,
      'Reported mark when available; otherwise bid/ask midpoint estimate. Cash and untracked instruments excluded.'];
    if (report.observations && report.observations.length) notes.push('Quotes observed '+[...new Set(report.observations)].join(', '));
    if (!report.complete && report.issues) notes.push(report.issues.join('; '));
    status.textContent = notes.join(' · ');
  }
  expirePortfolioValuation(data, now);
  return true;
}

let portfolioValuationPending = false;
async function pullPortfolioValuation(data) {
  if (portfolioValuationPending) return false;
  portfolioValuationPending = true;
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),15000);
  try {
    const response = await fetch('/api/portfolio-valuation',{cache:'no-store',signal:controller.signal});
    if (!response.ok) return false;
    const body = await response.json();
    return body.ok === true && applyPortfolioValuation(data,body.valuation,Date.now());
  } catch (error) {
    return false;
  } finally {
    clearTimeout(timer);
    portfolioValuationPending = false;
  }
}
