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
    if (status) status.textContent = 'Option quotes have expired. Refresh after the pricing job updates. Gross stocks remain a separate snapshot; cash and untracked instruments are excluded.';
    return true;
  }
  return false;
}
