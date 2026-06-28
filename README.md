# Investment Dashboard & Newsletter

A personal investment tracking system that sends a daily email newsletter, maintains a local web dashboard, and provides covered call, dividend, tax, and Buffett analysis tools. Prices are pulled from Yahoo Finance; email is sent via Gmail SMTP.

---

## What It Does

| Feature | Description |
|---|---|
| **Daily Newsletter** | Fetches closing prices, computes P&L by layer and holding, emails an HTML report each morning at 8 AM ET |
| **Local Dashboard** | Interactive web UI at `http://localhost:5001` with charts, holdings table, and live analysis tools |
| **Add / Manage Positions** | Add new positions directly from the Holdings UI (ticker, shares, avg cost, layer); reassign any holding to a different layer with full retroactive history rewrite |
| **Covered Call Analyzer** | Recommends option contracts based on your cost basis, flags blackout windows (earnings, ex-div) |
| **Covered Call Tracker** | Log and track open/closed covered call positions; tracks net P&L per position with close types (expired / bought back / assigned); auto-expires positions past their expiry date |
| **Dividend Tracker** | Dividend dates, tax impact by income bracket, monthly income chart, and ticker lookup tool |
| **Earnings Calendar** | Next earnings date per holding shown in Layer Summary and Holdings table |
| **Buffett Screener** | Nightly scan of ~2,300 NYSE tickers; surfaces stocks passing all 6 Buffett quality criteria; emails only net-new winners (no repeat notifications for stocks already on the list) |
| **Buffett Deep-Dive** | On-demand 13-point Buffett analysis for any ticker — gross margin, expense margins, EPS trend, balance sheet strength, buybacks, and more |
| **Portfolio Reminders** | Daily 7 AM ET email when any holding has earnings or ex-div within 3 days |
| **Layer Drift Alerts** | Daily check of layer weights vs. targets in `layer_targets.json`; emails when any layer drifts ≥5pp |
| **Tax Lot Tracker** | Lot-level cost basis per holding; modal shows per-lot ST/LT term, unrealized G/L, days to LT conversion |
| **FIFO Sell Tracker** | Record sales with automatic FIFO lot matching; previews which lots are consumed before confirming; undo support |
| **Realized Gains & Tax** | Dashboard card showing YTD (or all-time) realized gains split by ST/LT — **includes covered call premium income** — with estimated federal tax at editable bracket rates |
| **Private Data Backup** | Daily push of `investment.db`, `holdings.csv`, and `buffett.db` to a separate private GitHub repo |

---

## Requirements

- macOS (login item auto-start is macOS-specific)
- Python 3.9+ with a virtual environment
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/labairj-ai/investment.git ~/Desktop/investment
cd ~/Desktop/investment
```

### 2. Create the virtual environment

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install pandas yfinance matplotlib python-dotenv
```

### 3. Create `.env`

This file is gitignored and never committed. Create it manually:

```
EMAIL_FROM=you@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_TO=recipient@gmail.com
```

> **Gmail App Password**: Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), generate a password for "Mail", and paste the 16-character code (no spaces) as `EMAIL_APP_PASSWORD`.

### 4. Populate `holdings.csv`

```
Stock,Shares,AvgCost,Layer
JOBY,100,9.67,4
EW,100,85.31,3
...
```

You can also add positions directly from the dashboard UI — see [Holdings Management](#holdings-management) below.

**Layer definitions:**

| Layer | Name | Examples |
|---|---|---|
| 1 | Structural Ballast | Index funds, BRK.B |
| 2 | Cash-Flow Engines | SCHD, XOM, dividend payers |
| 3 | Compounders | GRMN, WMT, EW, NFLX |
| 4 | Convexity / Optionality | JOBY, BTC, IGV |
| 5 | Shock Absorbers / Regime Hedges | MCO, UNP, ITOCF, MITSF, NOC |

### 5. Run the newsletter once to seed the database

```bash
venv/bin/python3 send_newsletter_main.py
```

This fetches prices, writes history to `out/investment.db`, generates `out/layer_allocation.png`, and sends the email. The flag file `out/last_run_date.txt` prevents double-sends on the same day.

### 6. Generate the dashboard

```bash
venv/bin/python3 generate_dashboard.py
```

Output: `out/dashboard.html`

---

## Running the Dashboard

### Manual

```bash
python3 serve.py
```

Navigating to `http://localhost:5001` redirects automatically to the dashboard. Press `Ctrl+C` to stop.

`serve.py` is a full local API server — it serves static files **and** handles live API endpoints, and runs the daily newsletter and screener automatically as background threads.

### Auto-start on login (macOS)

The dashboard server is managed by a launchd agent (`com.investment.dashboard`) that starts `run_server.sh` (an infinite-loop wrapper around `serve.py`) automatically on login. If `serve.py` crashes, the wrapper restarts it within 5 seconds.

To start or restart the agent:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.investment.dashboard.plist 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.investment.dashboard.plist
launchctl kickstart gui/$(id -u)/com.investment.dashboard
```

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/covered-calls?ticker=EW` | Live option chain recommendations |
| `GET /api/dividends` | Dividend dates, yields, tax impact for all holdings |
| `GET /api/dividend-lookup?ticker=VYM&shares=100` | Dividend info for any ticker |
| `GET /api/dividend-timeline` | Monthly income (Jan–Dec, current year) |
| `GET /api/earnings` | Next earnings dates for all holdings |
| `GET /api/buffett-winners` | Latest Buffett screener results (includes valuation + first_seen) |
| `GET /api/buffett-analysis?ticker=KO` | On-demand 13-point Buffett deep-dive for any ticker |
| `GET /api/cc-positions` | All logged covered call positions (auto-expires past-expiry open positions) |
| `POST /api/cc-positions` | Log a new covered call position |
| `PATCH /api/cc-positions/<id>` | Update position status / closing details (computes net_premium server-side) |
| `GET /api/lots` | All cost lots across all tickers |
| `GET /api/lots?ticker=EW` | Lots for a specific ticker |
| `POST /api/lots` | Add a cost lot |
| `DELETE /api/lots/<id>` | Remove a cost lot |
| `GET /api/sells` | All sell transactions across all tickers |
| `GET /api/sells?ticker=EW` | Sell history for a specific ticker |
| `POST /api/sells` | Record a sale (FIFO lot allocation executed server-side) |
| `DELETE /api/sells/<id>` | Undo a sale (lots restored from snapshot) |
| `POST /api/holdings` | Add a new position (appends to CSV, fetches price, seeds DB) |
| `PATCH /api/holdings/<ticker>` | Reassign a holding's layer (rewrites all history retroactively) |

---

## Daily Newsletter

The newsletter runs automatically inside `serve.py` as a background thread — **no separate launchd job required**. When the server starts:

1. Checks if today's newsletter has already run (`out/last_run_date.txt`)
2. If not and it's ≥ 8 AM ET, runs `send_newsletter_main.py` → `generate_dashboard.py`
3. Rechecks every 30 minutes as a safety net

After a successful newsletter run, two additional checks fire automatically:
- **Layer drift check** — emails if any layer has drifted ≥5pp from `layer_targets.json`
- **Data backup** — pushes `investment.db`, `holdings.csv`, and `buffett.db` to the private `investment-data` repo

**Logs:** `out/newsletter.log`

To run manually at any time:

```bash
venv/bin/python3 send_newsletter_main.py && venv/bin/python3 generate_dashboard.py
```

---

## Dashboard Features

### Header
- **Tax Bracket dropdown** (top right) — toggles between $150k / $300k / $500k / $750k / $1M+ MFJ income scenarios; updates all dividend tax calculations and the after-tax chart line in real time

### KPI Cards (top row)
- **Portfolio Value** — total market value
- **Daily Change** — today's P&L vs yesterday's close
- **SPY Change** — benchmark comparison
- **Total Gain vs Cost** — unrealized P&L vs your average cost across all holdings
- **Est. Annual Dividends** — gross annual dividend income; subtitle shows net after-tax

### Charts
- Portfolio vs SPY cumulative return
- Allocation by layer (doughnut)
- Layer weight over time
- Today's layer performance (bar)
- **Dividend Income by Month** — blue bars (received) + green bars (expected) + purple cumulative line (gross) + orange dashed line (after-tax), Jan–Dec of current year

### Layer Summary Table
Columns: **Layer | Value | Weight | Δ$ | Δ% | Next Earnings**

Next Earnings shows the soonest reporting ticker per layer, color-coded red ≤7 days, orange ≤21 days, green further out.

### Holdings Table
Columns: **Ticker | Shares | Avg Cost | Price | Value | Total Gain | Daily Δ | Weight | Next Earnings | Layer | Tax Lots**

- Total Gain shows true return vs cost basis, with **ST** / **LT** / **⚠ MIXED** tax badge derived from your cost lots
- **Layer badge** (L1–L5, color-coded) — click to reassign the holding to a different layer; history is rewritten retroactively so no artificial spike appears in the weight chart
- **Lots** button opens the lot tracker modal

### Holdings Management

**Add a position** — click **+ Add Position** above the holdings table. Enter:
- Ticker, Shares, Avg Cost / Share, Layer (dropdown)

The server fetches the current market price from Yahoo Finance immediately, so the position appears in the table and layer allocation after saving. If the price isn't available (off-market hours), it will populate on the next newsletter run. After adding, use the **Lots** button to record the tax lot purchase date(s) and cost basis.

**Reassign a layer** — click any **L1–L5 badge** in the Layer column. The modal shows the current layer and lets you pick a new one. On confirm:
1. `holdings.csv` is updated
2. Every historical row in `holding_day` for that ticker is rewritten to the new layer
3. `layer_day` is fully recomputed from `holding_day` for all dates — the Layer Weight Over Time chart shows the holding as always having been in the new layer, with no discontinuity

### Tax Lot Tracker (modal)

Click **Lots** on any holding to open the modal. It contains three sections:

**Current Lots:**
- Per-lot table: purchase date, shares, cost/share, total cost, days held, ST/LT badge, unrealized G/L, days until lot turns LT
- Summary bar: lot count, total shares tracked, weighted avg cost, ST/LT share split, total G/L at current price
- Add Lot form (date, shares, cost/share, optional notes) and per-lot Remove button

**Record a Sale (FIFO):**
- Enter date sold, shares, sell price, and optional notes
- Click **Preview FIFO →** to see exactly which lots will be consumed (oldest first) before committing — shows per-lot cost basis, proceeds, gain/loss, and ST/LT term
- Click **Confirm Sale** to execute: oldest lots are reduced or deleted, the sale is recorded
- Click **Undo** on any past sale to fully restore the consumed lots

**Sell History:**
- All past sells for the ticker: date, shares, price, total G/L, ST G/L, LT G/L, lot-level detail

Lots are stored in `out/investment.db` (`cost_lots` table). Sells are stored in `sell_transactions`. Both persist independently of `holdings.csv`.

### Realized Gains & Tax Estimate

A dedicated dashboard card (below Holdings) showing the combined tax picture for stock sales **and** covered call premium income:

- **Year filter**: This Year (default) or All Time
- **Three KPI tiles**:
  - **Total Realized** — stock capital gains + CC net premium income combined
  - **Short-Term / Ordinary** — stock ST gains + CC premium (both taxed at ordinary income rate); shows breakdown sub-line when both are present
  - **Long-Term** — stock LT gains only (CC income never goes here)
- **Tax estimator**: editable ST and LT rate inputs (saved in browser localStorage), optional NIIT (3.8%) checkbox, and computed Est. ST Tax / Est. LT Tax / Total Est. Tax
- **Per-transaction table**: ticker, date, shares, price, total G/L, ST G/L, LT G/L, estimated tax per sell, lot-level detail, notes
- **Option Premium Income section**: per-position breakdown of gross premium collected, buyback cost (if bought back early), net income, estimated tax, and close type

Estimated tax applies to positive gains only (losses offset within each term bucket). Federal rates only — does not include state taxes.

### Covered Call Position Tracker

**Logging:** Use the **+ Log New Position** form — ticker, contracts, strike, expiry, premium/contract, open date.

**Closing a position:** Click **Close ▾** on any open row. A modal appears with three close types:
- **Expired Worthless** — option expired OTM; full premium is kept; `closed_price = 0`
- **Bought Back** — enter the buy-back price; net income = (sold − bought) × contracts × 100
- **Assigned** — stock called away at strike; full premium kept; optionally records the stock sale in the FIFO tracker at the strike price (the resulting stock capital gain/loss flows into ST/LT section)

**Auto-expiry:** On every page load, any open position whose expiry date has passed is automatically recorded as expired (full premium kept, `closed_date` set to the actual expiry date). A toast notification appears and prompts you to verify if any were actually assigned.

**Net P&L column:** Closed positions show actual net realized income, with buyback cost called out in red when applicable. The summary bar shows open gross premium and net realized income separately.

**Tax integration:** CC net premium income always flows into the **Short-Term / Ordinary** KPI tile and the EST. ST Tax calculation — premium income is always taxed as ordinary income regardless of how long the position was open.

### Buffett Deep-Dive Analyzer

Type any ticker and click **Analyze** (or press Enter) to run a 13-point Buffett analysis on demand.

**Score bar**: color-coded green (≥10/13 — strong), amber (7–9 — mixed), red (<7 — fails screen), with a one-line verdict.

**13 metrics checked:**

| # | Metric | Criteria |
|---|---|---|
| 1 | Gross Margin | > 40% |
| 2 | SG&A / Gross Profit | < 30% |
| 3 | R&D / Gross Profit | < 30% |
| 4 | Depreciation / Gross Profit | < 10% |
| 5 | Interest / Operating Income | < 15% |
| 6 | Net Income Margin | > 20% |
| 7 | EPS Growth | Year-over-year increase |
| 8 | Retained Earnings | Growing |
| 9 | Cash vs Total Debt | Cash > Debt |
| 10 | Debt / Equity | < 0.80 |
| 11 | Preferred Stock | None |
| 12 | Share Buybacks | Present |
| 13 | CapEx / Net Income | < 25% |

Banks and insurers are detected automatically (Gross Margin shown as N/A; other expense margins skip).

### Buffett Screener (nightly)

The screener runs automatically at **2 AM ET** each night as a background thread inside `serve.py`. It scans the full NYSE (~2,300 tickers) applying six quality criteria:

| Metric | Threshold |
|---|---|
| Gross Margin | ≥ 40% |
| SG&A / Gross Profit | ≤ 30% |
| Net Income Margin | ≥ 20% |
| Interest / Op. Income | ≤ 15% |
| CapEx / Net Income | ≤ 50% |
| Cash > Total Debt | Yes |

**Smart caching:** tickers whose `mostRecentQuarter` hasn't changed skip the full financial fetch. Valuation metrics (P/E, P/FCF, EV/EBITDA) are always refreshed from today's price data even on cache hits, so they're never stale.

**No repeat emails:** The screener emails only when a ticker qualifies for the **first time ever**. Once a ticker appears in `buffett_winner_history` it is never re-notified, regardless of how many subsequent scans it passes. The email fires once per scan run (at completion), not at each intermediate flush.

**Historical tracking:** `buffett_winner_history` records when each ticker first qualified; shown as "since YYYY-MM-DD" in the screener card.

**Logs:** `out/screener.log`

```bash
venv/bin/python3 buffett_screener.py   # run manually
```

### Covered Call Analyzer
Select any holding with **100+ shares** and click **Get Recommendations**.

**Strike selection logic:**
- Stock not yet up 10% from cost → floor = `avg_cost × 1.10`
- Stock already up ≥10% → floor = `current_price × 1.10`
- Ceiling: `current_price × 1.50`

**Columns:** Expiry | Strike | DTE | Bid | Ask | Mid | Prem% | Ann% | P/L if Called | Prob Called | OI

### Dividend Tracker
Auto-loads on page open. Hit **Refresh** to update; cached 1 hour per day.

**Columns:** Ticker | Status | Ex-Div Date | Pay Date | Amount/Share | This Payout | Annual Income | Est. Tax | Net After-Tax | Yield | Yield on Cost

**Dividend Lookup**: enter any ticker + share count to see metrics and projected portfolio impact.

---

## Portfolio Reminders (7 AM ET)

`serve.py` runs a daily reminder thread at **7 AM ET**. It scans all holdings for earnings and ex-dividend dates within 3 days and sends a single digest email with urgency indicators (🔴 next day · 🟡 2 days · 🟢 3 days).

**Flag file:** `out/last_reminder_date.txt`

---

## Layer Drift Alerts

After each successful 8 AM newsletter run, `serve.py` checks whether any layer has drifted ≥5pp from its target.

**Targets file:** `layer_targets.json` — created automatically from current weights on first run:

```json
{ "1": 28.5, "2": 12.0, "3": 35.0, "4": 14.5, "5": 10.0 }
```

---

## Private Data Backup

Financial data (`investment.db`, `holdings.csv`, `buffett.db`) is backed up daily to a **separate private GitHub repo** (`investment-data`) — stays private even if this code repo is made public.

**Run manually:**
```bash
bash ~/Desktop/investment/backup_data.sh
```

**Restore on a new machine:**
```bash
git clone https://github.com/labairj-ai/investment-data.git ~/.investment-backup
cp ~/.investment-backup/investment.db ~/Desktop/investment/out/
cp ~/.investment-backup/holdings.csv  ~/Desktop/investment/
cp ~/.investment-backup/buffett.db    ~/Desktop/investment/out/
```

---

## Covered Call CLI

```bash
venv/bin/python3 covered_call_rec.py EW          # single ticker
venv/bin/python3 covered_call_rec.py EW GRMN WMT # multiple
venv/bin/python3 covered_call_rec.py              # all holdings ≥100 shares
```

---

## Project Structure

```
investment/
├── holdings.csv                     # Portfolio positions — Stock, Shares, AvgCost, Layer
├── layer_targets.json               # Target layer allocations for drift alerts (auto-created)
├── backup_data.sh                   # Pushes DB + CSV to private investment-data repo
├── run_server.sh                    # Infinite-loop wrapper around serve.py (used by launchd)
├── send_newsletter_main.py          # Fetches prices, sends email, writes DB
├── generate_dashboard.py            # Generates out/dashboard.html
├── serve.py                         # HTTP server + all API endpoints + schedulers
├── buffett_screener.py              # NYSE Buffett screener — nightly at 2 AM ET
├── covered_call_rec.py              # Covered call recommendation + blackout engine
├── run_investment.sh                # Manual newsletter entry point
├── chart.umd.min.js                 # Bundled Chart.js (no CDN dependency)
├── favicon.svg                      # Dashboard browser tab icon
├── .env                             # ⚠ Not committed — email credentials
└── out/
    ├── investment.db                # SQLite: price history, cc_positions, cost_lots, sell_transactions
    ├── buffett.db                   # SQLite: Buffett screener cache, winners, history
    ├── dashboard.html               # Generated dashboard (served by serve.py)
    ├── layer_allocation.png         # Pie chart attached to newsletter
    ├── newsletter.log               # Daily newsletter run log
    ├── screener.log                 # Nightly Buffett screener log
    ├── last_run_date.txt            # Flag — prevents double newsletter sends
    ├── last_screener_date.txt       # Flag — prevents double screener runs
    ├── last_reminder_date.txt       # Flag — prevents double reminder emails
    └── buffett_screener.lock        # PID lock — prevents concurrent screener instances
```

---

## Environment Variables (`.env`)

| Variable | Description |
|---|---|
| `EMAIL_FROM` | Gmail address to send from |
| `EMAIL_APP_PASSWORD` | Gmail App Password (16 chars, no spaces) |
| `EMAIL_TO` | Recipient email address |

---

## Re-installing on a New Machine

```bash
git clone https://github.com/labairj-ai/investment.git ~/Desktop/investment
cd ~/Desktop/investment
python3 -m venv venv
venv/bin/pip install pandas yfinance matplotlib python-dotenv

# Restore data backup
git clone https://github.com/labairj-ai/investment-data.git ~/.investment-backup
cp ~/.investment-backup/investment.db out/
cp ~/.investment-backup/holdings.csv  .
cp ~/.investment-backup/buffett.db    out/

# Create .env with credentials (see Setup above)

# Generate dashboard
venv/bin/python3 generate_dashboard.py

# Start the server
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.investment.dashboard.plist
launchctl kickstart gui/$(id -u)/com.investment.dashboard
```
