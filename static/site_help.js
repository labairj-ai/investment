(() => {
  'use strict';
  const definitions = window.SITE_COLUMN_HELP || {};
  const roots = ['tab-macro', 'tab-learning', 'tab-shadow'].map(id => document.getElementById(id)).filter(Boolean);
  const normalize = value => value.toLowerCase().replace(/δ/g, 'delta').replace(/[^a-z0-9]/g, '');
  const tip = document.createElement('div');
  tip.id = 'column-help-tooltip'; tip.className = 'column-help-tooltip'; tip.role = 'tooltip'; tip.hidden = true;
  document.body.appendChild(tip);
  let active = null;
  function close() {
    if (active) active.removeAttribute('aria-describedby');
    active = null; tip.hidden = true;
  }
  function show(header) {
    if (active && active !== header) active.removeAttribute('aria-describedby');
    active = header; tip.textContent = header.dataset.columnHelp; tip.hidden = false;
    header.setAttribute('aria-describedby', tip.id);
    const rect = header.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - tip.offsetWidth - 8));
    const below = rect.bottom + 8;
    const top = below + tip.offsetHeight < window.innerHeight ? below : Math.max(8, rect.top - tip.offsetHeight - 8);
    tip.style.left = `${left}px`; tip.style.top = `${top}px`;
  }
  function decorate(root) {
    root.querySelectorAll('th').forEach(header => {
      if (header.dataset.columnHelp) return;
      const key = normalize(header.textContent);
      let text = definitions[key] || header.getAttribute('title');
      if (key === 'n' && normalize(header.closest('table').querySelector('th').textContent) === 'exploratorydimension') {
        text = 'Number of evaluable divergent cohorts in this exploratory dimension comparison. Uncertainty is clustered by decision date; cohort count alone does not establish effectiveness.';
      }
      if (!text) return; // Unknown future labels must get an explicit, reviewed definition.
      header.dataset.columnHelp = text;
      header.removeAttribute('title'); // Avoid a second native popup over the accessible one.
      header.setAttribute('scope', 'col'); header.tabIndex = 0;
      header.addEventListener('mouseenter', () => show(header));
      header.addEventListener('mouseleave', e => { if (!tip.contains(e.relatedTarget)) close(); });
      header.addEventListener('focus', () => show(header));
      header.addEventListener('blur', close);
      header.addEventListener('click', e => {
        if (e.pointerType === 'touch' || !e.pointerType) show(header);
      });
      header.addEventListener('keydown', e => {
        if (e.key === 'Escape') close();
        if ((e.key === 'Enter' || e.key === ' ') && !header.hasAttribute('onclick')) { e.preventDefault(); show(header); }
      });
    });
  }
  tip.addEventListener('mouseleave', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  document.addEventListener('pointerdown', e => { if (active && !active.contains(e.target) && !tip.contains(e.target)) close(); });
  window.addEventListener('resize', close);
  window.addEventListener('scroll', close, true);
  roots.forEach(root => {
    decorate(root);
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => { pending = false; if (active && !active.isConnected) close(); decorate(root); });
    }).observe(root, { childList: true, subtree: true });
  });
  document.querySelectorAll('.gloss-container').forEach(container => {
    const input = container.querySelector('.gloss-search');
    if (!input) return;
    const terms = [...container.querySelectorAll('.gloss-term')];
    const status = container.querySelector('.gloss-search-status');
    function filter() {
      const query = input.value.toLocaleLowerCase().trim();
      let count = 0;
      terms.forEach(term => { term.hidden = !term.textContent.toLocaleLowerCase().includes(query); if (!term.hidden) count++; });
      container.querySelectorAll('.gloss-section').forEach(section => {
        section.hidden = ![...section.querySelectorAll('.gloss-term')].some(term => !term.hidden);
      });
      status.textContent = query ? `${count} matching terms` : `${count} terms · Search by name, abbreviation, or definition`;
    }
    input.addEventListener('input', filter); filter();
  });
})();
