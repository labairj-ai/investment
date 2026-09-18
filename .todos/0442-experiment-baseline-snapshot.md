# Freeze Experiment Baseline Before Results Arrive

- **ID:** 0442
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0438

## Problem

There is currently no frozen record of the experimental conditions under which live 63-session
evidence is being collected. As the codebase evolves — scoring thresholds drift, base formula
weights change, risk policy tightens — future comparisons of challenger vs. base will be
contaminated by quiet strategy changes that occurred mid-experiment. Without a snapshot taken
before material outcomes arrive, it becomes impossible to assert "we measured alpha under these
exact conditions."

## Proposed approach

- Create `config/experiment_baseline.json` (committed, not gitignored) capturing:
  - Active model version and `model_id`
  - `evidence_contract_version`
  - Base score formula weights / composite threshold (from `strategy_config.py` or wherever live)
  - Active risk policy name and `policy_hash()`
  - Paper-book account ID and initial capital
  - Current git commit SHA at time of freeze
  - Freeze timestamp (ISO-8601)
- Write a small helper script (or one-time CLI in `agent_db.py`) that reads these values from the
  live DB and config files, then writes the JSON. Run it once and commit the result.
- Surface the baseline in the dashboard (readiness card or shadow tab) so it's visible alongside
  live metrics.
- Question: should the baseline be re-frozen automatically whenever `evidence_contract_version`
  increments, or always require a manual freeze? Manual is safer for the first version.

## Touches

- `config/experiment_baseline.json` (new file)
- `strategy_config.py` (read formula weights)
- `agent_db.py` or a new `scripts/freeze_baseline.py`
- `generate_dashboard.py` or `serve.py` (surface in dashboard)

## Done when

- [ ] `config/experiment_baseline.json` exists and is committed
- [ ] File includes model version, model_id, evidence_contract_version, base formula params, risk policy hash, paper-book account ID, commit SHA, and freeze timestamp
- [ ] Dashboard surfaces at least model version and commit SHA from the snapshot
- [ ] README or inline comment explains the file is frozen and should only be updated intentionally
