# Covered-call behavioral fingerprints (0729–0730)

The canonical registries are in `covered_call_fingerprint.py`. The independently
reviewed expected membership is in `tests/fixtures/cc_behavior_inventory_v1.json`.
`python scripts/check_cc_contract.py --fingerprint-inventory --json` lists every
canonical name, protected constant, configuration key and fingerprint version.

The model inventory has 85 functions, 4 types, 28 constants and 16 config keys.
The simulator inventory has 78 functions, 4 types, 16 constants and 28 config keys.
Every top-level function/class in V3, virtual, rec, surface, tax, outcomes,
evidence, validation, portfolio-position aggregation and CC agent orchestration requires explicit classification. Nested functions and
methods inherit their enclosing protected function/type identity. New functions
are not guessed to be behavioral: the completeness tests require a review choice.
Removing a known required registry entry also fails the independent inventory.

All 14 V3 functions are model behavioral, including bounded() and the thirteen
functions named in 0729. execution() and bounded() also affect virtual fills and
are shared. All sixteen virtual state/provenance/evidence functions are simulator
behavioral. management_contract() and simulator_contract_hash() construct the
fingerprint definition instead of performing economic transitions; their source
is protected as definition components. DataUnavailable is a protected type.

The rec inventory includes entry data preparation, volatility, floor/liquidity
filters, probability/pricing helpers, tax-lot economics, management context and
roll selection. Only print_report(), ai_context() and main() are nonbehavioral:
they format/operator-narrate/orchestrate already protected recommendation output.
Shared prospective management math is directly represented in the simulator
registry. The simulator fingerprint does not depend on unrelated entry utility;
changing utility requires a model bump, changing advance requires a simulator
contract bump, and changing execution requires both.

Agent orchestration, scorer activation, prompts, eligible-share/layer constants,
observe-only mode and preferred DTE bands are model protected. Live mode remains
observe_only; no activation, source-function or economic behavior is changed.

Imported deterministic helpers include the surface/duration model, IRS calendar,
FIFO selection, multi-lot position aggregation, surface/fill history, actual-chain
reconciliation, timestamp/calendar policy, outcome persistence/provenance,
decision creation, paired promotion evidence, validation and cadence policy.
Live prices, tax lots, filesystem locations, DB connection adapters and third-party
library internals are inputs/infrastructure rather than fingerprint values. No
protected module is imported/executed to obtain source or constant identity.
Explicit configuration-key and constant inventories cover the behavior/policy
surface; snapshots continue to bind episode-specific data and policy inputs.

Function/type identities contain canonical AST fields and the named global import
bindings they use. Comments, docstrings, whitespace, locations, empty
interpreter-added type_params, absolute paths, object repr, timestamps and runtime
function replacements are omitted. Each constant is statically resolved by name
and serialized by value; NormalDist parameters and timezone keys are data rather
than object representations. Unsupported constant expressions fail closed.
The fingerprint algorithm and source-provider implementation are themselves named
protected definition components. Registries are sorted by canonical name.

Config fingerprinting reads the actual flat runtime CC V3 config. The historical
single cc_v3 wrapper is also supported, but mixed flat/wrapped config is rejected.
Nonbehavioral config_version/display fields are omitted. Config and provenance
versions needed for virtual execution/promotion are explicitly named. The legacy
_config_contract_hash helper remains represented by source; its historical wrapper
handling is not the release boundary. The new simulator fingerprint covers actual
flat behavior keys, including fees, quote ages, cadence and promotion constraints.

Baseline schema cc-contract-v2 adds fingerprint_version to exact prior/proposed
identity. Legacy cc-contract-v1 is readable only as cc-behavior-v0. This release
moves to cc-behavior-v1 without changing model, simulator, simulator-contract,
management policy or cadence version constants or recommendation economics.

The one-time migration requires an exact EVIDENCE_INFRASTRUCTURE manifest with
fingerprint_migration: legacy-to-named-v1 and an immutable prior Git SHA. It proves
that the prior used the frozen legacy fingerprint definitions, recomputes its
legacy hashes, and compares every newly protected function/type/import binding,
constant, behavior config value and runtime version against the proposed source.
It also recomputes the proposed fingerprints. Any behavioral edit, missing source,
inconsistent prior/candidate identity, runtime version change, missing manifest,
caller prior file, or another definition transition rejects. Candidate promotion
must still exactly match computed current state. Ordinary behavioral transitions
continue to require every applicable forward component bump and exact manifest.

Existing records are not rewritten. New fingerprint identities can censor old
virtual chains and invalidate old certifications under the existing survivability
policy. Tests and this change perform no production database writes. V3 remains
observe-only.

Protected constants include both canonical values and transitive source declarations,
including configuration loading. Module audits reject function/type rebinding,
mutable initializer writes, and unclassified executable initialization so that
replacing a registered implementation outside its definition cannot evade the hash.
