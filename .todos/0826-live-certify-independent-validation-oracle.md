# TODO 0826 — Live-Certify the Independent Validation Oracle

- **ID:** 0826
- **Status:** in-progress
- **Priority:** critical
- **Risk:** L5 — validation trust boundary
- **Depends:** 0818 implementation, 0825
- **Blocks:** 0829, 0831

## Problem

PR #10 contains the isolated validation-oracle design, but fixture/unit tests do not establish that the real OptiPlex installation provides candidate-nonwritable trusted validation.

Before agents are permitted to automatically build software, the independent oracle must be installed and proven against adversarial candidates.

## Scope

### Provision oracle boundary

- [ ] Install oracle process outside candidate-controlled checkout.
- [ ] Use a dedicated runtime identity where practical.
- [ ] Provision private Unix socket.
- [ ] Provision private HMAC/signing key.
- [ ] Socket/key ownership must match trusted orchestration identity.
- [ ] Socket/key must not be group/world readable.
- [ ] Candidate container must not have access to oracle signing key.
- [ ] Builder must not have access to oracle socket unless through the fixed validator protocol.
- [ ] Oracle must never import candidate modules.
- [ ] Oracle must not access production investment data.

### Bind validation

Every trusted receipt must bind:

- [ ] repository;
- [ ] approved base SHA;
- [ ] candidate head SHA;
- [ ] trusted test-tree hash;
- [ ] candidate source-tree hash;
- [ ] expected test inventory;
- [ ] validator image digest;
- [ ] validation command class;
- [ ] process exit result;
- [ ] oracle protocol version.

### Adversarial live acceptance

Run real isolated candidates attempting:

- [ ] fake JUnit PASS;
- [ ] overwrite results;
- [ ] delete results;
- [ ] symlink artifact substitution;
- [ ] `os._exit(0)`;
- [ ] deliberate process crash;
- [ ] deliberate timeout;
- [ ] pytest monkeypatch;
- [ ] pytest plugin injection;
- [ ] candidate `conftest.py`;
- [ ] `sitecustomize.py`;
- [ ] module shadowing;
- [ ] trusted-test mutation;
- [ ] test-inventory truncation;
- [ ] duplicate test IDs;
- [ ] network access;
- [ ] GitHub credential access;
- [ ] SSH credential access;
- [ ] Docker socket access;
- [ ] production DB access.

Every adversarial case must fail closed.

### Certification

- [ ] Generate real, non-fixture technical certificate.
- [ ] Certificate identifies current harness hash.
- [ ] Certificate identifies validator image digest.
- [ ] Certificate includes artifact-integrity PASS.
- [ ] Certificate is time bounded.
- [ ] Harness change invalidates certificate.

## Required QA

- [ ] Clean candidate passes.
- [ ] Failing candidate fails.
- [ ] Candidate-produced result cannot create trusted PASS.
- [ ] Timeout cleans container.
- [ ] No residual candidate process/container.
- [ ] Host source remains unchanged.
- [ ] Oracle receipt is immutable.
- [ ] Wrong signature fails.
- [ ] Wrong candidate SHA fails.
- [ ] Wrong test inventory fails.

## Guardrails

- Do not enable autonomous implementation.
- Do not enable supervised builds until live certificate is PASS.
- Do not store signing key in repository.
- Do not permit candidate-written validation scripts.
- Do not count fixture certification toward operational evidence.

## Done when

- [ ] Real oracle is installed.
- [ ] Live adversarial suite passes.
- [ ] Non-fixture technical certificate is recorded.
- [ ] Dashboard reports current oracle/certificate health.

## Implementation / acceptance handoff — 2026-10-23

Live preflight found runtime/oracle unavailable. The current client is not an independent oracle backend. No backend, signing key, certificate or live adversarial PASS was fabricated; live certification is blocked pending the reviewed independent implementation and provisioning.

See [live operational acceptance](../docs/live-operational-acceptance.md) and the [sanitized live preflight](../docs/evidence/continuous-improvement-20261023/live-acceptance-preflight.json). This task remains in progress until every required live acceptance and release gate is satisfied.
