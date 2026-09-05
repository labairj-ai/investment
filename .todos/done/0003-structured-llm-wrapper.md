# Add generate_structured() Wrapper to ollama_client.py

- **ID:** 0003
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** none

## Problem

The current `generate()` function requests JSON via `response_format: {type: json_object}` but `stream_generate()` does not, yet several structured workflows use `stream_generate()` and parse JSON from the streamed text. This causes defensive parsing workarounds throughout the codebase (e.g., `serve.py` explicitly overwrites strike/expiration after the LLM response because the model sometimes hallucinated those values). Agents require machine-to-machine communication that must be reliable — streaming text-then-parse is fragile for that use case.

## Proposed approach

- Add `generate_structured(prompt, schema, model, thinking=True, retries=2)` to `ollama_client.py`.
- Forces JSON mode on every call.
- Validates the returned JSON against `schema` (can use a simple dict-based check or `jsonschema` if already available).
- Retries up to `retries` times on malformed output, with exponential backoff.
- Records: model name, prompt hash/version identifier, wall-clock latency, retry count.
- Returns a typed dict matching the schema — raises `StructuredOutputError` if all retries fail.
- Reserve `stream_generate()` for human-facing chat only; agent code must use `generate_structured()`.

## Touches

`ollama_client.py`, all agent files (once written), `portfolio_ai.py` (existing structured calls)

## Done when

- [ ] `generate_structured()` exists in `ollama_client.py` with JSON mode + validation + retry
- [ ] At least one existing structured call in `portfolio_ai.py` is migrated to use it as a proof of concept
- [ ] Malformed JSON response triggers retry and logs a warning, not a crash
- [ ] All retries exhausted → raises `StructuredOutputError` with the raw response included for debugging
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

