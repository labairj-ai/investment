# TODO 0871 — Remove tracked net value history chart

- **Status:** in-progress
- **Base:** ac356658dc3d8149691d6e985679445bcb8b88d6
- **Source:** Owner request to remove the tracked net value graph from the Investment dashboard.
- **Risk:** Display-only removal; retain valuation calculations, headline metric, financial state and trading safeguards.

## Scope and acceptance

Remove the history chart card and its JavaScript initialization from the existing dashboard generator. Keep other charts and valuation behavior. Reuse the synthetic dashboard fixture to verify absent chart, retained net headline/Stocks vs SPY chart and valid inline JavaScript. Run required CI, existing owner merge/release, then verify the actual production dashboard at desktop and mobile widths. No new infrastructure or database writes.

- [ ] Focused dashboard regression and required repository gates.
- [ ] PR CI, merge, merged-main CI and existing authorized OptiPlex release.
- [ ] Live desktop/mobile dashboard verifies chart removal and intact layout.
