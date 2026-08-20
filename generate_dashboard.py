#!/usr/bin/env python3
"""Generate a self-contained HTML investment dashboard from investment.db."""

import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"
OUT_PATH = PROJECT_DIR / "out" / "dashboard.html"
TZ = ZoneInfo("America/New_York")

LAYER_NAMES = {
    1: "L1 Structural Ballast",
    2: "L2 Cash-Flow Engines",
    3: "L3 Compounders",
    4: "L4 Convexity",
    5: "L5 Shock Absorbers",
}
# Canonical DB label for each layer number
LAYER_LABELS = {n: f"Layer {n}: {name}" for n, name in LAYER_NAMES.items()}

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
    "Layer 1: L1 Structural Ballast": "#4A90D9",
    "Layer 2: L2 Cash-Flow Engines":  "#50C878",
    "Layer 3: L3 Compounders":        "#F5A623",
    "Layer 4: L4 Convexity":          "#E74C3C",
    "Layer 5: L5 Shock Absorbers":    "#9B59B6",
}
LAYER_SHORT = {
    "Layer 1: L1 Structural Ballast": "L1 Structural Ballast",
    "Layer 2: L2 Cash-Flow Engines":  "L2 Cash-Flow Engines",
    "Layer 3: L3 Compounders":        "L3 Compounders",
    "Layer 4: L4 Convexity":          "L4 Convexity",
    "Layer 5: L5 Shock Absorbers":    "L5 Shock Absorbers",
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
    # ticker -> pre-computed change from DB (uses fast_info.previous_close, so 1-day accurate)
    db_changes = {h["ticker"]: (h["change_dollars"], h["change_pct"])
                  for h in db_holdings if h["day"] == today_date}

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

    total_value = sum(h["value"] for h in rebuilt)

    for h in rebuilt:
        # Daily change — use stored values (computed with fast_info.previous_close)
        stored = db_changes.get(h["ticker"])
        if stored and stored[0] is not None:
            h["change_dollars"] = stored[0]
            h["change_pct"]     = stored[1] or 0.0
        else:
            h["change_dollars"] = 0.0
            h["change_pct"] = 0.0

        # Total gain vs cost basis
        cost_basis = h["cost_basis"]
        h["total_gain_dollars"] = h["value"] - cost_basis
        h["total_gain_pct"] = ((h["value"] - cost_basis) / cost_basis * 100.0) if cost_basis else 0.0

        h["weight_pct"] = (h["value"] / total_value * 100.0) if total_value else 0.0

    # Rebuild layers by summing per-holding changes
    layer_map: dict[str, dict] = {}
    for h in rebuilt:
        ln = h["layer"]
        if ln not in layer_map:
            layer_map[ln] = {"layer": ln, "value": 0.0, "change_dollars": 0.0}
        layer_map[ln]["value"]         += h["value"]
        layer_map[ln]["change_dollars"] += h["change_dollars"]

    layers = []
    for ln, data in layer_map.items():
        chg = data["change_dollars"]
        pv  = data["value"] - chg
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
    #
    # Two-threshold strategy handles corrupted historical rows where the newsletter
    # fetched pre-market prices and stored near-zero total_change_dollars even
    # though total_value actually moved (the real 1-day market return):
    #   • Reliable _pchg (explains ≥10% of actual delta): original $1k / 0.5% threshold.
    #   • Unreliable _pchg (<10%): raise threshold to $10k / 5% so normal market
    #     moves (~1-3%) are not mistaken for cash flows, but large injections still are.
    port_cum    = [0.0]
    _twr_factor = 1.0
    _sub_start  = portfolio[0]["total_value"] if portfolio else 1.0
    for _i in range(1, len(portfolio)):
        _prev = portfolio[_i - 1]["total_value"]
        _curr = portfolio[_i]["total_value"]
        _pchg = portfolio[_i].get("total_change_dollars", 0) or 0
        actual_delta = _curr - _prev
        # Skip weekend/holiday duplicates where the newsletter repeats the same row
        if abs(actual_delta) > 1.0:
            _val_ex_cf    = _prev + _pchg
            _cf           = _curr - _val_ex_cf
            _pchg_reliable = _pchg != 0 and abs(_pchg) >= abs(actual_delta) * 0.10
            _threshold    = (max(1000.0, 0.005 * _prev) if _pchg_reliable
                             else max(10000.0, 0.05 * _prev))
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

    # ---- CC income KPI ----
    cc_ytd = 0.0
    cc_lifetime = 0.0
    cc_trade_count = 0
    try:
        _cc_conn = sqlite3.connect(str(DB_PATH), timeout=5)
        _cc_conn.row_factory = sqlite3.Row
        _cur_year = today_date[:4] if today_date else str(datetime.now(TZ).year)
        _ytd = _cc_conn.execute(
            """SELECT sum(net_premium) as t FROM cc_positions
               WHERE status IN ('closed','expired','assigned')
                 AND net_premium IS NOT NULL
                 AND COALESCE(closed_date, expiry) LIKE ?""",
            (f"{_cur_year}%",)
        ).fetchone()
        _life = _cc_conn.execute(
            """SELECT sum(net_premium) as t, count(*) as n FROM cc_positions
               WHERE status IN ('closed','expired','assigned')
                 AND net_premium IS NOT NULL"""
        ).fetchone()
        _cc_conn.close()
        cc_ytd        = float(_ytd["t"]  or 0)
        cc_lifetime   = float(_life["t"] or 0)
        cc_trade_count = int(_life["n"]  or 0)
    except Exception:
        pass

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
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background: #f4f6f9; color: #2c3e50; font-size: 14px; overflow-x: hidden; }}
    h1 {{ font-size: 1.4rem; font-weight: 700; }}
    h2 {{ font-size: 1rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: #7f8c8d; margin-bottom: 12px; }}

    header {{ background: #1a2340; color: #fff; padding: 18px 28px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
    header .subtitle {{ font-size: .85rem; color: #a0aec0; margin-top: 2px; }}

    .grid {{ display: grid; gap: 18px; padding: 20px 28px; }}
    .kpi-row {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 14px; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .three-col {{ display: grid; grid-template-columns: 2fr 1fr; gap: 18px; }}
    .goals-grid {{ display: grid; grid-template-columns: 1.65fr 1fr; gap: 16px; align-items: start; }}

    .card {{ background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.07); min-width: 0; }}
    .kpi {{ background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.07); min-width: 0; }}
    .kpi .label {{ font-size: .78rem; color: #7f8c8d; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; }}
    .kpi .sub {{ font-size: .82rem; margin-top: 2px; }}
    .kpi-link {{ cursor: pointer; transition: box-shadow .15s, transform .15s; }}
    .kpi-link:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,.13); transform: translateY(-1px); }}

    .pos {{ color: #27ae60; }}
    .neg {{ color: #e74c3c; }}

    canvas {{ max-height: 260px; }}

    .table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ text-align: left; padding: 7px 10px; border-bottom: 2px solid #eee; color: #7f8c8d; font-weight: 600; font-size: .75rem; text-transform: uppercase; white-space: nowrap; background: #fff; }}
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

    @media (max-width: 1200px) {{
      .kpi-row {{ grid-template-columns: repeat(3, 1fr); }}
      .three-col {{ grid-template-columns: 1fr; }}
      .grid {{ padding: 16px 20px; gap: 14px; }}
    }}
    @media (max-width: 900px) {{
      .kpi-row {{ grid-template-columns: repeat(3, 1fr); }}
      .two-col, .three-col, .goals-grid {{ grid-template-columns: 1fr; }}
      .grid {{ padding: 12px 14px; gap: 12px; }}
      header {{ padding: 14px 16px; }}
    }}
    @media (max-width: 600px) {{
      .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
      .kpi .value {{ font-size: 1.2rem; }}
    }}
    @keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}

    /* ── Invest Chat Panel ─────────────────────────────────────────────────── */
    #invest-chat-panel {{
      position: fixed; right: 0; top: 0; bottom: 0; width: 380px;
      background: #fff; border-left: 1px solid #dde;
      display: flex; flex-direction: column; z-index: 1200;
      box-shadow: -4px 0 24px rgba(0,0,0,.14);
    }}
    #invest-chat-header {{
      display: flex; align-items: center; justify-content: space-between;
      gap: .75rem; padding: .8rem 1rem;
      border-bottom: 1px solid #e8edf4; background: #f5f7fa; flex-shrink: 0;
    }}
    #invest-chat-header-text {{ display: flex; flex-direction: column; gap: 1px; min-width: 0; }}
    #invest-chat-label {{
      font-size: 10px; font-weight: 700; letter-spacing: .08em;
      text-transform: uppercase; color: #6c5ce7;
    }}
    #invest-chat-title {{
      font-size: 13px; font-weight: 600; color: #1a2340;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    #invest-chat-header-btns {{ display: flex; align-items: center; gap: .4rem; flex-shrink: 0; }}
    #invest-chat-clear {{
      background: none; border: 1px solid #dde; border-radius: 5px;
      padding: .15rem .5rem; font-size: 11px; color: #7f8c8d; cursor: pointer;
    }}
    #invest-chat-clear:hover {{ color: #1a2340; border-color: #aab; }}
    #invest-chat-close {{
      background: none; border: none; font-size: 1.4rem; line-height: 1;
      color: #7f8c8d; cursor: pointer; padding: 0 .2rem;
    }}
    #invest-chat-close:hover {{ color: #1a2340; }}
    #invest-chat-body {{ flex: 1; overflow-y: auto; display: flex; flex-direction: column; }}
    #invest-chat-empty {{
      flex: 1; display: flex; align-items: center; justify-content: center;
      padding: 2rem 1.5rem; text-align: center;
      color: #7f8c8d; font-size: 13px; line-height: 1.6;
    }}
    #invest-chat-messages {{ padding: .75rem; display: flex; flex-direction: column; gap: .6rem; }}
    .ic-msg {{
      max-width: 86%; padding: .5rem .75rem; border-radius: 10px;
      font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-break: break-word;
    }}
    .ic-msg-user {{
      align-self: flex-end; background: #6c5ce7; color: #fff; border-bottom-right-radius: 3px;
    }}
    .ic-msg-assistant {{
      align-self: flex-start; background: #f0f2f8; color: #1a2340; border-bottom-left-radius: 3px;
    }}
    .ic-cursor {{
      display: inline-block; width: 2px; height: .9em;
      background: #7f8c8d; margin-left: 2px; vertical-align: text-bottom;
      animation: ic-blink .9s step-end infinite;
    }}
    @keyframes ic-blink {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:0 }} }}
    #invest-chat-error {{
      font-size: 11px; color: #c0392b; background: #fdf2f2;
      border: 1px solid #f5c6c6; border-radius: 6px;
      padding: .4rem .65rem; margin: .5rem .75rem 0;
    }}
    #invest-chat-input-area {{
      border-top: 1px solid #e8edf4; padding: .65rem;
      display: flex; flex-direction: column; gap: .5rem;
      flex-shrink: 0; background: #f5f7fa;
    }}
    #invest-chat-chips {{ display: flex; flex-wrap: wrap; gap: .35rem; }}
    .ic-chip {{
      background: none; border: 1px solid #dde; border-radius: 20px;
      padding: .25rem .65rem; font-size: 11px; color: #555; cursor: pointer;
      transition: color .15s, border-color .15s;
    }}
    .ic-chip:hover:not(:disabled) {{ color: #6c5ce7; border-color: #6c5ce7; }}
    .ic-chip:disabled {{ opacity: .5; cursor: default; }}
    #invest-chat-input-row {{ display: flex; gap: .4rem; align-items: flex-end; }}
    #invest-chat-input {{
      flex: 1; border: 1px solid #dde; border-radius: 8px; padding: .45rem .65rem;
      font-size: 13px; font-family: inherit; background: #fff; color: #1a2340;
      resize: none; line-height: 1.5;
    }}
    #invest-chat-input:focus {{ outline: none; border-color: #6c5ce7; }}
    #invest-chat-input:disabled {{ opacity: .6; }}
    #invest-chat-send {{
      width: 34px; height: 34px; border-radius: 50%; border: none;
      background: #6c5ce7; color: #fff; font-size: .95rem; font-weight: 700;
      cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
    }}
    #invest-chat-send:disabled {{ opacity: .4; cursor: default; }}
    .btn-invest-chat {{
      background: none; border: 1.5px solid #6c5ce7; color: #6c5ce7;
      font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 6px;
      cursor: pointer; transition: background .15s, color .15s; touch-action: manipulation;
    }}
    .btn-invest-chat:hover {{ background: #6c5ce7; color: #fff; }}
    @media (max-width: 600px) {{
      #invest-chat-panel {{
        top: auto; left: 0; right: 0; width: 100%; height: 72vh;
        border-left: none; border-top: 1px solid #dde;
        border-radius: 14px 14px 0 0;
        box-shadow: 0 -4px 24px rgba(0,0,0,.15);
      }}
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

<!-- CC Edit Modal -->
<div id="cc-edit-overlay" onclick="closeCCEditModal(event)"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;align-items:center;justify-content:center;">
  <div onclick="event.stopPropagation()"
    style="background:#fff;border-radius:12px;padding:28px 32px;max-width:500px;width:95%;box-shadow:0 8px 40px rgba(0,0,0,.2);position:relative;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">
      <h2 style="font-size:1.05rem;font-weight:700;color:#1a2340;margin:0;">Edit Position</h2>
      <button onclick="closeCCEditModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;padding:4px 8px;">✕</button>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px;">
      <div>
        <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Ticker</label>
        <input id="cc-edit-ticker" type="text" placeholder="AAPL" maxlength="10"
          style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:14px;font-weight:700;text-transform:uppercase;box-sizing:border-box;">
      </div>
      <div>
        <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Contracts</label>
        <input id="cc-edit-contracts" type="number" min="1" step="1"
          style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:14px;box-sizing:border-box;">
      </div>
      <div>
        <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Strike ($)</label>
        <input id="cc-edit-strike" type="number" step="0.01" min="0"
          style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:14px;box-sizing:border-box;">
      </div>
      <div>
        <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Expiry</label>
        <input id="cc-edit-expiry" type="date"
          style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:13px;box-sizing:border-box;">
      </div>
      <div>
        <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Premium / Contract ($)</label>
        <input id="cc-edit-premium" type="number" step="0.01" min="0"
          style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:14px;box-sizing:border-box;">
      </div>
      <div>
        <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Opened Date</label>
        <input id="cc-edit-opened-date" type="date"
          style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:13px;box-sizing:border-box;">
      </div>
    </div>
    <div style="margin-bottom:18px;">
      <label style="font-size:10px;color:#aaa;text-transform:uppercase;">Notes</label>
      <input id="cc-edit-notes" type="text" placeholder="optional"
        style="width:100%;margin-top:4px;padding:7px 10px;border:1px solid #dde;border-radius:6px;font-size:13px;box-sizing:border-box;">
    </div>
    <button onclick="saveCCEdit()"
      style="width:100%;padding:10px;background:#1a2340;color:#fff;border:none;border-radius:7px;font-size:14px;font-weight:700;cursor:pointer;">
      Save Changes
    </button>
    <div id="cc-edit-status" style="margin-top:8px;font-size:12px;color:#888;text-align:center;"></div>
  </div>
</div>

<!-- Unified Tax Transactions Modal -->
<div id="txn-overlay" onclick="txnOverlayClick(event)"
  style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1100;align-items:flex-start;justify-content:center;padding:40px 16px;overflow-y:auto;">
  <div onclick="event.stopPropagation()"
    style="background:#fff;border-radius:14px;width:100%;max-width:1000px;box-shadow:0 12px 48px rgba(0,0,0,.25);overflow:hidden;">
    <div style="background:#1a2340;padding:20px 28px;display:flex;align-items:center;justify-content:space-between;">
      <div>
        <div style="color:#fff;font-size:1.1rem;font-weight:700;">📋 All Tax-Impacting Transactions</div>
        <div id="txn-subtitle" style="color:#8899bb;font-size:12px;margin-top:3px;">—</div>
      </div>
      <button onclick="closeTxnModal()" style="background:rgba(255,255,255,.1);border:none;color:#fff;font-size:18px;width:32px;height:32px;border-radius:50%;cursor:pointer;line-height:32px;text-align:center;">✕</button>
    </div>
    <div style="padding:24px 28px;">
      <div id="txn-modal-content"></div>
    </div>
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

<!-- ── Tax Loss Harvesting Modal ──────────────────────────────────────────── -->
<div id="tlh-overlay" onclick="tlhOverlayClick(event)" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1100;align-items:flex-start;justify-content:center;padding:40px 16px;overflow-y:auto;">
  <div onclick="event.stopPropagation()" style="background:#fff;border-radius:14px;width:100%;max-width:960px;box-shadow:0 12px 48px rgba(0,0,0,.25);overflow:hidden;">

    <!-- Header -->
    <div style="background:#1a2340;padding:20px 28px;display:flex;align-items:center;justify-content:space-between;">
      <div>
        <div style="color:#fff;font-size:1.1rem;font-weight:700;">✂ Tax Loss Harvesting</div>
        <div style="color:#8899bb;font-size:12px;margin-top:3px;">Model the tax impact of selling positions · bracket: <span id="tlh-bracket-label">—</span></div>
      </div>
      <button onclick="closeTLH()" style="background:rgba(255,255,255,.1);border:none;color:#fff;font-size:18px;width:32px;height:32px;border-radius:50%;cursor:pointer;line-height:32px;text-align:center;">✕</button>
    </div>

    <!-- Body -->
    <div style="padding:24px 28px;">

      <!-- Loading / error states -->
      <div id="tlh-loading" style="text-align:center;padding:40px;color:#888;">Loading positions…</div>
      <div id="tlh-error"   style="display:none;color:#e74c3c;padding:20px;font-size:13px;"></div>

      <!-- Main content (hidden until loaded) -->
      <div id="tlh-content" style="display:none;">

        <!-- Summary -->
        <div style="background:#f4f6fb;border-radius:10px;padding:20px 24px;margin-bottom:24px;">
          <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px;">Harvest Summary — Selected Positions</div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
            <!-- Left: Loss / gain buckets -->
            <div>
              <div style="font-size:12px;color:#888;margin-bottom:10px;font-weight:600;">What you'd realize</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <div style="background:#fff;border-radius:8px;padding:12px 14px;border-left:3px solid #e74c3c;">
                  <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">ST Losses</div>
                  <div id="tlh-st-loss" style="font-size:16px;font-weight:700;color:#e74c3c;">$0</div>
                </div>
                <div style="background:#fff;border-radius:8px;padding:12px 14px;border-left:3px solid #e67e22;">
                  <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">LT Losses</div>
                  <div id="tlh-lt-loss" style="font-size:16px;font-weight:700;color:#e67e22;">$0</div>
                </div>
                <div style="background:#fff;border-radius:8px;padding:12px 14px;border-left:3px solid #27ae60;">
                  <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">ST Gains</div>
                  <div id="tlh-st-gain" style="font-size:16px;font-weight:700;color:#27ae60;">$0</div>
                </div>
                <div style="background:#fff;border-radius:8px;padding:12px 14px;border-left:3px solid #2980b9;">
                  <div style="font-size:10px;color:#aaa;text-transform:uppercase;margin-bottom:4px;">LT Gains</div>
                  <div id="tlh-lt-gain" style="font-size:16px;font-weight:700;color:#2980b9;">$0</div>
                </div>
              </div>
            </div>

            <!-- Right: Tax impact -->
            <div>
              <div style="font-size:12px;color:#888;margin-bottom:10px;font-weight:600;">Tax impact</div>
              <div style="background:#fff;border-radius:8px;padding:16px;font-size:13px;line-height:2;">
                <div style="display:flex;justify-content:space-between;border-bottom:1px solid #f0f0f0;padding-bottom:6px;margin-bottom:6px;">
                  <span style="color:#666;">Current est. tax bill</span>
                  <span id="tlh-current-tax" style="font-weight:600;color:#c0392b;">—</span>
                </div>
                <div style="display:flex;justify-content:space-between;border-bottom:1px solid #f0f0f0;padding-bottom:6px;margin-bottom:6px;">
                  <span style="color:#666;">Net ST (ordinary rate <span id="tlh-st-rate">—</span>)</span>
                  <span id="tlh-net-st" style="font-weight:600;">—</span>
                </div>
                <div style="display:flex;justify-content:space-between;border-bottom:1px solid #f0f0f0;padding-bottom:6px;margin-bottom:6px;">
                  <span style="color:#666;">Net LT (qualified rate <span id="tlh-lt-rate">—</span>)</span>
                  <span id="tlh-net-lt" style="font-weight:600;">—</span>
                </div>
                <div id="tlh-ordinary-row" style="display:none;justify-content:space-between;border-bottom:1px solid #f0f0f0;padding-bottom:6px;margin-bottom:6px;">
                  <span style="color:#666;">Ordinary income offset (≤$3k)</span>
                  <span id="tlh-ordinary-save" style="font-weight:600;color:#27ae60;"></span>
                </div>
                <div id="tlh-carryforward-row" style="display:none;justify-content:space-between;border-bottom:1px solid #f0f0f0;padding-bottom:6px;margin-bottom:6px;">
                  <span style="color:#666;">Loss carry-forward</span>
                  <span id="tlh-carryforward" style="font-weight:600;color:#8899bb;"></span>
                </div>
                <div style="display:flex;justify-content:space-between;border-bottom:1px solid #f0f0f0;padding-bottom:6px;margin-bottom:6px;">
                  <span style="font-weight:600;color:#1a2340;">Harvest tax impact</span>
                  <span id="tlh-total-savings" style="font-weight:700;font-size:15px;color:#888;">$0</span>
                </div>
                <div style="display:flex;justify-content:space-between;margin-top:4px;">
                  <span style="font-weight:700;color:#1a2340;">Est. tax after harvest</span>
                  <span id="tlh-tax-after" style="font-weight:700;font-size:16px;color:#c0392b;">—</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Wash sale warning -->
          <div id="tlh-wash-warning" style="display:none;background:#fff8e1;border:1px solid #f9a825;border-radius:8px;padding:12px 16px;font-size:12px;color:#795548;">
            <strong>⚠ Wash Sale Rule:</strong> <span id="tlh-wash-tickers"></span>
            You cannot repurchase these securities (or substantially identical ones) within 30 days before or after the sale.
          </div>
        </div>

        <!-- Positions table -->
        <div style="font-size:11px;font-weight:700;color:#7f8c8d;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">
          Positions &nbsp;<span style="font-weight:400;color:#aaa;text-transform:none;">(check to include in harvest model)</span>
        </div>
        <div style="overflow-x:auto;margin-bottom:24px;">
          <table id="tlh-table" style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead>
              <tr style="border-bottom:2px solid #e8eaf0;text-align:right;">
                <th style="text-align:left;padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">
                  <input type="checkbox" id="tlh-check-all" onchange="tlhToggleAll(this.checked)" style="cursor:pointer;"> Ticker
                </th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">Shares</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">Avg Cost</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">Price</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">Mkt Value</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">ST P&L</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">LT P&L</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">Total P&L</th>
                <th style="padding:8px 6px;color:#7f8c8d;font-weight:600;font-size:11px;text-transform:uppercase;">Lots</th>
              </tr>
            </thead>
            <tbody id="tlh-tbody"></tbody>
          </table>
        </div>

      </div><!-- /tlh-content -->
    </div><!-- /body -->
  </div>
</div>

<header>
  <div>
    <h1>Investment Dashboard</h1>
    <div class="subtitle">{today_date} &nbsp;·&nbsp; {len(today_holdings)} holdings across 5 layers</div>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    <a href="/glossary" target="_blank" style="font-size:12px;padding:5px 14px;border:none;border-radius:5px;background:#2d3a55;color:#e2e8f0;cursor:pointer;font-weight:500;text-decoration:none;">📖 Glossary</a>
    <button id="refreshBtn" onclick="refreshDashboard()" style="font-size:12px;padding:5px 14px;border:none;border-radius:5px;background:#2d3a55;color:#e2e8f0;cursor:pointer;font-weight:500;">↻ Refresh Data</button>
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
      <div class="value {chg_class_main}" id="kpi-daily-value" data-stock-chg="{round(total_chg, 2)}" data-total-value="{round(total_v, 2)}">{money(total_chg)}</div>
      <div class="sub {chg_class_main}" id="kpi-daily-pct">{pct(total_chg_pct)}</div>
    </div>
    <div class="kpi">
      <div class="label">SPY Change</div>
      <div class="value {spy_class}">{pct(spy_chg)}</div>
    </div>
    <div class="kpi kpi-link" onclick="document.getElementById('holdings-table').scrollIntoView({{behavior:'smooth',block:'start'}})">
      <div class="label">Total Gain vs Cost</div>
      <div class="value {gain_class_main}">{money(total_gain_dollars)}</div>
      <div class="sub {gain_class_main}">{pct(total_gain_pct)}</div>
    </div>
    <div class="kpi kpi-link" onclick="document.getElementById('div-card').scrollIntoView({{behavior:'smooth',block:'start'}})">
      <div class="label">Est. Annual Dividends (After-Tax)</div>
      <div class="value" id="kpi-div-value" style="color:#27ae60;">—</div>
      <div class="sub" id="kpi-div-yield" style="color:#aaa;"></div>
    </div>
    <div class="kpi kpi-link" onclick="document.getElementById('cc-tracker-card').scrollIntoView({{behavior:'smooth',block:'start'}})">
      <div class="label">CC Income (YTD)</div>
      <div class="value" style="color:{'#27ae60' if cc_ytd > 0 else '#aaa'};">{money(cc_ytd) if cc_ytd else "—"}</div>
      <div class="sub" style="color:#aaa;">{f"Lifetime: {money(cc_lifetime)} · {cc_trade_count} trades" if cc_lifetime else "No closed positions yet"}</div>
    </div>
    <div class="kpi kpi-link" onclick="document.getElementById('realized-gains-card').scrollIntoView({{behavior:'smooth',block:'start'}})">
      <div class="label" id="kpi-tax-label">Est. Tax Bill</div>
      <div class="value" id="kpi-tax-value" style="color:#c0392b;">—</div>
      <div class="sub" id="kpi-tax-sub" style="color:#aaa;font-size:11px;"></div>
    </div>
  </div>

  <!-- Investment Goals & Strategy -->
  <div class="card" id="goals-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
      Investment Goals &amp; Strategy
      <span style="font-size:11px;color:#aaa;font-weight:400;">auto-updates with dividend data</span>
    </h2>

    <div class="goals-grid">

      <!-- Dividend Goal (wide left column) -->
      <div style="background:#f8fffe;border:1px solid #d4edda;border-radius:8px;padding:14px 16px;">
        <div style="font-size:11px;font-weight:700;color:#27ae60;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">
          Dividend Goal — $2,500 / mo by 2036
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
              <span style="color:#aaa;">$2,500/mo by 2036</span>
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
    <div class="table-scroll">
    <table>
      <thead><tr><th>Layer</th><th>Value</th><th>Weight</th><th>Δ $</th><th>Δ %</th><th>Next Earnings</th></tr></thead>
      <tbody>{layer_rows}</tbody>
    </table>
    </div>
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

    <div class="table-scroll" id="holdings-scroll-wrap">
    <table id="holdings-table">
      <thead id="holdings-thead"><tr><th>Ticker</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>Total Gain</th><th>Daily Δ</th><th>Weight</th><th>Next Earnings</th><th>Layer</th><th>Tax Lots</th></tr></thead>
      <tbody>{holdings_rows}</tbody>
    </table>
    </div>
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
        <button onclick="openTxnModal()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:600;">📋 All Transactions</button>
        <button onclick="openTLH()" style="font-size:11px;padding:4px 12px;background:#1a2340;border:none;border-radius:5px;cursor:pointer;color:#fff;font-weight:600;">✂ Tax Harvesting</button>
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
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <div style="display:flex;background:#f0f2f5;border-radius:6px;padding:3px;gap:2px;">
          <button id="deep-mode-btn-annual" onclick="setDeepMode('annual')"
            style="padding:4px 12px;border:none;border-radius:4px;font-size:12px;font-weight:600;cursor:pointer;background:#1a2340;color:#fff;">Annual</button>
          <button id="deep-mode-btn-ttm" onclick="setDeepMode('ttm')"
            style="padding:4px 12px;border:none;border-radius:4px;font-size:12px;font-weight:600;cursor:pointer;background:transparent;color:#888;">TTM</button>
        </div>
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
        <div id="deep-source-label" style="font-size:10px;color:#bbb;margin-top:3px;"></div>
      </div>
    </div>

    <!-- Results table -->
    <div id="deep-results-wrap"></div>
  </div>

  <!-- Covered Call Analyzer -->
  <div class="card" id="cc-card">
    <h2>Covered Call Analyzer</h2>
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">
      <select id="cc-ticker" onchange="onCCTickerChange(this.value)" style="padding:8px 12px;border:1px solid #dde;border-radius:6px;font-size:13px;background:#fff;color:#2c3e50;min-width:160px;">
        <option value="">Select a holding…</option>
        {cc_ticker_options}
      </select>
      <button id="cc-btn" onclick="analyzeCoveredCall()"
        style="padding:8px 18px;background:#1a2340;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">
        Get Recommendations
      </button>
      <button id="cc-refresh-btn" onclick="analyzeCoveredCall(true)" style="display:none;padding:6px 12px;background:#fff;color:#555;border:1px solid #dde;border-radius:6px;font-size:12px;cursor:pointer;">
        ↺ Force Refresh
      </button>
      <button id="cc-ai-btn" onclick="getAIAnalysis()" disabled
        style="padding:8px 18px;background:#b0a8e0;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:not-allowed;opacity:0.6;">
        🤖 AI Analysis
      </button>
      <span id="cc-status" style="font-size:12px;color:#7f8c8d;"></span>
    </div>
    <div id="cc-results"></div>
    <div id="cc-ai-panel" style="display:none;margin-top:1rem;border:1.5px solid #6c5ce7;border-radius:8px;padding:1rem;background:#f8f7ff;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;">
        <div style="font-weight:700;color:#6c5ce7;font-size:14px;">
          🤖 AI Analysis
          <span id="cc-ai-model" style="font-size:11px;background:#e8e5ff;padding:2px 7px;border-radius:4px;color:#6c5ce7;margin-left:0.5rem;font-weight:500;"></span>
        </div>
        <button class="btn-invest-chat"
          onclick="openInvestChat('cc',document.getElementById('cc-ticker').value,document.getElementById('cc-ticker').value+' — Covered Call Chat',['Is now a good time to sell?','What if the stock drops 5%?','Explain the regret probability','Should I pick a different strike?'])">💬 Chat</button>
      </div>
      <div id="cc-ai-content"></div>
    </div>
  </div>

  <!-- ── AI Chat Panel (fixed right drawer, shared by winner + CC contexts) ── -->
  <div id="invest-chat-panel" style="display:none;flex-direction:column;">
    <div id="invest-chat-header">
      <div id="invest-chat-header-text">
        <span id="invest-chat-label">AI Chat</span>
        <span id="invest-chat-title"></span>
      </div>
      <div id="invest-chat-header-btns">
        <button id="invest-chat-clear" onclick="icClear()" style="display:none;">Clear</button>
        <button id="invest-chat-close" onclick="closeInvestChat()">×</button>
      </div>
    </div>
    <div id="invest-chat-body">
      <div id="invest-chat-empty">Ask follow-up questions about this analysis.</div>
      <div id="invest-chat-messages"></div>
      <div id="invest-chat-error" style="display:none;"></div>
    </div>
    <div id="invest-chat-input-area">
      <div id="invest-chat-chips"></div>
      <div id="invest-chat-input-row">
        <textarea id="invest-chat-input" rows="2" placeholder="Ask something… (Enter to send, Shift+Enter for newline)"></textarea>
        <button id="invest-chat-send" onclick="icSend()" title="Send">↑</button>
      </div>
    </div>
  </div>

  <!-- Covered Call Position Tracker -->
  <div class="card" id="cc-tracker-card">
    <h2 style="display:flex;align-items:center;justify-content:space-between;">
      Covered Call Position Tracker
      <span style="display:flex;gap:6px;align-items:center;">
        <button onclick="evaluateCCPositions()" id="cc-eval-btn" style="font-size:11px;padding:4px 12px;background:#e8f5e9;border:1px solid #a5d6a7;border-radius:5px;cursor:pointer;color:#2e7d32;font-weight:600;">🔄 Evaluate Positions</button>
        <button onclick="importCCFromCSV()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:500;">⬆ Import CSV</button>
        <button onclick="loadCCPositions()" style="font-size:11px;padding:4px 12px;background:#f4f6f9;border:1px solid #dde;border-radius:5px;cursor:pointer;color:#555;font-weight:500;">↻ Refresh</button>
      </span>
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

    <!-- Evaluate positions panel -->
    <div id="cc-eval-panel" style="display:none;margin-top:1rem;border:1.5px solid #27ae60;border-radius:8px;padding:1rem;background:#f0fdf4;">
      <div style="font-weight:700;color:#27ae60;margin-bottom:0.75rem;font-size:14px;">🔄 Position Evaluations</div>
      <div id="cc-eval-content"></div>
    </div>
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
  {{ label: "$150k household",  qualified: 0.15,  niit: 0.000, ordinary: 0.22, magi: 150000 }},
  {{ label: "$300k household",  qualified: 0.15,  niit: 0.038, ordinary: 0.24, magi: 300000 }},
  {{ label: "$500k household",  qualified: 0.15,  niit: 0.038, ordinary: 0.32, magi: 500000 }},
  {{ label: "$750k household",  qualified: 0.20,  niit: 0.038, ordinary: 0.35, magi: 750000 }},
  {{ label: "$1M+ household",   qualified: 0.20,  niit: 0.038, ordinary: 0.37, magi: 1000000 }},
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

let _divStatusFilter = new Set(["upcoming", "payment_due"]);

function _divStatusOf(r) {{
  if (r.declared)    return "upcoming";
  if (r.pay_pending) return "payment_due";
  return "last_known";
}}

function _divChip(key, label, color) {{
  const on = _divStatusFilter.has(key);
  return `<span onclick="_divToggleFilter('${{key}}')"
    style="cursor:pointer;padding:2px 10px;border-radius:10px;font-size:10px;font-weight:600;user-select:none;
           border:1px solid ${{on ? color : '#dde'}};background:${{on ? color + '18' : '#f4f6f9'}};
           color:${{on ? color : '#888'}};">
    ${{label}}</span>`;
}}

function _divToggleFilter(key) {{
  if (_divStatusFilter.has(key)) _divStatusFilter.delete(key);
  else _divStatusFilter.add(key);
  renderDividendTable();
}}

function renderDividendTable() {{
  if (!_divData) return;
  const results = document.getElementById("div-results");
  const b = CURRENT_BRACKET;

  const totalAnnual   = _divData.results.reduce((s, r) => s + (r.annual_income || 0), 0);
  const totalAfterTax = _divData.results.reduce((s, r) => s + (r.annual_income || 0) * (1 - effectiveRate(r.tax_type || "qualified")), 0);
  const totalPort     = {total_v};
  document.getElementById("kpi-div-value").textContent =
    "$" + Math.round(totalAfterTax).toLocaleString("en-US");
  document.getElementById("kpi-div-yield").textContent =
    "gross $" + Math.round(totalAnnual).toLocaleString("en-US") +
    (totalPort > 0 ? "  ·  " + (totalAnnual / totalPort * 100).toFixed(2) + "% yield" : "");
  _flashEl("kpi-div-value");

  const filterBar = `
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:10px;
                padding:7px 12px;background:#f8fafc;border:1px solid #e8edf4;border-radius:8px;">
      <span style="font-size:10px;color:#aaa;font-weight:600;text-transform:uppercase;letter-spacing:.04em;">Show</span>
      ${{_divChip("upcoming",    "Upcoming",    "#1a6e38")}}
      ${{_divChip("payment_due", "Payment Due", "#1a56b0")}}
      ${{_divChip("last_known",  "Last Known",  "#888")}}
      <span style="margin-left:auto;font-size:11px;color:#aaa;" id="div-filter-count"></span>
    </div>`;

  const filtered = _divData.results.filter(r => _divStatusFilter.has(_divStatusOf(r)));

  const rows = filtered.map(r => {{
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
      : r.pay_pending
        ? `<span style="background:#e8f0fe;color:#1a56b0;border:1px solid #a8c4f5;border-radius:4px;padding:1px 7px;font-size:10px;font-weight:700;">PAYMENT DUE</span>`
        : `<span style="background:#f4f6f9;color:#888;border:1px solid #dde;border-radius:4px;padding:1px 7px;font-size:10px;">LAST KNOWN</span>`;
    const exDiv  = r.ex_div_date || "—";
    const payDay = r.pay_date ? (r.pay_date_estimated ? "~" + r.pay_date : r.pay_date) : "—";
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

  const noRows = filtered.length === 0
    ? `<tr><td colspan="11" style="padding:16px;text-align:center;color:#aaa;font-size:12px;">No dividends match the selected filters.</td></tr>` : "";

  results.innerHTML = filterBar + `
    <div style="overflow-x:auto;margin-top:4px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead id="div-thead"><tr style="background:#f4f6f9;">
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
      <tbody>${{rows}}${{noRows}}</tbody>
    </table>
    </div>
    <p style="font-size:11px;color:#aaa;margin-top:8px;">
      Tax basis: MFJ ${{b.label.replace(" household","")}} — Qualified ${{qRate}}% (cap gains + NIIT), Ordinary ${{oRate}}% (marginal + NIIT), Municipal = federal exempt.
      As of ${{_divData.as_of}}.
    </p>`;

  const countEl = document.getElementById("div-filter-count");
  if (countEl) countEl.textContent = filtered.length === _divData.results.length
    ? `${{_divData.results.length}} holdings`
    : `${{filtered.length}} of ${{_divData.results.length}} holdings`;
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

function _flashEl(id) {{
  const el = document.getElementById(id);
  if (!el) return;
  el.style.transition = "background 0.1s";
  el.style.background = "#fffbe6";
  setTimeout(() => {{ el.style.background = ""; }}, 600);
}}

function onTaxBracketChange(sel) {{
  CURRENT_BRACKET = TAX_BRACKETS[sel.value];
  renderDividendTable();
  renderGoalsCard();
  if (typeof loadDividendTimeline === "function") loadDividendTimeline();
}}

// ── Investment Goals card ──────────────────────────────────────────────────
function renderGoalsCard() {{
  // ── Dividend goal ──
  const GOAL_MONTHLY    = 2500;
  const GOAL_PORT       = 2000000;
  const GOAL_YEAR       = 2036;
  const CUR_YEAR        = new Date().getFullYear();
  const YEARS_LEFT      = Math.max(1, GOAL_YEAR - CUR_YEAR);
  const DIV_TAX_RATE = CURRENT_BRACKET.qualified + CURRENT_BRACKET.niit;

  const totalAnnual = _divData
    ? _divData.results.reduce((s, r) => s + (r.annual_income || 0) * (1 - effectiveRate(r.tax_type || "qualified")), 0) : 0;
  const totalGross  = _divData
    ? _divData.results.reduce((s, r) => s + (r.annual_income || 0), 0) : 0;
  const monthly     = totalGross / 12;
  const monthlyNet  = totalAnnual / 12;
  const pct         = Math.min(100, totalGross > 0 ? (monthly / GOAL_MONTHLY * 100) : 0);
  const gap         = GOAL_MONTHLY - monthly;
  const reqCagr     = totalGross > 0
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
  if (nEl) {{ nEl.textContent = `after tax (${{(DIV_TAX_RATE*100).toFixed(1)}}% avg): ${{fmtM(monthlyNet)}}`; _flashEl("goal-div-net"); }}
  const bEl = document.getElementById("goal-div-bar");
  if (bEl) bEl.style.width = pct + "%";
  const pEl = document.getElementById("goal-div-pct");
  if (pEl) {{ pEl.textContent = pct.toFixed(1) + "% of $2,500/mo target"; pEl.style.color = pct >= 80 ? "#27ae60" : pct >= 40 ? "#e67e22" : "#e74c3c"; }}
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
    if (w.dividend_yield && w.dividend_yield > 0) vals.push(`Yield ${{w.dividend_yield.toFixed(1)}}%`);
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
    const hasST = lots.some(l => (today - new Date(l.purchase_date + "T00:00:00")) / 86400000 <= 365);
    const hasLT = lots.some(l => (today - new Date(l.purchase_date + "T00:00:00")) / 86400000 > 365);
    const stCount = lots.filter(l => (today - new Date(l.purchase_date + "T00:00:00")) / 86400000 <= 365).length;
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
    const isLT    = daysHeld > 365;
    const termBadge = isLT
      ? `<span style="background:#f0fff4;color:#27ae60;border:1px solid #ade;border-radius:3px;padding:1px 6px;font-size:10px;font-weight:700;">LT</span>`
      : `<span style="background:#fff0f0;color:#e74c3c;border:1px solid #fcc;border-radius:3px;padding:1px 6px;font-size:10px;font-weight:700;">ST</span>`;
    const lotValue    = l.shares * price;
    const lotCost     = l.shares * l.cost_per_share;
    const lotGain     = lotValue - lotCost;
    const lotGainPct  = lotCost > 0 ? (lotGain / lotCost * 100) : 0;
    const gainColor   = lotGain >= 0 ? "#27ae60" : "#e74c3c";
    const ltDate      = new Date(purchaseDate); ltDate.setFullYear(ltDate.getFullYear() + 1); ltDate.setDate(ltDate.getDate() + 1);
    const ltDaysLeft  = Math.ceil((ltDate - today) / 86400000);
    const ltStr       = isLT ? "" : `<div style="font-size:10px;color:#aaa;">LT eligible: ${{ltDate.toLocaleDateString("en-US",{{month:"short",day:"numeric",year:"numeric"}})}} (${{ltDaysLeft}}d)</div>`;

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
    const term        = daysHeld > 365 ? "LT" : "ST";
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
  const stRate      = parseFloat(document.getElementById("tax-st-rate")?.value  || 35) / 100;
  const ltRate      = parseFloat(document.getElementById("tax-lt-rate")?.value  || 20) / 100;
  const niitChecked = document.getElementById("tax-niit")?.checked;
  const niit        = niitChecked ? 0.038 : 0;  // flat rate for per-row estimates

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

  // Aggregate NIIT uses IRS lesser-of formula: 3.8% × min(NII, max(0, MAGI − $250k threshold))
  const NIIT_THRESHOLD = 250000;
  const nii          = Math.max(0, stGain) + Math.max(0, ltGain);
  const niitBase     = niitChecked ? Math.min(nii, Math.max(0, (CURRENT_BRACKET.magi || 0) - NIIT_THRESHOLD)) : 0;
  const niitEffRate  = nii > 0 && niitBase > 0 ? (niitBase / nii) * 0.038 : 0;
  const stTax  = Math.max(0, stGain) * (stRate + niitEffRate);
  const ltTax  = Math.max(0, ltGain) * (ltRate + niitEffRate);
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
    Est. Tax = positive gains only · federal rate only · rates: ST ${{(stRate*100).toFixed(1)}}%${{niitChecked?" +NIIT (lesser-of formula)":""}} / LT ${{(ltRate*100).toFixed(1)}}%${{niitChecked?" +NIIT (lesser-of formula)":""}}
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
  const NIIT_THRESHOLD_KPI = 250000;
  const niiKPI         = Math.max(0, stGain) + Math.max(0, ltGain);
  const niitCheckedKPI = document.getElementById("tax-niit")?.checked;
  const niitBaseKPI    = niitCheckedKPI ? Math.min(niiKPI, Math.max(0, (CURRENT_BRACKET.magi || 0) - NIIT_THRESHOLD_KPI)) : 0;
  const niitEffRateKPI = niiKPI > 0 && niitBaseKPI > 0 ? (niitBaseKPI / niiKPI) * 0.038 : 0;
  const stTax   = Math.max(0, stGain) * (stRate + niitEffRateKPI);
  const ltTax   = Math.max(0, ltGain) * (ltRate + niitEffRateKPI);
  const totTax  = stTax + ltTax;

  _currentYearTax = {{ stGain, ltGain, stTax, ltTax, totTax,
                       stRate: stRate + niitEffRateKPI, ltRate: ltRate + niitEffRateKPI }};

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
let _bViewMode = "table";
let _bSort    = {{ col: "quality_score", dir: -1 }};
let _bFilters = {{ q: "", exchange: "", layer: 0, risk: "low", valuation: "" }};

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
    _bViewMode = "layer";
    _bSort    = {{ col: "quality_score", dir: -1 }};
    _bFilters = {{ q: "", exchange: "", layer: 0, risk: "low", valuation: "" }};

    const partialNote = (running || (lastScan && scanned < total * 0.95))
      ? `<span style="color:#e67e22;"> · partial results (${{pct}}% scanned)</span>` : "";

    resultsEl.innerHTML += `
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:10px;">
        <span style="font-size:11px;color:#888;font-weight:600;">View:</span>
        <button id="bview-table" onclick="_bSetView('table')"
          style="padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;cursor:pointer;
                 border:1px solid #dde;background:#f4f6f9;color:#555;">Table</button>
        <button id="bview-layer" onclick="_bSetView('layer')"
          style="padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;cursor:pointer;
                 border:1px solid #6c63ff;background:#6c63ff;color:#fff;">By Layer</button>
      </div>
      <div id="buffett-table-wrap" style="display:none;"></div>
      <div id="buffett-layer-view-wrap"></div>
      <p style="font-size:11px;color:#aaa;margin-top:6px;">
        Green = quality · Blue = valuation · Purple = layer · Red = trap risk${{partialNote}}
      </p>`;
    _renderLayerView();

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
  const val  = _bFilters.valuation;

  // Filter
  let rows = _buffettAllWinners.filter(w => {{
    if (exch && w.exchange !== exch) return false;
    if (lyr  && w.layer_rec !== lyr) return false;
    if (risk && w.value_trap_risk !== risk) return false;
    if (val) {{
      const wVal = (w.ai_analysis && !w.ai_analysis.error) ? w.ai_analysis.valuation : null;
      if (wVal !== val) return false;
    }}
    if (q) {{
      const hay = ((w.ticker||"") + " " + (w.company||"") + " " + (w.sector||"") + " " + (w.country||"")).toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});

  // Sort
  const riskOrder  = {{ low:1, medium:2, high:3, null:9, undefined:9 }};
  const valOrder   = {{ cheap:1, fair:2, stretched:3 }};
  const col = _bSort.col;
  const dir = _bSort.dir;
  rows = rows.slice().sort((a, b) => {{
    let av, bv;
    if (col === "ticker")           {{ av = a.ticker || ""; bv = b.ticker || ""; }}
    else if (col === "company")     {{ av = a.company || ""; bv = b.company || ""; }}
    else if (col === "layer_rec")   {{ av = a.layer_rec || 99; bv = b.layer_rec || 99; }}
    else if (col === "value_trap_risk") {{ av = riskOrder[a.value_trap_risk]||9; bv = riskOrder[b.value_trap_risk]||9; }}
    else if (col === "ai_valuation") {{
      const aV = (a.ai_analysis && !a.ai_analysis.error) ? a.ai_analysis.valuation : null;
      const bV = (b.ai_analysis && !b.ai_analysis.error) ? b.ai_analysis.valuation : null;
      av = valOrder[aV] ?? 9; bv = valOrder[bV] ?? 9;
    }}
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

  const hiddenCount = risk === "low"
    ? _buffettAllWinners.filter(w => w.value_trap_risk !== "low").length : 0;
  const hiddenNote = hiddenCount > 0
    ? `<span style="font-size:10px;color:#aaa;font-style:italic;">${{hiddenCount}} medium/high-risk hidden</span>` : "";
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
      ${{chip("risk","low","✓ Safe",risk)}}
      ${{chip("risk","","All",risk)}}
      ${{chip("risk","high","Traps",risk)}}
      <span style="font-size:10px;color:#aaa;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-left:4px;">AI Valuation</span>
      ${{chip("valuation","cheap","Cheap",val)}}
      ${{chip("valuation","fair","Fair",val)}}
      ${{chip("valuation","stretched","Stretched",val)}}
      ${{hiddenNote}}
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
    const score = w.quality_score;
    const scoreColor = score >= 70 ? "#27ae60" : score >= 50 ? "#f39c12" : score != null ? "#c0392b" : "#aaa";
    const scoreHtml = score != null
      ? `<span style="font-weight:700;color:${{scoreColor}};font-size:13px;">${{score}}</span><span style="color:#ccc;font-size:10px;">/100</span>`
      : `<span style="color:#ccc;">—</span>`;
    const sectorShort = (w.sector || "").slice(0, 14);
    const divPct = w.dividend_yield ? w.dividend_yield.toFixed(1) + "%" : "—";
    const hasAI = w.ai_analysis && !w.ai_analysis.error;
    const convHtml = hasAI && w.ai_analysis.conviction
      ? "⭐".repeat(Math.min(5, Math.max(1, w.ai_analysis.conviction)))
      : `<span style="color:#ccc;font-size:10px;font-style:italic;">AI▾</span>`;
    const aiBtnLabel = hasAI ? "✓ AI" : "AI ▾";
    const aiBtnStyle = hasAI
      ? `background:#eafaf1;border-color:#a9dfbf;color:#1e8449;`
      : `background:#f4f6f9;border-color:#dde;color:#555;`;
    const aiVal = hasAI ? w.ai_analysis.valuation : null;
    const aiValColor = aiVal === "cheap" ? "#27ae60" : aiVal === "fair" ? "#7f8c8d" : aiVal === "stretched" ? "#c0392b" : null;
    const aiValHtml = aiValColor
      ? `<span style="display:inline-block;padding:1px 6px;border-radius:6px;font-size:9px;font-weight:700;
           background:${{aiValColor}}22;color:${{aiValColor}};border:1px solid ${{aiValColor}}44;">${{aiVal}}</span>`
      : `<span style="color:#ccc;font-size:10px;">—</span>`;
    const countryHtml = w.country
      ? `<span style="font-size:11px;color:#555;">${{w.country}}</span>`
      : `<span style="color:#ccc;">—</span>`;
    return `
      <tr id="brow-${{w.ticker}}" style="background:${{rowBg}};border-bottom:1px solid #f0f2f5;">
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
        <td style="padding:8px 6px;text-align:center;">${{scoreHtml}}</td>
        <td style="padding:8px 6px;vertical-align:middle;">${{_bLayerBadge(w.layer_rec, w.layer_reason)}}</td>
        <td style="padding:8px 6px;vertical-align:top;">${{_bTrapBadge(w.value_trap_risk, w.value_trap_flags)}}</td>
        <td style="padding:8px 10px;color:#555;font-size:11px;max-width:90px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${{w.sector || ""}}">${{sectorShort || "—"}}</td>
        <td style="padding:8px 10px;white-space:nowrap;">${{countryHtml}}</td>
        <td style="padding:8px 10px;text-align:center;">${{aiValHtml}}</td>
        <td style="padding:8px 10px;color:#8e44ad;">${{divPct}}</td>
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
        <td id="bconv-${{w.ticker}}" style="padding:6px 8px;text-align:center;white-space:nowrap;">${{convHtml}}</td>
        <td style="padding:10px 12px;text-align:center;cursor:pointer;touch-action:manipulation;" onclick="_bAI('${{w.ticker}}')">
          <button id="bai-btn-${{w.ticker}}"
            style="padding:4px 10px;border-radius:8px;font-size:10px;font-weight:600;pointer-events:none;
                   border:1px solid;${{aiBtnStyle}}">${{aiBtnLabel}}</button>
        </td>
      </tr>
      <tr id="bai-row-${{w.ticker}}" style="display:none;background:#f8fafc;border-bottom:1px solid #e8edf4;">
        <td colspan="22" style="padding:0;">
          <div id="bai-content-${{w.ticker}}" style="padding:10px 16px;font-size:12px;"></div>
        </td>
      </tr>`;
  }}).join("\\n");

  const noResults = rows.length === 0
    ? `<tr><td colspan="22" style="padding:20px;text-align:center;color:#aaa;font-size:12px;">
         No stocks match the current filters.</td></tr>` : "";

  wrap.innerHTML = filterBar + `
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead id="screener-thead"><tr style="background:#f4f6f9;border-bottom:2px solid #e8eaf0;">
        <th style="padding:7px 6px;text-align:center;font-size:10px;color:#bbb;width:28px;">#</th>
        ${{thStyle("ticker","Ticker")}}
        ${{thStyle("company","Company")}}
        ${{thStyle("quality_score","Score","#16a085","center")}}
        ${{thStyle("layer_rec","Layer","#9b59b6")}}
        ${{thStyle("value_trap_risk","Trap Risk","#c0392b")}}
        ${{thStyle("sector","Sector")}}
        ${{thStyle("country","Country")}}
        ${{thStyle("ai_valuation","AI Val","#8e44ad","center")}}
        ${{thStyle("dividend_yield","Div %","#8e44ad")}}
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
        <th style="padding:7px 8px;font-size:10px;color:#e67e22;font-weight:600;text-transform:uppercase;text-align:center;">Conv</th>
        <th style="padding:7px 8px;font-size:10px;color:#aaa;font-weight:600;text-transform:uppercase;">AI</th>
      </tr></thead>
      <tbody>${{tableRows}}${{noResults}}</tbody>
    </table>
    </div>`;
}}

// ── Buffett: view toggle ──────────────────────────────────────────────────
function _bSetView(mode) {{
  _bViewMode = mode;
  const tWrap = document.getElementById("buffett-table-wrap");
  const lWrap = document.getElementById("buffett-layer-view-wrap");
  const tBtn  = document.getElementById("bview-table");
  const lBtn  = document.getElementById("bview-layer");
  if (!tWrap || !lWrap) return;
  const btnBase = "padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;cursor:pointer;border:1px solid;";
  if (mode === "table") {{
    tWrap.style.display = "";
    lWrap.style.display = "none";
    if (tBtn) tBtn.style.cssText = btnBase + "border-color:#6c63ff;background:#6c63ff;color:#fff;";
    if (lBtn) lBtn.style.cssText = btnBase + "border-color:#dde;background:#f4f6f9;color:#555;";
    _renderBuffettTable();
  }} else {{
    tWrap.style.display = "none";
    lWrap.style.display = "";
    if (lBtn) lBtn.style.cssText = btnBase + "border-color:#6c63ff;background:#6c63ff;color:#fff;";
    if (tBtn) tBtn.style.cssText = btnBase + "border-color:#dde;background:#f4f6f9;color:#555;";
    _renderLayerView();
  }}
}}

// ── Buffett: per-row AI analysis ──────────────────────────────────────────
async function _bAI(ticker) {{
  const btn     = document.getElementById(`bai-btn-${{ticker}}`);
  const aiRow   = document.getElementById(`bai-row-${{ticker}}`);
  const content = document.getElementById(`bai-content-${{ticker}}`);
  if (!btn || !aiRow || !content) return;

  // Toggle if already loaded
  if (aiRow.style.display !== "none") {{ aiRow.style.display = "none"; return; }}

  // Find winner in memory
  const w = _buffettAllWinners.find(x => x.ticker === ticker);
  if (!w) return;

  // Render if AI analysis already cached in memory
  if (w.ai_analysis && !w.ai_analysis.error) {{
    content.innerHTML = _bAIPanel(ticker, w.ai_analysis);
    aiRow.style.display = "";
    btn.textContent = "✓ AI";
    btn.style.background = "#eafaf1"; btn.style.borderColor = "#a9dfbf"; btn.style.color = "#1e8449";
    return;
  }}

  // Generate via API
  btn.textContent = "⏳ …";
  btn.disabled = true;
  // Show the row immediately with a streaming pre so user sees progress
  content.innerHTML =
    `<pre id="bai-stream-${{ticker}}" style="margin:0;font-size:11px;color:#555;white-space:pre-wrap;` +
    `word-break:break-word;max-height:220px;overflow-y:auto;background:#f4f4f4;` +
    `padding:0.6rem;border-radius:5px;line-height:1.5">Starting AI analysis…</pre>`;
  aiRow.style.display = "";
  const streamEl = document.getElementById(`bai-stream-${{ticker}}`);
  try {{
    // Retry the initial POST up to 3 times on transient network errors
    let r1, d1;
    for (let attempt = 0; attempt < 3; attempt++) {{
      try {{
        if (attempt > 0) {{
          streamEl.textContent = `Network error — retrying (${{attempt}}/2)…`;
          await new Promise(res => setTimeout(res, 1500 * attempt));
        }}
        r1 = await fetch("/api/buffett-ai-analyze", {{
          method: "POST", headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{ticker}})
        }});
        d1 = await r1.json();
        break;
      }} catch(_) {{
        if (attempt === 2) throw new Error("Network error — server unreachable after 3 attempts");
      }}
    }}
    if (!d1.ok) throw new Error(d1.error || "API error");

    let analysis;
    if (d1.cached) {{
      analysis = d1.analysis;
    }} else {{
      // Poll job and stream progress into the pre element
      const jobId = d1.job_id;
      let lastProgress = "";
      while (true) {{
        await new Promise(res => setTimeout(res, 1000));
        let dp;
        try {{
          const rp = await fetch(`/api/analysis-job/${{jobId}}`);
          dp = await rp.json();
        }} catch (_) {{
          streamEl.textContent = (lastProgress || "AI is thinking…") + "\\n[reconnecting…]";
          continue;
        }}
        if (dp.status === "error") throw new Error(dp.error || "AI error");
        if (dp.progress && dp.progress !== lastProgress) {{
          lastProgress = dp.progress;
          streamEl.textContent = dp.progress;
          streamEl.scrollTop = streamEl.scrollHeight;
        }}
        if (dp.status === "done") {{ analysis = dp.result?.analysis; break; }}
      }}
    }}
    if (!analysis) throw new Error("No analysis returned");
    w.ai_analysis = analysis;
    content.innerHTML = _bAIPanel(ticker, analysis);
    btn.textContent = "✓ AI";
    btn.style.background = "#eafaf1"; btn.style.borderColor = "#a9dfbf"; btn.style.color = "#1e8449";
    const convCell = document.getElementById(`bconv-${{ticker}}`);
    if (convCell && analysis.conviction) {{
      convCell.textContent = "⭐".repeat(Math.min(5, Math.max(1, analysis.conviction)));
    }}
  }} catch(e) {{
    content.innerHTML = `<span style="color:#c0392b;font-size:11px;">⚠ ${{e.message}}</span>`;
    btn.textContent = "AI ▾";
  }} finally {{
    btn.disabled = false;
  }}
}}

function _bAIPanel(ticker, ai) {{
  const moatColor = ai.moat_strength === "strong" ? "#27ae60" : ai.moat_strength === "moderate" ? "#f39c12" : "#c0392b";
  const valColor  = ai.valuation === "cheap" ? "#27ae60" : ai.valuation === "fair" ? "#7f8c8d" : "#c0392b";
  const stars = "⭐".repeat(Math.min(5, Math.max(1, ai.conviction || 3)));
  const badge = (label, color) =>
    `<span style="display:inline-block;padding:1px 7px;border-radius:8px;font-size:10px;font-weight:700;
                  background:${{color}}22;color:${{color}};border:1px solid ${{color}}44;">${{label}}</span>`;

  const redundantEntries = (ai.redundancy || []);
  let redundancyHtml = "";
  if (redundantEntries.length > 0) {{
    const rows = redundantEntries.map(r => {{
      const supColor = r.winner_superior ? "#27ae60" : "#c0392b";
      const supLabel = r.winner_superior ? "Winner better" : "Keep holding";
      return `<tr style="border-bottom:1px solid #e8edf4;">
        <td style="padding:5px 8px;font-weight:600;color:#1a2340;white-space:nowrap;">${{r.ticker}}</td>
        <td style="padding:5px 8px;color:#555;font-size:11px;">${{r.redundancy_reason || "—"}}</td>
        <td style="padding:5px 8px;text-align:center;">${{badge(supLabel, supColor)}}</td>
        <td style="padding:5px 8px;color:#555;font-size:11px;">${{r.superiority_reason || "—"}}</td>
      </tr>`;
    }}).join("");
    redundancyHtml = `
      <div style="margin-top:12px;border-top:2px solid #e8edf4;padding-top:10px;">
        <div style="font-weight:600;color:#1a2340;font-size:11px;margin-bottom:6px;">⚖️ Holdings Overlap (${{redundantEntries.length}} redundant)</div>
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
          <thead>
            <tr style="background:#f5f7fa;">
              <th style="padding:4px 8px;text-align:left;color:#7f8c8d;font-size:10px;font-weight:600;">Holding</th>
              <th style="padding:4px 8px;text-align:left;color:#7f8c8d;font-size:10px;font-weight:600;">Why Redundant</th>
              <th style="padding:4px 8px;text-align:center;color:#7f8c8d;font-size:10px;font-weight:600;">Verdict</th>
              <th style="padding:4px 8px;text-align:left;color:#7f8c8d;font-size:10px;font-weight:600;">Detail</th>
            </tr>
          </thead>
          <tbody>${{rows}}</tbody>
        </table>
      </div>`;
  }} else if (Array.isArray(ai.redundancy)) {{
    redundancyHtml = `
      <div style="margin-top:12px;border-top:2px solid #e8edf4;padding-top:8px;">
        <div style="font-size:11px;color:#27ae60;font-weight:600;">✓ No overlap with existing holdings</div>
      </div>`;
  }}

  return `
    <div style="max-width:860px;">
      <div style="display:flex;justify-content:flex-end;gap:6px;margin-bottom:6px;">
        <button class="btn-invest-chat"
          onclick="openInvestChat('winner','${{ticker}}','${{ticker}} — Buffett Analysis',['Why this conviction level?','What is the biggest risk?','How does this compare to what I own?','When would you sell?'])">💬 Chat</button>
        <button onclick="_bAIRerun('${{ticker}}')"
          style="font-size:10px;padding:3px 10px;border-radius:6px;border:1px solid #dde;
                 background:#f4f6f9;color:#555;cursor:pointer;touch-action:manipulation;">↻ Re-run</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div>
          <div style="font-weight:600;color:#1a2340;font-size:11px;margin-bottom:3px;">📊 Thesis</div>
          <div style="color:#333;line-height:1.5;">${{ai.thesis || "—"}}</div>
        </div>
        <div>
          <div style="font-weight:600;color:#1a2340;font-size:11px;margin-bottom:3px;">🏰 Moat</div>
          <div>${{badge(ai.moat_strength || "?", moatColor)}} <span style="color:#555;">${{ai.moat_note || ""}}</span></div>
          <div style="margin-top:6px;font-weight:600;color:#1a2340;font-size:11px;">💰 Valuation</div>
          <div>${{badge(ai.valuation || "?", valColor)}} <span style="color:#555;">${{ai.valuation_note || ""}}</span></div>
        </div>
        <div>
          <div style="font-weight:600;color:#c0392b;font-size:11px;margin-bottom:3px;">⚑ Top Risk</div>
          <div style="color:#555;">${{ai.top_risk || "—"}}</div>
        </div>
        <div>
          <div style="font-weight:600;color:#1a2340;font-size:11px;margin-bottom:3px;">Conviction ${{stars}}</div>
          <div style="color:#888;font-size:11px;">${{ai.layer_fit || ""}}</div>
        </div>
      </div>
      ${{redundancyHtml}}
    </div>`;
}}

function _bAIRerun(ticker) {{
  const w = _buffettAllWinners.find(x => x.ticker === ticker);
  if (w) delete w.ai_analysis;
  const aiRow = document.getElementById(`bai-row-${{ticker}}`);
  if (aiRow) aiRow.style.display = "none";
  const btn = document.getElementById(`bai-btn-${{ticker}}`);
  if (btn) {{ btn.textContent = "AI ▾"; btn.style.background = "#f4f6f9"; btn.style.borderColor = "#dde"; btn.style.color = "#555"; }}
  _bAI(ticker);
}}

// ── Buffett: layer view ───────────────────────────────────────────────────
const _bLayerDesc = {{
  1: "Mega-cap, ultra-stable — your portfolio's shock absorber during crashes",
  2: "Dividend payers with pricing power — cash flow while you wait",
  3: "Quality compounders — long-duration growth at a reasonable price",
  4: "Small-cap & high-growth — nonlinear upside, higher volatility",
  5: "Energy, defense, utilities — regime hedges against inflation/geopolitical risk",
}};

function _renderLayerView() {{
  const wrap = document.getElementById("buffett-layer-view-wrap");
  if (!wrap) return;
  const lw      = D.layerWeightsByNum || {{}};
  const targets  = D.layerTargets     || {{}};
  let html = "";

  for (let n = 1; n <= 5; n++) {{
    const meta    = _bLayerMeta[n] || {{}};
    const winners = _buffettAllWinners.filter(w =>
      w.layer_rec === n && (!_bFilters.risk || w.value_trap_risk === _bFilters.risk)
    ).sort((a, b) => {{
      const aR = a.ai_layer_rank, bR = b.ai_layer_rank;
      if (aR != null && bR != null) return aR - bR;
      if (aR != null) return -1;
      if (bR != null) return  1;
      return (b.quality_score || 0) - (a.quality_score || 0);
    }});

    const curPct  = (lw[n]?.weight || 0).toFixed(1);
    const tgtPct  = targets[n] || 0;
    const gap     = (parseFloat(curPct) - tgtPct).toFixed(1);
    const gapHtml = Math.abs(gap) < 1
      ? `<span style="color:#27ae60;font-weight:700;">✓ On target</span>`
      : gap < 0
        ? `<span style="color:#c0392b;font-weight:700;">▼ ${{Math.abs(gap)}}% under</span>`
        : `<span style="color:#f39c12;font-weight:700;">▲ ${{gap}}% over</span>`;

    const allocationBar = `
      <div style="display:inline-flex;gap:16px;align-items:center;font-size:11px;
                  background:#fff;padding:4px 10px;border-radius:6px;border:1px solid #e8edf4;">
        <span>Current: <b>${{curPct}}%</b></span>
        <span>Target: <b>${{tgtPct}}%</b></span>
        ${{gapHtml}}
        <span style="color:#aaa;">${{winners.length}} winner${{winners.length!==1?"s":""}}</span>
      </div>`;

    // Mini-table of top 5 winners
    let miniRows = "";
    if (winners.length === 0) {{
      miniRows = `<tr><td colspan="8" style="padding:12px;text-align:center;color:#aaa;font-size:11px;font-style:italic;">
        No ${{_bFilters.risk ? _bFilters.risk + "-risk " : ""}}screener winners in this layer.</td></tr>`;
    }} else {{
      winners.slice(0, 5).forEach((w, idx) => {{
        const sc = w.quality_score;
        const scClr = sc >= 70 ? "#27ae60" : sc >= 50 ? "#f39c12" : sc != null ? "#c0392b" : "#aaa";
        const div = w.dividend_yield ? w.dividend_yield.toFixed(1) + "%" : "—";
        const hasAI = w.ai_analysis && !w.ai_analysis.error;
        const stars = hasAI ? "⭐".repeat(Math.min(5, Math.max(1, w.ai_analysis.conviction || 3))) : "";
        const aiBtnStyle = hasAI
          ? "background:#eafaf1;border-color:#a9dfbf;color:#1e8449;"
          : "background:#f8f9ff;border-color:#c5b8f0;color:#6c3fc5;";
        const aiBtnLabel = hasAI ? "✓ AI" : "AI▾";
        const hasLayerRank = w.ai_layer_rank != null;
        const rankBadge = hasLayerRank
          ? `<span style="font-size:9px;color:#6c3fc5;font-weight:700;background:#f0eeff;` +
            `border-radius:3px;padding:0 3px;margin-right:3px;">🤖${{w.ai_layer_rank}}</span>`
          : "";
        const trBg = idx % 2 === 0 ? "#fff" : "#f9fafb";
        miniRows += `<tr style="background:${{trBg}};border-bottom:1px solid #f0f2f5;">
          <td style="padding:6px 8px;font-size:11px;color:#aaa;text-align:center;">${{idx+1}}</td>
          <td style="padding:6px 8px;font-weight:700;color:#1a2340;">${{w.ticker}}</td>
          <td style="padding:6px 8px;color:#555;font-size:11px;max-width:100px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${{w.company || "—"}}</td>
          <td style="padding:6px 8px;text-align:center;font-weight:700;color:${{scClr}};font-size:12px;">${{sc != null ? sc : "—"}}</td>
          <td style="padding:6px 8px;color:#27ae60;font-weight:600;">${{w.gross_margin?.toFixed(1)}}%</td>
          <td style="padding:6px 8px;color:#2980b9;">${{w.pe_ratio != null ? w.pe_ratio.toFixed(1)+"x" : "—"}}</td>
          <td style="padding:6px 8px;color:#8e44ad;">${{div}}</td>
          <td style="padding:10px 10px;cursor:pointer;touch-action:manipulation;" onclick="_bAI('${{w.ticker}}')">
            ${{rankBadge}}<span style="font-size:12px;">${{stars}}</span>
            <button id="bai-btn-${{w.ticker}}"
              style="font-size:10px;padding:4px 8px;border-radius:3px;border:1px solid;pointer-events:none;margin-left:2px;${{aiBtnStyle}}">${{aiBtnLabel}}</button>
          </td>
        </tr>
        <tr id="bai-row-${{w.ticker}}" style="display:none;background:#f8fafc;">
          <td colspan="8"><div id="bai-content-${{w.ticker}}" style="padding:10px 14px;font-size:12px;"></div></td>
        </tr>`;
      }});
      if (winners.length > 5) {{
        miniRows += `<tr><td colspan="8" style="padding:4px 8px;text-align:center;font-size:10px;color:#aaa;">
          + ${{winners.length - 5}} more — switch to Table view to see all</td></tr>`;
      }}
    }}

    const compareResultId = `blayer-cmp-${{n}}`;
    html += `
      <div style="border:1px solid #e8edf4;border-radius:10px;margin-bottom:16px;overflow:hidden;">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;
                    padding:10px 14px;background:${{meta.bg}};color:${{meta.color}};">
          <span style="font-weight:700;font-size:13px;">${{meta.label}}: ${{_bLayerDesc[n]?.split("—")[0].trim() || "Layer "+n}}</span>
          ${{allocationBar}}
        </div>
        <div style="padding:6px 0;font-size:11px;color:#777;padding-left:14px;padding-top:6px;padding-bottom:4px;
                    border-bottom:1px solid #f0f2f5;font-style:italic;">${{_bLayerDesc[n] || ""}}</div>
        <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
          <thead><tr style="background:#f8fafc;border-bottom:1px solid #e8edf4;">
            <th style="padding:5px 8px;font-size:10px;color:#bbb;text-align:center;width:24px;">#</th>
            <th style="padding:5px 8px;font-size:10px;color:#555;text-align:left;">Ticker</th>
            <th style="padding:5px 8px;font-size:10px;color:#555;text-align:left;">Company</th>
            <th style="padding:5px 8px;font-size:10px;color:#16a085;text-align:center;">Score</th>
            <th style="padding:5px 8px;font-size:10px;color:#27ae60;text-align:left;">Gross%</th>
            <th style="padding:5px 8px;font-size:10px;color:#2980b9;text-align:left;">P/E</th>
            <th style="padding:5px 8px;font-size:10px;color:#8e44ad;text-align:left;">Div%</th>
            <th style="padding:5px 8px;font-size:10px;color:#e67e22;text-align:left;">Conviction</th>
          </tr></thead>
          <tbody>${{miniRows}}</tbody>
        </table>
        </div>
        ${{winners.length > 0 ? `
        <div style="padding:8px 14px;border-top:1px solid #f0f2f5;">
          <button onclick="_bLayerCompare(${{n}})"
            style="padding:4px 12px;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer;
                   border:1px solid #6c63ff;background:#f0eeff;color:#6c63ff;">
            Compare Layer ${{n}} ▸</button>
          <div id="${{compareResultId}}" style="margin-top:8px;"></div>
        </div>` : ""}}
      </div>`;
  }}
  wrap.innerHTML = html;
}}

async function _bLayerCompare(layerNum) {{
  const resultEl = document.getElementById(`blayer-cmp-${{layerNum}}`);
  if (!resultEl) return;
  resultEl.innerHTML =
    `<pre id="blayer-stream-${{layerNum}}" style="margin:0;font-size:11px;color:#555;white-space:pre-wrap;` +
    `word-break:break-word;max-height:220px;overflow-y:auto;background:#f4f4f4;` +
    `padding:0.6rem;border-radius:5px;line-height:1.5">🤖 Asking AI to rank…</pre>`;
  const streamEl = document.getElementById(`blayer-stream-${{layerNum}}`);
  try {{
    // Retry initial POST up to 3 times on transient network errors
    let r1, d1;
    for (let attempt = 0; attempt < 3; attempt++) {{
      try {{
        if (attempt > 0) {{
          streamEl.textContent = `Network error — retrying (${{attempt}}/2)…`;
          await new Promise(res => setTimeout(res, 1500 * attempt));
        }}
        r1 = await fetch("/api/buffett-layer-compare", {{
          method: "POST", headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{layer: layerNum}})
        }});
        d1 = await r1.json();
        break;
      }} catch(_) {{
        if (attempt === 2) throw new Error("Network error — server unreachable after 3 attempts");
      }}
    }}
    if (!d1.ok) throw new Error(d1.error || "API error");
    const jobId = d1.job_id;
    let lastProgress = "";
    let result;
    while (true) {{
      await new Promise(res => setTimeout(res, 1000));
      let dp;
      try {{
        const rp = await fetch(`/api/analysis-job/${{jobId}}`);
        dp = await rp.json();
      }} catch (_) {{
        streamEl.textContent = (lastProgress || "🤖 Asking AI to rank…") + "\\n[reconnecting…]";
        continue;
      }}
      if (dp.status === "done") {{ result = dp.result; break; }}
      if (dp.status === "error") throw new Error(dp.error || "AI error");
      if (dp.progress && dp.progress !== lastProgress) {{
        lastProgress = dp.progress;
        streamEl.textContent = dp.progress;
        streamEl.scrollTop = streamEl.scrollHeight;
      }}
    }}
    if (!result) throw new Error("No result");
    const ranked = (result.ranked || []).sort((a, b) => (a.rank || 0) - (b.rank || 0));
    const rows = ranked.map((r, i) =>
      `<div style="padding:4px 0;border-bottom:1px solid #f0f2f5;display:flex;gap:8px;align-items:baseline;">
        <span style="font-size:11px;color:#aaa;min-width:18px;text-align:right;">${{i+1}}.</span>
        <span style="font-weight:700;color:#1a2340;min-width:50px;">${{r.ticker}}</span>
        <span style="color:#555;font-size:11px;">${{r.note || ""}}</span>
      </div>`
    ).join("");
    resultEl.innerHTML = `
      <div style="background:#f8fafc;border:1px solid #e8edf4;border-radius:8px;padding:10px 14px;margin-top:4px;">
        <div style="font-weight:600;color:#1a2340;font-size:11px;margin-bottom:6px;">🤖 AI Layer ${{layerNum}} Ranking</div>
        ${{result.summary ? `<div style="color:#555;font-size:11px;margin-bottom:8px;font-style:italic;">${{result.summary}}</div>` : ""}}
        ${{rows || '<div style="color:#aaa;font-size:11px;">No rankings returned.</div>'}}
      </div>`;
  }} catch(e) {{
    resultEl.innerHTML = `<span style="color:#c0392b;font-size:11px;">⚠ ${{e.message}}</span>`;
  }}
}}

// ── Buffett Deep-Dive Analyzer ────────────────────────────────────────────
let _deepMode = "annual";

function setDeepMode(mode) {{
  _deepMode = mode;
  const btnAnnual = document.getElementById("deep-mode-btn-annual");
  const btnTTM    = document.getElementById("deep-mode-btn-ttm");
  const active    = "padding:4px 12px;border:none;border-radius:4px;font-size:12px;font-weight:600;cursor:pointer;background:#1a2340;color:#fff;";
  const inactive  = "padding:4px 12px;border:none;border-radius:4px;font-size:12px;font-weight:600;cursor:pointer;background:transparent;color:#888;";
  btnAnnual.style.cssText = mode === "annual" ? active : inactive;
  btnTTM.style.cssText    = mode === "ttm"    ? active : inactive;
}}

async function runDeepAnalysis() {{
  const input  = document.getElementById("deep-ticker-input");
  const ticker = (input?.value || "").trim().toUpperCase();
  if (!ticker) {{ input?.focus(); return; }}

  const status  = document.getElementById("deep-status");
  const summary = document.getElementById("deep-summary");
  const wrap    = document.getElementById("deep-results-wrap");
  const modeLabel = _deepMode === "ttm" ? "TTM (trailing 12 months)" : "annual";
  status.textContent  = `Fetching ${{modeLabel}} financials for ${{ticker}}…`;
  summary.style.display = "none";
  wrap.innerHTML = "";

  try {{
    // Start background job — connection drops (phone lock, app switch) won't abort the run
    const startRes = await fetch("/api/analysis-job", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{type: "buffett", ticker, mode: _deepMode}}),
    }});
    const startData = await startRes.json();
    if (!startData.ok) {{ status.textContent = "Error: " + startData.error; return; }}
    const jobId = startData.job_id;

    // Poll until done
    let data = null;
    while (true) {{
      await new Promise(r => setTimeout(r, 1500));
      let poll;
      try {{
        const pollRes = await fetch(`/api/analysis-job/${{jobId}}`);
        poll = await pollRes.json();
      }} catch (_) {{
        // network blip — keep trying; the job continues server-side
        status.textContent = `Reconnecting… (${{ticker}})`;
        continue;
      }}
      if (poll.status === "error") {{ status.textContent = "Error: " + poll.error; return; }}
      if (poll.progress) status.textContent = poll.progress;
      if (poll.status === "done") {{ data = poll.result; break; }}
    }}

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
    document.getElementById("deep-source-label").textContent   = data.period_label ? `📄 ${{data.period_label}}` : "";
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

    const edgarType = _deepMode === "ttm" ? "10-Q" : "10-K";
    const srcNote = data.period_label
      ? `Source: ${{data.period_label}} · via Yahoo Finance (yfinance) · verify at <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=${{edgarType}}&dateb=&owner=include&count=10&search_text=" target="_blank" style="color:#aaa;">SEC EDGAR</a>`
      : `Source: Most recent ${{_deepMode === "ttm" ? "quarterly" : "annual"}} filing · via Yahoo Finance`;
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
      </table></div>
    <div style="font-size:10px;color:#bbb;margin-top:8px;">${{srcNote}}</div>`;
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
}}

// ── CC Position Tracker ───────────────────────────────────────────────────
// ── CC Position Tracker ───────────────────────────────────────────────────
let _allCCPositions  = [];
let _ccCloseTargetId = null;
let _ccCloseType     = null;
let _ccEditTargetId  = null;

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
  const thisYear      = new Date().getFullYear().toString();
  const ytdClosed     = closed.filter(p => (p.closed_date || p.expiry || "").startsWith(thisYear));
  const ytdNet        = ytdClosed.reduce((s,p) => s + (p.net_premium ?? 0), 0);
  const openMtmTotal  = open.filter(p => p.pnl_total != null && !isNaN(p.pnl_total)).reduce((s,p) => s + p.pnl_total, 0);
  const openMtmDay    = open.filter(p => p.pnl_day   != null && !isNaN(p.pnl_day)).reduce((s,p)  => s + p.pnl_day,   0);
  const hasMtm        = open.some(p => p.current_mark != null && p.pnl_total != null && !isNaN(p.pnl_total));

  // Adjust the daily change KPI to include today's option P&L
  (function() {{
    const el  = document.getElementById("kpi-daily-value");
    const pct = document.getElementById("kpi-daily-pct");
    if (!el || !hasMtm) return;
    const stockChg  = parseFloat(el.dataset.stockChg  || 0);
    const totalVal  = parseFloat(el.dataset.totalValue || 0);
    const adjChg    = stockChg + openMtmDay;
    const prevTotal = totalVal - adjChg;
    const adjPct    = prevTotal > 0 ? adjChg / prevTotal * 100 : 0;
    el.textContent  = (adjChg >= 0 ? "+" : "") + "$" + Math.abs(Math.round(adjChg)).toLocaleString("en-US");
    el.style.color  = adjChg >= 0 ? "" : "#e74c3c";
    if (pct) {{
      pct.textContent = (adjPct >= 0 ? "+" : "") + adjPct.toFixed(2) + "%";
      pct.style.color = adjPct >= 0 ? "" : "#e74c3c";
    }}
  }})();

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

  const makeRow = (p, ccMonthId, ccHidden) => {{
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

    const markCell = isOpen
      ? (p.current_mark != null
          ? `<td style="padding:7px 10px;">$${{p.current_mark.toFixed(2)}}</td>`
          : `<td style="padding:7px 10px;color:#ccc;font-size:11px;">—</td>`)
      : `<td style="padding:7px 10px;"></td>`;

    const pnlTotalCell = isOpen
      ? `<td style="padding:7px 10px;">${{fmtPnl(p.pnl_total)}}</td>`
      : `<td style="padding:7px 10px;"></td>`;

    const pnlDayCell = isOpen
      ? `<td style="padding:7px 10px;">${{fmtPnl(p.pnl_day)}}</td>`
      : `<td style="padding:7px 10px;"></td>`;

    const actionCell = isOpen
      ? `<td style="padding:7px 10px;">
           <button onclick="openCCCloseModal(${{p.id}})"
             style="font-size:10px;padding:3px 10px;background:#1a2340;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:600;">
             Close ▾
           </button>
         </td>`
      : `<td style="padding:7px 10px;font-size:11px;color:#aaa;">${{p.closed_date || ""}}</td>`;

    const _trExtra = ccMonthId ? ` data-ccmonth="${{ccMonthId}}"` : "";
    const _hiddenStyle = ccHidden ? "display:none;" : "";
    return `<tr${{_trExtra}} style="${{_hiddenStyle}}border-bottom:1px solid #f2f4f7;">
      <td style="padding:7px 10px;font-weight:700;white-space:nowrap;">
        ${{p.ticker}}<button onclick="openCCEditModal(${{p.id}})"
          style="font-size:9px;padding:2px 5px;background:none;color:#bbb;border:1px solid #e0e0e0;border-radius:3px;cursor:pointer;margin-left:5px;vertical-align:middle;"
          title="Edit position">✎</button>
      </td>
      <td style="padding:7px 10px;">${{p.contracts}}×</td>
      <td style="padding:7px 10px;">$${{p.strike.toFixed(2)}}</td>
      <td style="padding:7px 10px;">${{p.expiry}} ${{isOpen ? dteTag(p.expiry) : ""}}</td>
      <td style="padding:7px 10px;">$${{p.premium_per_contract.toFixed(2)}}</td>
      <td style="padding:7px 10px;color:#555;">$${{gross.toFixed(2)}}</td>
      ${{markCell}}
      ${{pnlTotalCell}}
      ${{pnlDayCell}}
      ${{netCell}}
      <td style="padding:7px 10px;">${{statusBadge(p)}}</td>
      <td style="padding:7px 10px;font-size:11px;color:#aaa;">${{p.opened_date}}</td>
      <td style="padding:7px 10px;font-size:11px;color:#aaa;">${{p.notes || ""}}</td>
      ${{actionCell}}
    </tr>`;
  }};

  const fmtPnl = v => (v == null || isNaN(v)) ? `<span style="color:#ccc;">—</span>` : (v >= 0 ? `<span style="color:#27ae60;">+$${{v.toFixed(2)}}</span>` : `<span style="color:#e74c3c;">-$${{Math.abs(v).toFixed(2)}}</span>`);

  const summaryHtml = `
    <div style="display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px;padding:12px 16px;background:#f8fafc;border-radius:8px;font-size:13px;">
      <span>Open: <b>${{open.length}}</b></span>
      <span>Open gross premium: <b style="color:#1a6e38;">$${{openGross.toFixed(2)}}</b></span>
      ${{hasMtm ? `<span>Unrealized P&amp;L: <b>${{fmtPnl(openMtmTotal)}}</b></span>` : ""}}
      ${{hasMtm ? `<span>Today's option P&amp;L: <b>${{fmtPnl(openMtmDay)}}</b></span>` : ""}}
      <span style="border-left:1px solid #dde;padding-left:16px;">YTD income: <b style="color:#27ae60;">$${{ytdNet.toFixed(2)}}</b></span>
      <span style="color:#aaa;font-size:12px;">All-time: $${{netRealized.toFixed(2)}}</span>
      ${{buybackCost > 0 ? `<span style="color:#aaa;font-size:12px;">($${{grossRealized.toFixed(2)}} gross − $${{buybackCost.toFixed(2)}} buybacks)</span>` : ""}}
    </div>`;

  const th  = s => `<th style="padding:7px 10px;text-align:left;font-size:11px;color:#7f8c8d;text-transform:uppercase;">${{s}}</th>`;
  const thG = s => `<th style="padding:7px 10px;text-align:left;font-size:11px;color:#27ae60;text-transform:uppercase;">${{s}}</th>`;
  const COLS = 14;
  const thead = `<thead id="cc-tracker-thead"><tr style="background:#f4f6f9;">
    ${{th("Ticker")}}${{th("Contracts")}}${{th("Strike")}}${{th("Expiry/DTE")}}
    ${{th("Prem/Contract")}}${{th("Gross")}}
    ${{th("Mark")}}${{thG("Unrealized P&L")}}${{thG("Today's P&L")}}
    ${{thG("Net Realized")}}
    ${{th("Status")}}${{th("Opened")}}${{th("Notes")}}${{th("")}}
  </tr></thead>`;

  let html = summaryHtml + `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">${{thead}}<tbody>`;
  if (open.length) {{
    html += `<tr><td colspan="${{COLS}}" style="padding:5px 10px;font-size:11px;font-weight:700;color:#1a2340;background:#f0f7ff;">Open Positions</td></tr>`;
    html += open.map(p => makeRow(p)).join("");
  }}
  function renderClosedAccordion(positions, sectionLabel, ridPrefix, hdrBg, hdrColor, hdrBorder, dateKey) {{
    if (!positions.length) return;
    const byMonth = {{}};
    positions.forEach(p => {{
      const raw = dateKey(p);
      const d   = raw ? new Date(raw + "T00:00:00") : null;
      const key = d ? d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") : "unknown";
      if (!byMonth[key]) byMonth[key] = [];
      byMonth[key].push(p);
    }});
    const months = Object.keys(byMonth).sort().reverse();
    html += `<tr><td colspan="${{COLS}}" style="padding:5px 10px;font-size:11px;font-weight:700;color:#888;background:#f9f9f9;">${{sectionLabel}}</td></tr>`;
    months.forEach(key => {{
      const [yr, mo] = key.split("-");
      const label = yr === "unknown" ? "Unknown Date"
        : new Date(parseInt(yr), parseInt(mo)-1, 1).toLocaleDateString("en-US", {{month:"long",year:"numeric"}});
      const mp   = byMonth[key];
      const mNet = mp.reduce((s,p) => s + (p.net_premium ?? 0), 0);
      const rid  = ridPrefix + key;
      html += `<tr style="cursor:pointer;background:${{hdrBg}};border-bottom:1px solid ${{hdrBorder}};" onclick="toggleCCMonth('${{rid}}')">
        <td colspan="${{COLS}}" style="padding:7px 12px;font-size:12px;font-weight:700;color:${{hdrColor}};">
          <span id="${{rid}}-arrow" style="display:inline-block;margin-right:6px;transition:transform 0.15s;">▶</span>
          ${{label}}
          <span style="font-weight:400;opacity:0.7;margin-left:10px;font-size:11px;">${{mp.length}} position${{mp.length>1?"s":""}} · +$${{mNet.toFixed(2)}} net</span>
        </td>
      </tr>`;
      html += mp.map(p => makeRow(p, rid, true)).join("");
    }});
  }}

  const expiredPos  = closed.filter(p => p.status === "expired");
  const otherClosed = closed.filter(p => p.status !== "expired");

  renderClosedAccordion(otherClosed, "Closed / Assigned", "cc-cls-",
    "#f4f6fb", "#555", "#dde", p => p.closed_date || p.expiry);
  renderClosedAccordion(expiredPos, "Expired Worthless", "cc-exp-",
    "#fffdf5", "#8a6d00", "#ffe082", p => p.expiry);
  html += `</tbody></table></div>`;
  if (closed.length || open.length) {{
    html = `<canvas id="cc-income-chart" style="max-height:185px;margin-bottom:16px;"></canvas>` + html;
  }}
  results.innerHTML = html;
  if (closed.length || open.length) {{
    (function() {{
      const monthData = {{}};
      function addToMonth(p, type, raw, amount) {{
        if (!raw) return;
        const d = new Date(raw + "T00:00:00");
        const key = d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0");
        if (!monthData[key]) monthData[key] = {{expired:0, closed:0, pending:0}};
        monthData[key][type] += amount;
      }}
      const isPreSystem = p => p.notes === "pre-system income entry";
      otherClosed.filter(p => !isPreSystem(p)).forEach(p => addToMonth(p, "closed",  p.closed_date || p.expiry, p.net_premium ?? 0));
      expiredPos.filter(p  => !isPreSystem(p)).forEach(p => addToMonth(p, "expired", p.expiry,                  p.net_premium ?? 0));
      open.forEach(p        => addToMonth(p, "pending", p.opened_date,              p.premium_per_contract * p.contracts * 100));
      const months = Object.keys(monthData).sort();
      const moNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      const labels = months.map(k => {{
        const [yr, mo] = k.split("-");
        return moNames[parseInt(mo)-1] + " '" + yr.slice(2);
      }});
      if (window._ccIncomeChart) window._ccIncomeChart.destroy();
      window._ccIncomeChart = new Chart(document.getElementById("cc-income-chart"), {{
        type: "bar",
        data: {{
          labels,
          datasets: [
            {{
              label: "Expired Worthless",
              data: months.map(k => monthData[k].expired),
              backgroundColor: "rgba(255,193,7,0.75)",
              borderColor: "#f0c000",
              borderWidth: 1,
              stack: "income",
            }},
            {{
              label: "Closed / Assigned",
              data: months.map(k => monthData[k].closed),
              backgroundColor: "rgba(90,120,190,0.65)",
              borderColor: "#8aa0d0",
              borderWidth: 1,
              stack: "income",
            }},
            {{
              label: "Pending (Open)",
              data: months.map(k => monthData[k].pending),
              backgroundColor: "rgba(120,140,180,0.18)",
              borderColor: "rgba(90,120,190,0.6)",
              borderWidth: 2,
              stack: "income",
            }},
          ],
        }},
        options: {{
          responsive: true,
          plugins: {{
            legend: {{position:"bottom", labels:{{font:{{size:11}}}}}},
            tooltip: {{
              callbacks: {{
                label: ctx => {{
                  const v = ctx.parsed.y;
                  if (!v) return null;
                  const prefix = ctx.dataset.label === "Pending (Open)" ? " (gross) " : " ";
                  return prefix + ctx.dataset.label + ": +$" + v.toFixed(2);
                }},
                footer: items => {{
                  const tot = items.reduce((s,i) => s + i.parsed.y, 0);
                  return tot ? ` Total: +$${{tot.toFixed(2)}}` : null;
                }},
              }},
            }},
          }},
          scales: {{
            x: {{stacked:true, grid:{{display:false}}, ticks:{{font:{{size:11}}}}}},
            y: {{stacked:true, ticks:{{callback: v => "$" + v, font:{{size:11}}}}, grid:{{color:"#f0f0f0"}}}},
          }},
        }},
      }});
    }})();
  }}
}}

function toggleCCMonth(id) {{
  const rows  = document.querySelectorAll(`[data-ccmonth="${{id}}"]`);
  const arrow = document.getElementById(id + "-arrow");
  const isHidden = rows.length && rows[0].style.display === "none";
  rows.forEach(r => r.style.display = isHidden ? "" : "none");
  if (arrow) arrow.style.transform = isHidden ? "rotate(90deg)" : "";
}}

async function importCCFromCSV() {{
  const status = document.getElementById("cc-tracker-status");
  status.textContent = "Importing from covered_calls.csv…";
  try {{
    const res  = await fetch("/api/cc-import", {{method:"POST"}});
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Import error: " + data.error; return; }}
    status.textContent = `✓ Imported ${{data.added}} position(s), ${{data.skipped}} already existed.`;
    setTimeout(() => {{ status.textContent = ""; }}, 4000);
    loadCCPositions();
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
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

// ── CC Edit Modal ─────────────────────────────────────────────────────────
function openCCEditModal(id) {{
  _ccEditTargetId = id;
  const p = _allCCPositions.find(x => x.id === id);
  if (!p) return;
  document.getElementById("cc-edit-ticker").value      = p.ticker;
  document.getElementById("cc-edit-contracts").value   = p.contracts;
  document.getElementById("cc-edit-strike").value      = p.strike;
  document.getElementById("cc-edit-expiry").value      = p.expiry;
  document.getElementById("cc-edit-premium").value     = p.premium_per_contract;
  document.getElementById("cc-edit-opened-date").value = p.opened_date;
  document.getElementById("cc-edit-notes").value       = p.notes || "";
  document.getElementById("cc-edit-status").textContent = "";
  document.getElementById("cc-edit-overlay").style.display = "flex";
}}

function closeCCEditModal(e) {{
  if (!e || e.target === document.getElementById("cc-edit-overlay"))
    document.getElementById("cc-edit-overlay").style.display = "none";
}}

async function saveCCEdit() {{
  const status = document.getElementById("cc-edit-status");
  const body = {{
    ticker:               (document.getElementById("cc-edit-ticker").value || "").trim().toUpperCase(),
    contracts:            parseInt(document.getElementById("cc-edit-contracts").value),
    strike:               parseFloat(document.getElementById("cc-edit-strike").value),
    expiry:               document.getElementById("cc-edit-expiry").value,
    premium_per_contract: parseFloat(document.getElementById("cc-edit-premium").value),
    opened_date:          document.getElementById("cc-edit-opened-date").value,
    notes:                document.getElementById("cc-edit-notes").value,
  }};
  if (!body.ticker || !body.contracts || !body.strike || !body.expiry ||
      !body.premium_per_contract || !body.opened_date) {{
    status.textContent = "⚠ Fill in all required fields.";
    return;
  }}
  status.textContent = "Saving…";
  try {{
    const res  = await fetch(`/api/cc-positions/${{_ccEditTargetId}}`, {{
      method: "PATCH", headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify(body),
    }});
    const data = await res.json();
    if (!data.ok) {{ status.textContent = "Error: " + data.error; return; }}
    document.getElementById("cc-edit-overlay").style.display = "none";
    loadCCPositions();
  }} catch(e) {{ status.textContent = "Error: " + e.message; }}
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

// ── Covered Call AI Analysis ──────────────────────────────────────────────
function onCCTickerChange(val) {{
  const btn = document.getElementById("cc-ai-btn");
  if (val) {{
    btn.disabled = false;
    btn.style.background = "#6c5ce7";
    btn.style.cursor = "pointer";
    btn.style.opacity = "1";
  }} else {{
    btn.disabled = true;
    btn.style.background = "#b0a8e0";
    btn.style.cursor = "not-allowed";
    btn.style.opacity = "0.6";
  }}
  document.getElementById("cc-ai-panel").style.display = "none";
}}

async function getAIAnalysis() {{
  const ticker = document.getElementById("cc-ticker").value;
  if (!ticker) {{ alert("Select a ticker first, then click Get Recommendations to load options data."); return; }}
  const btn     = document.getElementById("cc-ai-btn");
  const panel   = document.getElementById("cc-ai-panel");
  const content = document.getElementById("cc-ai-content");
  btn.disabled = true;
  btn.textContent = "⏳ Analyzing…";
  panel.style.display = "block";
  content.innerHTML =
    `<pre id="cc-ai-stream" style="margin:0;font-size:11px;color:#555;white-space:pre-wrap;` +
    `word-break:break-word;max-height:220px;overflow-y:auto;background:#f4f4f4;` +
    `padding:0.6rem;border-radius:5px;line-height:1.5"></pre>`;
  const streamEl = document.getElementById("cc-ai-stream");
  try {{
    // Start background job — connection drops won't abort the Ollama run
    const startRes = await fetch("/api/analysis-job", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{type: "cc-ai", ticker}}),
    }});
    if (!startRes.ok) {{
      const err = await startRes.json().catch(() => ({{error: startRes.statusText}}));
      throw new Error(err.error || "Failed to start analysis");
    }}
    const startData = await startRes.json();
    if (!startData.ok) throw new Error(startData.error);
    const jobId = startData.job_id;

    // Poll — each response includes accumulated Ollama output in `progress`
    let lastProgress = "";
    while (true) {{
      await new Promise(r => setTimeout(r, 1000));
      let poll;
      try {{
        const pollRes = await fetch(`/api/analysis-job/${{jobId}}`);
        poll = await pollRes.json();
      }} catch (_) {{
        streamEl.textContent = (lastProgress || "AI is thinking…") + "\\n[reconnecting…]";
        continue;
      }}
      if (poll.status === "error") throw new Error(poll.error);
      if (poll.progress && poll.progress !== lastProgress) {{
        lastProgress = poll.progress;
        if (poll.progress === "Sending to AI…") {{
          streamEl.textContent = poll.progress;
        }} else {{
          // Show raw token stream until done event renders the formatted panel
          streamEl.textContent = poll.progress;
          streamEl.scrollTop = streamEl.scrollHeight;
        }}
      }}
      if (poll.status === "done") {{
        renderAIInsights(poll.result);
        break;
      }}
    }}
  }} catch(e) {{
    content.innerHTML = `<p style="color:#e74c3c;margin:0">Analysis failed: ${{e.message}}</p>`;
  }} finally {{
    btn.disabled = false;
    btn.textContent = "🤖 AI Analysis";
  }}
}}

function renderAIInsights(data) {{
  const ins = data.insight;
  const rec = ins.recommendation;
  // Highlight the recommended row in the existing recs table
  document.querySelectorAll("#cc-results table tbody tr").forEach(tr => {{
    const txt = tr.textContent;
    if (txt.includes(rec.expiration) && txt.includes(String(rec.strike))) {{
      tr.style.outline = "2.5px solid #6c5ce7";
      tr.style.outlineOffset = "-2px";
    }}
  }});
  document.getElementById("cc-ai-model").textContent = data.model;
  const sec = (icon, title, body) =>
    `<div style="margin-bottom:0.9rem">
       <div style="font-weight:600;color:#2c3e50;font-size:13px;margin-bottom:0.3rem">${{icon}} ${{title}}</div>
       <div style="color:#444;font-size:13px;line-height:1.6">${{body}}</div>
     </div>`;
  const risks = Array.isArray(ins.risks)
    ? `<ul style="margin:0.2rem 0 0 1.1rem;padding:0">${{ins.risks.map(r => `<li style="margin-bottom:0.25rem">${{r}}</li>`).join("")}}</ul>`
    : ins.risks || "";
  document.getElementById("cc-ai-content").innerHTML =
    sec("🎯", "My Pick",
      `<strong>#${{rec.rank}} — ${{rec.expiration}} $${{rec.strike}} call</strong><br>${{rec.summary}}`) +
    sec("💵", "What You're Agreeing To", ins.the_trade || ins.iv_context || "") +
    sec("📈", "Market Conditions Right Now", ins.market_conditions || ins.iv_context || "") +
    sec("⚠️", "What Could Go Wrong", ins.what_could_go_wrong || ins.no_call_case || "") +
    sec("🔍", "Things to Watch",
      (risks ? risks + "<br>" : "") + (ins.what_to_watch || ins.roll_strategy || "")) +
    (ins.timing_advice ? sec("⏰", "Timing", ins.timing_advice) : "");
  document.getElementById("cc-ai-panel").style.display = "block";
}}

// ── Covered Call Analyzer ─────────────────────────────────────────────────
function setCCSpreadFilter(mode) {{
  const res = document.getElementById('cc-results');
  if (!res) return;
  const allRows   = res.querySelectorAll('.cc-row-all');
  const failRows  = res.querySelectorAll('.cc-row-fail');
  const tightRows = res.querySelectorAll('.cc-row-tight');
  const bestRows  = res.querySelectorAll('.cc-row-best');
  const secHdrs   = res.querySelectorAll('.cc-sec-hdr');

  allRows.forEach(tr   => {{ tr.style.display = mode === 'all'   ? '' : 'none'; }});
  failRows.forEach(tr  => {{ tr.style.display = 'none'; }});
  secHdrs.forEach(el   => {{ el.style.display = mode === 'all'   ? '' : 'none'; }});
  tightRows.forEach(tr => {{ tr.style.display = mode === 'tight' ? '' : 'none'; }});
  bestRows.forEach(tr  => {{ tr.style.display = mode === 'best'  ? '' : 'none'; }});

  const failHdr = document.getElementById('cc-sec-hdr-fail');
  if (failHdr) {{ const ch = failHdr.querySelector('.cc-chevron'); if (ch) ch.textContent = '▶'; }}

  [['cc-filter-all','#6c5ce7'],['cc-filter-tight','#27ae60'],['cc-filter-best','#1a7ab5']].forEach(([id,color]) => {{
    const btn = document.getElementById(id);
    if (!btn) return;
    const active = id === 'cc-filter-' + mode;
    btn.style.background = active ? color  : '#fff';
    btn.style.color      = active ? '#fff' : color;
    btn.style.fontWeight = active ? '700'  : '600';
  }});

  ['all','tight','best'].forEach(m => {{
    const f = document.getElementById('cc-footer-' + m);
    if (f) f.style.display = m === mode ? '' : 'none';
  }});

  const nm = document.getElementById('cc-tight-none');
  if (nm) nm.style.display = (mode === 'tight' && tightRows.length === 0) ? '' : 'none';
}}

function toggleCCFloorFail() {{
  const rows = document.querySelectorAll('#cc-results .cc-row-fail');
  const hdr  = document.getElementById('cc-sec-hdr-fail');
  const ch   = hdr ? hdr.querySelector('.cc-chevron') : null;
  const hidden = !rows.length || rows[0].style.display === 'none';
  rows.forEach(tr => {{ tr.style.display = hidden ? '' : 'none'; }});
  if (ch) ch.textContent = hidden ? '▼' : '▶';
}}

async function analyzeCoveredCall(force = false) {{
  const ticker = document.getElementById("cc-ticker").value;
  if (!ticker) return;
  const status     = document.getElementById("cc-status");
  const results    = document.getElementById("cc-results");
  const btn        = document.getElementById("cc-btn");
  const refreshBtn = document.getElementById("cc-refresh-btn");

  btn.disabled = true;
  btn.textContent = "Fetching…";
  if (refreshBtn) {{ refreshBtn.disabled = true; refreshBtn.textContent = "Refreshing…"; }}
  status.textContent = "";
  results.innerHTML  = "";

  try {{
    const url  = `/api/covered-calls?ticker=${{ticker}}${{force ? '&force=1' : ''}}`;
    const res  = await fetch(url);
    const data = await res.json();

    if (!data.ok) {{
      status.textContent = "⚠ " + (data.error || "No results.");
    }} else {{
      results.innerHTML = renderCC(data);
      if (refreshBtn) refreshBtn.style.display = "";
    }}
  }} catch(e) {{
    status.textContent = "Error: " + e.message;
  }} finally {{
    btn.disabled = false;
    btn.textContent = "Get Recommendations";
    if (refreshBtn) {{ refreshBtn.disabled = false; refreshBtn.textContent = "↺ Force Refresh"; }}
  }}
}}

function prefillCCLog(ticker, contracts, strike, expiry, premium) {{
  document.getElementById("cc-log-ticker").value    = ticker;
  document.getElementById("cc-log-contracts").value = contracts;
  document.getElementById("cc-log-strike").value    = strike;
  document.getElementById("cc-log-expiry").value    = expiry;
  document.getElementById("cc-log-premium").value   = premium.toFixed(2);
  document.getElementById("cc-log-date").value      = new Date().toISOString().slice(0,10);
  const details = document.querySelector("#cc-tracker-card details");
  if (details) details.open = true;
  document.getElementById("cc-tracker-card").scrollIntoView({{behavior:"smooth"}});
}}

async function evaluateCCPositions() {{
  const btn   = document.getElementById("cc-eval-btn");
  const panel = document.getElementById("cc-eval-panel");
  const cont  = document.getElementById("cc-eval-content");
  btn.disabled = true;
  btn.textContent = "⏳ Evaluating…";
  panel.style.display = "block";
  cont.innerHTML = '<div style="font-size:12px;color:#555;">Fetching live data for open positions…</div>';
  try {{
    const res  = await fetch("/api/cc-evaluate");
    const data = await res.json();
    if (!data.ok) {{
      cont.innerHTML = `<div style="color:#c0392b;font-size:13px;">Error: ${{data.error || "Unknown error"}}</div>`;
      return;
    }}
    if (!data.evaluations || data.evaluations.length === 0) {{
      cont.innerHTML = '<div style="font-size:13px;color:#555;">No open positions found.</div>';
      return;
    }}
    const badgeStyle = {{
      hold:     "background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7",
      roll:     "background:#fff3e0;color:#e65100;border:1px solid #ffcc80",
      buy_back: "background:#fdecea;color:#c62828;border:1px solid #ef9a9a",
      unknown:  "background:#f4f6f9;color:#555;border:1px solid #dde",
    }};
    const badgeLabel = {{ hold:"HOLD", roll:"ROLL", buy_back:"BUY BACK", unknown:"?" }};
    const rows = data.evaluations.map(ev => {{
      const rec    = ev.recommendation || "unknown";
      const bStyle = badgeStyle[rec] || badgeStyle.unknown;
      const bLabel = badgeLabel[rec] || rec.toUpperCase();
      const badge  = `<span style="font-size:11px;font-weight:700;padding:3px 10px;border-radius:12px;${{bStyle}}">${{bLabel}}</span>`;
      const price  = ev.current_price != null ? `${{ev.current_price.toFixed(2)}}` : "—";
      const mark   = ev.current_mark  != null ? `${{ev.current_mark.toFixed(2)}}` : "—";
      const delta  = ev.delta         != null ? `Δ${{(ev.delta*100).toFixed(0)}}%` : "";
      const dte    = ev.dte           != null ? `${{ev.dte}}d` : "";
      const pct    = ev.pct_captured  != null ? `${{ev.pct_captured.toFixed(0)}}% cap` : "";
      const extStr = ev.remaining_extrinsic != null && ev.remaining_extrinsic_ann_yield != null
        ? `ext ${{ev.remaining_extrinsic.toFixed(2)}} (${{ev.remaining_extrinsic_ann_yield.toFixed(1)}}%/yr)`
        : "";
      const meta   = [price, delta, dte, pct, extStr].filter(Boolean).join(" · ");
      const avoid  = ev.has_avoid ? ' <span style="font-size:10px;color:#c62828;">⚠ event risk</span>' : "";
      const errMsg = ev.error ? `<div style="font-size:11px;color:#c0392b;margin-top:3px;">${{ev.error}}</div>` : "";
      let nextHtml = "";
      if (ev.next_contract) {{
        const nc  = ev.next_contract;
        const ncLabel = rec === "roll" ? "Roll into" : "Then write";
        const ncDelta = nc.delta != null ? ` · Δ${{(nc.delta*100).toFixed(0)}}%` : "";
        nextHtml = `<div style="margin-top:5px;padding:5px 8px;background:#fffbea;border:1px solid #ffe082;border-radius:5px;font-size:11px;color:#5d4037;">` +
          `<span style="font-weight:700;">${{ncLabel}}:</span> ` +
          `$${{nc.strike}} call · ${{nc.expiry}} (${{nc.dte}}d) · mid $${{nc.mid.toFixed(2)}} (${{nc.premium_pct.toFixed(2)}}%${{ncDelta}})` +
          `</div>`;
      }}
      return `<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid #d4edda;">
        <div style="min-width:90px">
          <span style="font-weight:700;font-size:14px;">${{ev.ticker}}</span>
          <span style="font-size:11px;color:#777;margin-left:4px;">${{ev.contracts}}× $${{ev.strike}} ${{ev.expiry}}</span>
          ${{avoid}}
        </div>
        <div style="flex:1">
          <div style="margin-bottom:4px;">${{badge}} <span style="font-size:12px;color:#444;margin-left:6px;">${{ev.reason || ""}}</span></div>
          <div style="font-size:11px;color:#888;">${{meta}} · mark ${{mark}}</div>
          ${{nextHtml}}
          ${{errMsg}}
        </div>
      </div>`;
    }}).join("");
    cont.innerHTML = rows;
  }} catch(e) {{
    cont.innerHTML = `<div style="color:#c0392b;font-size:13px;">Error: ${{e.message}}</div>`;
  }} finally {{
    btn.disabled = false;
    btn.textContent = "🔄 Evaluate Positions";
  }}
}}

function renderCC(d) {{
  const fmt  = v => "$" + v.toFixed(2);
  const pct  = v => v.toFixed(1) + "%";
  const contracts = Math.floor((d.shares || 0) / 100) || 1;

  const gainColor = d.gain_pct >= 0 ? "#27ae60" : "#e74c3c";
  const floorNote = `K + exec_prem ≥ cost × 1.10 (premium counts toward floor)`;
  const w52Color = d.current_price >= d.week52_high * 0.95 ? "#c8102e"
                 : d.current_price >= d.week52_high * 0.80 ? "#e67e22"
                 : "#555";

  let hvHtml = "";
  if (d.hv_rank != null) {{
    const hvColor = d.hv_rank >= 70 ? "#27ae60" : d.hv_rank >= 40 ? "#e67e22" : "#e74c3c";
    const hvLabel = d.hv_rank >= 70 ? "elevated ✓" : d.hv_rank >= 40 ? "moderate" : "compressed";
    let ivRichHtml = "";
    if (d.atm_iv != null && d.hv_forecast) {{
      const rich = (d.atm_iv / 100 / d.hv_forecast - 1) * 100;
      const rColor = rich > 10 ? "#27ae60" : rich < -5 ? "#e74c3c" : "#888";
      const rLabel = rich > 10 ? "rich" : rich < -5 ? "cheap" : "fair";
      ivRichHtml = ` · ATM IV ${{d.atm_iv.toFixed(1)}}% · HVfc ${{(d.hv_forecast*100).toFixed(1)}}% · <b style="color:${{rColor}}">${{rich >= 0 ? "+" : ""}}${{rich.toFixed(1)}}% (${{rLabel}})</b>`;
    }} else if (d.atm_iv != null) {{
      ivRichHtml = ` · ATM IV ${{d.atm_iv.toFixed(1)}}%`;
    }}
    const muHtml = d.mu != null ? ` · μ ${{d.mu >= 0 ? "+" : ""}}${{(d.mu*100).toFixed(1)}}%/yr` : "";
    hvHtml = `<span>HV Pct <b style="color:${{hvColor}}">${{d.hv_rank.toFixed(0)}}%</b> <span style="color:#aaa;font-size:11px;">${{hvLabel}}${{ivRichHtml}}${{muHtml}}</span></span>`;
  }}

  let ivContextHtml = "";
  if (d.hv_rank != null || (d.atm_iv != null && d.hv_forecast)) {{
    const ivRich = (d.atm_iv != null && d.hv_forecast)
      ? (d.atm_iv / 100 / d.hv_forecast - 1) * 100 : null;
    const sellSignal = (d.hv_rank != null && d.hv_rank >= 60) || (ivRich != null && ivRich > 10);
    const thinSignal = (d.hv_rank == null || d.hv_rank < 35) && (ivRich == null || ivRich < -5);
    let sigLabel, sigDetail, sigColor, sigBg;
    if (sellSignal) {{
      sigLabel = "Sell environment"; sigBg = "#d4edda"; sigColor = "#155724";
      sigDetail = "IV elevated vs historical vol — premiums above average";
    }} else if (thinSignal) {{
      sigLabel = "Thin premiums"; sigBg = "#f8d7da"; sigColor = "#721c24";
      sigDetail = "IV compressed below historical vol — consider waiting";
    }} else {{
      sigLabel = "Fair environment"; sigBg = "#fff3cd"; sigColor = "#856404";
      sigDetail = "IV near historical vol — reasonable premiums";
    }}
    ivContextHtml = `<div style="font-size:12px;background:${{sigBg}};color:${{sigColor}};border-radius:5px;padding:5px 10px;margin-bottom:8px;"><b>${{sigLabel}}</b> <span style="font-weight:400;">${{sigDetail}}</span></div>`;
  }}

  let histHtml = "";
  if (d.cc_history && d.cc_history.count > 0) {{
    const h = d.cc_history;
    const netColor = h.total_net >= 0 ? "#155724" : "#721c24";
    const assignedStr = h.assigned_count > 0 ? ` · ${{h.assigned_count}} assigned` : "";
    histHtml = `<div style="font-size:12px;color:#555;background:#f4f6f9;border-radius:5px;padding:5px 10px;margin-bottom:8px;">📋 Past ${{h.count}} CC${{h.count > 1 ? "s" : ""}} on ${{d.ticker}}: <b style="color:${{netColor}}">${{h.total_net >= 0 ? "+" : "-"}}$${{Math.abs(h.total_net).toFixed(2)}} net</b>${{assignedStr}}</div>`;
  }}

  const openStrikesSet = new Set((d.open_calls || []).map(oc => oc.strike + "|" + oc.expiry));

  const meta = `
    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:14px;font-size:13px;">
      <span>Current <b>${{fmt(d.current_price)}}</b></span>
      <span>Avg Cost/Share <b>${{fmt(d.avg_cost)}}</b></span>
      <span>Gain <b style="color:${{gainColor}}">${{d.gain_pct >= 0 ? "+" : ""}}${{pct(d.gain_pct)}}</b></span>
      <span>52w High <b style="color:${{w52Color}}">${{fmt(d.week52_high)}}</b> <span style="color:#aaa;font-size:11px;">${{d.week52_high_dt}}</span></span>
      <span>Min Strike <b>${{fmt(d.strike_floor)}}</b> <span style="color:#888;font-size:11px;">(${{floorNote}})</span></span>
      ${{hvHtml}}
    </div>`;

  const noteHtml = d.note
    ? `<div style="background:#fff8f0;border:1px solid #f5cba7;border-radius:6px;
                   padding:9px 12px;margin-bottom:12px;font-size:12px;color:#7d5a00;">
        ${{d.note}}
       </div>`
    : "";

  const tightRecs      = d.tight_recs || [];
  const tightCount     = tightRecs.length;
  const floorFailRecs  = d.floor_fail_recs || [];
  const floorFailCount = floorFailRecs.length;
  const hasRecs        = d.recs && d.recs.length > 0;
  const bestRecs       = tightRecs.filter(r => r.passes_floor !== false);
  const bestCount      = bestRecs.length;
  const autoMode       = bestCount > 0 ? 'best' : (!hasRecs && tightCount > 0) ? 'tight' : 'all';
  const autoOpenFail   = false;

  if (!hasRecs && tightCount === 0 && floorFailCount === 0) {{
    return meta + noteHtml + `<p style="color:#888;font-size:13px;">No qualifying contracts found.</p>`;
  }}

  function _ccRow(r, i, rowClass, initDisplay) {{
    const spread      = r.spread_width != null ? r.spread_width : (r.ask - r.bid);
    const isLive      = openStrikesSet.has(r.strike + "|" + r.expiration);
    const floorFail   = r.passes_floor === false;
    const rowBg       = floorFail      ? "background:#fafafa;"
                      : isLive         ? "background:#f0fff4;"
                      : r.has_avoid    ? "background:#fff5f5;"
                      : r.has_caution  ? "background:#fffbf0;"
                      : i === 0        ? "background:#f0f7ff;"
                      : "";
    const spreadColor = spread <= 0.10 ? "#27ae60" : spread <= 0.25 ? "#e67e22" : "#e74c3c";
    const plColor     = r.profit_if_called >= 10 ? "#27ae60" : "#e67e22";
    const alphaColor  = r.cc_alpha > 0 ? "#27ae60" : r.cc_alpha < -0.5 ? "#e74c3c" : "#e67e22";
    const regretColor = r.regret_prob < 0.10 ? "#27ae60" : r.regret_prob < 0.20 ? "#e67e22" : "#e74c3c";
    const scoreColor  = r.score >= 70 ? "#27ae60" : r.score >= 45 ? "#e67e22" : "#aaa";

    let blackout = "";
    if (r.has_avoid)   {{ blackout = `<div style="margin-top:4px;font-size:10px;font-weight:700;color:#c8102e;">📵 AVOID</div>`; }}
    else if (r.has_caution) {{ blackout = `<div style="margin-top:4px;font-size:10px;font-weight:700;color:#e67e22;">⚠️ CAUTION</div>`; }}

    const floorBadge = floorFail
      ? `<div style="margin-top:3px;font-size:10px;color:#aaa;">⚠ below profit floor</div>` : "";

    const riskLines = (r.risk_events || []).map(e => {{
      const color = e.severity === "avoid" ? "#c8102e" : "#e67e22";
      const icon  = e.severity === "avoid" ? "📵" : "⚠️";
      return `<div style="font-size:10px;color:${{color}};margin-top:2px;">${{icon}} ${{e.label.replace(/^[📵⚠️\\s]+/, "")}}</div>`;
    }}).join("");

    const liveBadge = isLive
      ? `<span style="font-size:10px;font-weight:700;color:#27ae60;margin-left:5px;background:#d5f5e3;padding:1px 5px;border-radius:3px;">LIVE</span>` : "";
    const logBtn = isLive ? "" :
      `<button onclick="prefillCCLog('${{d.ticker}}', ${{contracts}}, ${{r.strike}}, '${{r.expiration}}', ${{r.mid}})"
         style="font-size:10px;padding:2px 7px;background:#f0f7ff;border:1px solid #6c5ce7;border-radius:4px;cursor:pointer;color:#6c5ce7;font-weight:600;margin-top:4px;display:block;">
         Log →
       </button>`;

    const displayStyle = initDisplay === 'none' ? 'display:none;' : '';
    return `<tr class="${{rowClass}}" style="${{displayStyle}}${{rowBg}}border-bottom:1px solid #f2f4f7;">
      <td style="padding:8px 10px;">
        <span style="font-weight:${{i===0?"700":"400"}}">${{r.expiration}}</span>${{liveBadge}}
        ${{blackout}}${{floorBadge}}
        ${{riskLines}}
        ${{logBtn}}
      </td>
      <td style="padding:8px 10px;">${{fmt(r.strike)}}</td>
      <td style="padding:8px 10px;color:#7f8c8d;">${{r.dte}}d</td>
      <td style="padding:8px 10px;">${{fmt(r.bid)}}</td>
      <td style="padding:8px 10px;">${{fmt(r.ask)}}</td>
      <td style="padding:8px 10px;font-weight:600;color:${{spreadColor}};">${{fmt(spread)}}</td>
      <td style="padding:8px 10px;font-weight:600;">${{fmt(r.mid)}}</td>
      <td style="padding:8px 10px;">${{pct(r.premium_pct)}}</td>
      <td style="padding:8px 10px;font-weight:700;color:#1a2340;">${{pct(r.annualized_ret)}}</td>
      <td style="padding:8px 10px;font-weight:700;color:${{plColor}};">+${{pct(r.profit_if_called)}}</td>
      <td style="padding:8px 10px;color:${{!r.delta ? '#aaa' : r.delta < 0.20 ? '#27ae60' : r.delta < 0.35 ? '#e67e22' : '#e74c3c'}};">${{r.delta ? r.delta.toFixed(2) : '—'}}</td>
      <td style="padding:8px 10px;color:${{r.itm_prob_real == null ? '#aaa' : r.itm_prob_real < 0.20 ? '#27ae60' : r.itm_prob_real < 0.35 ? '#e67e22' : '#e74c3c'}};">${{r.itm_prob_real != null ? (r.itm_prob_real * 100).toFixed(1) + "%" : "—"}}</td>
      <td style="padding:8px 10px;color:#aaa;font-size:11px;">${{r.open_interest ?? "—"}}</td>
      <td style="padding:8px 10px;font-weight:700;color:${{alphaColor}};">${{r.cc_alpha != null ? (r.cc_alpha >= 0 ? "+" : "") + r.cc_alpha.toFixed(2) : "—"}}</td>
      <td style="padding:8px 10px;font-weight:600;color:${{regretColor}};">${{r.regret_prob != null ? (r.regret_prob * 100).toFixed(1) + "%" : "—"}}</td>
      <td style="padding:8px 10px;font-weight:700;color:${{scoreColor}};">${{r.score != null ? r.score.toFixed(0) : "—"}}</td>
      <td style="padding:8px 10px;font-weight:700;color:${{r.opp_score == null ? '#aaa' : r.opp_score >= 65 ? '#27ae60' : r.opp_score >= 40 ? '#e67e22' : '#aaa'}};">${{r.opp_score != null ? r.opp_score.toFixed(0) : "—"}}</td>
    </tr>`;
  }}

  const allRows   = (d.recs || []).map((r, i) => _ccRow(r, i, 'cc-row-all',   autoMode === 'all'   ? '' : 'none')).join('');
  const tightRows = tightRecs.map((r, i)       => _ccRow(r, i, 'cc-row-tight', autoMode === 'tight' ? '' : 'none')).join('');
  const bestRows  = bestRecs.map((r, i)         => _ccRow(r, i, 'cc-row-best',  autoMode === 'best'  ? '' : 'none')).join('');
  const failRows  = floorFailRecs.map((r, i)   => _ccRow(r, i, 'cc-row-fail',  autoOpenFail         ? '' : 'none')).join('');

  const _btnStyle = (color, active) =>
    `font-size:12px;padding:4px 12px;border-radius:14px;border:1.5px solid ${{color}};cursor:pointer;` +
    `font-weight:${{active?'700':'600'}};background:${{active?color:'#fff'}};color:${{active?'#fff':color}};`;
  const allBtnStyle   = _btnStyle('#6c5ce7', autoMode === 'all');
  const tightBtnStyle = _btnStyle('#27ae60', autoMode === 'tight');
  const bestBtnStyle  = _btnStyle('#1a7ab5', autoMode === 'best');

  const filterBar = `
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:10px;flex-wrap:wrap;">
      <span style="font-size:12px;color:#888;font-weight:600;">Show:</span>
      <button id="cc-filter-all" onclick="setCCSpreadFilter('all')" style="${{allBtnStyle}}">
        Qualifying (${{(d.recs || []).length}})
      </button>
      <button id="cc-filter-tight" onclick="setCCSpreadFilter('tight')" style="${{tightBtnStyle}}">
        Liquid (${{tightCount}})
      </button>
      ${{bestCount > 0 ? `<button id="cc-filter-best" onclick="setCCSpreadFilter('best')" style="${{bestBtnStyle}}">Best (${{bestCount}})</button>` : ''}}
      <span id="cc-tight-none" style="display:${{(autoMode==='tight' && tightCount===0)?'':'none'}};font-size:11px;color:#e74c3c;">
        No liquid contracts for this ticker.
      </span>
    </div>`;

  const footerAllStyle   = `display:${{autoMode === 'all'   ? '' : 'none'}};`;
  const footerTightStyle = `display:${{autoMode === 'tight' ? '' : 'none'}};`;
  const footerBestStyle  = `display:${{autoMode === 'best'  ? '' : 'none'}};`;

  const failChevron = autoOpenFail ? '▼' : '▶';
  const failHdrHtml = floorFailCount > 0 ? `
    <tr id="cc-sec-hdr-fail" class="cc-sec-hdr" style="${{autoMode !== 'all' ? 'display:none;' : ''}}background:#f8f8f8;cursor:pointer;" onclick="toggleCCFloorFail()">
      <td colspan="17" style="padding:6px 10px;font-size:11px;color:#aaa;font-weight:600;">
        <span class="cc-chevron">${{failChevron}}</span> Below profit floor (${{floorFailCount}})
      </td>
    </tr>` : '';

  return meta + ivContextHtml + histHtml + filterBar + `
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f4f6f9;">
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Expiry</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Strike</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">DTE</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Bid</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Ask</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;" title="Bid-ask spread. Green ≤$0.10, yellow ≤$0.25, red &gt;$0.25.">Spread</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Mid</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Prem%</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">Ann%</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">P/L if Called</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;" title="Option delta (rate of price change per $1 stock move). Not an exact assignment probability.">Delta</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;" title="Estimated probability stock closes above strike at expiry under real-world drift model. Lower = safer for sellers.">eITM%</th>
        <th style="padding:7px 10px;text-align:left;color:#7f8c8d;font-size:11px;text-transform:uppercase;">OI</th>
        <th style="padding:7px 10px;text-align:left;color:#6c5ce7;font-size:11px;text-transform:uppercase;" title="Expected premium minus expected upside surrendered (real-world drift). Positive = CC beats holding.">CC Alpha $</th>
        <th style="padding:7px 10px;text-align:left;color:#6c5ce7;font-size:11px;text-transform:uppercase;" title="P(S_T > K + premium): probability the CC underperforms simply holding the stock.">Regret %</th>
        <th style="padding:7px 10px;text-align:left;color:#6c5ce7;font-size:11px;text-transform:uppercase;" title="Multi-factor score within this ticker (25% CC Alpha + 15% each: yield, IV richness, liquidity, upside room, inverse regret). Not comparable across tickers.">Score</th>
        <th style="padding:7px 10px;text-align:left;color:#e67e22;font-size:11px;text-transform:uppercase;" title="Opportunity Score — cross-ticker comparable. Uses fixed absolute scales (not percentile ranks within this ticker). Compare across your holdings.">OppScore</th>
      </tr></thead>
      <tbody>${{allRows}}${{failHdrHtml}}${{failRows}}${{tightRows}}${{bestRows}}</tbody>
    </table>
    </div>
    <p id="cc-footer-all" style="font-size:11px;color:#aaa;margin-top:8px;${{footerAllStyle}}"><b>Qualifying</b> — passes profit floor (K + prem ≥ max(cost×1.10, price)), any spread width. Top ${{(d.recs||[]).length}} ranked by <b style="color:#6c5ce7">Score</b> (within-ticker percentile — not comparable across stocks). Spread color: <b style="color:#27ae60">green</b> ≤$0.10 · <b style="color:#e67e22">yellow</b> ≤$0.25 · <b style="color:#e74c3c">red</b> &gt;$0.25.</p>
    <p id="cc-footer-tight" style="font-size:11px;color:#aaa;margin-top:8px;${{footerTightStyle}}"><b>Liquid</b> — tight bid-ask spread (≤$0.25), easier to fill at a good price. Ranked by <b style="color:#e67e22">OppScore</b>. May include contracts below the profit floor (marked ⚠).</p>
    <p id="cc-footer-best" style="font-size:11px;color:#aaa;margin-top:8px;${{footerBestStyle}}"><b>Best</b> — passes profit floor <i>and</i> has a tight spread (≤$0.25). The intersection of Qualifying and Liquid, ranked by <b style="color:#e67e22">OppScore</b>.</p>
    ${{noteHtml}}`;
}}

// ── Sticky table headers ────────────────────────────────────────────────────
// Watches a set of (theadId, wrapperId) pairs. For dynamic tables (div/screener)
// the thead is injected by JS after load, so we poll until found then attach.
window.addEventListener("load", function() {{
  // [theadId, scrollWrapperId or null (use thead's closest table parent)]
  const TABLES = [
    ["holdings-thead",     "holdings-scroll-wrap"],
    ["div-thead",          null],
    ["screener-thead",     null],
    ["cc-tracker-thead",   null],
  ];

  const ghosts = {{}};

  function makeOrUpdateGhost(id, thead) {{
    const parent = thead.closest("div[style*='overflow-x']") || thead.closest(".table-scroll") || thead.parentElement.parentElement;
    const wrapRect = parent.getBoundingClientRect();

    if (!ghosts[id]) {{
      const g = document.createElement("table");
      g.id = id + "-ghost";
      g.style.cssText =
        "position:fixed;top:0;z-index:200;background:#fff;border-collapse:collapse;" +
        "box-shadow:0 2px 6px rgba(0,0,0,.12);pointer-events:none;";
      g.appendChild(thead.cloneNode(true));
      const liveThs  = thead.querySelectorAll("th");
      const ghostThs = g.querySelectorAll("th");
      liveThs.forEach((th, i) => {{
        if (ghostThs[i]) ghostThs[i].style.width = th.offsetWidth + "px";
      }});
      document.body.appendChild(g);
      ghosts[id] = g;
    }}
    ghosts[id].style.left  = wrapRect.left + "px";
    ghosts[id].style.width = wrapRect.width + "px";
  }}

  function removeGhost(id) {{
    if (ghosts[id]) {{ ghosts[id].remove(); delete ghosts[id]; }}
  }}

  function onScroll() {{
    TABLES.forEach(([theadId]) => {{
      const thead = document.getElementById(theadId);
      if (!thead) return;
      const theadRect = thead.getBoundingClientRect();
      const table     = thead.closest("table");
      const tableRect = table ? table.getBoundingClientRect() : theadRect;
      if (theadRect.top < 0 && tableRect.bottom > 40) {{
        makeOrUpdateGhost(theadId, thead);
      }} else {{
        removeGhost(theadId);
      }}
    }});
  }}

  window.addEventListener("scroll", onScroll, {{ passive: true }});
  window.addEventListener("resize", onScroll,  {{ passive: true }});
}});

async function refreshDashboard() {{
  const btn = document.getElementById("refreshBtn");
  btn.textContent = "Refreshing…";
  btn.disabled = true;
  try {{
    const res = await fetch("/api/refresh-dashboard", {{method:"POST"}});
    if (!res.ok) throw new Error("start failed");
    const d = await res.json();
    if (!d.ok) throw new Error(d.error || "start failed");
    // Poll the background job so we don't hold the connection open through Tailscale
    const jobId = d.job_id;
    while (true) {{
      await new Promise(r => setTimeout(r, 2000));
      let poll;
      try {{
        const pr = await fetch(`/api/analysis-job/${{jobId}}`);
        poll = await pr.json();
      }} catch (_) {{ continue; }}
      if (poll.progress) btn.textContent = poll.progress.replace("Running ", "").replace("…", "…");
      if (poll.status === "done") {{
        btn.textContent = "Done — reloading…";
        setTimeout(() => window.location.href = window.location.pathname + "?t=" + Date.now(), 800);
        return;
      }}
      if (poll.status === "error") throw new Error(poll.error || "refresh failed");
    }}
  }} catch(e) {{
    btn.textContent = "↻ Refresh Data";
    btn.disabled = false;
    alert("Refresh failed: " + e.message);
  }}
}}

// ── Tax Loss Harvesting ────────────────────────────────────────────────────
let _tlhData = null;
let _currentYearTax = {{ stGain: 0, ltGain: 0, stTax: 0, ltTax: 0, totTax: 0 }};

function openTLH() {{
  const overlay = document.getElementById("tlh-overlay");
  overlay.style.display = "flex";
  // sync bracket label and rates
  document.getElementById("tlh-bracket-label").textContent = CURRENT_BRACKET.label;
  document.getElementById("tlh-st-rate").textContent = ((CURRENT_BRACKET.ordinary + CURRENT_BRACKET.niit) * 100).toFixed(1) + "%";
  document.getElementById("tlh-lt-rate").textContent = ((CURRENT_BRACKET.qualified + CURRENT_BRACKET.niit) * 100).toFixed(1) + "%";
  // sync current tax bill (recompute so bracket matches)
  _updateTaxBillKPI();
  const curTaxEl = document.getElementById("tlh-current-tax");
  if (curTaxEl) {{
    curTaxEl.textContent = _currentYearTax.totTax > 0
      ? "$" + Math.round(_currentYearTax.totTax).toLocaleString("en-US")
      : "$0";
  }}
  if (_tlhData) {{ tlhRender(_tlhData); return; }}
  fetch("/api/tlh-analysis")
    .then(r => r.json())
    .then(d => {{
      _tlhData = d;
      tlhRender(d);
    }})
    .catch(e => {{
      document.getElementById("tlh-loading").style.display = "none";
      document.getElementById("tlh-error").style.display = "block";
      document.getElementById("tlh-error").textContent = "Failed to load: " + e;
    }});
}}

function closeTLH() {{ document.getElementById("tlh-overlay").style.display = "none"; }}
function tlhOverlayClick(e) {{ if (e.target === document.getElementById("tlh-overlay")) closeTLH(); }}

// ── All Tax Transactions Modal ────────────────────────────────────────────
function openTxnModal() {{
  const yearFilter = document.getElementById("gains-year-filter")?.value || "cur";
  const curYear    = new Date().getFullYear().toString();
  const stRate     = (parseFloat(document.getElementById("tax-st-rate")?.value) || 35) / 100;
  const ltRate     = (parseFloat(document.getElementById("tax-lt-rate")?.value) || 20) / 100;
  const niit       = document.getElementById("tax-niit")?.checked ? 0.038 : 0;
  const fmt2       = v => "$" + Math.abs(v).toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}});
  const fmtGain    = v => (v >= 0 ? "+" : "−") + fmt2(v);
  const gainColor  = v => v >= 0 ? "#27ae60" : "#e74c3c";

  const PRIOR_ST_2026 = 5288.53;
  const typeLabels = {{ expired:"EXPIRED", buyback:"BUYBACK", assigned:"ASSIGNED", closed:"CC CLOSE" }};
  const typeBg     = {{ expired:"background:#fff8e1;color:#8a6d00;border:1px solid #ffe082",
                        buyback:"background:#f4f6f9;color:#555;border:1px solid #dde",
                        assigned:"background:#fff0f0;color:#c8102e;border:1px solid #fcc",
                        closed:"background:#f4f6f9;color:#555;border:1px solid #dde" }};

  // Build unified list
  const txns = [];

  // 1. Stock sales
  let sells = Object.values(_allSells).flat();
  if (yearFilter === "cur") sells = sells.filter(s => s.sell_date?.startsWith(curYear));
  for (const s of sells) {{
    const lotStr = (s.fifo_detail || []).map(a =>
      `${{a.shares}}sh@$${{a.cost_per_share?.toFixed(2)}} ${{a.term}}`).join(" · ");
    txns.push({{
      typeBadge: `<span style="background:#eef2ff;color:#3a56d4;border:1px solid #c5d0f5;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700;">STOCK</span>`,
      ticker:    s.ticker,
      date:      s.sell_date || "—",
      detail:    `${{s.shares_sold?.toLocaleString("en-US",{{maximumFractionDigits:4}})}} sh @ $${{s.sell_price?.toFixed(2)}}`,
      total:     s.realized_gain || 0,
      st:        s.st_gain || 0,
      lt:        s.lt_gain || 0,
      notes:     lotStr || s.notes || "",
    }});
  }}

  // 2. CC closed positions (always short-term ordinary income)
  const ccClosed = _allCCPositions.filter(p =>
    p.status !== "open" && p.net_premium != null &&
    (yearFilter === "all" || p.closed_date?.startsWith(curYear))
  );
  for (const p of ccClosed) {{
    const ct  = p.close_type || "closed";
    const bg  = typeBg[ct] || typeBg.closed;
    const lbl = typeLabels[ct] || "CC";
    txns.push({{
      typeBadge: `<span style="border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700;${{bg}}">${{lbl}}</span>`,
      ticker:    p.ticker,
      date:      p.closed_date || "—",
      detail:    `${{p.contracts}}× $${{p.strike.toFixed(2)}} call · exp ${{p.expiry}}`,
      total:     p.net_premium,
      st:        p.net_premium,  // always ST
      lt:        0,
      notes:     p.notes || "",
    }});
  }}

  // 3. Prior-year ST lump (current year view only)
  if (yearFilter === "cur" && PRIOR_ST_2026 > 0) {{
    txns.push({{
      typeBadge: `<span style="background:#fff8e1;color:#8a6d00;border:1px solid #ffe082;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700;">PRIOR ST</span>`,
      ticker:    "—",
      date:      "pre-tracker",
      detail:    "Prior 2026 ST gains (pre-tracker lump)",
      total:     PRIOR_ST_2026,
      st:        PRIOR_ST_2026,
      lt:        0,
      notes:     "Unvalidated · review source records",
    }});
  }}

  // Sort by date desc (pre-tracker sorts last)
  txns.sort((a, b) => b.date.localeCompare(a.date));

  // Totals
  const totST   = txns.reduce((s, t) => s + t.st, 0);
  const totLT   = txns.reduce((s, t) => s + t.lt, 0);
  const totAll  = txns.reduce((s, t) => s + t.total, 0);
  const totTax  = Math.max(0, totST) * (stRate + niit) + Math.max(0, totLT) * (ltRate + niit);

  document.getElementById("txn-subtitle").textContent =
    `${{txns.length}} transaction${{txns.length !== 1 ? "s" : ""}} · ${{yearFilter === "cur" ? curYear : "All Time"}} · ST ${{(stRate*100).toFixed(1)}}%${{niit ? " +3.8% NIIT" : ""}} / LT ${{(ltRate*100).toFixed(1)}}%`;

  if (!txns.length) {{
    document.getElementById("txn-modal-content").innerHTML =
      `<div style="padding:40px;text-align:center;color:#aaa;">No transactions recorded${{yearFilter === "cur" ? " for " + curYear : " yet"}}.</div>`;
    document.getElementById("txn-overlay").style.display = "flex";
    return;
  }}

  const rows = txns.map(t => {{
    const rowST  = Math.max(0, t.st) * (stRate + niit);
    const rowLT  = Math.max(0, t.lt) * (ltRate + niit);
    const rowTax = rowST + rowLT;
    return `<tr style="border-bottom:1px solid #f5f5f5;">
      <td style="padding:7px 8px;">${{t.typeBadge}}</td>
      <td style="padding:7px 8px;font-weight:600;">${{t.ticker}}</td>
      <td style="padding:7px 8px;color:#555;white-space:nowrap;">${{t.date}}</td>
      <td style="padding:7px 8px;font-size:11px;color:#555;">${{t.detail}}</td>
      <td style="padding:7px 8px;font-weight:700;color:${{gainColor(t.total)}};">${{fmtGain(t.total)}}</td>
      <td style="padding:7px 8px;color:${{t.st !== 0 ? gainColor(t.st) : "#ccc"}};">${{t.st !== 0 ? fmtGain(t.st) : "—"}}</td>
      <td style="padding:7px 8px;color:${{t.lt !== 0 ? gainColor(t.lt) : "#ccc"}};">${{t.lt !== 0 ? fmtGain(t.lt) : "—"}}</td>
      <td style="padding:7px 8px;color:#c0392b;font-weight:600;">${{rowTax > 0 ? "~" + fmt2(rowTax) : "—"}}</td>
      <td style="padding:7px 8px;font-size:10px;color:#aaa;max-width:200px;">${{t.notes}}</td>
    </tr>`;
  }}).join("");

  const totRow = `<tr style="background:#f4f6f9;font-weight:700;border-top:2px solid #dde;">
    <td colspan="4" style="padding:8px;font-size:11px;color:#555;">TOTAL · ${{txns.length}} transaction${{txns.length!==1?"s":""}}</td>
    <td style="padding:8px;color:${{gainColor(totAll)}};">${{fmtGain(totAll)}}</td>
    <td style="padding:8px;color:${{gainColor(totST)}};">${{fmtGain(totST)}}</td>
    <td style="padding:8px;color:${{totLT !== 0 ? gainColor(totLT) : "#ccc"}};">${{totLT !== 0 ? fmtGain(totLT) : "—"}}</td>
    <td style="padding:8px;color:#c0392b;">~${{fmt2(totTax)}}</td>
    <td style="padding:8px;"></td>
  </tr>`;

  document.getElementById("txn-modal-content").innerHTML = `
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#f4f6f9;text-align:left;">
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Type</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Ticker</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Date</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Detail</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Total G/L</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">ST</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">LT</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Est. Tax</th>
          <th style="padding:6px 8px;font-size:10px;color:#888;text-transform:uppercase;">Notes / Lots</th>
        </tr></thead>
        <tbody>${{rows}}${{totRow}}</tbody>
      </table>
    </div>
    <div style="font-size:10px;color:#bbb;margin-top:10px;">
      Federal only · ST ${{(stRate*100).toFixed(1)}}%${{niit?" +3.8% NIIT":""}} / LT ${{(ltRate*100).toFixed(1)}}%${{niit?" +3.8% NIIT":""}} · does not include state taxes · consult a tax advisor
    </div>`;

  document.getElementById("txn-overlay").style.display = "flex";
}}

function closeTxnModal() {{ document.getElementById("txn-overlay").style.display = "none"; }}
function txnOverlayClick(e) {{ if (e.target === document.getElementById("txn-overlay")) closeTxnModal(); }}

function tlhFmt(v) {{
  const abs = Math.abs(v);
  const s = "$" + abs.toLocaleString("en-US", {{minimumFractionDigits:0, maximumFractionDigits:0}});
  return v < 0 ? "-" + s : "+" + s;
}}
function tlhMoney(v) {{
  return "$" + Math.abs(v).toLocaleString("en-US", {{minimumFractionDigits:0, maximumFractionDigits:0}});
}}

function tlhRender(data) {{
  document.getElementById("tlh-loading").style.display = "none";
  document.getElementById("tlh-content").style.display = "block";

  const tbody = document.getElementById("tlh-tbody");
  tbody.innerHTML = "";

  (data.positions || []).forEach((pos, i) => {{
    const isLoss = pos.total_pnl < 0;
    const pnlColor = pos.total_pnl < -0.01 ? "#e74c3c" : pos.total_pnl > 0.01 ? "#27ae60" : "#888";

    // Main position row
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid #f0f3f8";
    tr.style.transition = "background .1s";
    tr.onmouseenter = () => tr.style.background = "#f8fafd";
    tr.onmouseleave = () => tr.style.background = "";
    tr.innerHTML = `
      <td style="padding:10px 6px;text-align:left;">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
          <input type="checkbox" class="tlh-pos-check" data-idx="${{i}}" onchange="tlhCalc()"
            ${{isLoss ? "checked" : ""}}
            style="cursor:pointer;width:14px;height:14px;">
          <span style="font-weight:700;color:#1a2340;">${{pos.ticker}}</span>
        </label>
      </td>
      <td style="padding:10px 6px;text-align:right;color:#444;">${{pos.total_shares.toLocaleString()}}</td>
      <td style="padding:10px 6px;text-align:right;color:#444;">$${{pos.avg_cost.toFixed(2)}}</td>
      <td style="padding:10px 6px;text-align:right;color:#444;">$${{pos.price.toFixed(2)}}</td>
      <td style="padding:10px 6px;text-align:right;color:#444;">$${{pos.total_value.toLocaleString("en-US",{{maximumFractionDigits:0}})}}</td>
      <td style="padding:10px 6px;text-align:right;color:${{pos.st_pnl < 0 ? "#e74c3c" : pos.st_pnl > 0 ? "#27ae60" : "#888"}};">${{pos.st_pnl !== 0 ? tlhFmt(pos.st_pnl) : "—"}}</td>
      <td style="padding:10px 6px;text-align:right;color:${{pos.lt_pnl < 0 ? "#e74c3c" : pos.lt_pnl > 0 ? "#27ae60" : "#888"}};">${{pos.lt_pnl !== 0 ? tlhFmt(pos.lt_pnl) : "—"}}</td>
      <td style="padding:10px 6px;text-align:right;font-weight:600;color:${{pnlColor}};">${{tlhFmt(pos.total_pnl)}}</td>
      <td style="padding:10px 6px;text-align:center;">
        <button onclick="tlhToggleLots(${{i}})" style="font-size:11px;background:#f0f3f8;border:none;border-radius:4px;padding:3px 8px;cursor:pointer;color:#555;" title="Show lots">
          ${{pos.lots.length}} lot${{pos.lots.length !== 1 ? "s" : ""}} ▾
        </button>
      </td>`;
    tbody.appendChild(tr);

    // Expandable lots sub-rows (hidden by default)
    const lotsRow = document.createElement("tr");
    lotsRow.id = `tlh-lots-${{i}}`;
    lotsRow.style.display = "none";
    const lotsCell = document.createElement("td");
    lotsCell.colSpan = 9;
    lotsCell.style.padding = "0 6px 12px 28px";
    lotsCell.innerHTML = `<table style="width:100%;font-size:12px;border-collapse:collapse;color:#555;">
      <tr style="color:#aaa;font-size:10px;text-transform:uppercase;">
        <th style="padding:4px 6px;text-align:left;">Date</th>
        <th style="padding:4px 6px;text-align:right;">Days Held</th>
        <th style="padding:4px 6px;text-align:right;">Type</th>
        <th style="padding:4px 6px;text-align:right;">Shares</th>
        <th style="padding:4px 6px;text-align:right;">Cost/sh</th>
        <th style="padding:4px 6px;text-align:right;">Basis</th>
        <th style="padding:4px 6px;text-align:right;">Mkt Value</th>
        <th style="padding:4px 6px;text-align:right;">P&L</th>
      </tr>
      ${{pos.lots.map(l => `
        <tr style="border-top:1px solid #f5f5f5;">
          <td style="padding:4px 6px;">${{l.purchase_date}}</td>
          <td style="padding:4px 6px;text-align:right;">${{l.days_held}}</td>
          <td style="padding:4px 6px;text-align:right;">
            <span style="background:${{l.is_lt ? "#e8f4e8" : "#fef3e2"}};color:${{l.is_lt ? "#2e7d32" : "#e65100"}};border-radius:3px;padding:1px 6px;font-size:10px;">${{l.is_lt ? "LONG" : "SHORT"}}</span>
          </td>
          <td style="padding:4px 6px;text-align:right;">${{l.shares}}</td>
          <td style="padding:4px 6px;text-align:right;">$${{l.cost_per_share.toFixed(2)}}</td>
          <td style="padding:4px 6px;text-align:right;">$${{l.cost_basis.toLocaleString("en-US",{{maximumFractionDigits:0}})}}</td>
          <td style="padding:4px 6px;text-align:right;">$${{l.mkt_value.toLocaleString("en-US",{{maximumFractionDigits:0}})}}</td>
          <td style="padding:4px 6px;text-align:right;font-weight:600;color:${{l.pnl < 0 ? "#e74c3c" : "#27ae60"}};">${{tlhFmt(l.pnl)}}</td>
        </tr>`).join("")}}
    </table>`;
    lotsRow.appendChild(lotsCell);
    tbody.appendChild(lotsRow);
  }});

  tlhCalc();
}}

function tlhToggleLots(i) {{
  const row = document.getElementById(`tlh-lots-${{i}}`);
  if (!row) return;
  row.style.display = row.style.display === "none" ? "table-row" : "none";
}}

function tlhToggleAll(checked) {{
  document.querySelectorAll(".tlh-pos-check").forEach(cb => cb.checked = checked);
  tlhCalc();
}}

function tlhCalc() {{
  if (!_tlhData) return;
  const positions = _tlhData.positions || [];
  const checks = document.querySelectorAll(".tlh-pos-check");

  let stLoss = 0, stGain = 0, ltLoss = 0, ltGain = 0;
  const selectedLossTickers = [];

  checks.forEach((cb, i) => {{
    if (!cb.checked || i >= positions.length) return;
    const p = positions[i];
    if (p.st_pnl < 0) stLoss += Math.abs(p.st_pnl);
    else stGain += p.st_pnl;
    if (p.lt_pnl < 0) ltLoss += Math.abs(p.lt_pnl);
    else ltGain += p.lt_pnl;
    if (p.total_pnl < 0) selectedLossTickers.push(p.ticker);
  }});

  // display buckets
  document.getElementById("tlh-st-loss").textContent = stLoss > 0 ? "-" + tlhMoney(stLoss) : "$0";
  document.getElementById("tlh-lt-loss").textContent = ltLoss > 0 ? "-" + tlhMoney(ltLoss) : "$0";
  document.getElementById("tlh-st-gain").textContent = stGain > 0 ? "+" + tlhMoney(stGain) : "$0";
  document.getElementById("tlh-lt-gain").textContent = ltGain > 0 ? "+" + tlhMoney(ltGain) : "$0";

  // IRS netting: ST losses offset ST gains first, then LT gains; vice versa
  const stOrdRate  = CURRENT_BRACKET.ordinary + CURRENT_BRACKET.niit;
  const ltQualRate = CURRENT_BRACKET.qualified + CURRENT_BRACKET.niit;

  let netST = stGain - stLoss;
  let netLT = ltGain - ltLoss;

  // cross-netting between ST and LT
  if (netST < 0 && netLT > 0) {{
    const absorb = Math.min(Math.abs(netST), netLT);
    netLT -= absorb;
    netST += absorb;
  }} else if (netLT < 0 && netST > 0) {{
    const absorb = Math.min(Math.abs(netLT), netST);
    netST -= absorb;
    netLT += absorb;
  }}

  // tax impact per bucket (positive = owe more, negative = save)
  const stTaxImpact  = netST * stOrdRate;
  const ltTaxImpact  = netLT * ltQualRate;

  // ordinary income offset: applies only when total net is a loss
  const overallNetLoss = Math.max(0, -(netST + netLT));
  const ordOffset      = Math.min(3000, overallNetLoss);
  const ordBenefit     = ordOffset * stOrdRate;
  const carryForward   = Math.max(0, overallNetLoss - 3000);

  // net tax impact from this harvest: positive = you'll owe MORE, negative = you'll save
  const netTaxImpact = stTaxImpact + ltTaxImpact - ordBenefit;

  // ── display ──────────────────────────────────────────────────────────────

  document.getElementById("tlh-net-st").textContent = netST === 0 ? "—" :
    (netST > 0 ? "+" + tlhMoney(netST) + " owed" : "-" + tlhMoney(Math.abs(netST)) + " saved");
  document.getElementById("tlh-net-st").style.color = netST > 0 ? "#e74c3c" : netST < 0 ? "#27ae60" : "#888";

  document.getElementById("tlh-net-lt").textContent = netLT === 0 ? "—" :
    (netLT > 0 ? "+" + tlhMoney(netLT) + " owed" : "-" + tlhMoney(Math.abs(netLT)) + " saved");
  document.getElementById("tlh-net-lt").style.color = netLT > 0 ? "#e74c3c" : netLT < 0 ? "#27ae60" : "#888";

  const ordRow = document.getElementById("tlh-ordinary-row");
  if (ordBenefit > 0.5) {{
    ordRow.style.display = "flex";
    document.getElementById("tlh-ordinary-save").textContent = "-" + tlhMoney(ordBenefit) + " saved";
  }} else {{ ordRow.style.display = "none"; }}

  const cfRow = document.getElementById("tlh-carryforward-row");
  if (carryForward > 0.5) {{
    cfRow.style.display = "flex";
    document.getElementById("tlh-carryforward").textContent = tlhMoney(carryForward) + " → next year";
  }} else {{ cfRow.style.display = "none"; }}

  // "Harvest tax impact" row — bidirectional
  const impactEl = document.getElementById("tlh-total-savings");
  if (Math.abs(netTaxImpact) < 0.5) {{
    impactEl.textContent = "$0";
    impactEl.style.color = "#888";
  }} else if (netTaxImpact < 0) {{
    // net savings
    impactEl.textContent = "-" + tlhMoney(Math.abs(netTaxImpact));
    impactEl.style.color = "#27ae60";
  }} else {{
    // net additional tax owed
    impactEl.textContent = "+" + tlhMoney(netTaxImpact);
    impactEl.style.color = "#e74c3c";
  }}

  // current tax bill
  const curTaxEl = document.getElementById("tlh-current-tax");
  if (curTaxEl) {{
    curTaxEl.textContent = "$" + Math.round(_currentYearTax.totTax).toLocaleString("en-US");
  }}

  // est. tax after harvest
  const afterTax = Math.max(0, _currentYearTax.totTax + netTaxImpact);
  const afterEl  = document.getElementById("tlh-tax-after");
  if (afterEl) {{
    afterEl.textContent = "$" + Math.round(afterTax).toLocaleString("en-US");
    afterEl.style.color = afterTax > _currentYearTax.totTax ? "#c0392b"   // higher — bad
                        : afterTax < _currentYearTax.totTax ? "#27ae60"   // lower  — good
                        : "#888";
  }}

  // wash sale warning
  const washDiv = document.getElementById("tlh-wash-warning");
  if (selectedLossTickers.length > 0) {{
    washDiv.style.display = "block";
    const today = new Date();
    const washEnd = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000);
    const washDate = washEnd.toLocaleDateString("en-US", {{month:"short",day:"numeric",year:"numeric"}});
    document.getElementById("tlh-wash-tickers").textContent =
      selectedLossTickers.join(", ") + " — do not repurchase until " + washDate + ". ";
  }} else {{
    washDiv.style.display = "none";
  }}
}}

// ── Invest Chat Panel ─────────────────────────────────────────────────────
(function() {{
  let _icContext = null;  // {{type, id}}
  let _icMessages = [];   // {{role, content}}[]
  let _icStreaming = false;
  let _icReader = null;

  window.openInvestChat = function(contextType, contextId, title, chips) {{
    if (!contextId) return;
    // Close any in-flight stream from previous session
    if (_icReader) {{ try {{ _icReader.cancel(); }} catch(_) {{}} _icReader = null; }}
    _icContext = {{type: contextType, id: contextId}};
    _icMessages = [];
    _icStreaming = false;
    document.getElementById("invest-chat-title").textContent = title || contextId;
    document.getElementById("invest-chat-messages").innerHTML = "";
    document.getElementById("invest-chat-error").style.display = "none";
    document.getElementById("invest-chat-empty").style.display = "";
    document.getElementById("invest-chat-clear").style.display = "none";
    document.getElementById("invest-chat-input").value = "";
    document.getElementById("invest-chat-input").disabled = false;
    document.getElementById("invest-chat-send").disabled = false;

    const chipsEl = document.getElementById("invest-chat-chips");
    chipsEl.innerHTML = (chips || []).map(c =>
      `<button class="ic-chip" onclick="icSendText(${{JSON.stringify(c)}})">${{c}}</button>`
    ).join("");

    const panel = document.getElementById("invest-chat-panel");
    panel.style.display = "flex";

    const input = document.getElementById("invest-chat-input");
    setTimeout(() => input.focus(), 80);

    document.addEventListener("keydown", _icEscHandler);
  }};

  window.closeInvestChat = function() {{
    if (_icReader) {{ try {{ _icReader.cancel(); }} catch(_) {{}} _icReader = null; }}
    document.getElementById("invest-chat-panel").style.display = "none";
    document.removeEventListener("keydown", _icEscHandler);
  }};

  function _icEscHandler(e) {{
    if (e.key === "Escape") window.closeInvestChat();
  }}

  window.icClear = function() {{
    if (_icReader) {{ try {{ _icReader.cancel(); }} catch(_) {{}} _icReader = null; }}
    _icMessages = [];
    _icStreaming = false;
    document.getElementById("invest-chat-messages").innerHTML = "";
    document.getElementById("invest-chat-error").style.display = "none";
    document.getElementById("invest-chat-empty").style.display = "";
    document.getElementById("invest-chat-clear").style.display = "none";
    document.getElementById("invest-chat-input").disabled = false;
    document.getElementById("invest-chat-send").disabled = false;
    document.getElementById("invest-chat-chips").querySelectorAll(".ic-chip")
      .forEach(b => b.disabled = false);
    document.getElementById("invest-chat-input").focus();
  }};

  window.icSendText = function(text) {{ window.icSend(text); }};

  window.icSend = function(overrideText) {{
    const input = document.getElementById("invest-chat-input");
    const text = (overrideText !== undefined ? overrideText : input.value).trim();
    if (!text || _icStreaming || !_icContext) return;

    document.getElementById("invest-chat-empty").style.display = "none";
    document.getElementById("invest-chat-clear").style.display = "";
    document.getElementById("invest-chat-chips").querySelectorAll(".ic-chip")
      .forEach(b => b.disabled = true);

    _icMessages.push({{role: "user", content: text}});
    input.value = "";
    _icRender();
    _icStream();
  }};

  document.addEventListener("DOMContentLoaded", function() {{
    const input = document.getElementById("invest-chat-input");
    if (input) {{
      input.addEventListener("keydown", function(e) {{
        if (e.key === "Enter" && !e.shiftKey) {{
          e.preventDefault();
          window.icSend();
        }}
      }});
    }}
  }});

  function _icRender() {{
    const wrap = document.getElementById("invest-chat-messages");
    wrap.innerHTML = _icMessages.map((m, i) => {{
      const cls = m.role === "user" ? "ic-msg ic-msg-user" : "ic-msg ic-msg-assistant";
      const cursor = (_icStreaming && i === _icMessages.length - 1 && m.role === "assistant" && !m.content)
        ? '<span class="ic-cursor"></span>' : "";
      return `<div class="${{cls}}">${{_icEsc(m.content)}}${{cursor}}</div>`;
    }}).join("");
    wrap.scrollTop = wrap.scrollHeight;
  }}

  function _icEsc(s) {{
    return (s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/\\n/g,"<br>");
  }}

  async function _icStream() {{
    if (!_icContext) return;
    _icStreaming = true;
    document.getElementById("invest-chat-input").disabled = true;
    document.getElementById("invest-chat-send").disabled = true;
    document.getElementById("invest-chat-error").style.display = "none";

    _icMessages.push({{role: "assistant", content: ""}});
    _icRender();

    let done = false;
    try {{
      const res = await fetch("/api/invest-chat", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{
          context_type: _icContext.type,
          context_id:   _icContext.id,
          messages:     _icMessages.slice(0, -1),  // exclude the empty assistant placeholder
        }}),
      }});

      if (!res.ok) {{
        const err = await res.json().catch(() => ({{error: res.statusText}}));
        throw new Error(err.error || res.statusText);
      }}

      const reader = res.body.getReader();
      _icReader = reader;
      const dec = new TextDecoder();
      let buf = "";

      while (!done) {{
        const {{value, done: streamDone}} = await reader.read();
        if (streamDone) {{ done = true; break; }}
        buf += dec.decode(value, {{stream: true}});
        const lines = buf.split("\\n");
        buf = lines.pop();
        for (const line of lines) {{
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6));
          if (data.token) {{
            _icMessages[_icMessages.length - 1].content += data.token;
            _icRender();
          }}
          if (data.done) {{ done = true; break; }}
          if (data.error) {{ throw new Error(data.error); }}
        }}
      }}
    }} catch (err) {{
      // Remove empty assistant placeholder if nothing was received
      if (_icMessages.length && _icMessages[_icMessages.length-1].role === "assistant"
          && !_icMessages[_icMessages.length-1].content) {{
        _icMessages.pop();
      }}
      const errEl = document.getElementById("invest-chat-error");
      errEl.textContent = err.message;
      errEl.style.display = "";
      _icRender();
    }} finally {{
      _icReader = null;
      _icStreaming = false;
      document.getElementById("invest-chat-input").disabled = false;
      document.getElementById("invest-chat-send").disabled = false;
      document.getElementById("invest-chat-chips").querySelectorAll(".ic-chip")
        .forEach(b => b.disabled = false);
      document.getElementById("invest-chat-input").focus();
    }}
  }}
}})();
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
