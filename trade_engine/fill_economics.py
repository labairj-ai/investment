"""Shared long-equity settlement math. Percentage returns use percentage points."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FillEconomics:
    cost_basis: Decimal | None
    realized_pnl: Decimal | None
    realized_pnl_pct: Decimal | None
    cash_delta: Decimal
    new_qty: Decimal
    new_avg_cost: Decimal


def calculate_fill_economics(side, qty, price, fee, prior_qty, prior_avg_cost) -> FillEconomics:
    """Calculate from pre-fill holdings; fees affect cash/P&L, not average entry price.

    BUYs realize no P&L. Zero-basis SELLs have an undefined percentage return.
    Caller owns identity validation, oversell checks and atomic persistence.
    """
    qty, price, fee, prior_qty, prior_avg_cost = (
        Decimal(str(value)) for value in (qty, price, fee, prior_qty, prior_avg_cost)
    )
    if side in ('BUY', 'BUY_TO_CLOSE'):
        new_qty = prior_qty + qty
        avg = (prior_qty * prior_avg_cost + qty * price) / new_qty if new_qty else Decimal(0)
        return FillEconomics(None, None, None, -(qty * price + fee), new_qty, avg)
    if side not in ('SELL', 'SELL_TO_OPEN'):
        raise ValueError(f'Unsupported fill side: {side!r}')
    basis = qty * prior_avg_cost
    proceeds = qty * price - fee
    pnl = proceeds - basis
    return FillEconomics(basis, pnl, pnl / basis * 100 if basis else None,
                         proceeds, prior_qty - qty, prior_avg_cost)
