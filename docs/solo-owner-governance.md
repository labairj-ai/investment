# Action-scoped owner workflow

The authenticated owner reviews the exact PR, head and L5 risks and explicitly
selects MERGE_ONLY or MERGE_AND_DEPLOY. There is no inferred/default action.
MERGE_ONLY authorizes one immediate exact-head GitHub merge. It cannot authorize
source deployment, protected staging, Scout, autonomy or an epoch transition.
MERGE_AND_DEPLOY is available only when external owner policy explicitly supports
it; all existing merge, deployment, financial and runtime gates remain mandatory.

The new header is `OWNER-AUTHORIZATION solo-owner-3`. Old
`OWNER-REVIEW solo-owner-2` objects remain historical evidence but cannot satisfy
new action gates. Legacy installed pollers ignore the new header. Rationale is
explanation, never authority. A version or header must not be translated for an
old controller. Missing/unknown/conflicting scope fails closed.

See [the exact schema, migration and bootstrap runbook](owner-action-scopes.md).
The isolated owner connector and check publisher must come from separately
reviewed code outside candidate source and production/agent credentials. This
source PR installs nothing and issues no authorization. Required branch checks
and human owner identity cannot be bypassed to bootstrap a new issuer.

Existing governance rollout and real acceptance TODOs remain incomplete. No
fixture or CI result authorizes a deployment, Scout run or autonomy promotion.
