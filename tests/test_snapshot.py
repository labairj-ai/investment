"""Tests for snapshot.py — lot aggregation and as_of timestamps."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _parse_csv(rows: list[dict]) -> dict:
    """Simulate the CSV parsing from build_portfolio_snapshot()."""
    csv_map: dict = {}
    for row in rows:
        t = row.get("Stock", "").strip().upper()
        if not t:
            continue
        try:
            shares   = float(row.get("Shares") or 0)
            avg_cost = float(row.get("AvgCost") or 0)
            layer    = int(row.get("Layer") or 0)
            if t in csv_map:
                ex = csv_map[t]
                total = ex["shares"] + shares
                weighted = (ex["shares"] * ex["avg_cost"] + shares * avg_cost) / total if total > 0 else 0.0
                csv_map[t] = {"shares": total, "avg_cost": round(weighted, 4), "layer": ex["layer"]}
            else:
                csv_map[t] = {"shares": shares, "avg_cost": avg_cost, "layer": layer}
        except (ValueError, TypeError):
            pass
    return csv_map


def test_single_lot():
    rows = [{"Stock": "ANET", "Shares": "100", "AvgCost": "150.00", "Layer": "3"}]
    result = _parse_csv(rows)
    assert result["ANET"]["shares"] == 100.0
    assert result["ANET"]["avg_cost"] == 150.0


def test_two_lots_same_ticker():
    rows = [
        {"Stock": "ANET", "Shares": "60", "AvgCost": "110.00", "Layer": "3"},
        {"Stock": "ANET", "Shares": "70", "AvgCost": "145.00", "Layer": "3"},
    ]
    result = _parse_csv(rows)
    assert result["ANET"]["shares"] == 130.0
    expected_cost = (60 * 110 + 70 * 145) / 130
    assert abs(result["ANET"]["avg_cost"] - expected_cost) < 0.01


def test_three_lots_weighted_average():
    rows = [
        {"Stock": "BRK-B", "Shares": "10", "AvgCost": "300.00", "Layer": "1"},
        {"Stock": "BRK-B", "Shares": "20", "AvgCost": "320.00", "Layer": "1"},
        {"Stock": "BRK-B", "Shares": "30", "AvgCost": "340.00", "Layer": "1"},
    ]
    result = _parse_csv(rows)
    assert result["BRK-B"]["shares"] == 60.0
    # weighted avg = (10*300 + 20*320 + 30*340) / 60 = (3000+6400+10200)/60 = 19600/60
    expected = 19600 / 60
    assert abs(result["BRK-B"]["avg_cost"] - expected) < 0.01


def test_mixed_tickers():
    rows = [
        {"Stock": "ANET", "Shares": "50", "AvgCost": "100.00", "Layer": "3"},
        {"Stock": "SCHD", "Shares": "200", "AvgCost": "75.00", "Layer": "2"},
        {"Stock": "ANET", "Shares": "50", "AvgCost": "120.00", "Layer": "3"},
    ]
    result = _parse_csv(rows)
    assert result["ANET"]["shares"] == 100.0
    assert abs(result["ANET"]["avg_cost"] - 110.0) < 0.01
    assert result["SCHD"]["shares"] == 200.0


def test_snapshot_has_price_as_of_field(sample_snapshot):
    """PortfolioSnapshot has price_as_of field and it differs from date on weekends."""
    assert hasattr(sample_snapshot, "price_as_of")
    assert hasattr(sample_snapshot, "portfolio_as_of")
    assert hasattr(sample_snapshot, "layer_as_of")
    assert hasattr(sample_snapshot, "macro_as_of")
    assert hasattr(sample_snapshot, "financials_as_of")
    # price_as_of can differ from the snapshot date (weekend scenario)
    assert sample_snapshot.price_as_of == "2026-09-05"  # Friday
    assert sample_snapshot.date == "2026-09-06"          # Saturday
