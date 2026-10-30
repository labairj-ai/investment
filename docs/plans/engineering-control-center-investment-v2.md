# Investment Engineering Control Center — Implementation Contract v2

**Created:** 2026-10-29  
**Scope:** Existing `labairj-ai/investment` Development Agent only  
**Status:** Design and TODO backlog; no implementation or deployment
**Related TODOs:** 0856–0864

## 1. Fundamental separation

Investment keeps the authoritative `dev_agent`, its `development-control.sqlite3` ledger, scheduler, GitHub credentials, owner gateway, validator/oracle, certification and fixed deployment controller. The separately developed Qwen-only Engineering Agent microservice must not access, monitor, schedule, validate, write to, approve, merge or deploy Investment. This page is implemented in the Investment web stack, not in that standalone service.

Keep existing `/development-agent` and `GET /api/development-agent` compatible until actual supervised parity and separate retirement approval. Add the proposed `/engineering/projects/investment` interface behind an OFF-by-default route/feature gate. Existing source/ledger/approval policies take precedence over any visual design mockup.

## 2. Verified source context versus operational proof

At design time on 2026-10-29, committed `config/development_agent.json` uses `autonomous_implementation=false`, `auto_merge=false`, `supervised_loop_enabled=false`, `supervised_publish_pr=false`, `autonomy_stage=SHADOW`. These are **repository settings**, not live OptiPlex observations. GitHub PR #19 (watchdog) is open and PR #30 (oneshot certification verification) is merged; never hard-code these statuses in the live dashboard. Operational certification, timer qualification, installed runtime state, actual supervised runs and deployment health are unknown until fetched from the trusted ledger and host observers.

Do not display prototype candidate scores, invented test totals or offline sample audit entries as real operational data. Unknown evidence is UNAVAILABLE, stale evidence is STALE, and failed evidence is FAIL. None of these is PASS.

## 3. Navigation, screens and interaction contract

Desktop: Overview, Candidates, Pull Requests, Validation, Certification, Audit History. Mobile bottom bar: Home, Queue, PRs, Gates, More; More exposes Certification and Audit.

**Overview:** hero shows actual owner-facing supervised entry-gate READY / NOT READY / UNAVAILABLE, last observed/source identity, and up to three linked blockers. Distinct metrics: candidate backlog, PRs requiring owner decisions, trusted validation and current autonomy configuration. Live priority queue and event feed distinguish real scheduled discovery, manual/test activity, owner reviews and deployment outcomes.

**Candidates:** server-side paginated title/ID/component search and risk/state/category/source filters, sorting by verified value/risk/age. Candidate card contains ID, source, versioned value score/evidence quality, deterministic risk, stage and blocker. Drilldown shows scope and protected files, frozen TODO/acceptance criteria, approved base SHA, worktree/run context, reviewer findings, validation receipts, PR/merge/deployment observations and immutable event timeline. The L4/L5 path never has a generic Build control.

**Pull Requests:** show complete GitHub repo/branch/base/head SHA, linked candidates, deterministic risk, protected surfaces, independent Reviewer, exact-head CI, trusted Oracle, effective protection, owner disposition and deployment status independently. On review, freeze and present exact current head/diff/risks/missing evidence, highlight financial/execution consequences, and use **one owner Go/No-Go** through the already isolated authenticated owner connector. No browser token with owner GitHub/deployment rights. A newer head, refusal or stale evidence invalidates prior Go. Go authorizes only the existing governed process, not instantaneous deploy success. Owner action may wait for eligible CI automatically; no repeated approval ceremony.

**Validation:** complete versioned mandatory gate manifest: focused tests, full suite, release baseline, covered-call contract, agent contract, TODO consistency, development governance plus any additional current canonical gates. Show per-gate source/base/head/test-tree hash, image digest, trusted Oracle ID, signed receipt/verifier status, commands/version, exit code and verified JUnit inventory. A candidate-produced PASS/JUnit/CI-only result is not independent validation. Missing/stale/forged fields fail closed. No arbitrary shell/retest command from UI.

**Certification:** three *separate* groups: technical certificate/harness/source/sandbox/Oracle/GitHub protection/backup/scheduler observation; supervised genuine distinct successes (minimum 3) over the required 7-day calendar period and real deployed health; autonomy policy/eligibility/activation/current kill switch/risk ceiling. Fixtures/replays/manual Scout observations never create operating acceptance credit. Do not add an enable-autonomy toggle.

**Audit:** immutable append-only event feed with UTC canonical timestamp and ET rendering, sequence, actor identity source, candidate, PR, risk, exact source/head SHA, disposition, policy version and trusted receipt. Read-only filters and bounded redacted JSON/CSV export. Retain failure/denial evidence and avoid exposing raw private prompts, credentials or financial records.

## 4. Read-only API contract

Suggested Investment-owned routes (final naming subject to compatibility review):

- `GET /api/engineering/v1/projects/investment/overview`
- `GET /api/engineering/v1/projects/investment/candidates`
- `GET /api/engineering/v1/projects/investment/candidates/{id}`
- `GET /api/engineering/v1/projects/investment/prs`
- `GET /api/engineering/v1/projects/investment/validations/{run_id}`
- `GET /api/engineering/v1/projects/investment/certification`
- `GET /api/engineering/v1/projects/investment/audit`

Every critical status has `status`, `reason_code`, `reason_summary`, `observed_at`, `expires_at` when applicable, `source`, `policy_version`, `repository`, `head_sha` if applicable, `receipt_id` and `verifier_status`. API reads use existing Investment authorization, bounded output and strict project scoping. Owner-affecting operations go only through the current trusted gateway; these endpoints are not a new owner-action API.

## 5. Design and acceptance rules

- Mobile widths: 320, 360, 390, 430, 768, 1280, 1440px; no horizontal overflow, long hashes/text wrap, cards replace tables. Tap targets >=44x44 CSS px; mobile safe-area, accessible dialogs/bottom sheets, focus management, reduced motion, WCAG AA contrast.
- All risk and stale/failed evidence warnings remain visible at narrow widths. No owner Go on swipe, tap of card row or stale preview.
- Browser checks and synthetic fixtures do not substitute for physical iPhone/Android observation, live GitHub protection, host sandbox/Oracle qualification or supervised operational evidence.
- Security negative tests: forged owner IDs, replayed/stale Go, concurrent Go/No-Go, wrong head, tampered Oracle evidence, candidate-provided JUnit, unavailable API/cache, cross-origin/cross-project access, malicious HTML and export CSV formula injection.
- Existing Investment full suite, focused Development Agent tests, all eight exact-head release gates, owner review and production canary remain mandatory for change acceptance. No disabling or relaxing checks to obtain PASS.
- No deployment of these backlog files. UI rollout must be separately owner-reviewed, initially read-only, old dashboard remains functional, and rollback changes only UI source while preserving financial data and append-only ledger.

## 6. Ordered implementation

| TODO | Deliverable | Dependencies |
| --- | --- | --- |
| 0856 | Trusted read DTO, provenance, auth, pagination | Existing ledger/readiness |
| 0857 | Overview and admitted-state hero | 0856 |
| 0858 | Candidate filters/details/timeline | 0856, 0857 |
| 0860 | Trusted validation and gate details | 0856 |
| 0859 | Exact-head PR and one-Go review | 0856, 0860 |
| 0861 | Technical/supervised/autonomy certification | 0856, 0860 |
| 0862 | Audit timeline and safe export | 0856 |
| 0863 | Mobile/accessibility/security QA | 0857–0862 |
| 0864 | Release/parity/rollback/physical acceptance | All above |

Initial recommendation: implement 0856 read-only and 0857 overview before introducing owner Go review in 0859. UI source extraction should not interrupt the independent Scout qualification work or PR #19 watchdog review.

## 7. Design tradeoff

Prefer Investment-owned read-model presentation over a separate shared microservice. This avoids cross-project authority and minimizes changes to existing governance, but carries a short-term duplicate-view maintenance burden. Retain legacy page until measured parity and explicitly approved retirement.
