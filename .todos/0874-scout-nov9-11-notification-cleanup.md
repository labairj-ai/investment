# 0874 — Scout November 9–11 review and notification read cleanup

Status: in-progress

Base: 53f70764ab7585f92a4673322c90c4203f0e2099.
Candidate: a0baf7f0-1c5b-4658-b93f-d3155cff7aa9.

Problem: notification query or fetch failure skips closure of its owned connection.
Scope: one try/finally in serve.py; SQL, notification dispatch and fallback unchanged.
Risk: original proposal L5 retained; no autonomy, merge or deployment approval.
Acceptance: real SQLite query/fetch failures close handles; empty results and connect
failure preserve behavior. No server import/startup, email or production DB in tests.
Tests: focused cleanup regressions; all existing aggregate repository gates and CI.
Human decisions: independent review and merge required. Broad refactor deferred.
QA: before fix two failures/two passes; after fix 14 focused passes. Exact-head
full-suite, release-baseline, CC and CI evidence remain required before completion.
