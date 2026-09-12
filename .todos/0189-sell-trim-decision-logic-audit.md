# Sell/Trim Decision Logic Audit: Sell vs Trim, Valuation, Tax Asymmetry

- **ID:** 0189
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0188

## Problem

The current `_action_from_strength(ss)` function maps ss to TRIM (48–68) or EXIT (≥68) using static thresholds. This creates three design gaps the reviewer specifically raised:

**1. When should valuation-only → EXIT vs TRIM?**
Consider: T=5 (thesis intact), F=5 (fundamentals fine), V=90 (extreme valuation), P=50 (overweight), O=70 (better alternatives). That produces `ss = 0.40×5 + 0.20×5 + 0.15×90 + 0.15×50 + 0.10×70 = 2 + 1 + 13.5 + 7.5 + 7 = 31` → REVIEW. But a position at 90th valuation percentile with good alternatives arguably warrants TRIM, not just REVIEW. A purely valuation-driven concern never reaches TRIM unless T and F also contribute. The formula arguably underweights V for positions where the thesis is intact but the stock is priced for perfection.

**2. Should taxes affect TRIM differently from EXIT?**
Currently `_tax_note()` computes tax friction and stores it in the recommendation payload, but it does not modify the action or trim fraction. A TRIM and an EXIT see the exact same tax computation even though:
- EXIT: full position → may trigger large ST gains
- TRIM: partial sale → smaller immediate tax hit, but may leave ST risk unresolved

Cases where large ST tax burden should convert EXIT → TRIM (defer to LT treatment in 60 days) or TRIM fraction → smaller (e.g., 0.25 instead of 0.75) are not handled. The tax note goes to the LLM but isn't deterministically reflected in the suggested action.

**3. Is the TRIM fraction scaling well-calibrated?**
Current: `trim_fraction = 0.25 + (ss - 48) / 20 * 0.50`, scaling 0.25 → 0.75 over ss 48 → 68.
Questions:
- At ss=48 (entry band), is 25% trim appropriate, or should the entry trim be smaller (e.g., 15%)?
- Should P (concentration) independently floor the trim fraction? A 2× overweight position always warrants at least 33% trim even at ss=50.
- Should the LLM be allowed to adjust the trim fraction within ±1 step, or should the deterministic fraction be a hard constraint?

## Proposed approach

**Valuation-driven action floor:**
When V ≥ 80 and the thesis is intact (T ≤ 20), and alternatives exist (O ≥ 50), apply an action floor of REVIEW. If additionally P ≥ 50 (overweight), apply a TRIM floor regardless of composite ss. Code change:
```python
if V >= 80 and T <= 20 and O >= 50 and P >= 50:
    if suggested == "REVIEW":
        suggested = "TRIM"
        trim_fraction = 0.25   # conservative start since thesis is intact
```

**Tax-influenced action modification (deterministic):**
When `tax_friction_dollars > tax_friction_threshold` AND `action == "EXIT"`:
- If LT crossover date is within 60 days for the majority of shares: downgrade to TRIM (defer the rest)
- Trim fraction = min(fraction of shares already LT, existing trim_fraction)

This requires `_lot_tax_friction()` or `_tax_note()` to return the LT crossover schedule, similar to what `_lot_tax_friction()` already computes in `covered_call_rec.py`.

**TRIM fraction floor from concentration:**
```python
if P >= 55:  # 1.5× overweight
    trim_fraction = max(trim_fraction, 0.33)
if P >= 75:  # 2× overweight
    trim_fraction = max(trim_fraction, 0.50)
```

## Touches

- `agents/sell_trim_agent.py` — `_action_from_strength()`, `_trim_fraction_from_strength()`, `_run()` (post-scoring action modification block), `_tax_note()` (may need to return LT schedule)
- `covered_call_rec.py` — possibly share `TaxFrictionDetail.lot_schedule` for consistent lot analysis
- `tests/test_sell_trim_agent.py` — new tests for V-floor TRIM, tax-influenced downgrade, concentration trim floor

## Done when

- [ ] Valuation-only scenario (V≥80, T≤20, O≥50, P≥50) → at minimum TRIM, not REVIEW
- [ ] EXIT with large near-term ST tax burden and LT crossover < 60 days → deterministically downgraded to TRIM (or TRIM fraction reduced), not just noted in payload
- [ ] TRIM fraction floors by concentration level are applied
- [ ] All three changes are documented in the formula comment at the top of sell_trim_agent.py
- [ ] Existing tests pass; new scenario tests added
