# Solo-owner governance

This is a permanent owner-requested authority model, not a PR #6 exception. The human repository owner may review their own GitHub-authored AI-assisted changes. AI/automation cannot approve itself; independent Builder/Reviewer models, CI, financial canaries, contract and execution safeguards still apply. Human merge remains mandatory, auto-merge and autonomous implementation remain disabled.

## Operator identity and deployment

`DEV_AGENT_OWNER_BINDINGS` is a JSON object provisioned outside the repository and candidate worktree by the operator:

```json
{"repository":"labairj-ai/investment","owner_login":"labairj-ai","owner_id":260142791,"operators":{"os-interactive-cli":["OPERATOR_OS_LOGIN"],"tailscale-serve":["OPERATOR_VERIFIED_LOGIN"]}}
```

Replace placeholders with deliberately verified human identities. The personal repository owner login and immutable ID are rechecked through GitHub. No binding is installed by this change. Do not map agent/service accounts. Do not derive approval from commit authorship, API token possession, request JSON or CI.

The terminal path requires an interactive authenticated OS user, an allowlisted owner mapping and an exact confirmation phrase. A PTY alone is not a security boundary against another process running as that owner. Run operator approval on an owner-controlled account/host that the coding agent cannot impersonate; never delegate that terminal to the agent. Dashboard owner review requires Tailscale Serve authenticated identity, a loopback client and loopback-only backend listener, and an operator allowlist. Configure the backend to bind loopback and prevent direct network access before using this endpoint. Shared dashboard token alone cannot attest. Agent and owner credentials must be isolated operationally; code cannot distinguish two processes sharing all authority.

## Deliberate exact-head review

Use an operator-private `DEVELOPMENT_CONTROL_DB` named `development-control.sqlite3`. Initialize it with `python -m dev_agent.cli init`. Read the complete PR diff, risk evidence and CI first. Create `pr.json` containing `{"pr":6}` and obtain current context:

```
python -m dev_agent.cli owner-context --repository labairj-ai/investment --input pr.json --risk L5
```

Prepare a private JSON file with that exact `context`, a `decision` of `APPROVE`, `REQUEST_CHANGES` or `DEFER`, and explicit boolean `financial_ack`/`execution_ack` where required. Then personally invoke:

```
python -m dev_agent.cli owner-review --repository labairj-ai/investment --input owner-decision.json --nonce UNIQUE-OWNER-NONCE --rationale 'Personal review rationale'
```

The owner must type the exact displayed decision/repository/PR/head confirmation. The coding agent must not run this command for the owner. Alternatively the trusted owner dashboard boundary can POST the same context, decision, nonce, rationale and acknowledgments to `/api/development-agent/owner-review`; body actor names are ignored. Audit history appears in the dashboard; current validity must be rechecked because a historical record is not current approval.

L0–L2 require owner review and CI/evidence; L3 adds rationale; L4 adds financial review acknowledgment and all financial gates; L5 adds execution-risk acknowledgment and execution/account safeguards. This implementation conservatively requires both domain acknowledgments for L5. GitHub file inventory supplies a deterministic minimum risk; a caller can raise but cannot lower it. Unknown/executable presentation is at least L3. A new head or changed owner binding invalidates prior approval. Latest REQUEST_CHANGES/DEFER revokes approval, and nonce replay is rejected. Generic ledger events cannot create OWNER_REVIEW.

A fresh owner attestation is required to accept a recorded merge or qualify a pilot. It never calls a GitHub approval/merge/deployment API. CI/model PASS without it is insufficient. A separate trusted owner-check controller must enforce its corresponding GitHub status; see [protection deployment](../ops/solo-owner/README.md). Controller/app provisioning and live negative tests are not complete.

## PR #6 migration sequence

Policy adoption must first land on main through an explicit human owner decision under this owner-requested governance migration. PR #6 must then update onto governance-enabled main, run the entire exact-head suite and unchanged CC/release/governance gates, and receive a new authenticated owner review. The old bad4491e result is historical if its head changes. This implementation branch is stacked on PR #6 for compatibility; it must not be merged wholesale as a shortcut that lands PR #6 before governance adoption. A separate policy foundation PR supplies the initial documentation/checker change; remaining enforcement can then be applied to the updated development-agent branch.

The owner performs the final GitHub merge. Record its actual merge SHA, deploy that main SHA to OptiPlex under explicit deployment authority, retain rollback and verify service/dashboard/authentication, denied unauthorized API access, Advisor/read-only canaries, unchanged holdings and expected ledger, disabled autonomy and auto-merge. No deployment or merge is performed by this change. 0800 certification, prospective pilots and autonomy activation receive no credit from it.

## Policy foundation scope

This main-based foundation changes policy and its static contract guard, and brings forward only the previously owner-acknowledged cc-v3.4 JSON-safety contract repair from PR #6 so governance adoption can satisfy green CI. Runtime owner attestation and protection verification are prepared in a separate PR #6-based enforcement branch. Operator commands above become available only after that enforcement lands. The existing main CC failures are resolved through that already acknowledged migration, not waived. No recommendation algorithm or safeguard is changed by the extracted repair. Require new exact-head CI before adoption.
