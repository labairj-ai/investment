# Development-agent hardening 0785–0794

Base: 54a6ce560e1c440c1a7df06a783c3931bf2fcfd8 (hardening backlog plus current main).
Risk: elevated governance/authority tooling. Human review and merge remain required.

Implement trusted, command-manifest validation and ledger-only sealing first; authenticate
backup provenance without opening production during certification. Separate technical
certification, supervised execution and operational successes. Verify remote PR identity
and effective protection (classic and active repository/inherited rules), then expose
read-only readiness and adversarial certification. Finally add bounded autonomy admission
and prospective pilot accounting with an emergency disable path. Defaults remain disabled.

Validate security boundaries with disposable Git repositories, temporary dedicated ledgers,
real subprocess/JUnit parsing, signed synthetic backup fixtures and GitHub API fixtures.
Run focused and full tests, existing TODO/agent/development/release/CC gates, mobile browser
checks and real PR CI. No production mutations, secret modifications or protection changes.

0785–0792 code is built in dependency order in this integrated PR. External acceptance
remains explicitly open: operator-provisioned sandbox image, authenticated recent production
backup, non-bypass GitHub identity, human review and deployed observations. 0793 requires
three real governed pilots over seven calendar days; neither fixtures nor this coding turn
can satisfy it. 0794 supplies disabled admission controls only until that evidence exists.
No incomplete TODO is moved to done. The user request authorizes implementation, not
fabricated human pilot decisions, automatic merge, deployment or premature activation.
