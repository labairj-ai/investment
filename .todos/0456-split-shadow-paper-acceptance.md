# Split Acceptance into Shadow and Paper Milestones

- **ID:** 0456
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0455

## Problem

`first_sweep_acceptance.py` accepts any completed learning sweep — including an
OBSERVE-only run — and writes `experiment_canary_001.json` with "Architecture is
frozen after this passes." An OBSERVE sweep verifies the OH → ledger → shadow
scoring → episode lineage → winner selection path, but says nothing about the
challenger winner → `decision_variant` → PAPER_ACTIVE → actual paper challenger
decision path, which is the execution path that ultimately matters. Declaring the
full architecture frozen from OBSERVE alone overstates what has been validated.

## Proposed approach

Split the single acceptance into two milestone scripts/artifacts:

- **Shadow acceptance** (`experiment_shadow_canary_001.json`): written after the
  first successful OBSERVE sweep. Validates the observation pipeline only. Messaging
  should say "observation pipeline verified" — not "architecture frozen."

- **Paper acceptance** (`experiment_paper_canary_001.json`): written after the first
  genuine base-eligible PAPER_ACTIVE sweep. Runs all shadow checks plus: variant row
  exists, `challenger_episode_id` matches shadow winner, paper decision recorded.
  Only this artifact should carry "full learning-to-paper architecture validated."

Implement as two modes in `first_sweep_acceptance.py` (e.g. `--mode shadow` /
`--mode paper`) or as two separate scripts. Either way, each writes its own
append-only output file in `config/`.

## Touches

- `scripts/first_sweep_acceptance.py`
- `config/experiment_shadow_canary_001.json` (written when shadow sweep passes)
- `config/experiment_paper_canary_001.json` (written when paper sweep passes)
- `config/experiment_canary_001.json` — current file may need to be renamed/archived

## Done when

- [ ] Shadow-pipeline acceptance writes `experiment_shadow_canary_001.json` and says "observation pipeline verified"
- [ ] Paper-execution acceptance writes `experiment_paper_canary_001.json` and says "full architecture validated"
- [ ] Neither artifact can be written by the other mode's sweep
- [ ] Existing `experiment_canary_001.json` reference is cleaned up or renamed
