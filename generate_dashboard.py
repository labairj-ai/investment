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
            ticker = normalize_ticker(row["Stock"])
            layer_num = int(str(row["Layer"]).strip())
            layer_label = f"Layer {layer_num}: {LAYER_NAMES[layer_num]}"
            result[ticker] = {
                "shares":   float(row["Shares"]),
                "avg_cost": float(row["AvgCost"]),
                "layer":    layer_label,
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
            holdings_rows += f'<tr class="layer-header"><td colspan="9" style="background:{lcolor}22;border-left:4px solid {lcolor};padding:6px 10px;font-weight:600;color:#333">{h["layer"]}</td></tr>\n'
            prev_layer = h["layer"]
        daily_class = "pos" if h["change_pct"] >= 0 else "neg"
        gain_class  = "pos" if h["total_gain_pct"] >= 0 else "neg"
        holdings_rows += f"""<tr>
          <td>{h["ticker"]}</td>
          <td>{h["shares"]:,.2f}</td>
          <td>${h["avg_cost"]:,.2f}</td>
          <td>${h["price"]:,.2f}</td>
          <td>{money(h["value"])}</td>
          <td class="{gain_class}" style="font-weight:600;">{pct(h["total_gain_pct"])}</td>
          <td class="{daily_class}">{pct(h["change_pct"])}</td>
          <td>{h["weight_pct"]:.1f}%</td>
          <td id="earn-{h["ticker"]}" style="font-size:12px;color:#7f8c8d;">—</td>
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

<header>
  <div>
    <h1>Investment Dashboard</h1>
    <div class="subtitle">{today_date} &nbsp;·&nbsp; {len(today_holdings)} holdings across 5 layers</div>
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
      <thead><tr><th>Ticker</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Total Gain</th><th>Daily Δ</th><th>Weight</th><th>Next Earnings</th></tr></thead>
      <tbody>{holdings_rows}</tbody>
    </table>
  </div>

  <!-- Dividends -->
  <div class="card" id="div-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;">
      Upcoming Dividends
      <button onclick="loadDividends()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:500;">↻ Refresh</button>
    </h2>
    <div id="div-status" style="font-size:12px;color:#7f8c8d;">Loading…</div>
    <div id="div-results"></div>
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
async function loadDividends() {{
  const status  = document.getElementById("div-status");
  const results = document.getElementById("div-results");
  status.textContent = "Loading dividend data…";
  results.innerHTML  = "";

  try {{
    const res  = await fetch("/api/dividends");
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}

    // ── populate annual dividend KPI card ────────────────────────────────
    const totalAnnual = data.results.reduce((s, r) => s + (r.annual_income || 0), 0);
    const totalPort   = {total_v};
    document.getElementById("kpi-div-value").textContent =
      "$" + Math.round(totalAnnual).toLocaleString("en-US");
    document.getElementById("kpi-div-yield").textContent =
      totalPort > 0 ? (totalAnnual / totalPort * 100).toFixed(2) + "% portfolio yield" : "";

    status.textContent = "";
    const rows = data.results.map(r => {{
      const badge = r.declared
        ? `<span style="background:#e8f8ee;color:#1a6e38;border:1px solid #a8e0b8;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;">UPCOMING</span>`
        : `<span style="background:#f4f6f9;color:#888;border:1px solid #dde;border-radius:4px;padding:1px 7px;font-size:10px;">LAST KNOWN</span>`;
      const exDiv  = r.ex_div_date || "—";
      const payDay = r.pay_date    || "—";
      const amount = r.declared_amount ? "$" + r.declared_amount.toFixed(4) : "—";
      const total  = r.total_payout  ? "$" + r.total_payout.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}) : "—";
      const income = r.annual_income ? "$" + r.annual_income.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}) : "—";
      const yld    = r.div_yield     ? r.div_yield.toFixed(2) + "%" : "—";
      const yoc    = r.yield_on_cost ? r.yield_on_cost.toFixed(2) + "%" : "—";
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
        <td style="padding:8px 10px;">${{yld}}</td>
        <td style="padding:8px 10px;color:#888;">${{yoc}}</td>
      </tr>`;
    }}).join("");

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
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Yield</th>
          <th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">Yield on Cost</th>
        </tr></thead>
        <tbody>${{rows}}</tbody>
      </table>
      </div>
      <p style="font-size:11px;color:#aaa;margin-top:8px;">As of ${{data.as_of}}. DECLARED = upcoming announced date. LAST PAID = most recent; next date not yet announced.</p>`;
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }}
}}

// Auto-load dividends on page open
window.addEventListener("load", loadDividends);

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

  const meta = `
    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:14px;font-size:13px;">
      <span>Current <b>${{fmt(d.current_price)}}</b></span>
      <span>Cost basis <b>${{fmt(d.avg_cost)}}</b></span>
      <span>Gain <b style="color:${{gainColor}}">${{d.gain_pct >= 0 ? "+" : ""}}${{pct(d.gain_pct)}}</b></span>
      <span>Min strike <b>${{fmt(d.strike_floor)}}</b> <span style="color:#888;font-size:11px;">(${{floorNote}})</span></span>
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
      return `<div style="font-size:10px;color:${{color}};margin-top:2px;">${{icon}} ${{e.label.replace(/^[📵⚠️\s]+/, "")}}</div>`;
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
