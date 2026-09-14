"""End-to-end paper integration tests (0296).

These tests hit the real Alpaca paper endpoint. Required environment variables:
  ALPACA_API_KEY       — Alpaca paper API key
  ALPACA_API_SECRET    — Alpaca paper API secret

For order submission tests additionally require (0300):
  ALPACA_INTEGRATION_SUBMIT=1   — must be exactly "1"; "0" or any other value skips
  ALPACA_EXPECTED_ACCOUNT_ID    — the paper account ID to bind the adapter to

Mark: pytest.mark.integration — skipped in CI unless credentials are present.

Run read-only tests:
    ALPACA_API_KEY=... ALPACA_API_SECRET=... pytest tests/test_alpaca_integration.py -m integration -v

Run submission tests (requires clean paper account):
    ALPACA_API_KEY=... ALPACA_API_SECRET=... ALPACA_INTEGRATION_SUBMIT=1 \
    ALPACA_EXPECTED_ACCOUNT_ID=... pytest tests/test_alpaca_integration.py -m integration -v
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL

# ── Skip guards ───────────────────────────────────────────────────────────────

_KEY = os.environ.get("ALPACA_API_KEY")
_SECRET = os.environ.get("ALPACA_API_SECRET")
_HAVE_CREDS = bool(_KEY and _SECRET)

integration = pytest.mark.integration
skip_no_creds = pytest.mark.skipif(
    not _HAVE_CREDS,
    reason="ALPACA_API_KEY / ALPACA_API_SECRET not set — skipping live integration tests",
)


def _make_adapter(submission_enabled: bool = False) -> AlpacaAdapter:
    assert _KEY and _SECRET, "Credentials required"
    expected_account_id = os.environ.get("ALPACA_EXPECTED_ACCOUNT_ID") or None
    return AlpacaAdapter(
        api_key=_KEY,
        api_secret=_SECRET,
        base_url=_ALPACA_PAPER_URL,
        data_url=_ALPACA_DATA_URL,
        submission_enabled=submission_enabled,
        expected_account_id=expected_account_id,
    )


# ── Phase 1: Read-only binding ────────────────────────────────────────────────

@integration
@skip_no_creds
class TestReadOnlyBinding:
    def test_get_account_id_returns_string(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        assert isinstance(account_id, str) and len(account_id) > 0

    def test_get_broker_account_has_positive_values(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        state = adapter.get_broker_account(account_id)
        assert state.account_id == account_id
        assert state.cash > 0
        assert state.nav > 0
        assert state.buying_power >= 0

    def test_get_positions_returns_list(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        positions = adapter.get_positions(account_id)
        assert isinstance(positions, list)
        for p in positions:
            assert isinstance(p.symbol, str)
            assert p.qty > 0

    def test_get_open_orders_returns_list(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        orders = adapter.get_open_orders(account_id)
        assert isinstance(orders, list)

    def test_get_fills_returns_list(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills = adapter.get_fills(account_id)
        assert isinstance(fills, list)
        # All fills should carry the account_id (0298)
        for f in fills:
            assert f.account_id == account_id

    def test_get_quote_aapl_returns_valid_quote(self):
        adapter = _make_adapter()
        quote = adapter.get_quote("AAPL")
        assert quote is not None
        assert quote.bid > 0
        assert quote.ask > 0
        assert quote.ask >= quote.bid
        assert quote.symbol == "AAPL"


# ── Phase 2: Go/no-go matrix ──────────────────────────────────────────────────

@integration
@skip_no_creds
class TestGoNoGoMatrix:
    def test_get_fills_idempotent(self):
        """Matrix point 4: duplicate fill replay — same fill IDs returned on two calls."""
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills_first = adapter.get_fills(account_id)
        fills_second = adapter.get_fills(account_id)
        ids_first = {f.broker_fill_id for f in fills_first}
        ids_second = {f.broker_fill_id for f in fills_second}
        assert ids_first == ids_second

    def test_fill_account_id_never_none(self):
        """Matrix point 5: all fills carry account_id so apply_broker_fill() will pass (0298)."""
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills = adapter.get_fills(account_id)
        for f in fills:
            assert f.account_id is not None, f"fill {f.broker_fill_id} has account_id=None"


# ── Phase 3: Live order tests ─────────────────────────────────────────────────

@integration
@skip_no_creds
class TestLiveOrderRoundTrip:
    """1-share DAY LIMIT order: submit → WORKING → cancel → CANCELLED.

    Requires ALPACA_INTEGRATION_SUBMIT=1 (exactly) and ALPACA_EXPECTED_ACCOUNT_ID (0300).
    """

    @pytest.fixture(autouse=True)
    def require_submit_flag(self):
        # Must be exactly "1" — "0" or any other truthy string does NOT enable (0300)
        if os.environ.get("ALPACA_INTEGRATION_SUBMIT") != "1":
            pytest.skip(
                "ALPACA_INTEGRATION_SUBMIT != '1' — skipping order submission tests"
            )
        if not os.environ.get("ALPACA_EXPECTED_ACCOUNT_ID"):
            pytest.skip(
                "ALPACA_EXPECTED_ACCOUNT_ID not set — required for submission tests (0300)"
            )

    def test_submit_limit_below_market_then_cancel(self):
        from trade_engine.models import TradeIntent, Side, InstrumentType, OrderType, TimeInForce
        adapter = _make_adapter(submission_enabled=True)
        account_id = adapter.get_account_id()

        # Get a far-below-market quote so the order will not fill
        quote = adapter.get_quote("AAPL")
        assert quote is not None
        far_below = round(quote.bid * 0.90, 2)

        client_id = f"test-{uuid.uuid4().hex[:8]}"
        intent = TradeIntent(
            intent_id="integration-test",
            account_id=account_id,
            recommendation_id=None,
            agent_run_id=None,
            instrument_type=InstrumentType.EQUITY,
            symbol="AAPL",
            side=Side.BUY,
            quantity=1.0,
            contracts=None,
            option_type=None,
            strike=None,
            expiration=None,
            order_type=OrderType.LIMIT,
            limit_price=far_below,
            time_in_force=TimeInForce.DAY,
            strategy="integration-test",
            thesis_version=None,
            strategy_config_hash=None,
            policy_hash=None,
            valid_until="2099-12-31T23:59:59Z",
            created_at="2026-09-14T00:00:00Z",
        )

        # Submit
        ack = adapter.submit_order(intent, client_order_id=client_id)
        assert ack.broker_order_id
        assert ack.normalized_state in ("WORKING", "PARTIALLY_FILLED")

        time.sleep(1)

        # Verify lookup by client_order_id works (crash recovery path) (0297)
        found = adapter.find_order_by_client_order_id(client_id)
        assert found is not None
        assert found.symbol == "AAPL"

        # Cancel (204 response handled correctly) (0297)
        cancel_ack = adapter.cancel_order(ack.broker_order_id)
        assert cancel_ack.accepted

        time.sleep(1)

        # Confirm final state
        final = adapter.get_order(ack.broker_order_id)
        assert final is not None
        assert final.state == "CANCELLED"
