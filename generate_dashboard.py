#!/usr/bin/env python3
"""Generate a self-contained HTML investment dashboard from investment.db."""

import csv
import json
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

    # Cumulative return from first day
    base = portfolio[0]["total_value"] if portfolio else 1
    port_cum = [((v / base) - 1) * 100 for v in port_values]

    # SPY cumulative (sum of daily %, approximate)
    spy_cum = []
    running = 0.0
    for r in portfolio:
        running += r["spy_change_pct"]
        spy_cum.append(round(running, 4))

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
            holdings_rows += f'<tr class="layer-header"><td colspan="10" style="background:{lcolor}22;border-left:4px solid {lcolor};padding:6px 10px;font-weight:600;color:#333">{h["layer"]}</td></tr>\n'
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
    .kpi-row {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }}
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
  </div>

  <!-- Discipline anchor -->
  <div class="anchor-bar">
    <div class="anchor-dot"></div>
    <span>Discipline anchor: today's portfolio behavior was <b style="color:{anchor_color}">{anchor}</b> with no judgment violations requiring action.</span>
  </div>

  {flags_html}

  <!-- Main charts row -->
  <div class="three-col">
    <div class="card">
      <h2>Portfolio vs SPY — Cumulative Return</h2>
      <canvas id="cumChart"></canvas>
    </div>
    <div class="card">
      <h2>Allocation by Layer</h2>
      <canvas id="pieChart"></canvas>
    </div>
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
    <table>
      <thead><tr><th>Ticker</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Total Gain</th><th>Daily Δ</th><th>Weight</th><th>Next Earnings</th><th>Tax Lots</th></tr></thead>
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
        <div style="font-size:11px;color:#aaa;margin-top:2px;">Taxed as ordinary income</div>
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
    <h2 style="display:flex;align-items:center;justify-content:space-between;">
      Buffett Screener — NYSE Winners
      <button onclick="loadBuffett()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:500;">↻ Refresh</button>
    </h2>
    <div id="buffett-meta" style="font-size:12px;color:#7f8c8d;margin-bottom:10px;">Loading…</div>
    <div id="buffett-results"></div>
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
new Chart(document.getElementById("pieChart"), {{
  type: "doughnut",
  data: {{
    labels: D.pieLabels,
    datasets: [{{ data: D.pieValues, backgroundColor: D.pieColors, borderWidth: 2, borderColor: "#fff" }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: "bottom", labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{ctx.parsed.toLocaleString("en-US", {{style:"currency", currency:"USD", maximumFractionDigits:0}})}}` }} }}
    }}
  }}
}});

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
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

function onTaxBracketChange(sel) {{
  CURRENT_BRACKET = TAX_BRACKETS[sel.value];
  renderDividendTable();
  // Redraw chart with new after-tax line
  if (typeof loadDividendTimeline === "function") loadDividendTimeline();
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

  const totalGain = sells.reduce((s, x) => s + (x.realized_gain || 0), 0);
  const stGain    = sells.reduce((s, x) => s + (x.st_gain || 0), 0);
  const ltGain    = sells.reduce((s, x) => s + (x.lt_gain || 0), 0);

  const stTax  = Math.max(0, stGain) * (stRate + niit);
  const ltTax  = Math.max(0, ltGain) * (ltRate + niit);
  const totTax = stTax + ltTax;

  // KPI updates
  const totalEl = document.getElementById("gains-total");
  if (totalEl) {{
    totalEl.textContent  = sells.length ? _fmtGain(totalGain) : "—";
    totalEl.style.color  = sells.length ? _gainColor(totalGain) : "#1a2340";
  }}
  const stEl = document.getElementById("gains-st");
  if (stEl) {{
    stEl.textContent = sells.length ? _fmtGain(stGain) : "—";
    stEl.style.color = sells.length ? (stGain >= 0 ? "#c0392b" : "#27ae60") : "#e74c3c";
  }}
  const ltEl = document.getElementById("gains-lt");
  if (ltEl) {{
    ltEl.textContent = sells.length ? _fmtGain(ltGain) : "—";
    ltEl.style.color = sells.length ? (ltGain >= 0 ? "#27ae60" : "#e74c3c") : "#27ae60";
  }}
  const countEl = document.getElementById("gains-txn-count");
  if (countEl) countEl.textContent = sells.length ? `${{sells.length}} transaction${{sells.length!==1?"s":""}}` : "";

  const fmt2 = v => "$" + v.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}});
  const estStEl = document.getElementById("tax-est-st");
  if (estStEl) {{ estStEl.textContent = sells.length ? fmt2(stTax)  : "—"; estStEl.style.color = stTax  > 0 ? "#c0392b" : "#888"; }}
  const estLtEl = document.getElementById("tax-est-lt");
  if (estLtEl) {{ estLtEl.textContent = sells.length ? fmt2(ltTax)  : "—"; estLtEl.style.color = ltTax  > 0 ? "#c0392b" : "#888"; }}
  const estTotEl = document.getElementById("tax-est-total");
  if (estTotEl) {{ estTotEl.textContent = sells.length ? fmt2(totTax) : "—"; estTotEl.style.color = totTax > 0 ? "#c0392b" : "#888"; }}

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
async function loadBuffett() {{
  const metaEl   = document.getElementById("buffett-meta");
  const resultsEl = document.getElementById("buffett-results");
  metaEl.textContent = "Loading…";
  resultsEl.innerHTML = "";

  try {{
    const res  = await fetch("/api/buffett-winners");
    const data = await res.json();
    if (!data.ok) {{ metaEl.textContent = "Error loading screener data."; return; }}

    const m       = data.meta || {{}};
    const cached  = data.cache_count || 0;
    const running = data.scan_running;
    const partial = parseInt(m.winners_found || "0");

    if (!m.last_scan) {{
      if (cached === 0) {{
        // Never started
        metaEl.innerHTML = `<span style="color:#aaa;">No scan results yet — screener runs nightly at 2 AM ET.</span>`;
        return;
      }} else if (running) {{
        // Actively scanning
        const eta = data.eta_seconds;
        let etaStr = "";
        if (eta != null && eta > 0) {{
          const h = Math.floor(eta / 3600);
          const m = Math.floor((eta % 3600) / 60);
          const s = eta % 60;
          if (h > 0)      etaStr = ` &nbsp;·&nbsp; ETA ~${{h}}h ${{m}}m`;
          else if (m > 0) etaStr = ` &nbsp;·&nbsp; ETA ~${{m}}m ${{s}}s`;
          else            etaStr = ` &nbsp;·&nbsp; ETA ~${{s}}s`;
        }}
        metaEl.innerHTML = `⏳ Scan in progress — <b>${{cached.toLocaleString()}}</b> tickers scanned, <b>${{partial}}</b> winners so far${{etaStr}}. Full results appear when complete.`;
        // Still show partial winners below if any exist
        if (!data.winners.length) return;
      }} else {{
        // Crashed / killed before finishing
        metaEl.innerHTML = `
          <div style="background:#fff5f0;border-left:3px solid #e74c3c;padding:8px 12px;border-radius:4px;margin-bottom:8px;font-size:12px;">
            ⚠️ <b>Incomplete scan</b> — the last run stopped at <b>${{cached.toLocaleString()}}</b> of ~2,348 tickers before finishing.
            The ${{partial}} winner${{partial !== 1 ? "s" : ""}} below reflect only what was scanned.
            Next automatic scan runs at 2 AM ET, or click <b>↻ Refresh</b> after restarting the screener manually.
          </div>`;
        if (!data.winners.length) return;
      }}
    }}

    const inProgressNote = running
      ? ` &nbsp;<span style="color:#e67e22;font-size:11px;">⏳ new scan in progress (${{cached.toLocaleString()}} done)</span>`
      : "";
    metaEl.innerHTML = `
      Last completed scan: <b>${{m.last_scan}}</b> &nbsp;·&nbsp;
      Tickers scanned: <b>${{m.tickers_scanned || "—"}}</b> &nbsp;·&nbsp;
      Winners: <b style="color:#27ae60;">${{m.winners_found || data.winners.length}}</b>
      ${{inProgressNote}}
      <span style="color:#aaa;font-size:11px;display:block;margin-top:3px;">(Gross ≥40% · SG&A ≤30% · Net Income ≥20% · Interest ≤15% · CapEx ≤50% · Cash&gt;Debt)</span>`;

    if (!data.winners.length) {{
      resultsEl.innerHTML = `<p style="color:#888;font-size:13px;">No winners found in the last scan.</p>`;
      return;
    }}

    const rows = data.winners.map(w => {{
      const yf       = `https://finance.yahoo.com/quote/${{w.ticker}}`;
      const cnbc     = `https://www.cnbc.com/quotes/${{w.ticker.replace("-",".")}}`;
      const mw       = `https://www.marketwatch.com/investing/stock/${{w.ticker.replace("-",".").toLowerCase()}}`;
      const linkStyle = `font-size:10px;padding:1px 5px;border-radius:3px;border:1px solid #dde;color:#555;text-decoration:none;white-space:nowrap;`;
      const fmtVal   = v => v != null && v !== 0 ? v.toFixed(1) + "x" : "—";
      const firstSeen = w.first_seen
        ? `<div style="font-size:10px;color:#aaa;margin-top:2px;">since ${{w.first_seen}}</div>` : "";
      return `
      <tr style="border-bottom:1px solid #f2f4f7;">
        <td style="padding:8px 10px;">
          <div style="font-weight:700;color:#1a2340;margin-bottom:2px;">${{w.ticker}}</div>
          ${{firstSeen}}
          <div style="display:flex;gap:4px;margin-top:3px;">
            <a href="${{yf}}" target="_blank" rel="noopener" style="${{linkStyle}}background:#f0f7ff;">YF</a>
            <a href="${{cnbc}}" target="_blank" rel="noopener" style="${{linkStyle}}background:#fff8f0;">CNBC</a>
            <a href="${{mw}}" target="_blank" rel="noopener" style="${{linkStyle}}background:#f0fff4;">MW</a>
          </div>
        </td>
        <td style="padding:8px 10px;color:#555;">${{w.company || "—"}}</td>
        <td style="padding:8px 10px;">${{w.price ? "$" + w.price.toFixed(2) : "—"}}</td>
        <td style="padding:8px 10px;font-weight:600;color:#27ae60;">${{w.gross_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;">${{w.sga_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;font-weight:600;color:#27ae60;">${{w.net_income_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;">${{w.interest_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;">${{w.capex_margin?.toFixed(1)}}%</td>
        <td style="padding:8px 10px;color:#27ae60;font-weight:600;">${{w.cash_gt_debt}}</td>
        <td style="padding:8px 10px;color:#555;">${{w.pe_ratio != null ? w.pe_ratio.toFixed(1) + "x" : "—"}}</td>
        <td style="padding:8px 10px;color:#555;">${{fmtVal(w.p_fcf)}}</td>
        <td style="padding:8px 10px;color:#555;">${{fmtVal(w.ev_ebitda)}}</td>
      </tr>`;
    }}).join("");

    resultsEl.innerHTML = `
      <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#f4f6f9;">
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Ticker</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Company</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Price</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#27ae60;text-transform:uppercase;">Gross %</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">SG&amp;A %</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#27ae60;text-transform:uppercase;">Net Inc %</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Interest %</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">CapEx %</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#27ae60;text-transform:uppercase;">Cash&gt;Debt</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#2980b9;text-transform:uppercase;">P/E</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#2980b9;text-transform:uppercase;">P/FCF</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#2980b9;text-transform:uppercase;">EV/EBITDA</th>
        </tr></thead>
        <tbody>${{rows}}</tbody>
      </table>
      </div>
      <p style="font-size:11px;color:#aaa;margin-top:8px;">
        Sorted by Gross Margin. Quality criteria: Gross ≥40% · SG&amp;A ≤30% · Net Income ≥20% · Interest ≤15% · CapEx ≤50% · Cash&gt;Debt.
        Valuation: P/E = trailing; P/FCF = market cap / free cash flow; EV/EBITDA from yfinance.
        <span style="color:#2980b9;">Blue columns</span> = valuation (populated on next nightly scan).
      </p>`;
  }} catch(e) {{
    metaEl.textContent = "Error: " + e.message;
  }}
}}

window.addEventListener("load", loadBuffett);

// ── CC Position Tracker ───────────────────────────────────────────────────
async function loadCCPositions() {{
  const status  = document.getElementById("cc-tracker-status");
  const results = document.getElementById("cc-tracker-results");
  status.textContent = "Loading…";
  results.innerHTML  = "";

  try {{
    const res  = await fetch("/api/cc-positions");
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}

    const positions = data.positions || [];
    status.textContent = "";

    if (!positions.length) {{
      results.innerHTML = `<p style="color:#888;font-size:13px;margin-top:8px;">No positions logged yet. Use the form above to add your first covered call.</p>`;
      return;
    }}

    const today       = new Date().toISOString().slice(0,10);
    const open        = positions.filter(p => p.status === "open");
    const closed      = positions.filter(p => p.status !== "open");
    const totalPremium = positions.reduce((s,p) => s + p.premium_per_contract * p.contracts * 100, 0);
    const openPremium  = open.reduce((s,p) => s + p.premium_per_contract * p.contracts * 100, 0);

    function statusBadge(p) {{
      const colors = {{open:"#e8f8ee;color:#1a6e38;border-color:#a8e0b8", closed:"#f4f6f9;color:#888;border-color:#dde",
                       expired:"#fff8e1;color:#8a6d00;border-color:#ffe082", assigned:"#fff0f0;color:#c8102e;border-color:#fcc"}};
      const c = colors[p.status] || colors["closed"];
      return `<span style="background:${{c}};border:1px solid;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;">${{p.status.toUpperCase()}}</span>`;
    }}

    function dteTag(expiry) {{
      const d = Math.round((new Date(expiry + "T00:00:00") - new Date()) / 86400000);
      if (d < 0) return `<span style="color:#aaa;font-size:11px;">(expired)</span>`;
      const c = d <= 7 ? "#c8102e" : d <= 21 ? "#e67e22" : "#27ae60";
      return `<span style="color:${{c}};font-size:11px;">${{d}}d</span>`;
    }}

    const makeRow = p => {{
      const total = (p.premium_per_contract * p.contracts * 100).toFixed(2);
      const closeBtn = p.status === "open"
        ? `<button onclick="closeCC(${{p.id}})" style="font-size:10px;padding:2px 8px;background:#f4f6f9;border:1px solid #dde;border-radius:4px;cursor:pointer;">Close</button>`
        : "";
      return `<tr style="border-bottom:1px solid #f2f4f7;">
        <td style="padding:7px 10px;font-weight:700;">${{p.ticker}}</td>
        <td style="padding:7px 10px;">${{p.contracts}}x</td>
        <td style="padding:7px 10px;">$${{p.strike.toFixed(2)}}</td>
        <td style="padding:7px 10px;">${{p.expiry}} ${{p.status==="open" ? dteTag(p.expiry) : ""}}</td>
        <td style="padding:7px 10px;">$${{p.premium_per_contract.toFixed(2)}}</td>
        <td style="padding:7px 10px;font-weight:600;color:#27ae60;">$${{total}}</td>
        <td style="padding:7px 10px;">${{statusBadge(p)}}</td>
        <td style="padding:7px 10px;">${{p.opened_date}}</td>
        <td style="padding:7px 10px;color:#aaa;font-size:11px;">${{p.notes || ""}}</td>
        <td style="padding:7px 10px;">${{closeBtn}}</td>
      </tr>`;
    }};

    const summaryHtml = `
      <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px;padding:12px 16px;background:#f8fafc;border-radius:8px;font-size:13px;">
        <span>Open positions: <b>${{open.length}}</b></span>
        <span>Open premium held: <b style="color:#27ae60;">$${{openPremium.toFixed(2)}}</b></span>
        <span>All-time premium collected: <b style="color:#1a2340;">$${{totalPremium.toFixed(2)}}</b></span>
      </div>`;

    const thead = `<thead><tr style="background:#f4f6f9;">
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Ticker</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Contracts</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Strike</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Expiry / DTE</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Prem/Contract</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#27ae60;text-transform:uppercase;">Total Premium</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Status</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Opened</th>
      <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Notes</th>
      <th></th>
    </tr></thead>`;

    let tableHtml = summaryHtml + `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">${{thead}}<tbody>`;
    if (open.length) {{
      tableHtml += `<tr><td colspan="10" style="padding:5px 10px;font-size:11px;font-weight:700;color:#1a2340;background:#f0f7ff;">Open Positions</td></tr>`;
      tableHtml += open.map(makeRow).join("");
    }}
    if (closed.length) {{
      tableHtml += `<tr><td colspan="10" style="padding:5px 10px;font-size:11px;font-weight:700;color:#888;background:#f9f9f9;">Closed / Expired / Assigned</td></tr>`;
      tableHtml += closed.map(makeRow).join("");
    }}
    tableHtml += `</tbody></table></div>`;
    results.innerHTML = tableHtml;
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

async function logCCPosition() {{
  const status = document.getElementById("cc-log-status");
  const body   = {{
    ticker:               (document.getElementById("cc-log-ticker").value   || "").trim().toUpperCase(),
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
      method:  "POST",
      headers: {{"Content-Type":"application/json"}},
      body:    JSON.stringify(body),
    }});
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    status.textContent = "✓ Logged!";
    setTimeout(() => {{ status.textContent = ""; }}, 2000);
    loadCCPositions();
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

async function closeCC(id) {{
  const closedDate  = new Date().toISOString().slice(0,10);
  const closedPrice = prompt("Closing price / buy-back cost per contract ($):");
  if (closedPrice === null) return;
  try {{
    await fetch(`/api/cc-positions/${{id}}`, {{
      method:  "PATCH",
      headers: {{"Content-Type":"application/json"}},
      body:    JSON.stringify({{
        status:      "closed",
        closed_date: closedDate,
        closed_price: parseFloat(closedPrice) || null,
      }}),
    }});
    loadCCPositions();
  }} catch(e) {{
    alert("Error: " + e.message);
  }}
}}

window.addEventListener("load", loadCCPositions);

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
