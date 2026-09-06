"""
Canonical portfolio snapshot builder.

Importable by any agent without circular imports (does not import serve.py).
"""

import json
import sqlite3
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def build_portfolio_snapshot():
    """Build a fully-populated PortfolioSnapshot from the latest DB data.

    Reads holding_day for prices/weights, holdings.csv for shares/avg_cost,
    layer_day for layer weights, and holding_macro_scores for macro scores.
    Returns a PortfolioSnapshot with real data; fields default to 0 if DB is
    not yet populated for today (retry logic lives in the caller).
    """
    import csv as _csv
    from agents.contracts import PortfolioSnapshot, HoldingSnapshot
    from strategy_config import LAYER_LABELS

    db = PROJECT_DIR / "out" / "investment.db"

    csv_map: dict = {}
    csv_path = PROJECT_DIR / "holdings.csv"
    if csv_path.exists():
        with open(csv_path, newline="") as _f:
            for row in _csv.DictReader(_f):
                t = (row.get("Stock") or "").strip().upper()
                if t:
                    try:
                        csv_map[t] = {
                            "shares": float(row.get("Shares") or 0),
                            "avg_cost": float(row.get("AvgCost") or 0),
                            "layer": int(row.get("Layer") or 0),
                        }
                    except (ValueError, TypeError):
                        pass

    price_map: dict = {}
    total_value = 0.0
    layer_weights: dict = {}
    macro_scores: dict = {}

    if db.exists():
        _conn = sqlite3.connect(str(db), timeout=10)
        _conn.row_factory = sqlite3.Row
        try:
            _hday = _conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
            if _hday:
                for r in _conn.execute(
                    "SELECT ticker, price, value, weight_pct FROM holding_day WHERE day=?",
                    (_hday,),
                ):
                    price_map[r["ticker"]] = {
                        "price": r["price"] or 0.0,
                        "value": r["value"] or 0.0,
                        "weight_pct": r["weight_pct"] or 0.0,
                    }
                prow = _conn.execute(
                    "SELECT total_value FROM portfolio_day WHERE day=?", (_hday,)
                ).fetchone()
                if prow:
                    total_value = prow["total_value"] or 0.0

            _lday = _conn.execute("SELECT MAX(day) FROM layer_day").fetchone()[0]
            if _lday:
                _label_to_num = {v: k for k, v in LAYER_LABELS.items()}
                for r in _conn.execute(
                    "SELECT layer, weight_pct FROM layer_day WHERE day=?", (_lday,)
                ):
                    num = _label_to_num.get(r["layer"])
                    if num is not None:
                        layer_weights[num] = r["weight_pct"] or 0.0

            for r in _conn.execute(
                "SELECT ticker, scores FROM holding_macro_scores"
            ):
                try:
                    macro_scores[r["ticker"]] = json.loads(r["scores"])
                except Exception:
                    pass
        finally:
            _conn.close()

    holdings = []
    for ticker, info in csv_map.items():
        pdata = price_map.get(ticker, {})
        holdings.append(HoldingSnapshot(
            ticker=ticker,
            layer=info["layer"],
            shares=info["shares"],
            avg_cost=info["avg_cost"],
            current_price=pdata.get("price", 0.0),
            market_value=pdata.get("value", 0.0),
            weight_pct=pdata.get("weight_pct", 0.0),
        ))

    from datetime import date as _date
    return PortfolioSnapshot(
        date=_date.today().isoformat(),
        total_value=total_value,
        holdings=holdings,
        layer_weights=layer_weights,
        macro_scores=macro_scores,
        generated_at=time.time(),
    )
