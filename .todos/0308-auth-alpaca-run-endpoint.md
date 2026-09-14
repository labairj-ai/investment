# Authenticate Alpaca Execution Endpoint and Restrict CORS

- **ID:** 0308
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** none

## Problem

`POST /api/trade-engine/run-alpaca` has no authentication. Any client that can reach the service can trigger an execution cycle that submits real paper orders to Alpaca (`submission_enabled=True` is unconditional). Additionally, all responses — including mutation endpoints — return `Access-Control-Allow-Origin: *`, exposing account activity to any origin. The service binds to `0.0.0.0`, so the application itself enforces no boundary; Tailscale ACLs are the only protection today.

## Proposed approach

- Read `TRADE_ENGINE_API_TOKEN` from env in `serve.py` at startup.
- In `_handle_trade_engine_run_alpaca()`, read `X-Trade-Engine-Token` header and compare with `hmac.compare_digest` (constant-time); return 401 if missing or wrong.
- Strip `Access-Control-Allow-Origin: *` from all `/api/alpaca/*` and `/api/trade-engine/run-alpaca` responses; keep wildcard CORS only on read-only dashboard endpoints where it is intentional.
- Add `TRADE_ENGINE_API_TOKEN=<random>` to optiplex `/etc/systemd/system/investment.service.d/override.conf`; generate with `openssl rand -hex 32`.
- Open question: should GET `/api/alpaca/*` (account balance, fills, positions) also require the token, or is read-only exposure acceptable given Tailscale?

## Touches

- `serve.py` — request auth check, CORS headers on alpaca/execution handlers
- `/etc/systemd/system/investment.service.d/override.conf` on optiplex — new env var

## Done when

- [ ] `POST /api/trade-engine/run-alpaca` returns 401 with no or wrong `X-Trade-Engine-Token`
- [ ] Correct token allows the request through
- [ ] `/api/alpaca/*` responses do not include `Access-Control-Allow-Origin: *`
- [ ] `TRADE_ENGINE_API_TOKEN` is set in optiplex systemd override and service restarts cleanly
- [ ] Token is not committed to the git repo
