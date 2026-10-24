# Explicit unauthenticated public discovery reader

Base: approved main `05d6cccf734d4604d1a8c10406d9e3d7598e9c6f`.
Separate from pending PR16's service-fingerprint fix. Risk: L5, discovery transport/
installation trust boundary. Production remains untouched; no activation changes.

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
