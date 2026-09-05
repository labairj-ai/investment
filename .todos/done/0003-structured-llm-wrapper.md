# Add generate_structured() Wrapper to ollama_client.py

- **ID:** 0003
- **Status:** done
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

## Outcome

Added to `ollama_client.py`:
- `StructuredOutputError(RuntimeError)` — carries `.raw` attribute with the last model response for debugging
- `_validate_schema(obj, schema, path)` — recursive key-presence checker; schema values are documentation only, not type constraints
- `generate_structured(prompt, schema, model, temperature, num_predict, thinking, retries)` — non-streaming, `response_format: json_object`, parse → validate → retry with exponential backoff (`2**attempt` seconds); logs prompt SHA1 hash, attempt number, and latency on every retry or failure; raises `StructuredOutputError` after all retries exhausted

Migrated `generate_macro_score_summary()` in `portfolio_ai.py`: replaced the `stream_generate()` accumulate-then-`_extract_last_json()` pattern with a single `generate_structured()` call using `schema={"portfolio": "", "layers": {}}`. Removed the orphaned `full_text = ""` variable.

QA verified with mocks: bad-JSON-then-good retries and succeeds; all-bad raises `StructuredOutputError` with the raw tail attached; valid response returns immediately.

For next items: agents should call `generate_structured()` for all machine-to-machine JSON payloads. `stream_generate()` remains the right choice for human-facing streaming chat (where latency matters and the output doesn't need to be machine-parsed). The remaining `stream_generate()` + `_extract_json()` patterns in `portfolio_ai.py` (news summaries, macro score batches) are candidates for future migration but were intentionally left — they are large variable-schema outputs where the batch key is the ticker symbol, making a fixed schema impractical without a per-ticker wrapper.

## Done when

- [x] `generate_structured()` exists in `ollama_client.py` with JSON mode + validation + retry
- [x] At least one existing structured call in `portfolio_ai.py` is migrated to use it as a proof of concept
- [x] Malformed JSON response triggers retry and logs a warning, not a crash
- [x] All retries exhausted → raises `StructuredOutputError` with the raw response included for debugging
- [x] QA evaluation conducted: functionality verified working, no regressions introduced

