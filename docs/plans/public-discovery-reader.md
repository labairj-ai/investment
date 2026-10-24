# Explicit unauthenticated public discovery reader

Original implementation base: `05d6cccf734d4604d1a8c10406d9e3d7598e9c6f`.
Refreshed review base: `ac92da951808fe93b5a1fafc370b0e9b0410e67a` (PR16 merged
separately by explicit owner instruction). Risk: L5, discovery transport/installation
trust boundary. Production remains on the original approved release; no activation
changes. PR17 is not authorized to merge or deploy in this refresh.

Add a discovery-only reader with explicit public/token modes. Public mode must
never inspect credentials or invoke gh, must disable ambient proxies/auth handlers,
and must issue only HTTPS GET repository metadata and the fixed bounded workflow
runs endpoint at api.github.com. Redirects must remain inside that exact reviewed
allowlist. Verify canonical public metadata before and after workflow reads, with
no cached visibility or credential fallback. Token mode requires the existing
private dedicated token and read-only permission verification.

Persist explicit mode/repository in the reviewed installer configuration. Public
installation does not require/read a token; private installation keeps its existing
credential gate. No changes to owner review, CI/protection readers, deployment,
models, financial behavior, L0 scope, genuine timers or authority flags.

Make collection failures invalidate the old spool before network access and publish
an unavailable result, exiting nonzero. Scout must reject spools missing required
CI/telemetry/performance sources. Thus rate-limit/private/transport failures cannot
reuse cached success or create candidates. Preserve all existing negative controls.

Test no secret/file/CLI access, HTTPS GET-only endpoints, redirects, public-to-private
transitions, token compatibility, rate limits and no stale-spool fallback through
actual Scout entry. Run focused/full tests and all eight unchanged release gates,
open an exact-head review PR, and verify real CI. Do not merge, install or deploy.

## Sequential refresh

Merge the new reviewed main into PR17 without rewriting either concern. Preserve
the entire historical 2026-10-24 credential failure/0-of-3 record verbatim, then
append the original explicit public-reader source-support section. Keep public
implementation/tests byte-identical to the prior reviewed PR17 head. Verify the
new-main diff contains only the original nine public-reader files, then rerun the
full eight gates, public adversarial regressions and real exact-head CI. Stop for
ChatGPT review; no merge, deployment, installation, timer or activation changes.
