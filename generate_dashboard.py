#!/usr/bin/env python3
"""Generate a self-contained HTML investment dashboard from investment.db."""

import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path("/Users/ai_lab/Desktop/investment")
DB_PATH = PROJECT_DIR / "out" / "investment.db"
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"
OUT_PATH = PROJECT_DIR / "out" / "dashboard.html"
TZ = ZoneInfo("America/New_York")

LAYER_NAMES = {
    1: "Structural Ballast",
    2: "Cash-Flow Engines",
    3: "Compounders",
    4: "Convexity / Optionality",
    5: "Shock Absorbers / Regime Hedges",
}

def normalize_ticker(t: str) -> str:
    t = str(t).strip().upper().lstrip("$")
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            t = f"{left}-{right}"
    return t

def load_csv_holdings() -> dict:
    """Return {ticker: {shares, avg_cost, layer_label}} from holdings.csv — always current."""
    result = {}
    with open(HOLDINGS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker      = normalize_ticker(row["Stock"])
            layer_num   = int(str(row["Layer"]).strip())
            layer_label = f"Layer {layer_num}: {LAYER_NAMES[layer_num]}"
            result[ticker] = {
                "shares":    float(row["Shares"]),
                "avg_cost":  float(row["AvgCost"]),
                "layer":     layer_label,
                "layer_num": layer_num,
            }
    return result

LAYER_COLORS = {
    "Layer 1: Structural Ballast":         "#4A90D9",
    "Layer 2: Cash-Flow Engines":          "#50C878",
    "Layer 3: Compounders":                "#F5A623",
    "Layer 4: Convexity / Optionality":    "#E74C3C",
    "Layer 5: Shock Absorbers / Regime Hedges": "#9B59B6",
}
LAYER_SHORT = {
    "Layer 1: Structural Ballast":         "L1 Ballast",
    "Layer 2: Cash-Flow Engines":          "L2 Cash-Flow",
    "Layer 3: Compounders":                "L3 Compounders",
    "Layer 4: Convexity / Optionality":    "L4 Convexity",
    "Layer 5: Shock Absorbers / Regime Hedges": "L5 Hedges",
}

def money(x):
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"

def pct(x):
    return f"{x:+.2f}%"

def load_data():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    portfolio = [dict(r) for r in conn.execute(
        "SELECT * FROM portfolio_day ORDER BY day"
    )]
    layers = [dict(r) for r in conn.execute(
        "SELECT * FROM layer_day ORDER BY day, layer"
    )]
    holdings = [dict(r) for r in conn.execute(
        "SELECT * FROM holding_day ORDER BY day, layer, ticker"
    )]
    conn.close()
    return portfolio, layers, holdings


def rebuild_today_holdings(today_date: str, db_holdings: list[dict], csv_holdings: dict) -> tuple[list[dict], list[dict]]:
    """
    Rebuild today's per-holding and per-layer snapshots using CSV shares (source of
    truth) and DB prices (last newsletter run).  Returns (holdings, layers).
    """
    # ticker -> price from DB (last known close)
    db_prices = {h["ticker"]: h["price"] for h in db_holdings if h["day"] == today_date}

    rebuilt = []
    for ticker, meta in csv_holdings.items():
        price = db_prices.get(ticker)
        if price is None:
            continue  # ticker added to CSV but not yet priced — skip gracefully
        shares    = meta["shares"]
        avg_cost  = meta["avg_cost"]
        value     = shares * price
        cost_basis = shares * avg_cost
        rebuilt.append({
            "day":        today_date,
            "ticker":     ticker,
            "layer":      meta["layer"],
            "layer_num":  meta["layer_num"],
            "shares":     shares,
            "avg_cost":   avg_cost,
            "price":      price,
            "value":      value,
            "cost_basis": cost_basis,
        })

    # Derive daily change figures: need prev-day prices from DB
    prev_prices = {}
    if db_holdings:
        days_with_data = sorted(set(h["day"] for h in db_holdings if h["day"] < today_date), reverse=True)
        if days_with_data:
            prev_day = days_with_data[0]
            prev_prices = {h["ticker"]: h["price"] for h in db_holdings if h["day"] == prev_day}

    total_value = sum(h["value"] for h in rebuilt)

    for h in rebuilt:
        # Daily change
        prev_price = prev_prices.get(h["ticker"])
        if prev_price and prev_price > 0:
            prev_value = h["shares"] * prev_price
            h["change_dollars"] = h["value"] - prev_value
            h["change_pct"] = (h["change_dollars"] / prev_value) * 100.0
        else:
            h["change_dollars"] = 0.0
            h["change_pct"] = 0.0

        # Total gain vs cost basis
        cost_basis = h["cost_basis"]
        h["total_gain_dollars"] = h["value"] - cost_basis
        h["total_gain_pct"] = ((h["value"] - cost_basis) / cost_basis * 100.0) if cost_basis else 0.0

        h["weight_pct"] = (h["value"] / total_value * 100.0) if total_value else 0.0

    # Rebuild layers
    layer_map: dict[str, dict] = {}
    for h in rebuilt:
        ln = h["layer"]
        if ln not in layer_map:
            layer_map[ln] = {"layer": ln, "value": 0.0, "prev_value": 0.0, "change_dollars": 0.0}
        prev_price = prev_prices.get(h["ticker"])
        layer_map[ln]["value"] += h["value"]
        if prev_price:
            layer_map[ln]["prev_value"] += h["shares"] * prev_price

    layers = []
    for ln, data in layer_map.items():
        pv = data["prev_value"]
        chg = data["value"] - pv
        layers.append({
            "layer": ln,
            "value": data["value"],
            "change_dollars": chg,
            "change_pct": (chg / pv * 100.0) if pv > 0 else 0.0,
            "weight_pct": (data["value"] / total_value * 100.0) if total_value else 0.0,
        })

    layers.sort(key=lambda l: l["layer"])
    return rebuilt, layers, total_value


def build_dashboard(portfolio, layers, holdings):
    today = portfolio[-1] if portfolio else {}
    today_date = today.get("day", "")

    csv_holdings = load_csv_holdings()
    today_holdings, today_layers, total_value_csv = rebuild_today_holdings(today_date, holdings, csv_holdings)

    today_holdings_sorted = sorted(today_holdings, key=lambda h: (h["layer"], -h["value"]))

    total_v = total_value_csv
    total_chg = sum(h["change_dollars"] for h in today_holdings)
    prev_total = total_v - total_chg
    total_chg_pct = (total_chg / prev_total * 100.0) if prev_total else 0.0
    spy_chg = today.get("spy_change_pct", 0)

    # ---- portfolio history chart data ----
    port_dates = [r["day"] for r in portfolio]
    port_values = [r["total_value"] for r in portfolio]
    port_chg_pct = [r["total_change_pct"] for r in portfolio]
    spy_chg_pct = [r["spy_change_pct"] for r in portfolio]

    # Time-weighted return — capital additions (new money) don't inflate the %.
    # When total_value jumps more than price-change alone explains, we close the
    # current sub-period and restart at the post-inflow value, then chain the
    # factors together.  Both series start at 0 % on the first date.
    port_cum    = [0.0]
    _twr_factor = 1.0
    _sub_start  = portfolio[0]["total_value"] if portfolio else 1.0
    for _i in range(1, len(portfolio)):
        _prev = portfolio[_i - 1]["total_value"]
        _curr = portfolio[_i]["total_value"]
        _pchg = portfolio[_i].get("total_change_dollars", 0) or 0
        # Skip weekend/holiday duplicates where the newsletter repeats the same row
        if abs(_curr - _prev) > 1.0:
            _val_ex_cf = _prev + _pchg          # expected value from prices alone
            _cf        = _curr - _val_ex_cf     # residual = external cash flow
            _threshold = max(1000.0, 0.005 * _prev)
            if abs(_cf) > _threshold:
                if _sub_start:
                    _twr_factor *= _val_ex_cf / _sub_start
                _sub_start = _curr
        _within = (_curr / _sub_start) if _sub_start else 1.0
        port_cum.append(round((_twr_factor * _within - 1) * 100, 4))

    # SPY normalized to 0 % on first date, properly compounded
    spy_cum = [0.0]
    _spy_f  = 1.0
    for _r in portfolio[1:]:
        _spy_f *= 1.0 + (_r.get("spy_change_pct", 0) or 0) / 100.0
        spy_cum.append(round((_spy_f - 1) * 100, 4))

    # ---- layer weight history ----
    all_layer_names = sorted(set(l["layer"] for l in layers))
    layer_weight_by_date = {}
    for l in layers:
        d = l["day"]
        if d not in layer_weight_by_date:
            layer_weight_by_date[d] = {}
        layer_weight_by_date[d][l["layer"]] = l["weight_pct"]

    layer_weight_datasets = []
    for ln in all_layer_names:
        layer_weight_datasets.append({
            "label": LAYER_SHORT.get(ln, ln),
            "data": [layer_weight_by_date.get(d, {}).get(ln, 0) for d in port_dates],
            "backgroundColor": LAYER_COLORS.get(ln, "#999"),
            "borderColor": LAYER_COLORS.get(ln, "#999"),
            "fill": False,
            "tension": 0.3,
            "pointRadius": 2,
        })

    # ---- today pie ----
    pie_labels = [LAYER_SHORT.get(l["layer"], l["layer"]) for l in today_layers]
    pie_values = [l["value"] for l in today_layers]
    pie_colors = [LAYER_COLORS.get(l["layer"], "#999") for l in today_layers]

    # ---- today layer bar ----
    layer_bar_labels = [LAYER_SHORT.get(l["layer"], l["layer"]) for l in today_layers]
    layer_bar_chg = [round(l["change_pct"], 3) for l in today_layers]
    layer_bar_colors = [
        "#27ae60" if v >= 0 else "#e74c3c"
        for v in layer_bar_chg
    ]

    # ---- flags ----
    LAYER_GROSS_DOMINANCE_PCT = 50.0
    HOLDING_GROSS_DOMINANCE_PCT = 25.0
    flags = []
    total_change = total_chg

    gross_layers = sum(abs(l["change_dollars"]) for l in today_layers)
    if gross_layers > 1e-9:
        top_l = max(today_layers, key=lambda l: abs(l["change_dollars"]))
        share = abs(top_l["change_dollars"]) / gross_layers * 100
        if share > LAYER_GROSS_DOMINANCE_PCT:
            net_txt = f" (net contribution: {pct((top_l['change_dollars']/total_change)*100)})" if abs(total_change) > 1e-9 else ""
            flags.append(f"⚠️ {top_l['layer']} drove {share:.1f}% of today's gross movement{net_txt}.")

    gross_holdings = sum(abs(h["change_dollars"]) for h in today_holdings)
    if gross_holdings > 1e-9:
        top_h = max(today_holdings, key=lambda h: abs(h["change_dollars"]))
        share = abs(top_h["change_dollars"]) / gross_holdings * 100
        if share > HOLDING_GROSS_DOMINANCE_PCT:
            net_txt = f" (net contribution: {pct((top_h['change_dollars']/total_change)*100)})" if abs(total_change) > 1e-9 else ""
            flags.append(f"⚠️ {top_h['ticker']} drove {share:.1f}% of today's gross movement{net_txt}.")

    flags_html = ""
    if flags:
        flags_html = '<div class="flags">' + "".join(f'<div class="flag">{f}</div>' for f in flags) + "</div>"

    anchor = "process-consistent" if not flags else "process-stressed"
    anchor_color = "#27ae60" if not flags else "#e67e22"

    # ---- holdings table rows ----
    holdings_rows = ""
    prev_layer = None
    for h in today_holdings_sorted:
        if h["layer"] != prev_layer:
            lcolor = LAYER_COLORS.get(h["layer"], "#999")
            holdings_rows += f'<tr class="layer-header"><td colspan="11" style="background:{lcolor}22;border-left:4px solid {lcolor};padding:6px 10px;font-weight:600;color:#333">{h["layer"]}</td></tr>\n'
            prev_layer = h["layer"]
        daily_class = "pos" if h["change_pct"] >= 0 else "neg"
        gain_class  = "pos" if h["total_gain_pct"] >= 0 else "neg"
        holdings_rows += f"""<tr>
          <td>{h["ticker"]}</td>
          <td>{h["shares"]:,.2f}</td>
          <td>${h["avg_cost"]:,.2f}</td>
          <td>${h["price"]:,.2f}</td>
          <td>{money(h["value"])}</td>
          <td class="{gain_class}" style="font-weight:600;">{pct(h["total_gain_pct"])} <span id="stlt-{h["ticker"]}" style="font-size:9px;vertical-align:middle;"></span></td>
          <td class="{daily_class}">{pct(h["change_pct"])}</td>
          <td>{h["weight_pct"]:.1f}%</td>
          <td id="earn-{h["ticker"]}" style="font-size:12px;color:#7f8c8d;">—</td>
          <td><span onclick="openLayerModal('{h["ticker"]}', {h["layer_num"]})"
            style="cursor:pointer;background:{lcolor}18;color:{lcolor};border:1px solid {lcolor}66;border-radius:4px;padding:2px 8px;font-size:10px;font-weight:700;white-space:nowrap;"
            title="Click to reassign layer">L{h["layer_num"]}</span></td>
          <td><button onclick="openLotsModal('{h["ticker"]}', {h["price"]:.4f})" style="font-size:10px;padding:2px 8px;background:#f4f6f9;border:1px solid #dde;border-radius:4px;cursor:pointer;color:#555;" title="View / edit tax lots">Lots</button></td>
        </tr>\n"""

    # ---- layer summary rows ----
    layer_rows = ""
    for l in today_layers:
        lcolor    = LAYER_COLORS.get(l["layer"], "#999")
        chg_class = "pos" if l["change_pct"] >= 0 else "neg"
        layer_num = l["layer"].split()[1].rstrip(":")  # "Layer 3: ..." → "3"
        layer_rows += f"""<tr>
          <td><span class="dot" style="background:{lcolor}"></span>{LAYER_SHORT.get(l["layer"], l["layer"])}</td>
          <td>{money(l["value"])}</td>
          <td>{l["weight_pct"]:.1f}%</td>
          <td class="{chg_class}">{money(l["change_dollars"])}</td>
          <td class="{chg_class}">{pct(l["change_pct"])}</td>
          <td id="layer-earn-{layer_num}" style="font-size:12px;color:#7f8c8d;">—</td>
        </tr>\n"""

    # ---- JSON for charts ----
    layer_weights_by_num = {}
    for _l in today_layers:
        try:
            _n = int(_l["layer"].split()[1].rstrip(":"))
            layer_weights_by_num[_n] = {"weight": round(_l["weight_pct"], 2), "value": round(_l["value"], 2)}
        except Exception:
            pass

    l4_positions = [
        {"ticker": h["ticker"], "value": round(h["value"], 2), "weight": round(h["value"] / total_value_csv * 100, 2) if total_value_csv else 0}
        for h in today_holdings if h.get("layer_num") == 4
    ]

    _lt_path = os.path.join(os.path.dirname(__file__), "layer_targets.json")
    try:
        with open(_lt_path) as _f:
            layer_targets_data = {int(k): v for k, v in json.load(_f).items()}
    except Exception:
        layer_targets_data = {}

    chart_data = json.dumps({
        "dates": port_dates,
        "portValues": port_values,
        "portCum": port_cum,
        "spyCum": spy_cum,
        "portChgPct": port_chg_pct,
        "spyChgPct": spy_chg_pct,
        "pieLabels": pie_labels,
        "pieValues": pie_values,
        "pieColors": pie_colors,
        "layerBarLabels": layer_bar_labels,
        "layerBarChg": layer_bar_chg,
        "layerBarColors": layer_bar_colors,
        "layerWeightDatasets": layer_weight_datasets,
        "layerWeightsByNum":   layer_weights_by_num,
        "layerTargets":        layer_targets_data,
        "l4Positions":         l4_positions,
        "totalValue":          round(total_value_csv, 2),
        "holdings":            [{"ticker": h["ticker"], "layer": h["layer_num"]} for h in today_holdings],
    }, default=float)

    # Covered call ticker dropdown — all holdings sorted alphabetically
    cc_ticker_options = "\n        ".join(
        f'<option value="{h["ticker"]}">{h["ticker"]} ({h["shares"]:,.0f} shares)</option>'
        for h in sorted(today_holdings, key=lambda x: x["ticker"])
        if h["shares"] >= 100
    )

    # Total gain vs cost basis
    total_cost_basis  = sum(h["cost_basis"] for h in today_holdings)
    total_gain_dollars = total_v - total_cost_basis
    total_gain_pct     = (total_gain_dollars / total_cost_basis * 100.0) if total_cost_basis else 0.0
    gain_class_main    = "pos" if total_gain_dollars >= 0 else "neg"

    generated_at = datetime.now(TZ).strftime("%A, %B %d, %Y at %I:%M %p ET")
    chg_class_main = "pos" if total_chg >= 0 else "neg"
    spy_class = "pos" if spy_chg >= 0 else "neg"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Investment Dashboard — {today_date}</title>
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <script src="../chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background: #f4f6f9; color: #2c3e50; font-size: 14px; }}
    h1 {{ font-size: 1.4rem; font-weight: 700; }}
    h2 {{ font-size: 1rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: #7f8c8d; margin-bottom: 12px; }}

    header {{ background: #1a2340; color: #fff; padding: 18px 28px; display: flex; align-items: center; justify-content: space-between; }}
    header .subtitle {{ font-size: .85rem; color: #a0aec0; margin-top: 2px; }}

    .grid {{ display: grid; gap: 18px; padding: 20px 28px; }}
    .kpi-row {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .three-col {{ display: grid; grid-template-columns: 2fr 1fr; gap: 18px; }}

    .card {{ background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.07); }}
    .kpi {{ background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.07); }}
    .kpi .label {{ font-size: .78rem; color: #7f8c8d; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; }}
    .kpi .sub {{ font-size: .82rem; margin-top: 2px; }}

    .pos {{ color: #27ae60; }}
    .neg {{ color: #e74c3c; }}

    canvas {{ max-height: 260px; }}

    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ text-align: left; padding: 7px 10px; border-bottom: 2px solid #eee; color: #7f8c8d; font-weight: 600; font-size: .75rem; text-transform: uppercase; }}
    td {{ padding: 7px 10px; border-bottom: 1px solid #f2f4f7; }}
    tr:last-child td {{ border-bottom: none; }}
    .layer-header td {{ font-size: .8rem; }}
    .dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 7px; vertical-align: middle; }}

    .flags {{ margin-top: 10px; }}
    .flag {{ background: #fff8e1; border-left: 3px solid #f39c12; padding: 8px 12px; margin-bottom: 6px; border-radius: 4px; font-size: .85rem; }}

    .anchor-bar {{ background: #fff; border-radius: 10px; padding: 14px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.07); display: flex; align-items: center; gap: 10px; }}
    .anchor-dot {{ width: 12px; height: 12px; border-radius: 50%; background: {anchor_color}; flex-shrink: 0; }}
    .anchor-bar span {{ font-size: .88rem; }}

    .generated {{ text-align: right; font-size: .75rem; color: #a0aec0; padding: 0 28px 16px; }}

    @media (max-width: 800px) {{
      .kpi-row {{ grid-template-columns: 1fr 1fr 1fr; }}
      .two-col, .three-col {{ grid-template-columns: 1fr; }}
    }}
    @keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>

<!-- ── Tax Lots Modal ─────────────────────────────────────────────────────── -->
<div id="lots-modal-overlay" onclick="closeLots(event)" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;align-items:center;justify-content:center;">
  <div onclick="event.stopPropagation()" style="background:#fff;border-radius:12px;padding:28px 32px;max-width:760px;width:95%;max-height:88vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.2);position:relative;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">
      <div>
        <h2 id="lots-modal-title" style="font-size:1.1rem;font-weight:700;color:#1a2340;margin:0;text-transform:none;letter-spacing:0;"></h2>
        <div id="lots-modal-subtitle" style="font-size:12px;color:#7f8c8d;margin-top:3px;"></div>
      </div>
      <button onclick="closeLotsModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;padding:4px 8px;">✕</button>
    </div>

    <!-- Summary bar -->
    <div id="lots-summary" style="display:none;background:#f8fafc;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px;display:flex;gap:24px;flex-wrap:wrap;"></div>

    <!-- Existing lots table -->
    <div id="lots-table-wrap"></div>

    <!-- Add lot form -->
    <div style="margin-top:20px;padding-top:16px;border-top:1px solid #eee;">
      <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">Add a Lot</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:10px;">
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Purchased</label>
          <input id="lot-date" type="date" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Shares</label>
          <input id="lot-shares" type="number" step="0.001" min="0.001" placeholder="50" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Cost / Share ($)</label>
          <input id="lot-cost" type="number" step="0.01" min="0.01" placeholder="85.00" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Notes (optional)</label>
          <input id="lot-notes" placeholder="e.g. DRIP" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
      </div>
      <button onclick="addLot()" style="padding:7px 18px;background:#1a2340;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">Add Lot</button>
      <span id="lot-status" style="margin-left:10px;font-size:12px;color:#7f8c8d;"></span>
    </div>

    <!-- ── Record a Sale ─────────────────────────────────────────────────── -->
    <div style="margin-top:20px;padding-top:16px;border-top:2px solid #f0f0f0;">
      <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">Record a Sale (FIFO)</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:10px;">
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Date Sold</label>
          <input id="sell-date" type="date" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Shares Sold</label>
          <input id="sell-shares" type="number" step="0.001" min="0.001" placeholder="50" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Sell Price ($)</label>
          <input id="sell-price" type="number" step="0.01" min="0.01" placeholder="95.00" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Notes (optional)</label>
          <input id="sell-notes" placeholder="e.g. rebalance" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
      </div>
      <button onclick="showFifoPreview()" style="padding:7px 18px;background:#e67e22;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">Preview FIFO →</button>
      <span id="sell-status" style="margin-left:10px;font-size:12px;color:#7f8c8d;"></span>
      <div id="fifo-preview-wrap" style="margin-top:12px;"></div>
    </div>

    <!-- ── Sell History ──────────────────────────────────────────────────── -->
    <div style="margin-top:20px;padding-top:16px;border-top:1px solid #eee;">
      <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">Sell History</div>
      <div id="sell-history-wrap"><span style="font-size:13px;color:#aaa;">No sales recorded.</span></div>
    </div>
  </div>
</div>

<!-- ── CC Close Modal ──────────────────────────────────────────────────────── -->
<div id="cc-close-overlay" onclick="closeCCModal(event)"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;align-items:center;justify-content:center;">
  <div onclick="event.stopPropagation()"
    style="background:#fff;border-radius:12px;padding:28px 32px;max-width:480px;width:95%;box-shadow:0 8px 40px rgba(0,0,0,.2);position:relative;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">
      <h2 style="font-size:1.05rem;font-weight:700;color:#1a2340;margin:0;">Close Position</h2>
      <button onclick="closeCCModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;padding:4px 8px;">✕</button>
    </div>
    <div id="cc-close-summary" style="background:#f8fafc;border-radius:8px;padding:12px 16px;margin-bottom:18px;font-size:13px;"></div>

    <div style="font-size:10px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">How did it close?</div>
    <div style="display:flex;gap:8px;margin-bottom:18px;">
      <button id="cc-type-expired"  onclick="setCCCloseType('expired')"
        style="flex:1;padding:8px;border:2px solid #dde;border-radius:7px;background:#fff;font-size:12px;font-weight:600;cursor:pointer;">
        Expired Worthless<br><span style="font-weight:400;color:#888;">Full premium kept</span>
      </button>
      <button id="cc-type-buyback"  onclick="setCCCloseType('buyback')"
        style="flex:1;padding:8px;border:2px solid #dde;border-radius:7px;background:#fff;font-size:12px;font-weight:600;cursor:pointer;">
        Bought Back<br><span style="font-weight:400;color:#888;">Partial profit</span>
      </button>
      <button id="cc-type-assigned" onclick="setCCCloseType('assigned')"
        style="flex:1;padding:8px;border:2px solid #dde;border-radius:7px;background:#fff;font-size:12px;font-weight:600;cursor:pointer;">
        Assigned<br><span style="font-weight:400;color:#888;">Stock called away</span>
      </button>
    </div>

    <div id="cc-buyback-row" style="display:none;margin-bottom:14px;">
      <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Buy-back Price / Contract ($)</label>
      <input id="cc-close-price" type="number" step="0.01" min="0" placeholder="0.09"
        style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:14px;font-weight:600;">
    </div>

    <div style="margin-bottom:18px;">
      <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Close Date</label>
      <input id="cc-close-date" type="date"
        style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:13px;">
    </div>

    <!-- Shown only when Assigned is selected -->
    <div id="cc-assign-sell-row" style="display:none;background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:12px 14px;margin-bottom:14px;">
      <div style="font-size:12px;font-weight:700;color:#7a5c00;margin-bottom:6px;">Assignment = stock sale at strike</div>
      <div style="font-size:12px;color:#555;margin-bottom:10px;" id="cc-assign-sell-desc"></div>
      <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;font-size:13px;">
        <input type="checkbox" id="cc-assign-fifo-check" checked style="margin-top:2px;width:15px;height:15px;cursor:pointer;flex-shrink:0;">
        <span>Record the stock sale in the FIFO tracker<br>
          <span style="font-size:11px;color:#888;">The stock capital gain/loss will appear in the ST/LT gain section above the CC premium income.</span>
        </span>
      </label>
    </div>

    <div id="cc-close-preview" style="display:none;background:#f0fff4;border:1px solid #ade;border-radius:7px;padding:10px 14px;margin-bottom:14px;font-size:13px;"></div>

    <button onclick="confirmCCClose()"
      style="width:100%;padding:10px;background:#1a2340;color:#fff;border:none;border-radius:7px;font-size:14px;font-weight:700;cursor:pointer;">
      Confirm Close
    </button>
    <div id="cc-close-status" style="margin-top:8px;font-size:12px;color:#888;text-align:center;"></div>
  </div>
</div>

<!-- Layer reassignment modal -->
<div id="layer-change-overlay" onclick="closeLayerModal(event)"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;align-items:center;justify-content:center;">
  <div onclick="event.stopPropagation()"
    style="background:#fff;border-radius:12px;padding:28px 32px;max-width:460px;width:95%;box-shadow:0 8px 40px rgba(0,0,0,.2);">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
      <h2 style="font-size:1.05rem;font-weight:700;color:#1a2340;margin:0;">Reassign Layer</h2>
      <button onclick="closeLayerModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;padding:4px 8px;">✕</button>
    </div>
    <div id="layer-change-summary" style="background:#f8fafc;border-radius:8px;padding:10px 14px;margin-bottom:18px;font-size:13px;"></div>
    <div style="font-size:10px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">Move to layer</div>
    <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:20px;">
      <button id="lbtn-1" onclick="pickLayer(1)" style="text-align:left;padding:10px 14px;border:2px solid #dde;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;">
        <span style="font-weight:700;color:#4A90D9;">L1</span> &nbsp;Structural Ballast
      </button>
      <button id="lbtn-2" onclick="pickLayer(2)" style="text-align:left;padding:10px 14px;border:2px solid #dde;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;">
        <span style="font-weight:700;color:#50C878;">L2</span> &nbsp;Cash-Flow Engines
      </button>
      <button id="lbtn-3" onclick="pickLayer(3)" style="text-align:left;padding:10px 14px;border:2px solid #dde;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;">
        <span style="font-weight:700;color:#F5A623;">L3</span> &nbsp;Compounders
      </button>
      <button id="lbtn-4" onclick="pickLayer(4)" style="text-align:left;padding:10px 14px;border:2px solid #dde;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;">
        <span style="font-weight:700;color:#E74C3C;">L4</span> &nbsp;Convexity / Optionality
      </button>
      <button id="lbtn-5" onclick="pickLayer(5)" style="text-align:left;padding:10px 14px;border:2px solid #dde;border-radius:7px;background:#fff;cursor:pointer;font-size:13px;">
        <span style="font-weight:700;color:#9B59B6;">L5</span> &nbsp;Shock Absorbers / Regime Hedges
      </button>
    </div>
    <div style="font-size:11px;color:#aaa;margin-bottom:14px;line-height:1.5;">
      History is rewritten retroactively — the layer weight chart will show this holding as always having been in the new layer, with no artificial spike.
    </div>
    <button onclick="confirmLayerChange()"
      style="width:100%;padding:10px;background:#1a2340;color:#fff;border:none;border-radius:7px;font-size:14px;font-weight:700;cursor:pointer;">
      Confirm Reassignment
    </button>
    <div id="layer-change-status" style="margin-top:8px;font-size:12px;color:#888;text-align:center;"></div>
  </div>
</div>

<header>
  <div>
    <h1>Investment Dashboard</h1>
    <div class="subtitle">{today_date} &nbsp;·&nbsp; {len(today_holdings)} holdings across 5 layers</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px;">
    <label style="font-size:11px;color:#a0aec0;white-space:nowrap;">Tax Bracket</label>
    <select onchange="onTaxBracketChange(this)" style="font-size:12px;padding:5px 10px;border:none;border-radius:5px;background:#2d3a55;color:#e2e8f0;cursor:pointer;">
      <option value="0">$150k MFJ</option>
      <option value="1">$300k MFJ</option>
      <option value="2" selected>$500k MFJ</option>
      <option value="3">$750k MFJ</option>
      <option value="4">$1M+ MFJ</option>
    </select>
  </div>
</header>

<div class="grid">

  <!-- KPI row -->
  <div class="kpi-row">
    <div class="kpi">
      <div class="label">Portfolio Value</div>
      <div class="value">{money(total_v)}</div>
    </div>
    <div class="kpi">
      <div class="label">Daily Change</div>
      <div class="value {chg_class_main}">{money(total_chg)}</div>
      <div class="sub {chg_class_main}">{pct(total_chg_pct)}</div>
    </div>
    <div class="kpi">
      <div class="label">SPY Change</div>
      <div class="value {spy_class}">{pct(spy_chg)}</div>
    </div>
    <div class="kpi">
      <div class="label">Total Gain vs Cost</div>
      <div class="value {gain_class_main}">{money(total_gain_dollars)}</div>
      <div class="sub {gain_class_main}">{pct(total_gain_pct)}</div>
    </div>
    <div class="kpi">
      <div class="label">Est. Annual Dividends</div>
      <div class="value" id="kpi-div-value" style="color:#27ae60;">—</div>
      <div class="sub" id="kpi-div-yield" style="color:#aaa;"></div>
    </div>
    <div class="kpi">
      <div class="label" id="kpi-tax-label">Est. Tax Bill</div>
      <div class="value" id="kpi-tax-value" style="color:#c0392b;">—</div>
      <div class="sub" id="kpi-tax-sub" style="color:#aaa;font-size:11px;"></div>
    </div>
  </div>

  <!-- Discipline anchor -->
  <div class="anchor-bar">
    <div class="anchor-dot"></div>
    <span>Discipline anchor: today's portfolio behavior was <b style="color:{anchor_color}">{anchor}</b> with no judgment violations requiring action.</span>
  </div>

  {flags_html}

  <!-- Investment Goals & Strategy -->
  <div class="card" id="goals-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
      Investment Goals &amp; Strategy
      <span style="font-size:11px;color:#aaa;font-weight:400;">auto-updates with dividend data</span>
    </h2>

    <div style="display:grid;grid-template-columns:1.65fr 1fr;gap:16px;align-items:start;">

      <!-- Dividend Goal (wide left column) -->
      <div style="background:#f8fffe;border:1px solid #d4edda;border-radius:8px;padding:14px 16px;">
        <div style="font-size:11px;font-weight:700;color:#27ae60;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">
          Dividend Goal — $5,000 / mo by 2036
        </div>
        <!-- current status row -->
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:10px;">
          <div>
            <div style="display:flex;align-items:baseline;gap:6px;">
              <span id="goal-div-monthly" style="font-size:26px;font-weight:700;color:#1a2340;">—</span>
              <span style="font-size:12px;color:#7f8c8d;">/ mo gross</span>
            </div>
            <div id="goal-div-net" style="font-size:11px;color:#7f8c8d;">after tax: —</div>
          </div>
          <div style="flex:1;">
            <div style="background:#e8f5e9;border-radius:4px;height:8px;overflow:hidden;margin-bottom:4px;">
              <div id="goal-div-bar" style="height:100%;background:linear-gradient(90deg,#27ae60,#1abc9c);border-radius:4px;width:0%;transition:width .5s;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:10px;">
              <span id="goal-div-pct" style="color:#27ae60;font-weight:600;">0% of target</span>
              <span style="color:#aaa;">$5,000/mo by 2036</span>
            </div>
          </div>
        </div>
        <div id="goal-div-gap"  style="font-size:11px;color:#7f8c8d;margin-bottom:2px;"></div>
        <div id="goal-div-cagr" style="font-size:11px;color:#7f8c8d;margin-bottom:10px;"></div>

        <!-- Portfolio Value Goal -->
        <div style="border-top:1px dashed #c8e6c9;padding-top:10px;margin-bottom:10px;">
          <div style="font-size:11px;font-weight:700;color:#2980b9;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">
            Portfolio Value Goal — $2M by 2036
          </div>
          <div style="display:flex;align-items:center;gap:16px;">
            <div>
              <div style="display:flex;align-items:baseline;gap:5px;">
                <span id="goal-port-value" style="font-size:22px;font-weight:700;color:#1a2340;">—</span>
                <span style="font-size:11px;color:#7f8c8d;">current</span>
              </div>
            </div>
            <div style="flex:1;">
              <div style="background:#dbeafe;border-radius:4px;height:8px;overflow:hidden;margin-bottom:4px;">
                <div id="goal-port-bar" style="height:100%;background:linear-gradient(90deg,#2980b9,#3498db);border-radius:4px;width:0%;transition:width .5s;"></div>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:10px;">
                <span id="goal-port-pct" style="color:#2980b9;font-weight:600;">0% of target</span>
                <span style="color:#aaa;">$2,000,000 by 2036</span>
              </div>
            </div>
          </div>
          <div id="goal-port-cagr" style="font-size:11px;color:#7f8c8d;margin-top:4px;"></div>
        </div>

        <!-- Quarterly targets (dividend + portfolio combined) -->
        <div id="goal-div-milestones" style="font-size:11px;"></div>
      </div>

      <!-- Right column: Barbell + Principles stacked -->
      <div style="display:flex;flex-direction:column;gap:14px;">

        <!-- Layer Allocation vs Target -->
        <div style="background:#fff;border:1px solid #e0e7ef;border-radius:8px;padding:12px 14px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <div style="font-size:11px;font-weight:700;color:#1a2340;text-transform:uppercase;letter-spacing:.05em;">
              Layer Allocation vs Target
            </div>
            <div style="font-size:9px;color:#bbb;letter-spacing:.03em;">bar scale: 0–50%</div>
          </div>
          <div id="goal-layer-alloc" style="font-size:11px;">
            <div style="color:#aaa;font-style:italic;">Loading…</div>
          </div>
        </div>

        <!-- Recommended Purchases -->
        <div style="background:#fff;border:1px solid #e0e7ef;border-radius:8px;padding:12px 14px;">
          <div style="font-size:11px;font-weight:700;color:#1a2340;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">
            Recommended Purchases
          </div>
          <div id="goal-recommendations" style="display:flex;flex-direction:column;gap:8px;font-size:11px;">
            <div style="color:#aaa;font-style:italic;">Loading…</div>
          </div>
        </div>

      </div><!-- end right column -->

    </div>
  </div>

  <!-- Main charts row -->
  <div class="card">
    <h2>Portfolio vs SPY — Cumulative Return <span style="font-size:11px;font-weight:400;color:#aaa;">(time-weighted, since Feb 11 2026)</span></h2>
    <canvas id="cumChart"></canvas>
  </div>

  <!-- Layer weight drift + today bar -->
  <div class="two-col">
    <div class="card">
      <h2>Layer Weight Over Time (%)</h2>
      <canvas id="weightChart"></canvas>
    </div>
    <div class="card">
      <h2>Today's Layer Performance</h2>
      <canvas id="layerBar"></canvas>
    </div>
  </div>

  <!-- Layer table -->
  <div class="card">
    <h2>Layer Summary — {today_date}</h2>
    <table>
      <thead><tr><th>Layer</th><th>Value</th><th>Weight</th><th>Δ $</th><th>Δ %</th><th>Next Earnings</th></tr></thead>
      <tbody>{layer_rows}</tbody>
    </table>
  </div>

  <!-- Holdings table -->
  <div class="card">
    <h2>Holdings — {today_date}</h2>

    <!-- Add position form -->
    <details style="margin-bottom:16px;">
      <summary style="cursor:pointer;font-size:12px;font-weight:600;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;padding:6px 0;">
        + Add Position
      </summary>
      <div style="margin-top:12px;padding:14px 16px;background:#f8fafc;border-radius:8px;border:1px solid #eee;">
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:12px;">
          <div>
            <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Ticker</label>
            <input id="add-pos-ticker" placeholder="e.g. AAPL" autocomplete="off"
              style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;text-transform:uppercase;">
          </div>
          <div>
            <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Shares</label>
            <input id="add-pos-shares" type="number" step="0.001" min="0" placeholder="100"
              style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
          </div>
          <div>
            <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Avg Cost / Share ($)</label>
            <input id="add-pos-cost" type="number" step="0.01" min="0" placeholder="150.00"
              style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
          </div>
          <div>
            <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Layer</label>
            <select id="add-pos-layer"
              style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;background:#fff;">
              <option value="1">L1 — Structural Ballast</option>
              <option value="2">L2 — Cash-Flow Engines</option>
              <option value="3" selected>L3 — Compounders</option>
              <option value="4">L4 — Convexity / Optionality</option>
              <option value="5">L5 — Shock Absorbers / Hedges</option>
            </select>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <button onclick="addHolding()"
            style="padding:7px 18px;background:#1a2340;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">
            Add Position
          </button>
          <span id="add-pos-status" style="font-size:12px;color:#7f8c8d;"></span>
        </div>
        <div style="font-size:11px;color:#aaa;margin-top:10px;line-height:1.5;">
          After adding, use <b>Lots</b> to record the tax purchase date(s) and cost basis for each lot.
          The current market price is fetched automatically — the position will appear in the table after saving.
        </div>
      </div>
    </details>

    <table>
      <thead><tr><th>Ticker</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Total Gain</th><th>Daily Δ</th><th>Weight</th><th>Next Earnings</th><th>Layer</th><th>Tax Lots</th></tr></thead>
      <tbody>{holdings_rows}</tbody>
    </table>
    <p style="font-size:11px;color:#aaa;margin-top:8px;">ST = short-term (&lt;1yr) · LT = long-term (≥1yr) — derived from your tax lots. Click <b>Lots</b> to add or view purchase history.</p>
  </div>

  <!-- Realized Gains & Tax Estimate -->
  <div class="card" id="realized-gains-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
      <span>Realized Gains &amp; Tax Estimate</span>
      <div style="display:flex;gap:8px;align-items:center;">
        <select id="gains-year-filter" onchange="renderRealizedGains()" style="font-size:12px;padding:4px 8px;border:1px solid #dde;border-radius:5px;background:#f9f9f9;cursor:pointer;">
          <option value="cur">This Year</option>
          <option value="all">All Time</option>
        </select>
        <button onclick="renderRealizedGains()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;">↻</button>
      </div>
    </h2>

    <!-- KPI row -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px;" id="gains-kpi-row">
      <div style="background:#f8fafc;border-radius:8px;padding:14px 16px;">
        <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Total Realized G/L</div>
        <div id="gains-total" style="font-size:22px;font-weight:700;color:#1a2340;">—</div>
        <div id="gains-txn-count" style="font-size:11px;color:#aaa;margin-top:2px;"></div>
      </div>
      <div style="background:#fff0f0;border-radius:8px;padding:14px 16px;border-left:3px solid #e74c3c;">
        <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Short-Term (&lt;1yr)</div>
        <div id="gains-st" style="font-size:22px;font-weight:700;color:#e74c3c;">—</div>
        <div id="gains-st-sub" style="font-size:11px;color:#aaa;margin-top:2px;">Taxed as ordinary income</div>
      </div>
      <div style="background:#f0fff4;border-radius:8px;padding:14px 16px;border-left:3px solid #27ae60;">
        <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Long-Term (≥1yr)</div>
        <div id="gains-lt" style="font-size:22px;font-weight:700;color:#27ae60;">—</div>
        <div style="font-size:11px;color:#aaa;margin-top:2px;">Preferred cap gains rate</div>
      </div>
    </div>

    <!-- Tax estimate row -->
    <div style="background:#f4f6f9;border-radius:8px;padding:14px 18px;margin-bottom:16px;">
      <div style="font-size:10px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">
        Estimated Federal Tax
        <span style="font-weight:400;text-transform:none;letter-spacing:0;margin-left:6px;color:#bbb;">Adjust rates for your bracket · saved in browser</span>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end;">
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">ST Rate</label>
          <div style="display:flex;align-items:center;gap:4px;margin-top:3px;">
            <input id="tax-st-rate" type="number" min="0" max="60" step="0.5" value="35"
              oninput="renderRealizedGains()"
              style="width:64px;padding:5px 7px;border:1px solid #dde;border-radius:5px;font-size:13px;font-weight:600;">
            <span style="font-size:13px;color:#555;">%</span>
          </div>
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">LT Rate</label>
          <div style="display:flex;align-items:center;gap:4px;margin-top:3px;">
            <input id="tax-lt-rate" type="number" min="0" max="40" step="0.5" value="20"
              oninput="renderRealizedGains()"
              style="width:64px;padding:5px 7px;border:1px solid #dde;border-radius:5px;font-size:13px;font-weight:600;">
            <span style="font-size:13px;color:#555;">%</span>
          </div>
        </div>
        <div>
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">NIIT (3.8%)</label>
          <div style="margin-top:6px;">
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;">
              <input id="tax-niit" type="checkbox" onchange="renderRealizedGains()" style="width:15px;height:15px;cursor:pointer;">
              <span style="color:#555;">Include</span>
            </label>
          </div>
        </div>
        <div style="padding-bottom:2px;">
          <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">Est. ST Tax</div>
          <div id="tax-est-st" style="font-size:18px;font-weight:700;color:#c0392b;">—</div>
        </div>
        <div style="padding-bottom:2px;">
          <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">Est. LT Tax</div>
          <div id="tax-est-lt" style="font-size:18px;font-weight:700;color:#27ae60;">—</div>
        </div>
        <div style="padding-bottom:2px;border-left:2px solid #dde;padding-left:18px;">
          <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">Total Est. Tax</div>
          <div id="tax-est-total" style="font-size:22px;font-weight:700;color:#1a2340;">—</div>
        </div>
      </div>
      <div style="font-size:10px;color:#bbb;margin-top:8px;">Federal only · does not include state taxes · consult a tax advisor</div>
    </div>

    <!-- Per-transaction table -->
    <div id="gains-table-wrap">
      <div style="font-size:13px;color:#aaa;">No sales recorded yet. Use the Lots modal on any holding to record a sale.</div>
    </div>
  </div>

  <!-- Buffett Deep-Dive Analyzer -->
  <div class="card" id="buffett-deep-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
      <span>Buffett Deep-Dive Analyzer</span>
      <div style="display:flex;gap:8px;align-items:center;">
        <input id="deep-ticker-input" placeholder="e.g. AAPL" maxlength="10"
          style="width:100px;padding:5px 10px;border:1px solid #dde;border-radius:5px;font-size:13px;text-transform:uppercase;"
          onkeydown="if(event.key==='Enter')runDeepAnalysis()">
        <button onclick="runDeepAnalysis()"
          style="padding:5px 16px;background:#1a2340;color:#fff;border:none;border-radius:5px;font-size:13px;font-weight:600;cursor:pointer;">
          Analyze
        </button>
      </div>
    </h2>
    <div id="deep-status" style="font-size:13px;color:#7f8c8d;min-height:20px;"></div>

    <!-- Summary bar (hidden until result loads) -->
    <div id="deep-summary" style="display:none;align-items:center;gap:20px;flex-wrap:wrap;
         background:#f8fafc;border-radius:8px;padding:14px 18px;margin:14px 0;">
      <div>
        <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.04em;">Ticker</div>
        <div id="deep-ticker-label" style="font-size:22px;font-weight:800;color:#1a2340;"></div>
      </div>
      <div>
        <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.04em;">Price</div>
        <div id="deep-price-label" style="font-size:22px;font-weight:700;color:#1a2340;"></div>
      </div>
      <div style="border-left:2px solid #dde;padding-left:18px;">
        <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.04em;">Buffett Score</div>
        <div id="deep-score-label" style="font-size:28px;font-weight:800;"></div>
      </div>
      <div id="deep-score-bar-wrap" style="flex:1;min-width:180px;">
        <div style="background:#e8ecf0;border-radius:4px;height:8px;overflow:hidden;">
          <div id="deep-score-bar" style="height:8px;border-radius:4px;transition:width .4s;"></div>
        </div>
        <div id="deep-score-label2" style="font-size:11px;color:#888;margin-top:4px;"></div>
      </div>
    </div>

    <!-- Results table -->
    <div id="deep-results-wrap"></div>
  </div>

  <!-- Covered Call Analyzer -->
  <div class="card" id="cc-card">
    <h2>Covered Call Analyzer</h2>
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">
      <select id="cc-ticker" style="padding:8px 12px;border:1px solid #dde;border-radius:6px;font-size:13px;background:#fff;color:#2c3e50;min-width:160px;">
        <option value="">Select a holding…</option>
        {cc_ticker_options}
      </select>
      <button id="cc-btn" onclick="analyzeCoveredCall()"
        style="padding:8px 18px;background:#1a2340;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">
        Get Recommendations
      </button>
      <span id="cc-status" style="font-size:12px;color:#7f8c8d;"></span>
    </div>
    <div id="cc-results"></div>
  </div>

  <!-- Covered Call Position Tracker -->
  <div class="card" id="cc-tracker-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;">
      Covered Call Position Tracker
      <button onclick="loadCCPositions()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:500;">↻ Refresh</button>
    </h2>

    <!-- Log new position form -->
    <details style="margin-bottom:16px;">
      <summary style="cursor:pointer;font-size:12px;font-weight:600;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;padding:6px 0;">
        + Log New Position
      </summary>
      <div style="margin-top:12px;padding:14px 16px;background:#f8fafc;border-radius:8px;border:1px solid #eee;">
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:10px;">
          <div><label style="font-size:10px;color:#aaa;text-transform:uppercase;">Ticker</label>
            <input id="cc-log-ticker" placeholder="e.g. EW" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;text-transform:uppercase;"></div>
          <div><label style="font-size:10px;color:#aaa;text-transform:uppercase;">Contracts</label>
            <input id="cc-log-contracts" type="number" min="1" placeholder="1" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;"></div>
          <div><label style="font-size:10px;color:#aaa;text-transform:uppercase;">Strike ($)</label>
            <input id="cc-log-strike" type="number" step="0.5" placeholder="100.00" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;"></div>
          <div><label style="font-size:10px;color:#aaa;text-transform:uppercase;">Expiry</label>
            <input id="cc-log-expiry" type="date" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;"></div>
          <div><label style="font-size:10px;color:#aaa;text-transform:uppercase;">Premium / Contract ($)</label>
            <input id="cc-log-premium" type="number" step="0.01" placeholder="2.50" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;"></div>
          <div><label style="font-size:10px;color:#aaa;text-transform:uppercase;">Opened</label>
            <input id="cc-log-date" type="date" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;"></div>
        </div>
        <div style="margin-bottom:10px;">
          <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Notes (optional)</label>
          <input id="cc-log-notes" placeholder="e.g. earnings next week" style="width:100%;margin-top:3px;padding:6px 8px;border:1px solid #dde;border-radius:5px;font-size:13px;">
        </div>
        <button onclick="logCCPosition()"
          style="padding:7px 18px;background:#1a2340;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">
          Log Position
        </button>
        <span id="cc-log-status" style="margin-left:10px;font-size:12px;color:#7f8c8d;"></span>
      </div>
    </details>

    <!-- Positions table -->
    <div id="cc-tracker-status" style="font-size:12px;color:#7f8c8d;">Loading…</div>
    <div id="cc-tracker-results"></div>
  </div>

  <!-- Dividend Timeline Chart -->
  <div class="card">
    <h2>Dividend Income by Month</h2>
    <div id="div-timeline-status" style="font-size:12px;color:#7f8c8d;">Loading…</div>
    <canvas id="divTimelineChart" style="max-height:220px;display:none;"></canvas>
  </div>

  <!-- Dividends -->
  <div class="card" id="div-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;">
      Upcoming Dividends
      <button onclick="loadDividends()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:500;">↻ Refresh</button>
    </h2>
    <div id="div-status" style="font-size:12px;color:#7f8c8d;">Loading…</div>
    <div id="div-results"></div>

    <!-- Ticker Lookup -->
    <div style="margin-top:24px;padding-top:18px;border-top:1px solid #eee;">
      <h2 style="margin-bottom:12px;">Dividend Lookup</h2>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <input id="lookup-ticker" type="text" placeholder="Ticker (e.g. VYM)"
          style="padding:7px 12px;border:1px solid #dde;border-radius:6px;font-size:13px;width:130px;text-transform:uppercase;"
          onkeydown="if(event.key==='Enter') lookupDividend()">
        <input id="lookup-shares" type="number" placeholder="# Shares" min="1"
          style="padding:7px 12px;border:1px solid #dde;border-radius:6px;font-size:13px;width:120px;"
          onkeydown="if(event.key==='Enter') lookupDividend()">
        <button onclick="lookupDividend()"
          style="padding:7px 18px;background:#1a2340;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">
          Look Up
        </button>
        <span id="lookup-status" style="font-size:12px;color:#7f8c8d;"></span>
      </div>
      <div id="lookup-results" style="margin-top:14px;"></div>
    </div>
  </div>

  <!-- Buffett Screener -->
  <div class="card" id="buffett-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
      Buffett Screener — NYSE + NASDAQ Winners
      <span style="display:flex;gap:6px;align-items:center;">
        <button id="buffett-run-btn" onclick="triggerBuffettScan()"
          style="font-size:11px;padding:4px 12px;background:#1a2340;color:#fff;border:none;border-radius:5px;cursor:pointer;font-weight:500;">
          ▶ Run Scan
        </button>
        <button onclick="loadBuffett()"
          style="font-size:11px;padding:4px 10px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;">
          ↻
        </button>
      </span>
    </h2>

    <!-- Status banner -->
    <div id="buffett-status-bar" style="margin-bottom:12px;"></div>

    <!-- Progress bar (hidden when idle) -->
    <div id="buffett-progress-wrap" style="display:none;margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#7f8c8d;margin-bottom:4px;">
        <span id="buffett-progress-label">Scanning…</span>
        <span id="buffett-progress-pct"></span>
      </div>
      <div style="background:#eef0f4;border-radius:4px;height:8px;overflow:hidden;">
        <div id="buffett-progress-bar"
          style="height:100%;background:linear-gradient(90deg,#2980b9,#27ae60);border-radius:4px;transition:width .4s ease;width:0%;"></div>
      </div>
      <div id="buffett-eta" style="font-size:11px;color:#7f8c8d;margin-top:4px;"></div>
    </div>

    <!-- Criteria chips -->
    <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:14px;">
      <span style="font-size:10px;padding:2px 7px;background:#e8f8f0;color:#27ae60;border-radius:10px;border:1px solid #b2dfcc;">Gross ≥40%</span>
      <span style="font-size:10px;padding:2px 7px;background:#f4f6f9;color:#555;border-radius:10px;border:1px solid #dde;">SG&amp;A ≤30%</span>
      <span style="font-size:10px;padding:2px 7px;background:#e8f8f0;color:#27ae60;border-radius:10px;border:1px solid #b2dfcc;">Net Income ≥20%</span>
      <span style="font-size:10px;padding:2px 7px;background:#f4f6f9;color:#555;border-radius:10px;border:1px solid #dde;">Interest ≤15%</span>
      <span style="font-size:10px;padding:2px 7px;background:#f4f6f9;color:#555;border-radius:10px;border:1px solid #dde;">CapEx ≤50%</span>
      <span style="font-size:10px;padding:2px 7px;background:#e8f8f0;color:#27ae60;border-radius:10px;border:1px solid #b2dfcc;">Cash &gt; Debt</span>
      <span style="font-size:10px;padding:2px 7px;background:#ebf5fb;color:#2980b9;border-radius:10px;border:1px solid #aed6f1;">+ P/E · P/FCF · EV/EBITDA</span>
    </div>

    <!-- Winners table -->
    <div id="buffett-results"></div>

    <!-- Log panel (collapsible) -->
    <div id="buffett-log-wrap" style="display:none;margin-top:12px;">
      <div onclick="document.getElementById('buffett-log-body').style.display = document.getElementById('buffett-log-body').style.display==='none' ? 'block' : 'none'"
        style="font-size:11px;color:#7f8c8d;cursor:pointer;user-select:none;padding:4px 0;">
        ▾ Recent screener log
      </div>
      <div id="buffett-log-body" style="display:none;background:#1a1a2e;border-radius:6px;padding:10px 12px;margin-top:4px;max-height:180px;overflow-y:auto;">
        <pre id="buffett-log-pre" style="margin:0;font-size:11px;line-height:1.6;white-space:pre-wrap;word-break:break-all;"></pre>
      </div>
    </div>
  </div>
  </div>

</div>

<div class="generated">Generated {generated_at}</div>

<script>
const D = {chart_data};

// Cumulative return chart
new Chart(document.getElementById("cumChart"), {{
  type: "line",
  data: {{
    labels: D.dates,
    datasets: [
      {{
        label: "Portfolio",
        data: D.portCum,
        borderColor: "#4A90D9",
        backgroundColor: "rgba(74,144,217,0.08)",
        fill: true,
        tension: 0.3,
        pointRadius: 1,
        borderWidth: 2,
      }},
      {{
        label: "SPY",
        data: D.spyCum,
        borderColor: "#e67e22",
        backgroundColor: "transparent",
        tension: 0.3,
        pointRadius: 1,
        borderWidth: 1.5,
        borderDash: [5,3],
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: "index", intersect: false }},
    plugins: {{ legend: {{ position: "top" }} }},
    scales: {{
      y: {{
        ticks: {{ callback: v => v.toFixed(1) + "%" }},
        grid: {{ color: "#f0f0f0" }}
      }},
      x: {{ grid: {{ display: false }}, ticks: {{ maxTicksLimit: 8 }} }}
    }}
  }}
}});

// Pie chart
// Layer weight over time
new Chart(document.getElementById("weightChart"), {{
  type: "line",
  data: {{ labels: D.dates, datasets: D.layerWeightDatasets }},
  options: {{
    responsive: true,
    interaction: {{ mode: "index", intersect: false }},
    plugins: {{ legend: {{ position: "bottom", labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }} }},
    scales: {{
      y: {{
        ticks: {{ callback: v => v.toFixed(0) + "%" }},
        grid: {{ color: "#f0f0f0" }}
      }},
      x: {{ grid: {{ display: false }}, ticks: {{ maxTicksLimit: 8 }} }}
    }}
  }}
}});

// Today's layer bar
new Chart(document.getElementById("layerBar"), {{
  type: "bar",
  data: {{
    labels: D.layerBarLabels,
    datasets: [{{
      label: "Δ % today",
      data: D.layerBarChg,
      backgroundColor: D.layerBarColors,
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{
        ticks: {{ callback: v => v.toFixed(2) + "%" }},
        grid: {{ color: "#f0f0f0" }}
      }},
      x: {{ grid: {{ display: false }} }}
    }}
  }}
}});

// ── Dividends ──────────────────────────────────────────────────────────────
// 2026 MFJ tax brackets (after ~$30k standard deduction)
// qualified = cap gains rate + NIIT; ordinary = marginal rate + NIIT
const TAX_BRACKETS = [
  {{ label: "$150k household",  qualified: 0.15,  niit: 0.000, ordinary: 0.22 }},
  {{ label: "$300k household",  qualified: 0.15,  niit: 0.038, ordinary: 0.24 }},
  {{ label: "$500k household",  qualified: 0.15,  niit: 0.038, ordinary: 0.32 }},
  {{ label: "$750k household",  qualified: 0.20,  niit: 0.038, ordinary: 0.35 }},
  {{ label: "$1M+ household",   qualified: 0.20,  niit: 0.038, ordinary: 0.37 }},
];
let CURRENT_BRACKET = TAX_BRACKETS[2];  // default $500k

function effectiveRate(tax_type) {{
  if (tax_type === "tax_exempt") return 0;
  if (tax_type === "ordinary")   return CURRENT_BRACKET.ordinary + CURRENT_BRACKET.niit;
  return CURRENT_BRACKET.qualified + CURRENT_BRACKET.niit;  // qualified
}}

function taxTypeLabel(tax_type) {{
  if (tax_type === "tax_exempt") return "Tax-Exempt";
  if (tax_type === "ordinary")   return "Ordinary";
  return "Qualified";
}}

// ── Dividend Lookup ───────────────────────────────────────────────────────────
async function lookupDividend() {{
  const ticker  = (document.getElementById("lookup-ticker").value || "").trim().toUpperCase();
  const shares  = parseFloat(document.getElementById("lookup-shares").value) || 0;
  const status  = document.getElementById("lookup-status");
  const results = document.getElementById("lookup-results");

  if (!ticker) {{ status.textContent = "Enter a ticker."; return; }}

  status.textContent = `Fetching ${{ticker}}…`;
  results.innerHTML  = "";

  try {{
    const res  = await fetch(`/api/dividend-lookup?ticker=${{ticker}}&shares=${{shares}}`);
    const d    = await res.json();
    if (!d.ok) {{ status.textContent = d.error || "Not found."; return; }}
    status.textContent = "";

    if (!d.annual_rate) {{
      results.innerHTML = `<p style="color:#888;font-size:13px;">
        <b>${{d.ticker}}</b> (${{d.name}}) — no dividend history found. Current price: $${{d.price?.toFixed(2) ?? "—"}}</p>`;
      return;
    }}

    const rate      = effectiveRate(d.tax_type || "qualified");
    const typeLabel = taxTypeLabel(d.tax_type || "qualified");
    const ratePct   = (rate * 100).toFixed(1) + "%";
    const tax       = d.annual_income ? d.annual_income * rate : null;
    const net       = d.annual_income ? d.annual_income * (1 - rate) : null;
    const fmt       = v => v != null ? "$" + v.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}) : "—";

    // Portfolio comparison
    const portAnnual = _divData
      ? _divData.results.reduce((s,r) => s + (r.annual_income||0), 0) : 0;
    const portNet    = _divData
      ? _divData.results.reduce((s,r) => s + (r.annual_income||0)*(1-effectiveRate(r.tax_type||"qualified")), 0) : 0;
    const newAnnual  = portAnnual + (d.annual_income || 0);
    const newNet     = portNet    + (net || 0);

    const exInfo = d.ex_div_date
      ? `${{d.ex_div_date}}${{d.days_to_ex != null ? ` (${{d.days_to_ex >= 0 ? d.days_to_ex+"d away" : Math.abs(d.days_to_ex)+"d ago"}})` : ""}}`
      : "—";
    const taxColor = d.tax_type === "tax_exempt" ? "#27ae60"
                   : d.tax_type === "ordinary"   ? "#c8102e" : "#555";

    results.innerHTML = `
      <div style="background:#f8fafc;border:1.5px solid #dde;border-radius:8px;padding:16px 20px;">
        <div style="font-size:14px;font-weight:700;margin-bottom:10px;color:#1a2340;">
          ${{d.ticker}} &nbsp;<span style="font-weight:400;color:#7f8c8d;font-size:12px;">${{d.name}}</span>
          <span style="float:right;font-size:12px;color:#555;">$${{d.price?.toFixed(2)}} / share</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px;">
          ${{card("Ex-Div Date", exInfo)}}
          ${{card("Pay Date", d.pay_date || "—")}}
          ${{card("Amount / Share", d.declared_amount ? "$"+d.declared_amount.toFixed(4) : "—")}}
          ${{card("Annual Rate", d.annual_rate ? "$"+d.annual_rate.toFixed(4) : "—")}}
          ${{card("Div Yield", d.div_yield ? d.div_yield.toFixed(2)+"%" : "—")}}
          ${{card("Tax Type", `<span style="color:${{taxColor}}">${{typeLabel}} (${{ratePct}})</span>`)}}
        </div>
        ${{shares > 0 ? `
        <div style="border-top:1px solid #eee;padding-top:12px;margin-top:4px;">
          <div style="font-size:12px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">
            With ${{shares.toLocaleString()}} shares
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px;">
            ${{card("This Payout", fmt(d.total_payout))}}
            ${{card("Annual Income", fmt(d.annual_income), "#1a2340")}}
            ${{card("Est. Tax", tax ? `-${{(tax).toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}` : "—", "#e74c3c")}}
            ${{card("Net After-Tax", fmt(net), "#27ae60")}}
          </div>
          <div style="font-size:12px;color:#555;background:#fff;border:1px solid #e8f0fe;border-radius:6px;padding:10px 14px;">
            📊 <b>Portfolio impact:</b>
            Annual income ${{fmt(portAnnual)}} → <b>${{fmt(newAnnual)}}</b> &nbsp;·&nbsp;
            After-tax ${{fmt(portNet)}} → <b style="color:#27ae60;">${{fmt(newNet)}}</b>
          </div>
        </div>` : ""}}
      </div>`;
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

function card(label, value, color="#2c3e50") {{
  return `<div style="background:#fff;border:1px solid #eee;border-radius:6px;padding:10px 12px;">
    <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;">${{label}}</div>
    <div style="font-size:13px;font-weight:600;color:${{color}}">${{value}}</div>
  </div>`;
}}

let _divData = null;

function renderDividendTable() {{
  if (!_divData) return;
  const results = document.getElementById("div-results");
  const b = CURRENT_BRACKET;

  const totalAnnual   = _divData.results.reduce((s, r) => s + (r.annual_income || 0), 0);
  const totalAfterTax = _divData.results.reduce((s, r) => s + (r.annual_income || 0) * (1 - effectiveRate(r.tax_type || "qualified")), 0);
  const totalPort     = {total_v};
  document.getElementById("kpi-div-value").textContent =
    "$" + Math.round(totalAnnual).toLocaleString("en-US");
  document.getElementById("kpi-div-yield").textContent =
    (totalPort > 0 ? (totalAnnual / totalPort * 100).toFixed(2) + "% yield" : "") +
    "  ·  $" + Math.round(totalAfterTax).toLocaleString("en-US") + " after-tax";

  const rows = _divData.results.map(r => {{
    const taxType   = r.tax_type || "qualified";
    const rate      = effectiveRate(taxType);
    const typeLabel = taxTypeLabel(taxType);
    const ratePct   = (rate * 100).toFixed(1) + "%";
    const typeColor = taxType === "tax_exempt" ? "#27ae60"
                    : taxType === "ordinary"   ? "#c8102e"
                    : "#555";
    const annualTax = r.annual_income ? r.annual_income * rate : null;
    const netIncome = r.annual_income ? r.annual_income * (1 - rate) : null;

    const badge = r.declared
      ? `<span style="background:#e8f8ee;color:#1a6e38;border:1px solid #a8e0b8;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;">UPCOMING</span>`
      : `<span style="background:#f4f6f9;color:#888;border:1px solid #dde;border-radius:4px;padding:1px 7px;font-size:10px;">LAST KNOWN</span>`;
    const exDiv  = r.ex_div_date || "—";
    const payDay = r.pay_date    || "—";
    const amount = r.declared_amount ? "$" + r.declared_amount.toFixed(4) : "—";
    const total  = r.total_payout  ? "$" + r.total_payout.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}) : "—";
    const income = r.annual_income ? "$" + r.annual_income.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}) : "—";
    const taxStr = taxType === "tax_exempt"
      ? `<span style="color:#27ae60;font-size:11px;">Federal Exempt</span>`
      : annualTax
        ? `<span style="color:#e74c3c;">-${{annualTax.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</span>
           <br><span style="font-size:10px;color:${{typeColor}};">${{typeLabel}} ${{ratePct}}</span>`
        : "—";
    const netStr = netIncome
      ? `<b style="color:#27ae60;">${{netIncome.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</b>`
      : taxType === "tax_exempt" ? `<b style="color:#27ae60;">${{income}}</b>` : "—";
    const yld = r.div_yield     ? r.div_yield.toFixed(2) + "%" : "—";
    const yoc = r.yield_on_cost ? r.yield_on_cost.toFixed(2) + "%" : "—";
    const daysTag = r.days_to_ex !== null && r.days_to_ex >= 0
      ? `<span style="color:${{r.days_to_ex <= 14 ? '#c8102e' : r.days_to_ex <= 30 ? '#e67e22' : '#27ae60'}};font-weight:600;">${{r.days_to_ex}}d away</span>`
      : r.days_to_ex !== null
        ? `<span style="color:#aaa;font-size:11px;">${{Math.abs(r.days_to_ex)}}d ago</span>`
        : "";
    return `<tr style="border-bottom:1px solid #f2f4f7;">
      <td style="padding:8px 10px;font-weight:600;">${{r.ticker}}</td>
      <td style="padding:8px 10px;">${{badge}}</td>
      <td style="padding:8px 10px;">${{exDiv}} ${{daysTag}}</td>
      <td style="padding:8px 10px;">${{payDay}}</td>
      <td style="padding:8px 10px;font-weight:600;">${{amount}}</td>
      <td style="padding:8px 10px;">${{total}}</td>
      <td style="padding:8px 10px;">${{income}}</td>
      <td style="padding:8px 10px;">${{taxStr}}</td>
      <td style="padding:8px 10px;">${{netStr}}</td>
      <td style="padding:8px 10px;">${{yld}}</td>
      <td style="padding:8px 10px;color:#888;">${{yoc}}</td>
    </tr>`;
  }}).join("");

  const qRate = ((b.qualified + b.niit) * 100).toFixed(1);
  const oRate = ((b.ordinary  + b.niit) * 100).toFixed(1);

  results.innerHTML = `
    <div style="overflow-x:auto;margin-top:10px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f4f6f9;">
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Ticker</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Status</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Ex-Div Date</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Pay Date</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Amount/Share</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">This Payout</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Annual Income</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Est. Tax</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Net After-Tax</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Yield</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Yield on Cost</th>
      </tr></thead>
      <tbody>${{rows}}</tbody>
    </table>
    </div>
    <p style="font-size:11px;color:#aaa;margin-top:8px;">
      Tax basis: MFJ ${{b.label.replace(" household","")}} — Qualified ${{qRate}}% (cap gains + NIIT), Ordinary ${{oRate}}% (marginal + NIIT), Municipal = federal exempt.
      As of ${{_divData.as_of}}.
    </p>`;
}}

async function loadDividends() {{
  const status = document.getElementById("div-status");
  status.textContent = "Loading dividend data…";
  document.getElementById("div-results").innerHTML = "";
  try {{
    const res  = await fetch("/api/dividends");
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    _divData = data;
    status.textContent = "";
    renderDividendTable();
    renderGoalsCard();
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

function onTaxBracketChange(sel) {{
  CURRENT_BRACKET = TAX_BRACKETS[sel.value];
  renderDividendTable();
  renderGoalsCard();
  // Redraw chart with new after-tax line
  if (typeof loadDividendTimeline === "function") loadDividendTimeline();
}}

// ── Investment Goals card ──────────────────────────────────────────────────
function renderGoalsCard() {{
  // ── Dividend goal ──
  const GOAL_MONTHLY    = 5000;
  const GOAL_PORT       = 2000000;
  const GOAL_YEAR       = 2036;
  const CUR_YEAR        = new Date().getFullYear();
  const YEARS_LEFT      = Math.max(1, GOAL_YEAR - CUR_YEAR);
  const NIIT_RATE       = 0.038;
  const DIV_TAX_RATE    = 0.20 + NIIT_RATE;

  const totalAnnual = _divData
    ? _divData.results.reduce((s, r) => s + (r.annual_income || 0), 0) : 0;
  const monthly     = totalAnnual / 12;
  const monthlyNet  = monthly * (1 - DIV_TAX_RATE);
  const pct         = Math.min(100, totalAnnual > 0 ? (monthly / GOAL_MONTHLY * 100) : 0);
  const gap         = GOAL_MONTHLY - monthly;
  const reqCagr     = totalAnnual > 0
    ? (Math.pow(GOAL_MONTHLY / monthly, 1 / YEARS_LEFT) - 1) * 100 : null;

  // ── Portfolio value goal ──
  const portVal     = D.totalValue || 0;
  const portPct     = Math.min(100, portVal > 0 ? portVal / GOAL_PORT * 100 : 0);
  const portGap     = GOAL_PORT - portVal;
  const portCagr    = portVal > 0 ? (Math.pow(GOAL_PORT / portVal, 1 / YEARS_LEFT) - 1) * 100 : null;

  const fmt$ = v => "$" + v.toLocaleString("en-US", {{minimumFractionDigits:0, maximumFractionDigits:0}});
  const fmtM = v => "$" + v.toLocaleString("en-US", {{minimumFractionDigits:0, maximumFractionDigits:0}}) + "/mo";

  const mEl = document.getElementById("goal-div-monthly");
  if (mEl) mEl.textContent = fmtM(monthly);
  const nEl = document.getElementById("goal-div-net");
  if (nEl) nEl.textContent = `after tax (23.8%): ${{fmtM(monthlyNet)}}`;
  const bEl = document.getElementById("goal-div-bar");
  if (bEl) bEl.style.width = pct + "%";
  const pEl = document.getElementById("goal-div-pct");
  if (pEl) {{ pEl.textContent = pct.toFixed(1) + "% of $5,000/mo target"; pEl.style.color = pct >= 80 ? "#27ae60" : pct >= 40 ? "#e67e22" : "#e74c3c"; }}
  const gEl = document.getElementById("goal-div-gap");
  if (gEl) gEl.textContent = gap > 0 ? `Gap: ${{fmtM(gap)}} · ${{YEARS_LEFT}} yrs to ${{GOAL_YEAR}}` : `✓ Target reached!`;
  const cEl = document.getElementById("goal-div-cagr");
  if (cEl) cEl.textContent = reqCagr != null
    ? `Required div CAGR (div growth + DRIP + new capital): ${{reqCagr.toFixed(1)}}%/yr`
    : "No dividend data yet";

  // ── Portfolio Value Goal DOM updates ──
  const pvEl = document.getElementById("goal-port-value");
  if (pvEl) pvEl.textContent = portVal > 0 ? fmt$(portVal) : "—";
  const pbEl = document.getElementById("goal-port-bar");
  if (pbEl) pbEl.style.width = portPct + "%";
  const ppEl = document.getElementById("goal-port-pct");
  if (ppEl) {{
    ppEl.textContent = portVal > 0 ? portPct.toFixed(1) + "% of $2M target" : "0% of target";
    ppEl.style.color = portPct >= 50 ? "#27ae60" : "#2980b9";
  }}
  const pcEl = document.getElementById("goal-port-cagr");
  if (pcEl) pcEl.textContent = portCagr != null
    ? `Required CAGR: ${{portCagr.toFixed(1)}}%/yr · ${{fmt$(portGap)}} still needed`
    : "No portfolio data";

  // Quarterly targets with recommendations
  const today        = new Date();
  const Q_END_MONTH  = [2, 5, 8, 11];
  const Q_END_DAY    = [31, 30, 30, 31];
  const Q_NAMES      = ["Q1","Q2","Q3","Q4"];
  const curQ         = Math.floor(today.getMonth() / 3);
  const rate         = reqCagr != null ? reqCagr / 100 : 0;
  const portYield    = (totalAnnual > 0 && D.totalValue > 0) ? totalAnnual / D.totalValue : 0;

  const msEl = document.getElementById("goal-div-milestones");
  if (msEl && reqCagr != null && monthly > 0) {{

    let yr = today.getFullYear();
    let q  = curQ;
    let rows = "";

    const pRate = portCagr != null ? portCagr / 100 : null;

    for (let i = 0; i < 8; i++) {{
      const endDate    = new Date(yr, Q_END_MONTH[q], Q_END_DAY[q]);
      const yearsAhead = (endDate - today) / (365.25 * 86400000);
      const label      = `${{Q_NAMES[q]}} ${{yr}}`;
      const isCurrent  = (i === 0);
      const isPast     = yearsAhead < 0;

      // Dividend targets
      const divTarget  = monthly * Math.pow(1 + rate, Math.max(0, yearsAhead));
      const divGap     = divTarget - monthly;
      const divOnTrack = divGap < 1;

      // Portfolio value targets
      const portTarget    = pRate != null ? portVal * Math.pow(1 + pRate, Math.max(0, yearsAhead)) : 0;
      const portQGap      = portTarget - portVal;
      const portQOnTrack  = portQGap < 500;   // within $500 counts as on track

      // Dividend status badge
      let divBadge;
      if (isCurrent) {{
        divBadge = divOnTrack
          ? `<span style="background:#eafaf1;color:#1e8449;border:1px solid #a9dfbf;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:600;">✓ On track</span>`
          : `<span style="background:#fef9e7;color:#9a6700;border:1px solid #f9e79f;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:600;">⚠ ${{fmtM(divGap)}} behind</span>`;
      }} else if (isPast) {{
        divBadge = divOnTrack ? `<span style="color:#27ae60;font-size:10px;">✓</span>` : `<span style="color:#e67e22;font-size:10px;">⚠</span>`;
      }} else {{
        divBadge = "";
      }}

      // Portfolio status badge
      let portBadge;
      if (isCurrent) {{
        portBadge = portQOnTrack
          ? `<span style="background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:600;">✓ On track</span>`
          : `<span style="background:#fef9e7;color:#9a6700;border:1px solid #f9e79f;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:600;">⚠ ${{fmt$(portQGap)}} behind</span>`;
      }} else if (isPast) {{
        portBadge = portQOnTrack ? `<span style="color:#2980b9;font-size:10px;">✓</span>` : `<span style="color:#e67e22;font-size:10px;">⚠</span>`;
      }} else {{
        portBadge = "";
      }}

      // Dividend recommendation
      let divRec = "";
      if (!divOnTrack) {{
        const capitalNeeded = portYield > 0 ? (divGap * 12) / portYield : 0;
        divRec = `<span style="font-size:10px;color:#aaa;"> · deploy ~${{fmt$(capitalNeeded)}} at ${{(portYield*100).toFixed(1)}}% yield</span>`;
      }}

      const rowBg  = isCurrent ? "background:#f4f3ff;border-radius:6px;" : "";
      const fw     = isCurrent ? "600" : "400";
      const tcol   = isCurrent ? "#1a2340" : (isPast ? "#888" : "#555");
      const dotCol = isCurrent ? "#6c3fc5" : (divOnTrack && portQOnTrack ? "#27ae60" : (isPast ? "#e67e22" : "#ddd"));
      const dot    = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${{dotCol}};flex-shrink:0;margin-top:4px;"></span>`;

      rows += `<div style="display:flex;gap:10px;align-items:flex-start;padding:5px 6px;${{rowBg}}margin-bottom:2px;">
        ${{dot}}
        <div style="flex:1;min-width:0;">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <span style="font-weight:${{fw}};color:${{tcol}};font-size:11px;min-width:58px;">${{label}}</span>
            <span style="font-size:10px;color:#aaa;font-weight:400;">Div:</span>
            <span style="font-weight:${{fw}};color:${{tcol}};font-size:11px;">${{fmtM(divTarget)}}</span>
            ${{divBadge}}
            <span style="font-size:10px;color:#aaa;margin-left:4px;">Port:</span>
            <span style="font-weight:${{fw}};color:${{tcol}};font-size:11px;">${{fmt$(portTarget)}}</span>
            ${{portBadge}}
          </div>
          ${{!divOnTrack ? `<div style="font-size:10px;color:#aaa;margin-top:2px;padding-left:0;">→ Need +${{fmtM(divGap)}}${{divRec}}</div>` : ""}}
        </div>
      </div>`;

      q++;
      if (q > 3) {{ q = 0; yr++; }}
    }}

    msEl.innerHTML = `
      <div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;border-top:1px solid #e8f5e9;padding-top:10px;">
        Quarterly Targets &nbsp;·&nbsp; Div ${{reqCagr.toFixed(1)}}% CAGR &nbsp;·&nbsp; Port ${{portCagr != null ? portCagr.toFixed(1)+"%" : "—"}} CAGR &nbsp;·&nbsp; yield ${{portYield > 0 ? (portYield*100).toFixed(2)+"%" : "—"}}
      </div>
      ${{rows}}`;
  }}

  // ── Layer Allocation vs Target ──
  const lw      = D.layerWeightsByNum || {{}};
  const targets = D.layerTargets     || {{}};
  const total   = D.totalValue       || 0;

  const ALLOC_META = {{
    1: {{ name: "L1 Structural Ballast",  color: "#4A90D9" }},
    2: {{ name: "L2 Cash-Flow Engines",   color: "#27ae60" }},
    3: {{ name: "L3 Compounders",         color: "#e67e22" }},
    4: {{ name: "L4 Convexity",           color: "#7c3aed", band: "10–15% band" }},
    5: {{ name: "L5 Shock Absorbers",     color: "#9B59B6" }},
  }};

  const allocEl = document.getElementById("goal-layer-alloc");
  if (allocEl) {{
    const rows = [1,2,3,4,5].map(n => {{
      const actual = (lw[n] || {{}}).weight || 0;
      const target = targets[n] || 0;
      const drift  = actual - target;
      const m      = ALLOC_META[n];

      const driftColor = Math.abs(drift) <= 2 ? "#27ae60" : drift > 0 ? "#e67e22" : "#2980b9";
      const driftIcon  = Math.abs(drift) <= 2 ? "✓" : drift > 0 ? "▲" : "▼";
      const driftStr   = Math.abs(drift) < 0.05 ? "on target" : `${{drift > 0 ? "+" : ""}}${{drift.toFixed(1)}}pp`;

      const barPct    = Math.min(100, (actual / 50) * 100).toFixed(1);
      const targetPct = Math.min(100, (target / 50) * 100).toFixed(1);
      const bandTag   = m.band ? `<span style="font-size:9px;color:#aaa;"> (${{m.band}})</span>` : "";

      return `
      <div style="margin-bottom:${{n < 5 ? "10px" : "0"}};">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
          <div style="display:flex;align-items:center;gap:5px;">
            <span style="width:7px;height:7px;border-radius:50%;background:${{m.color}};display:inline-block;flex-shrink:0;"></span>
            <span style="font-weight:600;color:#1a2340;">${{m.name}}</span>${{bandTag}}
          </div>
          <div style="display:flex;align-items:center;gap:6px;font-size:10px;white-space:nowrap;">
            <span style="color:#1a2340;font-weight:700;">${{actual.toFixed(1)}}%</span>
            <span style="color:#bbb;">/ ${{target}}%</span>
            <span style="color:${{driftColor}};font-weight:600;">${{driftIcon}} ${{driftStr}}</span>
          </div>
        </div>
        <div style="position:relative;height:6px;background:#f0f2f5;border-radius:3px;">
          <div style="position:absolute;left:0;top:0;bottom:0;width:${{barPct}}%;background:${{m.color}};border-radius:3px;opacity:0.8;transition:width .5s;"></div>
          <div style="position:absolute;left:${{targetPct}}%;top:-2px;bottom:-2px;width:2px;background:#1a2340;border-radius:1px;opacity:0.35;"></div>
        </div>
      </div>`;
    }}).join("");

    allocEl.innerHTML = rows || `<div style="color:#aaa;">No portfolio data</div>`;
  }}

  // Kick off async recommendation engine (fetches screener + earnings)
  loadRecommendations({{
    portVal, totalAnnual, monthly, gap, reqCagr, portCagr,
    rate, today, Q_END_MONTH, Q_END_DAY, curQ,
  }});
}}

// ── Recommendation engine ──────────────────────────────────────────────────
const LAYER_META = {{
  1: {{ name: "L1 Structural Ballast",  color: "#4A90D9", bg: "#eff6ff", border: "#bfdbfe" }},
  2: {{ name: "L2 Cash-Flow Engines",   color: "#27ae60", bg: "#f0fdf4", border: "#a9dfbf" }},
  3: {{ name: "L3 Compounders",         color: "#e67e22", bg: "#fff8f0", border: "#f5cba7" }},
  4: {{ name: "L4 Convexity",           color: "#E74C3C", bg: "#fff1f1", border: "#fbb6b6" }},
  5: {{ name: "L5 Shock Absorbers",     color: "#9B59B6", bg: "#f9f0ff", border: "#d7b8f5" }},
}};

async function loadRecommendations(ctx) {{
  const recPanel = document.getElementById("goal-recommendations");
  if (!recPanel) return;

  const {{ portVal, totalAnnual, monthly, gap, reqCagr, portCagr,
          rate, today, Q_END_MONTH, Q_END_DAY, curQ }} = ctx;

  const fmt$ = v => "$" + Math.round(v).toLocaleString("en-US");
  const fmtM = v => "$" + Math.round(v).toLocaleString("en-US") + "/mo";

  // Fetch screener winners + earnings in parallel
  let winners = [], earningsByTicker = {{}};
  try {{
    const [wRes, eRes] = await Promise.all([
      fetch("/api/buffett-winners"),
      fetch("/api/earnings"),
    ]);
    const wData = await wRes.json();
    const eData = await eRes.json();
    winners = wData.winners || [];
    for (const e of (eData.earnings || [])) {{
      if (e.next_earnings_date) earningsByTicker[e.ticker] = e.next_earnings_date;
    }}
  }} catch(e) {{
    recPanel.innerHTML = `<div style="color:#aaa;font-size:11px;">Could not load screener data.</div>`;
    return;
  }}

  const heldSet    = new Set((D.holdings || []).map(h => h.ticker));
  const targets    = D.layerTargets     || {{}};
  const lw         = D.layerWeightsByNum || {{}};
  const portYield  = totalAnnual > 0 && portVal > 0 ? totalAnnual / portVal : 0;

  // Dividend yield of held tickers from _divData (for L2 context)
  const divYieldHeld = {{}};
  for (const r of (_divData?.results || [])) {{
    if (r.ticker && r.yield) divYieldHeld[r.ticker] = r.yield;
  }}

  // ── Score each winner ────────────────────────────────────────────────────
  const RISK_SCORE = {{ low: 3, medium: 2, unknown: 1, high: -99 }};
  const now = Date.now();

  const candidates = winners
    .filter(w => !heldSet.has(w.ticker) && w.value_trap_risk !== "high")
    .map(w => {{
      // Valuation penalty — prefer cheaper on a composite of available metrics
      let valPenalty = 0;
      if (w.pe_ratio  && w.pe_ratio  > 40) valPenalty += 1;
      if (w.pe_ratio  && w.pe_ratio  > 60) valPenalty += 1;
      if (w.ev_ebitda && w.ev_ebitda > 25) valPenalty += 1;
      if (w.p_fcf     && w.p_fcf     > 35) valPenalty += 1;

      // Earnings proximity flag (within 14 days)
      let earningsFlag = null;
      const eDate = earningsByTicker[w.ticker];
      if (eDate) {{
        const daysAway = Math.round((new Date(eDate) - now) / 86400000);
        if (daysAway >= 0 && daysAway <= 14) earningsFlag = daysAway;
      }}

      // Value trap flags
      let trapFlags = [];
      try {{ trapFlags = JSON.parse(w.value_trap_flags || "[]"); }} catch(_) {{}}

      return {{
        ...w,
        score: (RISK_SCORE[w.value_trap_risk] || 1) * 10 - valPenalty,
        earningsFlag,
        trapFlags,
        layerFit: w.layer_rec || 3,
      }};
    }})
    .sort((a, b) => b.score - a.score);

  // ── Layer gaps (all layers, sorted by underweight %) ────────────────────
  const layerGaps = [];
  for (let n = 1; n <= 5; n++) {{
    const tgt  = targets[n] || 0;
    const curr = (lw[n] || {{}}).weight || 0;
    const drift = tgt - curr;
    if (drift > 1) layerGaps.push({{ n, tgt, curr, drift, dollar: (drift / 100) * portVal }});
  }}
  layerGaps.sort((a, b) => b.drift - a.drift);

  // ── Helper: render a candidate ticker chip ───────────────────────────────
  const riskColor = {{ low: "#1e8449", medium: "#9a6700", unknown: "#7f8c8d", high: "#c0392b" }};
  const riskBg    = {{ low: "#eafaf1", medium: "#fef9e7", unknown: "#f4f4f4", high: "#fdecea" }};
  const riskLabel = {{ low: "✓ Low risk", medium: "⚠ Med risk", unknown: "? Unrated", high: "✗ High risk" }};

  function tickerCard(w) {{
    const risk  = w.value_trap_risk || "unknown";
    const rBadge = `<span style="background:${{riskBg[risk]}};color:${{riskColor[risk]}};border-radius:4px;padding:1px 5px;font-size:9px;font-weight:700;">${{riskLabel[risk]}}</span>`;

    const vals = [];
    if (w.pe_ratio  != null) vals.push(`P/E ${{w.pe_ratio.toFixed(0)}}`);
    if (w.p_fcf     != null) vals.push(`P/FCF ${{w.p_fcf.toFixed(0)}}`);
    if (w.ev_ebitda != null) vals.push(`EV/EBITDA ${{w.ev_ebitda.toFixed(0)}}`);
    if (w.dividend_yield && w.dividend_yield > 0) vals.push(`Yield ${{(w.dividend_yield*100).toFixed(1)}}%`);
    const valStr = vals.length ? `<span style="color:#888;font-size:10px;"> · ${{vals.join(" · ")}}</span>` : "";

    const earnWarn = w.earningsFlag != null
      ? `<span style="color:#e67e22;font-size:10px;"> ⚠ earnings in ${{w.earningsFlag}}d</span>` : "";

    const flagStr = w.trapFlags.length
      ? `<div style="color:#c0392b;font-size:9px;margin-top:2px;">⚑ ${{w.trapFlags.join(", ")}}</div>` : "";

    const layerReason = w.layer_reason
      ? `<div style="color:#aaa;font-size:9px;margin-top:1px;">${{w.layer_reason}}</div>` : "";

    const exchBadge = w.exchange
      ? `<span style="font-size:9px;font-weight:600;padding:1px 5px;border-radius:3px;background:${{w.exchange==="NYSE"?"#e8f4fd":"#edf7ed"}};color:${{w.exchange==="NYSE"?"#1a5276":"#1e8449"}};">${{w.exchange}}</span>`
      : "";
    return `<div style="background:#f9fbfd;border:1px solid #e8edf4;border-radius:6px;padding:6px 9px;margin-bottom:5px;">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span style="font-weight:700;font-size:12px;color:#1a2340;">${{w.ticker}}</span>
        ${{exchBadge}}${{rBadge}}${{valStr}}${{earnWarn}}
      </div>
      ${{flagStr}}${{layerReason}}
    </div>`;
  }}

  // ── Build recommendation sections ────────────────────────────────────────
  let html = "";

  // 1. For each underweight layer, show top Buffett picks that fit
  const usedLayers = new Set();
  for (const lg of layerGaps.slice(0, 4)) {{
    if (lg.n === 4) continue; // L4 handled by barbell panel
    const picks = candidates.filter(c => c.layerFit === lg.n).slice(0, 3);
    if (!picks.length) continue;
    usedLayers.add(lg.n);

    const meta = LAYER_META[lg.n];
    const divLine = lg.n === 2 && portYield > 0
      ? `<div style="font-size:10px;color:#27ae60;margin-bottom:6px;">
           +${{fmtM((lg.dollar * portYield) / 12)}} estimated monthly income from deploying ${{fmt$(lg.dollar)}} at ${{(portYield*100).toFixed(1)}}% yield
         </div>` : "";

    html += `<div style="margin-bottom:12px;">
      <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:4px;">
        <span style="font-weight:700;color:${{meta.color}};font-size:11px;">${{meta.name}}</span>
        <span style="font-size:10px;color:#888;">${{lg.curr.toFixed(1)}}% → ${{lg.tgt.toFixed(1)}}% target · deploy ${{fmt$(lg.dollar)}}</span>
      </div>
      ${{divLine}}
      ${{picks.map(tickerCard).join("")}}
    </div>`;
  }}

  // 2. Capital pace for $2M goal
  if (portCagr != null && portVal > 0) {{
    const nextQDate    = new Date(today.getFullYear(), Q_END_MONTH[curQ], Q_END_DAY[curQ]);
    const nextYrsAhd   = Math.max(0, (nextQDate - today) / (365.25 * 86400000));
    const portQTarget  = portVal * Math.pow(1 + portCagr / 100, Math.max(nextYrsAhd, 0.25));
    const growthOnly   = portVal * (Math.pow(1 + portCagr / 100, 0.25) - 1);
    const newCapNeeded = Math.max(0, portQTarget - portVal - growthOnly);

    if (newCapNeeded > 500) {{
      html += `<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:7px;padding:9px 11px;margin-bottom:8px;">
        <div style="font-weight:700;color:#2980b9;font-size:11px;margin-bottom:3px;">Capital pace — $2M by 2036</div>
        <div style="color:#444;font-size:11px;line-height:1.5;">
          Deploy <b>${{fmt$(newCapNeeded)}}</b> this quarter to stay on pace for ${{fmt$(portQTarget)}} by Q-end.
          Prioritize the most underweight layer above.
        </div>
      </div>`;
    }} else {{
      html += `<div style="background:#f0fdf4;border:1px solid #a9dfbf;border-radius:7px;padding:9px 11px;margin-bottom:8px;">
        <div style="font-weight:700;color:#27ae60;font-size:11px;margin-bottom:2px;">Portfolio on pace for $2M</div>
        <div style="color:#444;font-size:11px;">Organic growth at ${{portCagr.toFixed(1)}}% CAGR covers this quarter. Additional capital accelerates the timeline.</div>
      </div>`;
    }}
  }}

  // 3. If no screener data aligned with underweight layers, show best overall picks
  if (!usedLayers.size) {{
    const topPicks = candidates.slice(0, 3);
    if (topPicks.length) {{
      html += `<div style="margin-bottom:8px;">
        <div style="font-weight:700;color:#1a2340;font-size:11px;margin-bottom:6px;">Top Buffett screener picks</div>
        ${{topPicks.map(tickerCard).join("")}}
      </div>`;
    }} else {{
      html += `<div style="color:#aaa;font-size:11px;font-style:italic;">No screener winners yet — run the Buffett scan below.</div>`;
    }}
  }}

  recPanel.innerHTML = html || `<div style="color:#aaa;font-size:11px;font-style:italic;">No recommendations available.</div>`;
}}

// Auto-load dividends on page open
window.addEventListener("load", loadDividends);

// ── Dividend Timeline Chart ─────────────────────────────────────────────────
let divTimelineChartInst = null;

async function loadDividendTimeline() {{
  const status = document.getElementById("div-timeline-status");
  const canvas = document.getElementById("divTimelineChart");
  try {{
    const res  = await fetch("/api/dividend-timeline");
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error loading timeline."; return; }}

    status.textContent = "";
    canvas.style.display = "block";

    const labels = data.months.map(m => {{
      const [y, mo] = m.split("-");
      return new Date(+y, +mo - 1, 1).toLocaleDateString("en-US", {{month:"short", year:"2-digit"}});
    }});

    const idx    = data.this_month_idx;
    const recvd  = data.received.map((v, i) => i <= idx ? v : null);
    const expctd = data.expected.map((v, i) => i >= idx ? v : null);

    // Cumulative gross total
    const combined = data.months.map((_, i) => (data.received[i] || 0) + (data.expected[i] || 0));
    let running = 0;
    const cumulative = combined.map(v => {{ running += v; return Math.round(running * 100) / 100; }});

    // Cumulative after-tax using current bracket's qualified rate (conservative avg)
    const netRate = CURRENT_BRACKET.qualified + CURRENT_BRACKET.niit;
    let runningNet = 0;
    const cumulativeNet = combined.map(v => {{
      runningNet += v * (1 - netRate);
      return Math.round(runningNet * 100) / 100;
    }});

    if (divTimelineChartInst) divTimelineChartInst.destroy();
    divTimelineChartInst = new Chart(canvas, {{
      type: "bar",
      data: {{
        labels,
        datasets: [
          {{
            label: "Received",
            data:  recvd,
            backgroundColor: "rgba(74,144,217,0.75)",
            borderColor:     "#4A90D9",
            borderWidth: 1,
            borderRadius: 3,
            yAxisID: "y",
          }},
          {{
            label: "Expected",
            data:  expctd,
            backgroundColor: "rgba(80,200,120,0.55)",
            borderColor:     "#50C878",
            borderWidth: 1,
            borderRadius: 3,
            yAxisID: "y",
          }},
          {{
            type: "line",
            label: "Cumulative (gross)",
            data:  cumulative,
            borderColor:     "#9B59B6",
            backgroundColor: "rgba(155,89,182,0.08)",
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.3,
            fill: false,
            yAxisID: "y2",
          }},
          {{
            type: "line",
            label: "Cumulative (after-tax)",
            data:  cumulativeNet,
            borderColor:     "#E67E22",
            backgroundColor: "rgba(230,126,34,0.06)",
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.3,
            fill: false,
            borderDash: [5, 3],
            yAxisID: "y2",
          }},
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: "index", intersect: false }},
        plugins: {{
          legend: {{ position: "top", labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }},
          tooltip: {{
            callbacks: {{
              label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.y != null ? "$" + ctx.parsed.y.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}) : "—"}}`,
            }}
          }},
        }},
        scales: {{
          y: {{
            beginAtZero: true,
            position: "left",
            ticks: {{ callback: v => "$" + v.toFixed(0) }},
            grid: {{ color: "#f0f0f0" }},
            title: {{ display: true, text: "Monthly", font: {{ size: 10 }}, color: "#aaa" }},
          }},
          y2: {{
            beginAtZero: true,
            position: "right",
            ticks: {{ callback: v => "$" + (v >= 1000 ? (v/1000).toFixed(1) + "k" : v.toFixed(0)) }},
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: "Cumulative", font: {{ size: 10 }}, color: "#9B59B6" }},
          }},
          x: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }} }} }}
        }}
      }}
    }});
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

window.addEventListener("load", loadDividendTimeline);

// ── Layer Earnings ──────────────────────────────────────────────────────────
async function loadLayerEarnings() {{
  try {{
    const res  = await fetch("/api/earnings");
    const data = await res.json();
    if (!data.ok) return;

    // For each layer, find the soonest earnings (upcoming preferred, else most recent past)
    const best = {{}};
    for (const item of data.results) {{
      const ln = item.layer_num;
      if (!best[ln]) {{
        best[ln] = item;
      }} else {{
        // Prefer upcoming over past; among same type, pick nearest
        const currUp  = best[ln].is_upcoming;
        const itemUp  = item.is_upcoming;
        if (itemUp && !currUp) {{
          best[ln] = item;
        }} else if (itemUp === currUp) {{
          if (Math.abs(item.days_to_earn) < Math.abs(best[ln].days_to_earn))
            best[ln] = item;
        }}
      }}
    }}

    // ── layer summary cells ──────────────────────────────────────────────────
    for (const [ln, item] of Object.entries(best)) {{
      const el = document.getElementById("layer-earn-" + ln);
      if (!el) continue;
      el.innerHTML = earnCell(item, true);
    }}

    // ── per-holding cells ────────────────────────────────────────────────────
    for (const item of data.results) {{
      const el = document.getElementById("earn-" + item.ticker);
      if (!el) continue;
      el.innerHTML = earnCell(item, false);
    }}
  }} catch(e) {{}}
}}

function earnCell(item, showTicker) {{
  const d     = new Date(item.earnings_date + "T00:00:00");
  const label = d.toLocaleDateString("en-US", {{ month:"short", day:"numeric" }});
  const days  = item.days_to_earn;
  let color = "#7f8c8d", suffix = "";
  if (item.is_upcoming) {{
    color  = days <= 7 ? "#c8102e" : days <= 21 ? "#e67e22" : "#27ae60";
    suffix = ` <span style="color:${{color}};font-size:11px;">(${{days}}d)</span>`;
  }} else {{
    suffix = ` <span style="color:#bbb;font-size:10px;">(est.)</span>`;
  }}
  const prefix = showTicker ? `<b style="color:#2c3e50;">${{item.ticker}}</b> ` : "";
  return `${{prefix}}<span style="color:${{item.is_upcoming ? color : '#7f8c8d'}};">${{label}}</span>${{suffix}}`;
}}

window.addEventListener("load", loadLayerEarnings);

// ── Tax Lot Tracker ───────────────────────────────────────────────────────
let _allLots = {{}};      // {{ ticker: [lot, ...] }}
let _lotsModalTicker = null;
let _lotsModalPrice  = null;

async function loadAllLots() {{
  try {{
    const res  = await fetch("/api/lots");
    const data = await res.json();
    if (!data.ok) return;
    _allLots = {{}};
    for (const lot of data.lots) {{
      if (!_allLots[lot.ticker]) _allLots[lot.ticker] = [];
      _allLots[lot.ticker].push(lot);
    }}
    renderAllStltBadges();
  }} catch(e) {{}}
}}

function renderAllStltBadges() {{
  const today = new Date();
  today.setHours(0,0,0,0);
  for (const [ticker, lots] of Object.entries(_allLots)) {{
    const el = document.getElementById("stlt-" + ticker);
    if (!el || !lots.length) continue;
    const hasST = lots.some(l => (today - new Date(l.purchase_date + "T00:00:00")) / 86400000 < 365);
    const hasLT = lots.some(l => (today - new Date(l.purchase_date + "T00:00:00")) / 86400000 >= 365);
    const stCount = lots.filter(l => (today - new Date(l.purchase_date + "T00:00:00")) / 86400000 < 365).length;
    if (hasST && hasLT) {{
      el.innerHTML = `<span title="Mixed holding: ${{stCount}} short-term lot${{stCount!==1?'s':''}} — click Lots for details"
        style="background:#fff3cd;color:#7d5a00;border:1.5px solid #e6ac00;border-radius:4px;padding:2px 7px;font-weight:700;font-size:9px;letter-spacing:.03em;cursor:default;">
        ⚠ MIXED</span>`;
    }} else if (hasST) {{
      el.innerHTML = `<span style="background:#fff0f0;color:#e74c3c;border:1px solid #fcc;border-radius:3px;padding:1px 5px;font-weight:700;font-size:9px;">ST</span>`;
    }} else {{
      el.innerHTML = `<span style="background:#f0fff4;color:#27ae60;border:1px solid #ade;border-radius:3px;padding:1px 5px;font-weight:700;font-size:9px;">LT</span>`;
    }}
  }}
}}

function openLotsModal(ticker, currentPrice) {{
  _lotsModalTicker = ticker;
  _lotsModalPrice  = currentPrice;
  document.getElementById("lots-modal-title").textContent = ticker + " — Tax Lots";
  document.getElementById("lot-notes").value = "";
  document.getElementById("lot-status").textContent = "";
  document.getElementById("sell-shares").value = "";
  document.getElementById("sell-price").value  = "";
  document.getElementById("sell-date").value   = "";
  document.getElementById("sell-notes").value  = "";
  document.getElementById("sell-status").textContent = "";
  document.getElementById("fifo-preview-wrap").innerHTML = "";
  renderLotsModal();
  renderSellHistory(ticker);
  document.getElementById("lots-modal-overlay").style.display = "flex";
}}

function closeLotsModal() {{
  document.getElementById("lots-modal-overlay").style.display = "none";
  _lotsModalTicker = null;
}}

function closeLots(e) {{
  if (e.target === document.getElementById("lots-modal-overlay")) closeLotsModal();
}}

function renderLotsModal() {{
  const ticker = _lotsModalTicker;
  const price  = _lotsModalPrice;
  const lots   = (_allLots[ticker] || []).slice().sort((a,b) => a.purchase_date.localeCompare(b.purchase_date));
  const today  = new Date(); today.setHours(0,0,0,0);

  const wrap  = document.getElementById("lots-table-wrap");
  const sumEl = document.getElementById("lots-summary");

  if (!lots.length) {{
    wrap.innerHTML = `<p style="color:#888;font-size:13px;">No lots recorded yet. Add your first lot below.</p>`;
    sumEl.style.display = "none";
    document.getElementById("lots-modal-subtitle").textContent = "";
    return;
  }}

  let totalShares = 0, totalCost = 0, totalSTShares = 0, totalLTShares = 0;
  const rows = lots.map(l => {{
    const purchaseDate = new Date(l.purchase_date + "T00:00:00");
    const daysHeld = Math.floor((today - purchaseDate) / 86400000);
    const isLT    = daysHeld >= 365;
    const termBadge = isLT
      ? `<span style="background:#f0fff4;color:#27ae60;border:1px solid #ade;border-radius:3px;padding:1px 6px;font-size:10px;font-weight:700;">LT</span>`
      : `<span style="background:#fff0f0;color:#e74c3c;border:1px solid #fcc;border-radius:3px;padding:1px 6px;font-size:10px;font-weight:700;">ST</span>`;
    const lotValue    = l.shares * price;
    const lotCost     = l.shares * l.cost_per_share;
    const lotGain     = lotValue - lotCost;
    const lotGainPct  = lotCost > 0 ? (lotGain / lotCost * 100) : 0;
    const gainColor   = lotGain >= 0 ? "#27ae60" : "#e74c3c";
    const ltDate      = new Date(purchaseDate); ltDate.setFullYear(ltDate.getFullYear() + 1);
    const ltStr       = isLT ? "" : `<div style="font-size:10px;color:#aaa;">LT: ${{ltDate.toLocaleDateString("en-US",{{month:"short",day:"numeric",year:"numeric"}})}} (${{365-daysHeld}}d)</div>`;

    totalShares += l.shares;
    totalCost   += lotCost;
    if (isLT) totalLTShares += l.shares; else totalSTShares += l.shares;

    return `<tr style="border-bottom:1px solid #f2f4f7;">
      <td style="padding:7px 10px;">${{l.purchase_date}}</td>
      <td style="padding:7px 10px;">${{l.shares.toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:4}})}}</td>
      <td style="padding:7px 10px;">$${{l.cost_per_share.toFixed(2)}}</td>
      <td style="padding:7px 10px;">$${{lotCost.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</td>
      <td style="padding:7px 10px;color:#555;">${{daysHeld}}d ${{termBadge}}</td>
      <td style="padding:7px 10px;">${{ltStr}}
        <span style="font-weight:600;color:${{gainColor}};">${{lotGain >= 0 ? "+" : ""}}<span>$${{Math.abs(lotGain).toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</span>
        <span style="font-size:11px;color:${{gainColor}};"> (${{lotGainPct >= 0 ? "+" : ""}}${{lotGainPct.toFixed(1)}}%)</span>
      </td>
      <td style="padding:7px 10px;color:#aaa;font-size:11px;">${{l.notes || ""}}</td>
      <td style="padding:7px 10px;">
        <button onclick="deleteLot(${{l.id}})" style="font-size:10px;padding:2px 8px;background:#fff0f0;border:1px solid #fcc;border-radius:4px;cursor:pointer;color:#e74c3c;">✕</button>
      </td>
    </tr>`;
  }}).join("");

  wrap.innerHTML = `
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f4f6f9;">
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Purchased</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Shares</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Cost/Share</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Total Cost</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Held / Term</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Unrealized G/L</th>
        <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Notes</th>
        <th></th>
      </tr></thead>
      <tbody>${{rows}}</tbody>
    </table></div>`;

  const wavgCost = totalShares > 0 ? totalCost / totalShares : 0;
  const totalGain = totalShares * price - totalCost;
  const totalGainPct = totalCost > 0 ? totalGain / totalCost * 100 : 0;
  const gainColor = totalGain >= 0 ? "#27ae60" : "#e74c3c";
  sumEl.style.display = "flex";
  sumEl.innerHTML = `
    <span>Lots tracked: <b>${{lots.length}}</b></span>
    <span>Shares: <b>${{totalShares.toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:4}})}}</b></span>
    <span>Wtd avg cost: <b>$${{wavgCost.toFixed(2)}}</b></span>
    <span>ST: <b style="color:#e74c3c;">${{totalSTShares.toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:4}})}}</b> shares</span>
    <span>LT: <b style="color:#27ae60;">${{totalLTShares.toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:4}})}}</b> shares</span>
    <span>Total G/L: <b style="color:${{gainColor}};">${{totalGain >= 0 ? "+" : ""}}$${{Math.abs(totalGain).toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}} (${{totalGainPct >= 0 ? "+" : ""}}${{totalGainPct.toFixed(1)}}%)</b></span>`;

  document.getElementById("lots-modal-subtitle").textContent =
    `Current price: $${{price?.toFixed(2)}} · ${{totalSTShares > 0 && totalLTShares > 0 ? "Mixed ST/LT" : totalSTShares > 0 ? "All short-term" : "All long-term"}}`;
}}

async function addLot() {{
  const ticker = _lotsModalTicker;
  if (!ticker) return;
  const status = document.getElementById("lot-status");
  const body   = {{
    ticker,
    shares:         parseFloat(document.getElementById("lot-shares").value),
    cost_per_share: parseFloat(document.getElementById("lot-cost").value),
    purchase_date:  document.getElementById("lot-date").value,
    notes:          document.getElementById("lot-notes").value,
  }};
  if (!body.shares || !body.cost_per_share || !body.purchase_date) {{
    status.textContent = "⚠ Date, shares, and cost are required.";
    return;
  }}
  status.textContent = "Saving…";
  try {{
    const res  = await fetch("/api/lots", {{
      method: "POST", headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    status.textContent = "✓ Added";
    document.getElementById("lot-shares").value = "";
    document.getElementById("lot-cost").value   = "";
    document.getElementById("lot-date").value   = "";
    document.getElementById("lot-notes").value  = "";
    setTimeout(() => {{ status.textContent = ""; }}, 1500);
    // Refresh local cache
    if (!_allLots[ticker]) _allLots[ticker] = [];
    _allLots[ticker].push({{id: data.id, ticker, ...body}});
    renderLotsModal();
    renderAllStltBadges();
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
}}

async function deleteLot(id) {{
  if (!confirm("Remove this lot?")) return;
  try {{
    const res  = await fetch(`/api/lots/${{id}}`, {{ method: "DELETE" }});
    const data = await res.json();
    if (!data.ok) {{ alert("Error: " + data.error); return; }}
    const ticker = _lotsModalTicker;
    if (ticker && _allLots[ticker]) {{
      _allLots[ticker] = _allLots[ticker].filter(l => l.id !== id);
    }}
    renderLotsModal();
    renderAllStltBadges();
  }} catch(e) {{ alert("Error: " + e.message); }}
}}

window.addEventListener("load", loadAllLots);

// ── Add Position ──────────────────────────────────────────────────────────
async function addHolding() {{
  const statusEl  = document.getElementById("add-pos-status");
  const ticker    = (document.getElementById("add-pos-ticker").value || "").trim().toUpperCase();
  const shares    = parseFloat(document.getElementById("add-pos-shares").value);
  const avg_cost  = parseFloat(document.getElementById("add-pos-cost").value);
  const layer_num = parseInt(document.getElementById("add-pos-layer").value);

  if (!ticker)         {{ statusEl.textContent = "⚠ Enter a ticker."; return; }}
  if (!(shares > 0))   {{ statusEl.textContent = "⚠ Shares must be > 0."; return; }}
  if (!(avg_cost > 0)) {{ statusEl.textContent = "⚠ Avg cost must be > 0."; return; }}

  statusEl.textContent = "Saving and fetching price…";
  try {{
    const res  = await fetch("/api/holdings", {{
      method:  "POST",
      headers: {{"Content-Type": "application/json"}},
      body:    JSON.stringify({{ ticker, shares, avg_cost, layer_num }}),
    }});
    const data = await res.json();
    if (!data.ok) {{
      statusEl.textContent = "Error: " + data.error;
      return;
    }}
    const priceNote = data.price
      ? ` · current price $$${{data.price.toFixed(2)}} · position value $$${{data.value?.toFixed(2)}}`
      : " · price will update on next newsletter run";
    statusEl.innerHTML = `<span style="color:#27ae60;">✓ ${{data.ticker}} added to ${{data.layer}}${{priceNote}}. Reloading…</span>`;
    setTimeout(() => window.location.reload(), 1200);
  }} catch(e) {{
    statusEl.textContent = "Error: " + e.message;
  }}
}}

// ── FIFO Sell Tracker ────────────────────────────────────────────────────
let _allSells = {{}};   // {{ ticker: [sell, ...] }}

async function loadAllSells() {{
  try {{
    const res  = await fetch("/api/sells");
    const data = await res.json();
    if (!data.ok) return;
    _allSells = {{}};
    for (const s of data.sells) {{
      if (!_allSells[s.ticker]) _allSells[s.ticker] = [];
      _allSells[s.ticker].push(s);
    }}
  }} catch(e) {{}}
}}

function _fifoPreviewCalc(lots, sharesToSell, sellPrice, sellDate) {{
  const sorted = [...lots].sort((a, b) =>
    a.purchase_date < b.purchase_date ? -1 : a.purchase_date > b.purchase_date ? 1 : a.id - b.id
  );
  const sellDt    = new Date(sellDate + "T00:00:00");
  let   remaining = sharesToSell;
  const allocs    = [];
  for (const lot of sorted) {{
    if (remaining <= 0.0001) break;
    const purchaseDt  = new Date(lot.purchase_date + "T00:00:00");
    const daysHeld    = Math.floor((sellDt - purchaseDt) / 86400000);
    const term        = daysHeld >= 365 ? "LT" : "ST";
    const sharesUsed  = Math.min(lot.shares, remaining);
    const costBasis   = sharesUsed * lot.cost_per_share;
    const proceeds    = sharesUsed * sellPrice;
    allocs.push({{ lot_id: lot.id, purchase_date: lot.purchase_date,
      cost_per_share: lot.cost_per_share, shares: sharesUsed, days_held: daysHeld,
      term, cost_basis: costBasis, proceeds, gain: proceeds - costBasis }});
    remaining -= sharesUsed;
  }}
  if (remaining > 0.0001) return {{ error: `Only ${{sharesToSell - remaining}} shares in lots — cannot sell ${{sharesToSell}}` }};
  return {{ allocs }};
}}

function showFifoPreview() {{
  const ticker    = _lotsModalTicker;
  const lots      = _allLots[ticker] || [];
  const wrap      = document.getElementById("fifo-preview-wrap");
  const status    = document.getElementById("sell-status");
  const shares    = parseFloat(document.getElementById("sell-shares").value);
  const price     = parseFloat(document.getElementById("sell-price").value);
  const date      = document.getElementById("sell-date").value;

  status.textContent = "";
  if (!shares || !price || !date) {{ status.textContent = "⚠ Date, shares, and price are required."; return; }}

  const result = _fifoPreviewCalc(lots, shares, price, date);
  if (result.error) {{ wrap.innerHTML = `<p style="color:#e74c3c;font-size:13px;">${{result.error}}</p>`; return; }}

  const {{allocs}} = result;
  const totalGain = allocs.reduce((s, a) => s + a.gain, 0);
  const stGain    = allocs.filter(a => a.term === "ST").reduce((s, a) => s + a.gain, 0);
  const ltGain    = allocs.filter(a => a.term === "LT").reduce((s, a) => s + a.gain, 0);
  const gainColor = totalGain >= 0 ? "#27ae60" : "#e74c3c";

  const rows = allocs.map(a => {{
    const gc = a.gain >= 0 ? "#27ae60" : "#e74c3c";
    const badge = a.term === "LT"
      ? `<span style="background:#f0fff4;color:#27ae60;border:1px solid #ade;border-radius:3px;padding:1px 5px;font-size:10px;font-weight:700;">LT</span>`
      : `<span style="background:#fff0f0;color:#e74c3c;border:1px solid #fcc;border-radius:3px;padding:1px 5px;font-size:10px;font-weight:700;">ST</span>`;
    return `<tr style="border-bottom:1px solid #f5f5f5;">
      <td style="padding:5px 8px;">${{a.purchase_date}}</td>
      <td style="padding:5px 8px;">${{a.shares.toLocaleString("en-US",{{minimumFractionDigits:0,maximumFractionDigits:4}})}}</td>
      <td style="padding:5px 8px;">$${{a.cost_per_share.toFixed(2)}}</td>
      <td style="padding:5px 8px;">$${{a.cost_basis.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</td>
      <td style="padding:5px 8px;">$${{a.proceeds.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</td>
      <td style="padding:5px 8px;font-weight:600;color:${{gc}};">${{a.gain>=0?"+":""}}$${{Math.abs(a.gain).toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</td>
      <td style="padding:5px 8px;">${{badge}} ${{a.days_held}}d</td>
    </tr>`;
  }}).join("");

  wrap.innerHTML = `
    <div style="background:#fffbf0;border:1px solid #f0d080;border-radius:8px;padding:14px;">
      <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;margin-bottom:8px;">FIFO Lot Allocation Preview</div>
      <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead><tr style="background:#f9f3e0;">
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Lot Date</th>
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Shares</th>
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Cost/Share</th>
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Cost Basis</th>
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Proceeds</th>
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Gain / Loss</th>
          <th style="padding:5px 8px;text-align:left;color:#888;font-size:10px;text-transform:uppercase;">Term</th>
        </tr></thead>
        <tbody>${{rows}}</tbody>
      </table></div>
      <div style="margin-top:10px;padding-top:8px;border-top:1px solid #e8d88a;display:flex;gap:20px;flex-wrap:wrap;font-size:12px;">
        <span>Proceeds: <b>$${{(shares*price).toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</b></span>
        <span>ST Gain: <b style="color:${{stGain>=0?"#27ae60":"#e74c3c"}}">${{stGain>=0?"+":""}}$${{Math.abs(stGain).toFixed(2)}}</b></span>
        <span>LT Gain: <b style="color:${{ltGain>=0?"#27ae60":"#e74c3c"}}">${{ltGain>=0?"+":""}}$${{Math.abs(ltGain).toFixed(2)}}</b></span>
        <span>Total G/L: <b style="color:${{gainColor}}">${{totalGain>=0?"+":""}}$${{Math.abs(totalGain).toFixed(2)}}</b></span>
      </div>
      <button onclick="confirmSell()" style="margin-top:12px;padding:7px 20px;background:#c0392b;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">Confirm Sale</button>
      <span style="margin-left:8px;font-size:11px;color:#aaa;">This will reduce/remove the oldest lots and record the sale.</span>
    </div>`;
}}

async function confirmSell() {{
  const ticker = _lotsModalTicker;
  const status = document.getElementById("sell-status");
  const body   = {{
    ticker,
    shares_sold: parseFloat(document.getElementById("sell-shares").value),
    sell_price:  parseFloat(document.getElementById("sell-price").value),
    sell_date:   document.getElementById("sell-date").value,
    notes:       document.getElementById("sell-notes").value,
  }};
  status.textContent = "Recording…";
  try {{
    const res  = await fetch("/api/sells", {{
      method: "POST", headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    status.textContent = "✓ Sale recorded";
    document.getElementById("sell-shares").value = "";
    document.getElementById("sell-price").value  = "";
    document.getElementById("sell-date").value   = "";
    document.getElementById("sell-notes").value  = "";
    document.getElementById("fifo-preview-wrap").innerHTML = "";
    setTimeout(() => {{ status.textContent = ""; }}, 2000);
    // Refresh lot cache from server (lots may have been mutated)
    await loadAllLots();
    await loadAllSells();
    renderLotsModal();
    renderSellHistory(ticker);
    renderAllStltBadges();
    renderRealizedGains();
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
}}

function renderSellHistory(ticker) {{
  const wrap  = document.getElementById("sell-history-wrap");
  const sells = (_allSells[ticker] || []).slice().sort((a,b) => b.sell_date.localeCompare(a.sell_date));
  if (!sells.length) {{
    wrap.innerHTML = `<span style="font-size:13px;color:#aaa;">No sales recorded.</span>`;
    return;
  }}
  const rows = sells.map(s => {{
    const gc = s.realized_gain >= 0 ? "#27ae60" : "#e74c3c";
    const detail = (s.fifo_detail || []).map(a => {{
      const badge = a.term === "LT"
        ? `<span style="background:#f0fff4;color:#27ae60;border:1px solid #ade;border-radius:3px;padding:0 4px;font-size:9px;font-weight:700;">LT</span>`
        : `<span style="background:#fff0f0;color:#e74c3c;border:1px solid #fcc;border-radius:3px;padding:0 4px;font-size:9px;font-weight:700;">ST</span>`;
      const gc2 = a.gain >= 0 ? "#27ae60" : "#e74c3c";
      return `${{a.shares}} sh @ $${{a.cost_per_share?.toFixed(2)}} (${{a.purchase_date}}) ${{badge}} <span style="color:${{gc2}}">${{a.gain>=0?"+":""}}$${{Math.abs(a.gain||0).toFixed(2)}}</span>`;
    }}).join("<br>");
    return `<tr style="border-bottom:1px solid #f5f5f5;vertical-align:top;">
      <td style="padding:6px 8px;white-space:nowrap;">${{s.sell_date}}</td>
      <td style="padding:6px 8px;">${{s.shares_sold}}</td>
      <td style="padding:6px 8px;">$${{s.sell_price?.toFixed(2)}}</td>
      <td style="padding:6px 8px;font-weight:600;color:${{gc}};">${{s.realized_gain>=0?"+":""}}$${{Math.abs(s.realized_gain||0).toFixed(2)}}</td>
      <td style="padding:6px 8px;color:#e74c3c;">${{s.st_gain!==0?(s.st_gain>=0?"+":"")+"$"+Math.abs(s.st_gain||0).toFixed(2):"—"}}</td>
      <td style="padding:6px 8px;color:#27ae60;">${{s.lt_gain!==0?(s.lt_gain>=0?"+":"")+"$"+Math.abs(s.lt_gain||0).toFixed(2):"—"}}</td>
      <td style="padding:6px 8px;font-size:11px;color:#888;line-height:1.6;">${{detail}}</td>
      <td style="padding:6px 8px;"><button onclick="undoSell(${{s.id}})" style="font-size:10px;padding:2px 8px;background:#fff0f0;border:1px solid #fcc;border-radius:4px;cursor:pointer;color:#e74c3c;">Undo</button></td>
    </tr>`;
  }}).join("");
  wrap.innerHTML = `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:12px;">
    <thead><tr style="background:#f4f6f9;">
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Date</th>
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Shares</th>
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Price</th>
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Total G/L</th>
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">ST</th>
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">LT</th>
      <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Lot Detail</th>
      <th></th>
    </tr></thead>
    <tbody>${{rows}}</tbody>
  </table></div>`;
}}

async function undoSell(id) {{
  if (!confirm("Undo this sale? Lots will be restored.")) return;
  try {{
    const res  = await fetch(`/api/sells/${{id}}`, {{ method: "DELETE" }});
    const data = await res.json();
    if (!data.ok) {{ alert("Error: " + data.error); return; }}
    const ticker = _lotsModalTicker;
    if (ticker && _allSells[ticker]) {{
      _allSells[ticker] = _allSells[ticker].filter(s => s.id !== id);
    }}
    await loadAllLots();
    await loadAllSells();
    renderLotsModal();
    renderSellHistory(ticker);
    renderAllStltBadges();
    renderRealizedGains();
  }} catch(e) {{ alert("Error: " + e.message); }}
}}

window.addEventListener("load", loadAllSells);

// ── Realized Gains & Tax Estimate ────────────────────────────────────────
function _fmtGain(v) {{
  const abs = Math.abs(v).toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}});
  return (v >= 0 ? "+" : "−") + "$" + abs;
}}
function _gainColor(v) {{ return v >= 0 ? "#27ae60" : "#e74c3c"; }}

function renderRealizedGains() {{
  const yearFilter = document.getElementById("gains-year-filter")?.value || "cur";
  const curYear    = new Date().getFullYear().toString();
  const stRate     = parseFloat(document.getElementById("tax-st-rate")?.value  || 35) / 100;
  const ltRate     = parseFloat(document.getElementById("tax-lt-rate")?.value  || 20) / 100;
  const niit       = document.getElementById("tax-niit")?.checked ? 0.038 : 0;

  // Save rates to localStorage
  try {{
    localStorage.setItem("tax_st_rate", document.getElementById("tax-st-rate").value);
    localStorage.setItem("tax_lt_rate", document.getElementById("tax-lt-rate").value);
    localStorage.setItem("tax_niit",    document.getElementById("tax-niit").checked ? "1" : "0");
  }} catch(e) {{}}

  // Flatten all sells and filter by year
  let sells = Object.values(_allSells).flat();
  if (yearFilter === "cur") {{
    sells = sells.filter(s => s.sell_date?.startsWith(curYear));
  }}
  sells = sells.slice().sort((a,b) => b.sell_date.localeCompare(a.sell_date));

  const stockSTGain = sells.reduce((s, x) => s + (x.st_gain || 0), 0);
  const ltGain      = sells.reduce((s, x) => s + (x.lt_gain || 0), 0);
  const stockTotal  = sells.reduce((s, x) => s + (x.realized_gain || 0), 0);

  // CC premium income — always short-term ordinary income
  const yearCCClosed = _allCCPositions.filter(p =>
    p.status !== "open" && p.net_premium != null &&
    (yearFilter === "all" || p.closed_date?.startsWith(curYear))
  );
  const ccNetTotal = yearCCClosed.reduce((s, p) => s + (p.net_premium || 0), 0);

  // Prior YTD gains not yet entered as individual transactions (all ST until validated)
  const PRIOR_ST_2026 = 5288.53;
  const priorST = (yearFilter === "cur") ? PRIOR_ST_2026 : 0;

  // Combined totals
  const stGain    = stockSTGain + ccNetTotal + priorST;
  const totalGain = stockTotal  + ccNetTotal + priorST;
  const hasData   = sells.length > 0 || yearCCClosed.length > 0 || priorST > 0;

  const stTax  = Math.max(0, stGain) * (stRate + niit);
  const ltTax  = Math.max(0, ltGain) * (ltRate + niit);
  const totTax = stTax + ltTax;

  // Update top KPI immediately — must happen before any early returns below
  _updateTaxBillKPI();

  const fmt2 = v => "$" + v.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}});

  // KPI updates
  const totalEl = document.getElementById("gains-total");
  if (totalEl) {{
    totalEl.textContent = hasData ? _fmtGain(totalGain) : "—";
    totalEl.style.color = hasData ? _gainColor(totalGain) : "#1a2340";
  }}
  const stEl = document.getElementById("gains-st");
  if (stEl) {{
    stEl.textContent = hasData ? _fmtGain(stGain) : "—";
    stEl.style.color = hasData ? (stGain >= 0 ? "#c0392b" : "#27ae60") : "#e74c3c";
  }}
  const ltEl = document.getElementById("gains-lt");
  if (ltEl) {{
    ltEl.textContent = hasData ? _fmtGain(ltGain) : "—";
    ltEl.style.color = hasData ? (ltGain >= 0 ? "#27ae60" : "#e74c3c") : "#27ae60";
  }}

  // Sub-lines showing breakdown when CC income is present
  const countEl = document.getElementById("gains-txn-count");
  if (countEl) {{
    const parts = [];
    if (sells.length)        parts.push(`${{sells.length}} stock sale${{sells.length!==1?"s":""}}`);
    if (yearCCClosed.length) parts.push(`${{yearCCClosed.length}} CC close${{yearCCClosed.length!==1?"s":""}}`);
    if (priorST > 0)         parts.push(`+${{fmt2(priorST)}} prior ST (unvalidated)`);
    countEl.textContent = parts.join(" · ");
  }}
  const stSubEl = document.getElementById("gains-st-sub");
  if (stSubEl) {{
    const stParts = [];
    if (sells.length)        stParts.push(`Stock ST: <b>${{_fmtGain(stockSTGain)}}</b>`);
    if (ccNetTotal)          stParts.push(`CC: <b>${{_fmtGain(ccNetTotal)}}</b>`);
    if (priorST > 0)         stParts.push(`Prior ST: <b style="color:#e67e22;">${{fmt2(priorST)}} ⚠</b>`);
    stSubEl.innerHTML = stParts.length > 1 ? stParts.join(" · ") : "Taxed as ordinary income";
  }}

  const estStEl = document.getElementById("tax-est-st");
  if (estStEl) {{ estStEl.textContent = hasData ? fmt2(stTax) : "—"; estStEl.style.color = stTax > 0 ? "#c0392b" : "#888"; }}
  const estLtEl = document.getElementById("tax-est-lt");
  if (estLtEl) {{ estLtEl.textContent = hasData ? fmt2(ltTax) : "—"; estLtEl.style.color = ltTax > 0 ? "#c0392b" : "#888"; }}
  const estTotEl = document.getElementById("tax-est-total");
  if (estTotEl) {{ estTotEl.textContent = hasData ? fmt2(totTax) : "—"; estTotEl.style.color = totTax > 0 ? "#c0392b" : "#888"; }}

  // Per-transaction table
  const wrap = document.getElementById("gains-table-wrap");
  if (!wrap) return;
  if (!sells.length) {{
    wrap.innerHTML = `<div style="font-size:13px;color:#aaa;">No sales recorded${{yearFilter==="cur"?" for "+curYear:" yet"}}. Use the <b>Lots</b> modal on any holding to record a sale.</div>`;
    return;
  }}

  const rows = sells.map(s => {{
    const gc  = _gainColor(s.realized_gain || 0);
    const stc = (s.st_gain || 0) !== 0 ? _gainColor(s.st_gain) : "#aaa";
    const ltc = (s.lt_gain || 0) !== 0 ? _gainColor(s.lt_gain) : "#aaa";
    const stTaxRow = Math.max(0, s.st_gain || 0) * (stRate + niit);
    const ltTaxRow = Math.max(0, s.lt_gain || 0) * (ltRate + niit);
    const totTaxRow = stTaxRow + ltTaxRow;
    const detail = (s.fifo_detail || []).map(a => {{
      const badge = a.term === "LT"
        ? `<span style="background:#f0fff4;color:#27ae60;border:1px solid #ade;border-radius:3px;padding:0 4px;font-size:9px;font-weight:700;">LT</span>`
        : `<span style="background:#fff0f0;color:#e74c3c;border:1px solid #fcc;border-radius:3px;padding:0 4px;font-size:9px;font-weight:700;">ST</span>`;
      return `${{a.shares}}sh@$${{a.cost_per_share?.toFixed(2)}} ${{badge}}`;
    }}).join(" · ");
    return `<tr style="border-bottom:1px solid #f5f5f5;">
      <td style="padding:7px 8px;font-weight:600;">${{s.ticker}}</td>
      <td style="padding:7px 8px;color:#555;">${{s.sell_date}}</td>
      <td style="padding:7px 8px;">${{s.shares_sold?.toLocaleString("en-US",{{maximumFractionDigits:4}})}}</td>
      <td style="padding:7px 8px;">$${{s.sell_price?.toFixed(2)}}</td>
      <td style="padding:7px 8px;font-weight:700;color:${{gc}};">${{_fmtGain(s.realized_gain||0)}}</td>
      <td style="padding:7px 8px;color:${{stc}};">${{(s.st_gain||0)!==0?_fmtGain(s.st_gain):"—"}}</td>
      <td style="padding:7px 8px;color:${{ltc}};">${{(s.lt_gain||0)!==0?_fmtGain(s.lt_gain):"—"}}</td>
      <td style="padding:7px 8px;color:#c0392b;font-weight:600;">${{totTaxRow>0?"~"+fmt2(totTaxRow):"—"}}</td>
      <td style="padding:7px 8px;font-size:11px;color:#aaa;">${{detail}}</td>
      <td style="padding:7px 8px;font-size:11px;color:#aaa;">${{s.notes||""}}</td>
    </tr>`;
  }}).join("");

  wrap.innerHTML = `<div style="overflow-x:auto;margin-top:4px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f4f6f9;text-align:left;">
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Ticker</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Date</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Shares</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Price</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Total G/L</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">ST G/L</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">LT G/L</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Est. Tax</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Lot Detail</th>
        <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Notes</th>
      </tr></thead>
      <tbody>${{rows}}</tbody>
    </table></div>
  <div style="font-size:10px;color:#bbb;margin-top:8px;">
    Est. Tax = positive gains only · federal rate only · rates: ST ${{(stRate*100).toFixed(1)}}%${{niit?" +3.8% NIIT":""}} / LT ${{(ltRate*100).toFixed(1)}}%${{niit?" +3.8% NIIT":""}}
  </div>`;

  // ── Option Premium Income (CC) ─── reuses yearCCClosed + ccNetTotal from above
  const ccTax = Math.max(0, ccNetTotal) * (stRate + niit);

  if (yearCCClosed.length) {{
    const ccRows = yearCCClosed
      .slice().sort((a,b) => b.closed_date.localeCompare(a.closed_date))
      .map(p => {{
        const gross  = p.premium_per_contract * p.contracts * 100;
        const buyback = p.closed_price != null ? p.closed_price * p.contracts * 100 : 0;
        const net    = p.net_premium || 0;
        const gc     = net >= 0 ? "#27ae60" : "#e74c3c";
        const typeMap = {{ expired: "Expired", buyback: "Buy Back", assigned: "Assigned" }};
        const badge = {{
          expired:  "background:#fff8e1;color:#8a6d00;border:1px solid #ffe082",
          buyback:  "background:#f4f6f9;color:#555;border:1px solid #dde",
          assigned: "background:#fff0f0;color:#c8102e;border:1px solid #fcc",
        }}[p.close_type] || "background:#f4f4f4;color:#888;border:1px solid #eee";
        return `<tr style="border-bottom:1px solid #f5f5f5;">
          <td style="padding:6px 8px;font-weight:600;">${{p.ticker}}</td>
          <td style="padding:6px 8px;">$${{p.strike.toFixed(2)}} call</td>
          <td style="padding:6px 8px;">${{p.expiry}}</td>
          <td style="padding:6px 8px;">${{p.contracts}}×</td>
          <td style="padding:6px 8px;">$${{p.premium_per_contract.toFixed(2)}}</td>
          <td style="padding:6px 8px;color:#555;">$${{gross.toFixed(2)}}</td>
          <td style="padding:6px 8px;color:#e74c3c;">${{buyback > 0 ? "−$"+buyback.toFixed(2) : "—"}}</td>
          <td style="padding:6px 8px;font-weight:700;color:${{gc}};">${{net>=0?"+":""}}$${{Math.abs(net).toFixed(2)}}</td>
          <td style="padding:6px 8px;color:#c0392b;">~$${{(Math.max(0,net)*(stRate+niit)).toFixed(2)}}</td>
          <td style="padding:6px 8px;"><span style="border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;${{badge}}">${{typeMap[p.close_type]||p.status}}</span></td>
          <td style="padding:6px 8px;color:#aaa;font-size:11px;">${{p.closed_date||""}}</td>
        </tr>`;
      }}).join("");

    wrap.innerHTML += `
      <div style="margin-top:20px;padding-top:16px;border-top:2px solid #f0f0f0;">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
          <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;">
            Option Premium Income (Short-Term Ordinary)
          </div>
          <div style="display:flex;gap:16px;font-size:13px;">
            <span>Net Income: <b style="color:#27ae60;">${{ccNetTotal>=0?"+":""}}$${{Math.abs(ccNetTotal).toFixed(2)}}</b></span>
            <span>Est. Tax (ST ${{(stRate*100).toFixed(0)}}%${{niit?"+3.8%":""}}): <b style="color:#c0392b;">~$${{ccTax.toFixed(2)}}</b></span>
          </div>
        </div>
        <div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:12px;">
          <thead><tr style="background:#f4f6f9;">
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Ticker</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Strike</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Expiry</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Contracts</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Prem/Contract</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Gross</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Buyback Cost</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#27ae60;text-transform:uppercase;">Net Income</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#c0392b;text-transform:uppercase;">Est. Tax</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Close Type</th>
            <th style="padding:5px 8px;text-align:left;font-size:10px;color:#888;text-transform:uppercase;">Closed</th>
          </tr></thead>
          <tbody>${{ccRows}}</tbody>
        </table></div>
        <div style="font-size:10px;color:#bbb;margin-top:6px;">CC premium income is always short-term ordinary income and is included in the Short-Term KPI and tax estimate above. When assigned, the stock capital gain/loss is tracked separately via the FIFO sell tracker.</div>
      </div>`;
  }}
}}

function _updateTaxBillKPI() {{
  const now       = new Date();
  const curYear   = now.getFullYear();
  // Show current year while we're in it; once it flips to 2027+ show prior year as final
  const dispYear  = curYear <= 2026 ? curYear : curYear - 1;
  const isPrior   = curYear > dispYear;

  // Use the same rate inputs as renderRealizedGains() so both always agree
  const stRate = parseFloat(document.getElementById("tax-st-rate")?.value  || 35) / 100;
  const ltRate = parseFloat(document.getElementById("tax-lt-rate")?.value  || 20) / 100;
  const niit   = document.getElementById("tax-niit")?.checked ? 0.038 : 0;

  // Sells for display year
  const allSells  = Object.values(_allSells).flat();
  const ySells    = allSells.filter(s => s.sell_date && s.sell_date.startsWith(String(dispYear)));
  const stockST   = ySells.reduce((s, x) => s + (x.st_gain || 0), 0);
  const stockLT   = ySells.reduce((s, x) => s + (x.lt_gain || 0), 0);

  // CC closed positions for display year
  const yCCClosed = _allCCPositions.filter(p =>
    p.status !== "open" && p.net_premium != null &&
    p.closed_date && p.closed_date.startsWith(String(dispYear))
  );
  const ccNet = yCCClosed.reduce((s, p) => s + (p.net_premium || 0), 0);

  // Prior unvalidated ST (only applies for 2026 display year)
  const PRIOR_ST_2026 = 5288.53;
  const priorST = dispYear === 2026 ? PRIOR_ST_2026 : 0;

  const stGain  = stockST + ccNet + priorST;
  const ltGain  = stockLT;
  const stTax   = Math.max(0, stGain) * (stRate + niit);
  const ltTax   = Math.max(0, ltGain) * (ltRate + niit);
  const totTax  = stTax + ltTax;

  const fmt = v => "$" + Math.round(v).toLocaleString("en-US");

  const labelEl = document.getElementById("kpi-tax-label");
  const valEl   = document.getElementById("kpi-tax-value");
  const subEl   = document.getElementById("kpi-tax-sub");
  if (!labelEl || !valEl || !subEl) return;

  labelEl.textContent = isPrior ? `${{dispYear}} Tax Bill (Final)` : `Est. ${{dispYear}} Tax Bill`;
  valEl.textContent   = totTax > 0 ? fmt(totTax) : "$0";
  valEl.style.color   = totTax > 0 ? "#c0392b" : "#27ae60";
  subEl.textContent   = totTax > 0 ? `ST ${{fmt(stTax)}} · LT ${{fmt(ltTax)}}` : "No realized gains yet";
}}

function _initTaxRates() {{
  try {{
    const st = localStorage.getItem("tax_st_rate");
    const lt = localStorage.getItem("tax_lt_rate");
    const ni = localStorage.getItem("tax_niit");
    if (st) document.getElementById("tax-st-rate").value = st;
    if (lt) document.getElementById("tax-lt-rate").value = lt;
    if (ni) document.getElementById("tax-niit").checked  = ni === "1";
  }} catch(e) {{}}
}}

window.addEventListener("load", () => {{ _initTaxRates(); renderRealizedGains(); }});

// ── Buffett Screener ──────────────────────────────────────────────────────
let _buffettPollTimer  = null;
let _startupPollCount  = 0;
let _buffettAllWinners = [];
let _bSort    = {{ col: "gross_margin", dir: -1 }};
let _bFilters = {{ q: "", exchange: "", layer: 0, risk: "" }};

// ── Shared helpers (used by table + recommendations) ──────────────────────
const _bFmtVal = v => (v != null && isFinite(v)) ? v.toFixed(1) + "x" : "—";
const _bLnk    = `font-size:10px;padding:1px 5px;border-radius:3px;border:1px solid #dde;color:#555;text-decoration:none;white-space:nowrap;`;
const _bLayerMeta = {{
  1: {{ label:"L1", bg:"#1a2340", color:"#fff", title:"Structural Ballast" }},
  2: {{ label:"L2", bg:"#1a7a4a", color:"#fff", title:"Cash-Flow Engine" }},
  3: {{ label:"L3", bg:"#d4800a", color:"#fff", title:"Compounder" }},
  4: {{ label:"L4", bg:"#6c3fc5", color:"#fff", title:"Convexity / Optionality" }},
  5: {{ label:"L5", bg:"#b22222", color:"#fff", title:"Shock Absorber" }},
}};
const _bTrapMeta = {{
  low:    {{ label:"✓ Low",    bg:"#eafaf1", color:"#1e8449", border:"#a9dfbf" }},
  medium: {{ label:"⚠ Medium", bg:"#fef9e7", color:"#b7770d", border:"#f9e79f" }},
  high:   {{ label:"⛔ High",  bg:"#fdf2f2", color:"#c0392b", border:"#f5c6cb" }},
}};
function _bTrapBadge(risk, flagsJson) {{
  if (!risk) return `<span style="color:#bbb;font-size:11px;">—</span>`;
  const m = _bTrapMeta[risk] || _bTrapMeta.low;
  let flags = [];
  try {{ flags = JSON.parse(flagsJson || "[]"); }} catch(e) {{}}
  const flagLines = flags.length
    ? flags.map(f => `<div style="font-size:10px;color:#888;margin-top:2px;line-height:1.3;">• ${{f}}</div>`).join("")
    : `<div style="font-size:10px;color:#aaa;margin-top:2px;">No signals detected</div>`;
  return `<span title="${{flags.join("\\n") || "No signals"}}"
    style="display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;
           background:${{m.bg}};color:${{m.color}};border:1px solid ${{m.border}};cursor:default;white-space:nowrap;">${{m.label}}</span>${{flagLines}}`;
}}
function _bLayerBadge(rec, reason) {{
  if (!rec) return "—";
  const m = _bLayerMeta[rec] || {{}};
  return `<span title="${{reason || m.title || ""}}"
    style="display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;
           background:${{m.bg}};color:${{m.color}};cursor:default;white-space:nowrap;">${{m.label}}</span>
    <div style="font-size:10px;color:#888;margin-top:2px;max-width:120px;line-height:1.3;">${{reason || ""}}</div>`;
}}
function _bSortBy(col) {{
  if (_bSort.col === col) {{ _bSort.dir *= -1; }}
  else {{ _bSort.col = col; _bSort.dir = -1; }}
  _renderBuffettTable();
}}
function _bSetFilter(key, val) {{
  _bFilters[key] = val;
  _renderBuffettTable();
}}

function _fmtDuration(sec) {{
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h > 0) return `${{h}}h ${{m}}m`;
  if (m > 0) return `${{m}}m ${{s}}s`;
  return `${{s}}s`;
}}

async function triggerBuffettScan() {{
  const btn      = document.getElementById("buffett-run-btn");
  const statusEl = document.getElementById("buffett-status-bar");
  const progWrap = document.getElementById("buffett-progress-wrap");
  const progBar  = document.getElementById("buffett-progress-bar");

  btn.disabled       = true;
  btn.textContent    = "Starting…";
  _startupPollCount  = 0;

  // Paint immediate feedback so the user knows something is happening
  statusEl.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;font-size:12px;">
      <span style="display:inline-flex;align-items:center;gap:5px;background:#fff8e1;color:#e67e22;
                   border:1px solid #ffe082;border-radius:12px;padding:3px 10px;font-size:11px;font-weight:600;">
        <span style="animation:spin 1s linear infinite;display:inline-block;">⏳</span> Starting…
      </span>
      <span style="color:#7f8c8d;">Launching screener — fetching tickers…</span>
    </div>`;
  if (progWrap) {{
    progWrap.style.display = "block";
    if (progBar) {{ progBar.style.width = "0%"; }}
    const lbl = document.getElementById("buffett-progress-label");
    const pct = document.getElementById("buffett-progress-pct");
    const eta = document.getElementById("buffett-eta");
    if (lbl) lbl.textContent = "Initialising…";
    if (pct) pct.textContent = "0%";
    if (eta) eta.textContent = "ETA calculating…";
  }}

  try {{
    const res  = await fetch("/api/buffett-scan", {{method:"POST"}});
    const data = await res.json();
    if (data.ok) {{
      btn.textContent = "▶ Running…";
      // Poll every 5 s until scan_running is confirmed, then switch to 20 s cadence
      clearTimeout(_buffettPollTimer);
      _buffettPollTimer = setTimeout(_buffettStartupPoll, 5000);
    }} else {{
      btn.textContent = "▶ Run Scan";
      btn.disabled = false;
      statusEl.innerHTML = `
        <div style="background:#fff5f0;border-left:3px solid #e74c3c;padding:8px 12px;border-radius:4px;font-size:12px;">
          ${{data.reason === "already_running" ? "⚠ A scan is already in progress." : "⚠ Could not start scan: " + (data.reason || "unknown error")}}
        </div>`;
    }}
  }} catch(e) {{
    btn.textContent = "▶ Run Scan";
    btn.disabled = false;
    statusEl.innerHTML = `<div style="background:#fff5f0;border-left:3px solid #e74c3c;padding:8px 12px;border-radius:4px;font-size:12px;">
      ⚠ Network error: ${{e.message}}</div>`;
  }}
}}

// Fast-poll during startup (every 5 s), falls back to normal 20 s once confirmed running
async function _buffettStartupPoll() {{
  _startupPollCount++;
  await loadBuffett();
  // Keep fast-polling for up to 2 min (24 × 5 s) in case startup is slow
  if (_startupPollCount < 24) {{
    clearTimeout(_buffettPollTimer);
    _buffettPollTimer = setTimeout(_buffettStartupPoll, 5000);
  }}
  // loadBuffett() will set up its own 20 s timer once it sees scan_running = true
}}

async function loadBuffett() {{
  const statusEl  = document.getElementById("buffett-status-bar");
  const resultsEl = document.getElementById("buffett-results");
  const progWrap  = document.getElementById("buffett-progress-wrap");
  const progBar   = document.getElementById("buffett-progress-bar");
  const progLabel = document.getElementById("buffett-progress-label");
  const progPct   = document.getElementById("buffett-progress-pct");
  const etaEl     = document.getElementById("buffett-eta");
  const logWrap   = document.getElementById("buffett-log-wrap");
  const logPre    = document.getElementById("buffett-log-pre");
  const runBtn    = document.getElementById("buffett-run-btn");

  try {{
    const res  = await fetch("/api/buffett-winners");
    const data = await res.json();
    if (!data.ok) {{
      statusEl.innerHTML = `<div style="background:#fff5f0;border-left:3px solid #e74c3c;padding:8px 12px;border-radius:4px;font-size:12px;">
        ⚠️ Error loading screener data.</div>`;
      return;
    }}

    const m            = data.meta || {{}};
    const running      = !!data.scan_running;
    const cached       = data.cache_count || 0;
    const scanned      = parseInt(m.tickers_scanned || "0");
    const total        = parseInt(m.total_tickers || "2348");
    const winnersFound = parseInt(m.winners_found || data.winners.length || "0");
    const eta          = data.eta_seconds;
    const dur          = data.scan_duration;
    const lastScan     = m.last_scan || null;
    const scanStarted  = m.scan_started || null;
    const pct          = total > 0 ? Math.min(100, Math.round(scanned / total * 100)) : 0;
    const hasResults   = data.winners.length > 0;

    // ── Run button state ──
    runBtn.disabled    = running;
    runBtn.textContent = running ? "▶ Running…" : "▶ Run Scan";

    // ── Auto-poll while running (every 20s) ──
    clearTimeout(_buffettPollTimer);
    if (running) {{
      _buffettPollTimer = setTimeout(loadBuffett, 20000);
    }}

    // ── Status badge + stats row ──
    let badge = "", statsLine = "";

    if (running) {{
      badge = `<span style="display:inline-flex;align-items:center;gap:5px;background:#fff8e1;color:#e67e22;border:1px solid #ffe082;border-radius:12px;padding:3px 10px;font-size:11px;font-weight:600;">
        <span style="animation:spin 1s linear infinite;display:inline-block;">⏳</span> Scanning
      </span>`;
      statsLine = `<span style="color:#7f8c8d;">${{scanned.toLocaleString()}} / ${{total.toLocaleString()}} tickers</span>
        &nbsp;·&nbsp; <span style="color:#27ae60;font-weight:600;">${{winnersFound}} winner${{winnersFound!==1?"s":""}} so far</span>
        ${{scanStarted ? `&nbsp;·&nbsp; started ${{scanStarted.slice(11,16)}}` : ""}}`;
    }} else if (lastScan) {{
      const isComplete = scanned >= total * 0.95;
      if (isComplete) {{
        badge = `<span style="background:#e8f8f0;color:#27ae60;border:1px solid #b2dfcc;border-radius:12px;padding:3px 10px;font-size:11px;font-weight:600;">✓ Complete</span>`;
      }} else {{
        badge = `<span style="background:#fff5f0;color:#e74c3c;border:1px solid #f5c6cb;border-radius:12px;padding:3px 10px;font-size:11px;font-weight:600;">⚠ Incomplete</span>`;
      }}
      statsLine = `<span style="color:#7f8c8d;">Last scan: <b>${{lastScan}}</b></span>
        &nbsp;·&nbsp; ${{scanned.toLocaleString()}} tickers
        &nbsp;·&nbsp; <span style="color:#27ae60;font-weight:600;">${{winnersFound}} winner${{winnersFound!==1?"s":""}}</span>
        ${{dur ? `&nbsp;·&nbsp; <span style="color:#aaa;">ran in ${{_fmtDuration(dur)}}</span>` : ""}}`;
    }} else if (cached === 0) {{
      badge = `<span style="background:#f4f6f9;color:#aaa;border:1px solid #dde;border-radius:12px;padding:3px 10px;font-size:11px;">Never run</span>`;
      statsLine = `<span style="color:#aaa;">Auto-scan runs at 2 AM ET — or click Run Scan to start now.</span>`;
    }} else {{
      badge = `<span style="background:#fff5f0;color:#e74c3c;border:1px solid #f5c6cb;border-radius:12px;padding:3px 10px;font-size:11px;font-weight:600;">⚠ Stopped</span>`;
      statsLine = `<span style="color:#7f8c8d;">Stopped at ${{cached.toLocaleString()}} tickers — no completed scan yet.</span>`;
    }}

    statusEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12px;">
        ${{badge}}
        <span>${{statsLine}}</span>
      </div>`;

    // ── Progress bar ──
    if (running || (lastScan && scanned < total)) {{
      progWrap.style.display = "block";
      progBar.style.width    = pct + "%";
      progLabel.textContent  = running
        ? `${{scanned.toLocaleString()}} of ${{total.toLocaleString()}} tickers scanned`
        : `${{pct}}% of tickers covered in last scan`;
      progPct.textContent  = pct + "%";
      etaEl.innerHTML = running && eta != null && eta > 0
        ? `ETA ~${{_fmtDuration(eta)}} remaining`
        : running ? "Calculating ETA…" : "";
    }} else {{
      progWrap.style.display = "none";
    }}

    // ── Error / incomplete banner ──
    if (!running && lastScan && scanned < total * 0.95) {{
      resultsEl.innerHTML = `
        <div style="background:#fff5f0;border-left:3px solid #e74c3c;padding:8px 12px;border-radius:4px;margin-bottom:10px;font-size:12px;">
          ⚠️ <b>Scan stopped at ${{pct}}%</b> (${{scanned.toLocaleString()}} / ${{total.toLocaleString()}} tickers).
          The ${{winnersFound}} result${{winnersFound!==1?"s":""}} below cover only what was scanned.
          Click <b>▶ Run Scan</b> to restart, or wait for the 2 AM auto-run.
        </div>`;
    }} else {{
      resultsEl.innerHTML = "";
    }}

    // ── Log tail ──
    const logLines = data.log_tail || [];
    if (logLines.length) {{
      logWrap.style.display = "block";
      const colored = logLines.map(l => {{
        const isErr  = /error|traceback|exception|typeerror|valueerror|operationalerror/i.test(l);
        const isWarn = /warning|warn|already running/i.test(l);
        const isSep  = l.startsWith("===");
        const color  = isErr ? "#e74c3c" : isWarn ? "#e67e22" : isSep ? "#2980b9" : "#a0a8c0";
        return `<span style="color:${{color}}">${{l.replace(/&/g,"&amp;").replace(/</g,"&lt;")}}</span>`;
      }}).join("\\n");
      logPre.innerHTML = colored;
    }} else {{
      logWrap.style.display = "none";
    }}

    // ── Winners table ──
    if (!hasResults) {{
      if (!running) {{
        resultsEl.innerHTML += `<p style="color:#888;font-size:13px;margin-top:8px;">No winners found yet.</p>`;
      }}
      return;
    }}

    // Store for filter/sort re-renders; reset sort to default on fresh load
    _buffettAllWinners = data.winners;
    _bSort    = {{ col: "gross_margin", dir: -1 }};
    _bFilters = {{ q: "", exchange: "", layer: 0, risk: "" }};

    const partialNote = (running || (lastScan && scanned < total * 0.95))
      ? `<span style="color:#e67e22;"> · partial results (${{pct}}% scanned)</span>` : "";

    resultsEl.innerHTML += `<div id="buffett-table-wrap"></div>
      <p style="font-size:11px;color:#aaa;margin-top:6px;">
        Green = quality · Blue = valuation · Purple = layer · Red = trap risk${{partialNote}}
      </p>`;
    _renderBuffettTable();

  }} catch(e) {{
    document.getElementById("buffett-status-bar").innerHTML =
      `<div style="background:#fff5f0;border-left:3px solid #e74c3c;padding:8px 12px;border-radius:4px;font-size:12px;">
        ⚠️ Failed to load screener data: ${{e.message}}</div>`;
  }}
}}

window.addEventListener("load", loadBuffett);

// ── Buffett table: filter + sort renderer ─────────────────────────────────
function _renderBuffettTable() {{
  const wrap = document.getElementById("buffett-table-wrap");
  if (!wrap || !_buffettAllWinners.length) return;

  const q    = (_bFilters.q || "").toLowerCase();
  const exch = _bFilters.exchange;
  const lyr  = _bFilters.layer;
  const risk = _bFilters.risk;

  // Filter
  let rows = _buffettAllWinners.filter(w => {{
    if (exch && w.exchange !== exch) return false;
    if (lyr  && w.layer_rec !== lyr) return false;
    if (risk && w.value_trap_risk !== risk) return false;
    if (q) {{
      const hay = ((w.ticker||"") + " " + (w.company||"") + " " + (w.sector||"")).toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});

  // Sort
  const riskOrder = {{ low:1, medium:2, high:3, null:9, undefined:9 }};
  const col = _bSort.col;
  const dir = _bSort.dir;
  rows = rows.slice().sort((a, b) => {{
    let av, bv;
    if (col === "ticker")           {{ av = a.ticker || ""; bv = b.ticker || ""; }}
    else if (col === "company")     {{ av = a.company || ""; bv = b.company || ""; }}
    else if (col === "layer_rec")   {{ av = a.layer_rec || 99; bv = b.layer_rec || 99; }}
    else if (col === "value_trap_risk") {{ av = riskOrder[a.value_trap_risk]||9; bv = riskOrder[b.value_trap_risk]||9; }}
    else {{ av = a[col] ?? (dir > 0 ? Infinity : -Infinity); bv = b[col] ?? (dir > 0 ? Infinity : -Infinity); }}
    if (typeof av === "string") return dir * av.localeCompare(bv);
    return dir * (av - bv);
  }});

  // Column header builder
  const thStyle = (c, label, color="#7f8c8d", align="left") => {{
    const active = _bSort.col === c;
    const arrow  = active ? (_bSort.dir < 0 ? " ▼" : " ▲") : ` <span style="color:#ddd;font-size:9px;">⇅</span>`;
    const hl     = active ? "background:#ecf0ff;" : "";
    return `<th onclick="_bSortBy('${{c}}')" style="padding:7px 10px;text-align:${{align}};font-size:11px;color:${{color}};
      text-transform:uppercase;letter-spacing:.04em;cursor:pointer;user-select:none;white-space:nowrap;${{hl}}
      border-bottom:2px solid ${{active?"#6c63ff":"transparent"}};">
      ${{label}}${{arrow}}</th>`;
  }};

  // Filter chip builder
  const chip = (key, val, label, activeVal) => {{
    const on = activeVal === val;
    return `<span onclick="_bSetFilter('${{key}}','${{on ? "" : val}}')"
      style="cursor:pointer;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;user-select:none;
             border:1px solid ${{on?"#6c63ff":"#dde"}};background:${{on?"#6c63ff":"#f4f6f9"}};
             color:${{on?"#fff":"#555"}};">
      ${{label}}</span>`;
  }};

  const matchTxt = rows.length === _buffettAllWinners.length
    ? `${{_buffettAllWinners.length}} stocks`
    : `${{rows.length}} of ${{_buffettAllWinners.length}} stocks`;

  const filterBar = `
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;
                padding:8px 12px;background:#f8fafc;border:1px solid #e8edf4;border-radius:8px;">
      <input id="b-filter-q" value="${{_bFilters.q}}" placeholder="Search ticker / company…"
        oninput="_bFilters.q=this.value;_renderBuffettTable()"
        style="padding:4px 8px;border:1px solid #dde;border-radius:6px;font-size:11px;
               width:170px;outline:none;color:#333;">
      <span style="font-size:10px;color:#aaa;font-weight:600;text-transform:uppercase;letter-spacing:.04em;">Exchange</span>
      ${{chip("exchange","NYSE","NYSE",exch)}}
      ${{chip("exchange","NASDAQ","NASDAQ",exch)}}
      <span style="font-size:10px;color:#aaa;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-left:4px;">Layer</span>
      ${{[1,2,3,4,5].map(n => chip("layer",n,"L"+n,lyr)).join("")}}
      <span style="font-size:10px;color:#aaa;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-left:4px;">Risk</span>
      ${{chip("risk","low","Low",risk)}}
      ${{chip("risk","medium","Med",risk)}}
      ${{chip("risk","high","High",risk)}}
      <span style="margin-left:auto;font-size:11px;color:#aaa;">${{matchTxt}}</span>
    </div>`;

  const tableRows = rows.map((w, i) => {{
    const yf   = `https://finance.yahoo.com/quote/${{w.ticker}}`;
    const cnbc = `https://www.cnbc.com/quotes/${{w.ticker.replace("-",".")}}`;
    const mw   = `https://www.marketwatch.com/investing/stock/${{w.ticker.replace("-",".").toLowerCase()}}`;
    const since = w.first_seen ? `<div style="font-size:10px;color:#aaa;margin-top:1px;">since ${{w.first_seen}}</div>` : "";
    const exBadge = w.exchange
      ? `<span style="font-size:9px;font-weight:600;padding:1px 5px;border-radius:3px;
           background:${{w.exchange==="NYSE"?"#e8f4fd":"#edf7ed"}};
           color:${{w.exchange==="NYSE"?"#1a5276":"#1e8449"}};">${{w.exchange}}</span>` : "";
    const rowBg = i % 2 === 0 ? "#fff" : "#fafbfc";
    return `
      <tr style="background:${{rowBg}};border-bottom:1px solid #f0f2f5;">
        <td style="padding:8px 10px;font-size:11px;color:#bbb;text-align:center;">${{i+1}}</td>
        <td style="padding:8px 10px;">
          <div style="display:flex;align-items:center;gap:5px;">
            <span style="font-weight:700;color:#1a2340;">${{w.ticker}}</span>${{exBadge}}
          </div>
          ${{since}}
          <div style="display:flex;gap:3px;margin-top:3px;">
            <a href="${{yf}}"   target="_blank" rel="noopener" style="${{_bLnk}}background:#f0f7ff;">YF</a>
            <a href="${{cnbc}}" target="_blank" rel="noopener" style="${{_bLnk}}background:#fff8f0;">CNBC</a>
            <a href="${{mw}}"   target="_blank" rel="noopener" style="${{_bLnk}}background:#f0fff4;">MW</a>
          </div>
        </td>
        <td style="padding:8px 10px;color:#555;font-size:12px;">${{w.company || "—"}}</td>
        <td style="padding:8px 6px;vertical-align:middle;">${{_bLayerBadge(w.layer_rec, w.layer_reason)}}</td>
        <td style="padding:8px 6px;vertical-align:top;">${{_bTrapBadge(w.value_trap_risk, w.value_trap_flags)}}</td>
        <td style="padding:8px 10px;">${{w.price ? "$" + w.price.toFixed(2) : "—"}}</td>
        <td style="padding:8px 10px;font-weight:700;color:#27ae60;">${{w.gross_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;color:#555;">${{w.sga_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;font-weight:600;color:#27ae60;">${{w.net_income_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;color:#555;">${{w.interest_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;color:#555;">${{w.capex_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;font-weight:600;color:#27ae60;">${{w.cash_gt_debt}}</td>
        <td style="padding:8px 10px;color:#2980b9;">${{w.pe_ratio != null ? w.pe_ratio.toFixed(1) + "x" : "—"}}</td>
        <td style="padding:8px 10px;color:#2980b9;">${{_bFmtVal(w.p_fcf)}}</td>
        <td style="padding:8px 10px;color:#2980b9;">${{_bFmtVal(w.ev_ebitda)}}</td>
      </tr>`;
  }}).join("\\n");

  const noResults = rows.length === 0
    ? `<tr><td colspan="15" style="padding:20px;text-align:center;color:#aaa;font-size:12px;">
         No stocks match the current filters.</td></tr>` : "";

  wrap.innerHTML = filterBar + `
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f4f6f9;border-bottom:2px solid #e8eaf0;">
        <th style="padding:7px 6px;text-align:center;font-size:10px;color:#bbb;width:28px;">#</th>
        ${{thStyle("ticker","Ticker")}}
        ${{thStyle("company","Company")}}
        ${{thStyle("layer_rec","Layer","#9b59b6")}}
        ${{thStyle("value_trap_risk","Trap Risk","#c0392b")}}
        ${{thStyle("price","Price")}}
        ${{thStyle("gross_margin","Gross %","#27ae60")}}
        ${{thStyle("sga_margin","SG&amp;A %")}}
        ${{thStyle("net_income_margin","Net Inc %","#27ae60")}}
        ${{thStyle("interest_margin","Interest %")}}
        ${{thStyle("capex_margin","CapEx %")}}
        ${{thStyle("cash_gt_debt","Cash&gt;Debt","#27ae60")}}
        ${{thStyle("pe_ratio","P/E","#2980b9")}}
        ${{thStyle("p_fcf","P/FCF","#2980b9")}}
        ${{thStyle("ev_ebitda","EV/EBITDA","#2980b9")}}
      </tr></thead>
      <tbody>${{tableRows}}${{noResults}}</tbody>
    </table>
    </div>`;
}}

// ── Buffett Deep-Dive Analyzer ────────────────────────────────────────────
async function runDeepAnalysis() {{
  const input  = document.getElementById("deep-ticker-input");
  const ticker = (input?.value || "").trim().toUpperCase();
  if (!ticker) {{ input?.focus(); return; }}

  const status  = document.getElementById("deep-status");
  const summary = document.getElementById("deep-summary");
  const wrap    = document.getElementById("deep-results-wrap");
  status.textContent  = `Fetching financials for ${{ticker}}…`;
  summary.style.display = "none";
  wrap.innerHTML = "";

  try {{
    const res  = await fetch(`/api/buffett-analysis?ticker=${{encodeURIComponent(ticker)}}`);
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}

    status.textContent = "";
    const score = data.score;
    const max   = data.max_score;
    const pct   = score / max;
    const scoreColor = pct >= 0.77 ? "#27ae60" : pct >= 0.54 ? "#e67e22" : "#e74c3c";
    const verdict    = pct >= 0.77 ? "Strong Buffett candidate" : pct >= 0.54 ? "Mixed signals" : "Does not pass Buffett screen";

    document.getElementById("deep-ticker-label").textContent = data.ticker;
    document.getElementById("deep-price-label").textContent  = data.price > 0 ? `$${{data.price.toFixed(2)}}` : "—";
    const scoreEl = document.getElementById("deep-score-label");
    scoreEl.textContent = `${{score}}/${{max}}`;
    scoreEl.style.color = scoreColor;
    document.getElementById("deep-score-bar").style.width      = `${{(pct*100).toFixed(0)}}%`;
    document.getElementById("deep-score-bar").style.background = scoreColor;
    document.getElementById("deep-score-label2").textContent   = verdict;
    summary.style.display = "flex";

    const rows = data.results.map(r => {{
      const isPass = r.Result === "PASS";
      const isNA   = r.Result === "N/A";
      const badgeBg    = isPass ? "#f0fff4" : isNA ? "#f4f4f4" : "#fff0f0";
      const badgeBdr   = isPass ? "#ade"    : isNA ? "#ddd"    : "#fcc";
      const badgeColor = isPass ? "#27ae60" : isNA ? "#888"    : "#e74c3c";
      return `<tr style="border-bottom:1px solid #f5f5f5;">
        <td style="padding:7px 10px;font-weight:600;color:#1a2340;">${{r.Metric}}</td>
        <td style="padding:7px 10px;font-family:monospace;font-size:12px;color:#555;">${{r.Value}}</td>
        <td style="padding:7px 10px;font-size:12px;color:#888;">${{r.Criteria}}</td>
        <td style="padding:7px 10px;">
          <span style="background:${{badgeBg}};color:${{badgeColor}};border:1px solid ${{badgeBdr}};
            border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;">${{r.Result}}</span>
        </td>
        <td style="padding:7px 10px;font-size:11px;color:#aaa;">${{r.Note||""}}</td>
      </tr>`;
    }}).join("");

    wrap.innerHTML = `<div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#f4f6f9;text-align:left;">
          <th style="padding:7px 10px;font-size:10px;color:#888;text-transform:uppercase;">Metric</th>
          <th style="padding:7px 10px;font-size:10px;color:#888;text-transform:uppercase;">Value</th>
          <th style="padding:7px 10px;font-size:10px;color:#888;text-transform:uppercase;">Criteria</th>
          <th style="padding:7px 10px;font-size:10px;color:#888;text-transform:uppercase;">Result</th>
          <th style="padding:7px 10px;font-size:10px;color:#888;text-transform:uppercase;">Note</th>
        </tr></thead>
        <tbody>${{rows}}</tbody>
      </table></div>`;
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
}}

// ── CC Position Tracker ───────────────────────────────────────────────────
// ── CC Position Tracker ───────────────────────────────────────────────────
let _allCCPositions = [];
let _ccCloseTargetId = null;
let _ccCloseType     = null;

async function loadCCPositions() {{
  const status  = document.getElementById("cc-tracker-status");
  const results = document.getElementById("cc-tracker-results");
  status.textContent = "Loading…";
  results.innerHTML  = "";

  try {{
    const res  = await fetch("/api/cc-positions");
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    _allCCPositions = data.positions || [];
    status.textContent = "";
    renderCCPositions();
    renderRealizedGains();
    const autoExpired = data.auto_expired || [];
    if (autoExpired.length) {{
      const n = autoExpired.length;
      status.innerHTML = `<span style="color:#8a6d00;background:#fff8e1;border:1px solid #ffe082;border-radius:4px;padding:3px 10px;font-size:12px;">
        ✓ ${{n}} position${{n>1?"s":""}} past expiry auto-recorded as expired (full premium kept). Verify if any were assigned instead.
      </span>`;
      setTimeout(() => {{ if (status.innerHTML.includes("auto-recorded")) status.textContent = ""; }}, 8000);
    }}
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

function renderCCPositions() {{
  const results = document.getElementById("cc-tracker-results");
  const positions = _allCCPositions;

  if (!positions.length) {{
    results.innerHTML = `<p style="color:#888;font-size:13px;margin-top:8px;">No positions logged yet. Use the form above to add your first covered call.</p>`;
    return;
  }}

  const open   = positions.filter(p => p.status === "open");
  const closed = positions.filter(p => p.status !== "open");

  const openGross     = open.reduce((s,p)   => s + p.premium_per_contract * p.contracts * 100, 0);
  const netRealized   = closed.reduce((s,p) => s + (p.net_premium ?? 0), 0);
  const grossRealized = closed.reduce((s,p) => s + p.premium_per_contract * p.contracts * 100, 0);
  const buybackCost   = grossRealized - netRealized;

  function statusBadge(p) {{
    const map = {{
      open:     "background:#e8f8ee;color:#1a6e38;border-color:#a8e0b8",
      expired:  "background:#fff8e1;color:#8a6d00;border-color:#ffe082",
      assigned: "background:#fff0f0;color:#c8102e;border-color:#fcc",
      closed:   "background:#f4f6f9;color:#888;border-color:#dde",
    }};
    const c = map[p.status] || map.closed;
    const label = p.close_type ? p.close_type.toUpperCase() : p.status.toUpperCase();
    return `<span style="border:1px solid;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;${{c}}">${{label}}</span>`;
  }}

  function dteTag(expiry) {{
    const d = Math.round((new Date(expiry + "T00:00:00") - new Date()) / 86400000);
    if (d < 0) return `<span style="color:#aaa;font-size:11px;">(expired)</span>`;
    const c = d <= 7 ? "#c8102e" : d <= 21 ? "#e67e22" : "#27ae60";
    return `<span style="color:${{c}};font-weight:600;font-size:11px;">${{d}}d</span>`;
  }}

  const makeRow = p => {{
    const gross    = p.premium_per_contract * p.contracts * 100;
    const isOpen   = p.status === "open";
    const net      = p.net_premium;
    const buyback  = p.closed_price != null ? p.closed_price * p.contracts * 100 : null;

    const netCell  = isOpen
      ? `<td style="padding:7px 10px;color:#aaa;font-size:11px;">open</td>`
      : `<td style="padding:7px 10px;font-weight:700;color:#27ae60;">
           +$${{(net ?? 0).toFixed(2)}}
           ${{buyback ? `<div style="font-size:10px;color:#e74c3c;font-weight:400;">−$${{buyback.toFixed(2)}} buyback</div>` : ""}}
         </td>`;

    const actionCell = isOpen
      ? `<td style="padding:7px 10px;white-space:nowrap;">
           <button onclick="openCCCloseModal(${{p.id}})"
             style="font-size:10px;padding:3px 10px;background:#1a2340;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:600;">
             Close ▾
           </button>
         </td>`
      : `<td style="padding:7px 10px;font-size:11px;color:#aaa;">${{p.closed_date || ""}}</td>`;

    return `<tr style="border-bottom:1px solid #f2f4f7;">
      <td style="padding:7px 10px;font-weight:700;">${{p.ticker}}</td>
      <td style="padding:7px 10px;">${{p.contracts}}×</td>
      <td style="padding:7px 10px;">$${{p.strike.toFixed(2)}}</td>
      <td style="padding:7px 10px;">${{p.expiry}} ${{isOpen ? dteTag(p.expiry) : ""}}</td>
      <td style="padding:7px 10px;">$${{p.premium_per_contract.toFixed(2)}}</td>
      <td style="padding:7px 10px;color:#555;">$${{gross.toFixed(2)}}</td>
      ${{netCell}}
      <td style="padding:7px 10px;">${{statusBadge(p)}}</td>
      <td style="padding:7px 10px;font-size:11px;color:#aaa;">${{p.opened_date}}</td>
      <td style="padding:7px 10px;font-size:11px;color:#aaa;">${{p.notes || ""}}</td>
      ${{actionCell}}
    </tr>`;
  }};

  const summaryHtml = `
    <div style="display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px;padding:12px 16px;background:#f8fafc;border-radius:8px;font-size:13px;">
      <span>Open: <b>${{open.length}}</b></span>
      <span>Open gross premium: <b style="color:#1a6e38;">$${{openGross.toFixed(2)}}</b></span>
      <span style="border-left:1px solid #dde;padding-left:16px;">Net realized income: <b style="color:#27ae60;">$${{netRealized.toFixed(2)}}</b></span>
      ${{buybackCost > 0 ? `<span style="color:#aaa;font-size:12px;">($${{grossRealized.toFixed(2)}} gross − $${{buybackCost.toFixed(2)}} buybacks)</span>` : ""}}
    </div>`;

  const th = s => `<th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">${{s}}</th>`;
  const thead = `<thead><tr style="background:#f4f6f9;">
    ${{th("Ticker")}}${{th("Contracts")}}${{th("Strike")}}${{th("Expiry/DTE")}}
    ${{th("Prem/Contract")}}${{th("Gross")}}
    <th style="padding:7px 10px;text-align:left;font-size:11px;color:#27ae60;text-transform:uppercase;">Net Realized</th>
    ${{th("Status")}}${{th("Opened")}}${{th("Notes")}}${{th("")}}
  </tr></thead>`;

  let html = summaryHtml + `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">${{thead}}<tbody>`;
  if (open.length) {{
    html += `<tr><td colspan="11" style="padding:5px 10px;font-size:11px;font-weight:700;color:#1a2340;background:#f0f7ff;">Open Positions</td></tr>`;
    html += open.map(makeRow).join("");
  }}
  if (closed.length) {{
    html += `<tr><td colspan="11" style="padding:5px 10px;font-size:11px;font-weight:700;color:#888;background:#f9f9f9;">Closed / Expired / Assigned</td></tr>`;
    html += closed.map(makeRow).join("");
  }}
  html += `</tbody></table></div>`;
  results.innerHTML = html;
}}

async function logCCPosition() {{
  const status = document.getElementById("cc-log-status");
  const body   = {{
    ticker:               (document.getElementById("cc-log-ticker").value || "").trim().toUpperCase(),
    contracts:            parseInt(document.getElementById("cc-log-contracts").value),
    strike:               parseFloat(document.getElementById("cc-log-strike").value),
    expiry:               document.getElementById("cc-log-expiry").value,
    premium_per_contract: parseFloat(document.getElementById("cc-log-premium").value),
    opened_date:          document.getElementById("cc-log-date").value,
    notes:                document.getElementById("cc-log-notes").value,
  }};
  if (!body.ticker || !body.contracts || !body.strike || !body.expiry ||
      !body.premium_per_contract || !body.opened_date) {{
    status.textContent = "⚠ Fill in all required fields.";
    return;
  }}
  status.textContent = "Saving…";
  try {{
    const res  = await fetch("/api/cc-positions", {{
      method: "POST", headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    status.textContent = "✓ Logged!";
    setTimeout(() => {{ status.textContent = ""; }}, 2000);
    loadCCPositions();
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
}}

// ── CC Close Modal ────────────────────────────────────────────────────────
function openCCCloseModal(id) {{
  _ccCloseTargetId = id;
  _ccCloseType     = null;
  const p = _allCCPositions.find(x => x.id === id);
  if (!p) return;

  const gross = (p.premium_per_contract * p.contracts * 100).toFixed(2);
  document.getElementById("cc-close-summary").innerHTML =
    `<b style="font-size:15px;">${{p.ticker}}</b>
     <span style="color:#888;margin:0 8px;">·</span>
     ${{p.contracts}}× ${{p.strike.toFixed(2)}} call
     <span style="color:#888;margin:0 8px;">·</span>
     exp ${{p.expiry}}
     <span style="color:#888;margin:0 8px;">·</span>
     sold @ <b>$${{p.premium_per_contract.toFixed(2)}}</b>/contract
     <span style="color:#888;margin:0 8px;">·</span>
     gross <b style="color:#1a6e38;">$${{gross}}</b>`;

  document.getElementById("cc-close-date").value  = new Date().toISOString().slice(0,10);
  document.getElementById("cc-close-price").value = "";
  document.getElementById("cc-close-status").textContent = "";
  document.getElementById("cc-close-preview").style.display   = "none";
  document.getElementById("cc-buyback-row").style.display     = "none";
  document.getElementById("cc-assign-sell-row").style.display = "none";

  // Reset type button styles
  ["expired","buyback","assigned"].forEach(t => {{
    const el = document.getElementById("cc-type-" + t);
    el.style.borderColor = "#dde";
    el.style.background  = "#fff";
    el.style.color       = "#333";
  }});

  document.getElementById("cc-close-overlay").style.display = "flex";
}}

function closeCCModal(e) {{
  if (!e || e.target === document.getElementById("cc-close-overlay"))
    document.getElementById("cc-close-overlay").style.display = "none";
}}

function setCCCloseType(type) {{
  _ccCloseType = type;
  ["expired","buyback","assigned"].forEach(t => {{
    const el = document.getElementById("cc-type-" + t);
    const active = t === type;
    el.style.borderColor = active ? "#1a2340" : "#dde";
    el.style.background  = active ? "#1a2340" : "#fff";
    el.style.color       = active ? "#fff"    : "#333";
  }});
  document.getElementById("cc-buyback-row").style.display    = type === "buyback"  ? "block" : "none";
  const assignRow = document.getElementById("cc-assign-sell-row");
  if (assignRow) {{
    assignRow.style.display = type === "assigned" ? "block" : "none";
    if (type === "assigned") {{
      const p = _allCCPositions.find(x => x.id === _ccCloseTargetId);
      if (p) {{
        const shares = p.contracts * 100;
        const desc   = document.getElementById("cc-assign-sell-desc");
        if (desc) desc.textContent =
          `${{shares}} shares of ${{p.ticker}} will be sold at the ${{p.strike.toFixed(2)}} strike. ` +
          `The capital gain or loss on those shares (vs. your cost basis) goes in the ST/LT section above. ` +
          `The option premium (${{_fmtGain(p.net_premium ?? p.premium_per_contract * p.contracts * 100)}}) is tracked separately as CC income.`;
      }}
    }}
  }}
  _updateCCClosePreview();
}}

function _updateCCClosePreview() {{
  const p = _allCCPositions.find(x => x.id === _ccCloseTargetId);
  if (!p || !_ccCloseType) return;
  const buyback = _ccCloseType === "buyback"
    ? (parseFloat(document.getElementById("cc-close-price").value) || 0) : 0;
  const net   = (p.premium_per_contract - buyback) * p.contracts * 100;
  const gross = p.premium_per_contract * p.contracts * 100;
  const preview = document.getElementById("cc-close-preview");
  preview.style.display = "block";
  preview.style.background = net >= 0 ? "#f0fff4" : "#fff0f0";
  preview.style.borderColor = net >= 0 ? "#ade" : "#fcc";
  preview.innerHTML = `
    Net realized income: <b style="color:${{net>=0?"#27ae60":"#e74c3c"}};">${{net>=0?"+":""}}$${{Math.abs(net).toFixed(2)}}</b>
    ${{buyback > 0 ? `<span style="color:#888;font-size:11px;">($${{gross.toFixed(2)}} gross − $${{(buyback*p.contracts*100).toFixed(2)}} buyback)</span>` : ""}}
    <br><span style="font-size:11px;color:#888;">Always short-term ordinary income · taxed at your ST rate</span>`;
}}

document.getElementById("cc-close-price")?.addEventListener("input", _updateCCClosePreview);

async function confirmCCClose() {{
  if (!_ccCloseType) {{
    document.getElementById("cc-close-status").textContent = "⚠ Select how the position closed.";
    return;
  }}
  const closeDate  = document.getElementById("cc-close-date").value;
  const closePrice = _ccCloseType === "buyback"
    ? parseFloat(document.getElementById("cc-close-price").value) || 0 : 0;

  const statusMap = {{ expired: "expired", buyback: "closed", assigned: "assigned" }};
  const body = {{
    status:      statusMap[_ccCloseType],
    close_type:  _ccCloseType,
    closed_date: closeDate,
    closed_price: closePrice > 0 ? closePrice : null,
  }};

  document.getElementById("cc-close-status").textContent = "Saving…";
  try {{
    const res  = await fetch(`/api/cc-positions/${{_ccCloseTargetId}}`, {{
      method: "PATCH", headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!data.ok) {{
      document.getElementById("cc-close-status").textContent = "Error: " + data.error;
      return;
    }}

    // If assigned and user wants to record the stock sale in the FIFO tracker
    if (_ccCloseType === "assigned") {{
      const fifoCheck = document.getElementById("cc-assign-fifo-check");
      if (fifoCheck?.checked) {{
        const p = _allCCPositions.find(x => x.id === _ccCloseTargetId);
        if (p) {{
          document.getElementById("cc-close-status").textContent = "Recording stock sale…";
          try {{
            const sellRes = await fetch("/api/sells", {{
              method: "POST", headers: {{"Content-Type":"application/json"}},
              body: JSON.stringify({{
                ticker:     p.ticker,
                shares_sold: p.contracts * 100,
                sell_price: p.strike,
                sell_date:  closeDate,
              }}),
            }});
            const sellData = await sellRes.json();
            if (!sellData.ok) {{
              document.getElementById("cc-close-status").textContent =
                "CC closed. Stock sell error: " + sellData.error;
              await loadCCPositions();
              await loadAllSells();
              return;
            }}
          }} catch(e2) {{
            document.getElementById("cc-close-status").textContent = "CC closed. Sell error: " + e2.message;
            await loadCCPositions();
            await loadAllSells();
            return;
          }}
        }}
      }}
    }}

    document.getElementById("cc-close-overlay").style.display = "none";
    await loadCCPositions();
    await loadAllSells();
  }} catch(e) {{
    document.getElementById("cc-close-status").textContent = "Error: " + e.message;
  }}
}}

window.addEventListener("load", loadCCPositions);

// ── Layer Reassignment ────────────────────────────────────────────────────
const _LAYER_COLORS = {{
  1: "#4A90D9", 2: "#50C878", 3: "#F5A623", 4: "#E74C3C", 5: "#9B59B6"
}};
const _LAYER_LABELS = {{
  1: "L1 Structural Ballast",
  2: "L2 Cash-Flow Engines",
  3: "L3 Compounders",
  4: "L4 Convexity / Optionality",
  5: "L5 Shock Absorbers / Regime Hedges",
}};

let _layerChangeTicker  = null;
let _layerChangeFrom    = null;
let _layerChangeTo      = null;

function openLayerModal(ticker, currentLayerNum) {{
  _layerChangeTicker = ticker;
  _layerChangeFrom   = currentLayerNum;
  _layerChangeTo     = currentLayerNum;
  document.getElementById("layer-change-summary").innerHTML =
    `<b style="font-size:15px;">${{ticker}}</b>
     <span style="color:#888;margin:0 8px;">·</span>
     currently in <b style="color:${{_LAYER_COLORS[currentLayerNum]}};">${{_LAYER_LABELS[currentLayerNum]}}</b>`;
  document.getElementById("layer-change-status").textContent = "";
  pickLayer(currentLayerNum);
  document.getElementById("layer-change-overlay").style.display = "flex";
}}

function closeLayerModal(e) {{
  if (!e || e.target === document.getElementById("layer-change-overlay"))
    document.getElementById("layer-change-overlay").style.display = "none";
}}

function pickLayer(num) {{
  _layerChangeTo = num;
  for (let i = 1; i <= 5; i++) {{
    const btn = document.getElementById("lbtn-" + i);
    if (!btn) continue;
    const active = i === num;
    btn.style.borderColor = active ? _LAYER_COLORS[i] : "#dde";
    btn.style.background  = active ? _LAYER_COLORS[i] + "18" : "#fff";
    btn.style.fontWeight  = active ? "700" : "400";
  }}
}}

async function confirmLayerChange() {{
  if (_layerChangeTo === _layerChangeFrom) {{
    document.getElementById("layer-change-overlay").style.display = "none";
    return;
  }}
  const statusEl = document.getElementById("layer-change-status");
  statusEl.textContent = "Saving and rewriting history…";
  try {{
    const res  = await fetch(`/api/holdings/${{_layerChangeTicker}}`, {{
      method: "PATCH",
      headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify({{ layer_num: _layerChangeTo }}),
    }});
    const data = await res.json();
    if (!data.ok) {{
      statusEl.textContent = "Error: " + data.error;
      return;
    }}
    statusEl.textContent = "Done — reloading…";
    window.location.reload();
  }} catch(e) {{
    statusEl.textContent = "Error: " + e.message;
  }}
}}

// ── Covered Call Analyzer ─────────────────────────────────────────────────
async function analyzeCoveredCall() {{
  const ticker = document.getElementById("cc-ticker").value;
  if (!ticker) return;
  const status  = document.getElementById("cc-status");
  const results = document.getElementById("cc-results");
  const btn     = document.getElementById("cc-btn");

  btn.disabled  = true;
  btn.textContent = "Fetching…";
  status.textContent = "";
  results.innerHTML  = "";

  try {{
    const res  = await fetch(`/api/covered-calls?ticker=${{ticker}}`);
    const data = await res.json();

    if (!data.ok) {{
      status.textContent = "⚠ " + (data.error || "No results.");
    }} else {{
      results.innerHTML = renderCC(data);
    }}
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }} finally {{
    btn.disabled = false;
    btn.textContent = "Get Recommendations";
  }}
}}

function renderCC(d) {{
  const fmt  = v => "$" + v.toFixed(2);
  const pct  = v => v.toFixed(1) + "%";

  const gainColor = d.gain_pct >= 0 ? "#27ae60" : "#e74c3c";
  const floorNote = d.already_at_target
    ? `Already up ${{pct(d.gain_pct)}} — floor = current × 1.10`
    : `Up ${{pct(d.gain_pct)}} from cost — floor = cost × 1.10`;
  const w52Color = d.current_price >= d.week52_high * 0.95 ? "#c8102e"
                 : d.current_price >= d.week52_high * 0.80 ? "#e67e22"
                 : "#555";

  const meta = `
    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:14px;font-size:13px;">
      <span>Current <b>${{fmt(d.current_price)}}</b></span>
      <span>Avg Cost/Share <b>${{fmt(d.avg_cost)}}</b></span>
      <span>Gain <b style="color:${{gainColor}}">${{d.gain_pct >= 0 ? "+" : ""}}${{pct(d.gain_pct)}}</b></span>
      <span>52w High <b style="color:${{w52Color}}">${{fmt(d.week52_high)}}</b> <span style="color:#aaa;font-size:11px;">${{d.week52_high_dt}}</span></span>
      <span>Min Strike <b>${{fmt(d.strike_floor)}}</b> <span style="color:#888;font-size:11px;">(${{floorNote}})</span></span>
    </div>`;

  if (!d.recs || d.recs.length === 0) {{
    return meta + `<p style="color:#888;font-size:13px;">No qualifying contracts found.</p>`;
  }}

  const rows = d.recs.map((r, i) => {{
    const rowBg   = r.has_avoid   ? "background:#fff5f5;"
                  : r.has_caution ? "background:#fffbf0;"
                  : i === 0       ? "background:#f0f7ff;"
                  : "";
    const plColor = r.profit_if_called >= 10 ? "#27ae60" : "#e67e22";

    // Blackout badge
    let blackout = "";
    if (r.has_avoid) {{
      blackout = `<div style="margin-top:4px;font-size:10px;font-weight:700;color:#c8102e;">📵 AVOID</div>`;
    }} else if (r.has_caution) {{
      blackout = `<div style="margin-top:4px;font-size:10px;font-weight:700;color:#e67e22;">⚠️ CAUTION</div>`;
    }}

    // Risk event detail lines
    const riskLines = (r.risk_events || []).map(e => {{
      const color = e.severity === "avoid" ? "#c8102e" : "#e67e22";
      const icon  = e.severity === "avoid" ? "📵" : "⚠️";
      return `<div style="font-size:10px;color:${{color}};margin-top:2px;">${{icon}} ${{e.label.replace(/^[📵⚠️\\s]+/, "")}}</div>`;
    }}).join("");

    return `<tr style="${{rowBg}}border-bottom:1px solid #f2f4f7;">
      <td style="padding:8px 10px;">
        <span style="font-weight:${{i===0?"700":"400"}}">${{r.expiration}}</span>
        ${{blackout}}
        ${{riskLines}}
      </td>
      <td style="padding:8px 10px;">${{fmt(r.strike)}}</td>
      <td style="padding:8px 10px;color:#7f8c8d;">${{r.dte}}d</td>
      <td style="padding:8px 10px;">${{fmt(r.bid)}}</td>
      <td style="padding:8px 10px;">${{fmt(r.ask)}}</td>
      <td style="padding:8px 10px;font-weight:600;">${{fmt(r.mid)}}</td>
      <td style="padding:8px 10px;">${{pct(r.premium_pct)}}</td>
      <td style="padding:8px 10px;font-weight:700;color:#1a2340;">${{pct(r.annualized_ret)}}</td>
      <td style="padding:8px 10px;font-weight:700;color:${{plColor}};">+${{pct(r.profit_if_called)}}</td>
      <td style="padding:8px 10px;font-weight:600;color:${{!r.delta ? '#aaa' : r.delta < 0.2 ? '#27ae60' : r.delta < 0.35 ? '#e67e22' : '#e74c3c'}};">${{r.delta ? (r.delta * 100).toFixed(1) + '%' : '—'}}</td>
      <td style="padding:8px 10px;color:#aaa;font-size:11px;">${{r.open_interest ?? "—"}}</td>
    </tr>`;
  }}).join("");

  return meta + `
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f4f6f9;">
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Expiry</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Strike</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">DTE</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Bid</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Ask</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Mid</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Prem%</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Ann%</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">P/L if Called</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Prob Called</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">OI</th>
      </tr></thead>
      <tbody>${{rows}}</tbody>
    </table>
    </div>
    <p style="font-size:11px;color:#aaa;margin-top:8px;">Top ${{d.recs.length}} contracts by annualized return. Highlighted row = best pick.</p>`;
}}
</script>
</body>
</html>
"""
    return html


def main():
    portfolio, layers, holdings = load_data()
    html = build_dashboard(portfolio, layers, holdings)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written to: {OUT_PATH}")


if __name__ == "__main__":
    main()
