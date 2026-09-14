"""End-to-end paper integration tests (0296).

These tests hit the real Alpaca paper endpoint. They require:
  - ALPACA_API_KEY and ALPACA_API_SECRET in the environment
  - A clean paper account (no unrecognized open orders or positions)

Mark: pytest.mark.integration — skipped in CI unless credentials are present.

Run:
    ALPACA_API_KEY=... ALPACA_API_SECRET=... pytest tests/test_alpaca_integration.py -m integration -v
"""
from __future__ import annotations

import os
import time

import pytest

from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL

# ── Skip guard ────────────────────────────────────────────────────────────────

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
    return AlpacaAdapter(
        api_key=_KEY,
        api_secret=_SECRET,
        base_url=_ALPACA_PAPER_URL,
        data_url=_ALPACA_DATA_URL,
        submission_enabled=submission_enabled,
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
    """Matrix point 4: duplicate fill replay leaves counts unchanged.

    This test can be run without live order submission because it exercises
    the adapter-level fill mapping and deduplication path.
    """
    def test_get_fills_idempotent(self):
        adapter = _make_adapter()
        account_id = adapter.get_account_id()
        fills_first = adapter.get_fills(account_id)
        fills_second = adapter.get_fills(account_id)
        # Same set of fills returned on two consecutive calls
        ids_first = {f.broker_fill_id for f in fills_first}
        ids_second = {f.broker_fill_id for f in fills_second}
        assert ids_first == ids_second


# ── Phase 3: Live order tests ─────────────────────────────────────────────────

@integration
@skip_no_creds
class TestLiveOrderRoundTrip:
    """1-share DAY LIMIT order: submit → WORKING → cancel → CANCELLED.

    Requires ALPACA_INTEGRATION_SUBMIT=1 in the environment in addition to
    credentials. This prevents accidental order submission during read-only
    integration runs.
    """

    @pytest.fixture(autouse=True)
    def require_submit_flag(self):
        if not os.environ.get("ALPACA_INTEGRATION_SUBMIT"):
            pytest.skip("ALPACA_INTEGRATION_SUBMIT not set — skipping order submission tests")

    def test_submit_limit_below_market_then_cancel(self):
        from trade_engine.models import TradeIntent, Side
        adapter = _make_adapter(submission_enabled=True)
        account_id = adapter.get_account_id()

        # Get a far-below-market quote so the order never fills
        quote = adapter.get_quote("AAPL")
        assert quote is not None
        far_below = round(quote.bid * 0.90, 2)

        import uuid
        client_id = f"test-{uuid.uuid4().hex[:8]}"
        intent = TradeIntent(
            intent_id="integration-test",
            account_id=account_id,
            symbol="AAPL",
            side=Side.BUY,
            quantity=1.0,
            limit_price=far_below,
            recommendation_id=None,
        )

        # Submit
        ack = adapter.submit_order(intent, client_order_id=client_id)
        assert ack.broker_order_id
        assert ack.normalized_state in ("WORKING", "PARTIALLY_FILLED")

        # Brief settle before cancel
        time.sleep(1)

        # Verify order exists by client_order_id
        found = adapter.find_order_by_client_order_id(client_id)
        assert found is not None
        assert found.symbol == "AAPL"

        # Cancel
        cancel_ack = adapter.cancel_order(ack.broker_order_id)
        assert cancel_ack.accepted

        # Confirm final state
        time.sleep(1)
        final = adapter.get_order(ack.broker_order_id)
        assert final is not None
        assert final.state == "CANCELLED"
