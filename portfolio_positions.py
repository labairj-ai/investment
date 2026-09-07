"""Canonical portfolio position loader.

All code that needs to read holdings.csv should use this module so that
multi-lot tickers (same ticker appearing on multiple rows) are always
aggregated correctly with weighted-average cost.

Usage:
    from portfolio_positions import load_positions, get_position, get_lots
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from strategy_config import LAYER_NAMES

PROJECT_DIR  = Path(__file__).resolve().parent
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"

_TICKER_ALIASES: dict[str, str] = {"BRK/B": "BRK.B", "BRK/A": "BRK.A"}


def _normalize(ticker: str) -> str:
    t = ticker.strip().upper()
    return _TICKER_ALIASES.get(t, t)


@dataclass
class Lot:
    ticker:        str
    shares:        float
    avg_cost:      float
    layer:         int
    purchase_date: str | None = None


@dataclass
class Position:
    ticker:        str
    shares:        float          # total across all lots
    avg_cost:      float          # weighted-average cost basis
    layer:         int
    layer_label:   str
    lots:          list[Lot] = field(default_factory=list)

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost


def load_positions(csv_path: Path | None = None) -> dict[str, Position]:
    """Return {ticker: Position} aggregated across all lots.

    Multi-lot tickers are merged with weighted-average cost. The layer is taken
    from the first lot for that ticker (a warning is printed on mismatch).
    """
    path = csv_path or HOLDINGS_CSV
    if not path.exists():
        return {}

    raw: dict[str, list[Lot]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            ticker        = _normalize(row["Stock"])
            layer_num     = int(str(row["Layer"]).strip())
            purchase_date = (row.get("PurchaseDate") or "").strip() or None
            lot = Lot(
                ticker=ticker,
                shares=float(row["Shares"]),
                avg_cost=float(row["AvgCost"]),
                layer=layer_num,
                purchase_date=purchase_date,
            )
            raw.setdefault(ticker, []).append(lot)

    result: dict[str, Position] = {}
    for ticker, lots in raw.items():
        total_shares = sum(l.shares for l in lots)
        weighted_cost = (
            sum(l.shares * l.avg_cost for l in lots) / total_shares
            if total_shares > 0 else 0.0
        )
        layer_num = lots[0].layer
        if any(l.layer != layer_num for l in lots[1:]):
            print(f"[portfolio_positions] WARNING: {ticker} has lots in different layers; "
                  f"using layer {layer_num}")
        result[ticker] = Position(
            ticker=ticker,
            shares=total_shares,
            avg_cost=weighted_cost,
            layer=layer_num,
            layer_label=f"Layer {layer_num}: {LAYER_NAMES.get(layer_num, f'Layer {layer_num}')}",
            lots=lots,
        )
    return result


def get_position(ticker: str, csv_path: Path | None = None) -> Position | None:
    """Return aggregated Position for a single ticker, or None if not held."""
    return load_positions(csv_path).get(_normalize(ticker))


def get_lots(ticker: str, csv_path: Path | None = None) -> list[Lot]:
    """Return all individual lots for a ticker."""
    pos = get_position(ticker, csv_path)
    return pos.lots if pos else []
