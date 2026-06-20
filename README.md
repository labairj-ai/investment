# Investment Dashboard & Newsletter

A personal investment tracking system that sends a daily email newsletter, maintains a local web dashboard, and provides covered call and dividend analysis. Prices are pulled from Yahoo Finance; email is sent via Gmail SMTP.

---

## What It Does

| Feature | Description |
|---|---|
| **Daily Newsletter** | Fetches closing prices, computes P&L by layer and holding, emails an HTML report each morning at 8 AM |
| **Local Dashboard** | Interactive web UI at `http://localhost:5001/out/dashboard.html` with charts, holdings table, and live analysis tools |
| **Covered Call Analyzer** | Recommends option contracts based on your cost basis, flags blackout windows (earnings, ex-div) |
| **Dividend Tracker** | Auto-loads upcoming and last-known dividend dates, per-holding payout, annual income, yield and yield on cost |

---

## Requirements

- macOS (launchd automation is macOS-specific)
- Python 3.9+ with a virtual environment
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled
- Homebrew Python at `/opt/homebrew/opt/python@3.14/bin/python3.14` (used by the dashboard login item)

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

The file has four columns — edit directly or tell Claude to add positions one at a time:

```
Stock,Shares,AvgCost,Layer
JOBY,100,9.67,4
EW,100,85.31,3
...
```

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

Opens `http://localhost:5001/out/dashboard.html` automatically. Press `Ctrl+C` to stop.

`serve.py` is a full local API server — it serves static files **and** handles live API endpoints for the covered call analyzer and dividend tracker.

### Auto-start on login (macOS)

`InvestmentDashboard.app` is a background macOS app that silently starts the server on login (no dock icon, no window).

**One-time setup:**

```bash
open ~/Desktop/investment/InvestmentDashboard.app
```

Then add it to **System Settings → General → Login Items** so it runs automatically on every login.

---

## Automating the Daily Newsletter

The repo includes `com.investment.newsletter.plist`, which schedules `run_investment.sh` at **8:00 AM daily** via launchd.

**Install:**

```bash
cp com.investment.newsletter.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.investment.newsletter.plist
```

**Verify:**

```bash
launchctl list | grep investment
```

**Logs:** `out/newsletter.log`

`run_investment.sh` runs both `send_newsletter_main.py` (email + DB write) and `generate_dashboard.py` (dashboard regeneration) in sequence.

---

## Dashboard Features

### KPI Cards (top row)
- **Portfolio Value** — total market value
- **Daily Change** — today's P&L vs yesterday's close
- **SPY Change** — benchmark comparison
- **Total Gain vs Cost** — unrealized P&L vs your average cost across all holdings
- **Est. Annual Dividends** — estimated annual dividend income (populated on page load)

### Charts
- Portfolio vs SPY cumulative return
- Allocation by layer (doughnut)
- Layer weight over time
- Today's layer performance (bar)

### Holdings Table
Columns: **Ticker | Shares | Avg Cost | Price | Value | Total Gain | Daily Δ | Weight**

Total Gain shows true return vs your cost basis, not just daily moves.

### Covered Call Analyzer
Select any holding with **100+ shares** from the dropdown and click **Get Recommendations**.

Fetches live option chains and returns contracts ranked by annualized premium return, filtered to your minimum profit criteria.

**Strike selection logic:**
- Stock not yet up 10% from cost → floor = `avg_cost × 1.10`
- Stock already up ≥ 10% → floor = `current_price × 1.10` (lock in gain + another 10%)

**Columns:** Expiry | Strike | DTE | Bid | Ask | Mid | Prem% | Ann% | P/L if Called | Prob Called | OI

**Blackout windows** are flagged per contract:
- 📵 **AVOID** (red) — an earnings date falls between today and expiration (IV crush + gap risk)
- ⚠️ **CAUTION** (yellow) — ex-dividend date before expiration (early assignment / exercise risk)

**Prob Called** is the Black-Scholes delta (≈ probability of assignment), color-coded green < 20%, orange 20–35%, red > 35%.

### Dividend Tracker
Auto-loads on page open (parallel fetch, ~4 seconds). Hit **Refresh** to update; results are cached for 1 hour.

**Columns:** Ticker | Status | Ex-Div Date | Pay Date | Amount/Share | This Payout | Annual Income | Yield | Yield on Cost

- **UPCOMING** (green) — ex-div date is confirmed and in the future
- **LAST KNOWN** (grey) — most recent declared date; next not yet announced
- Days countdown: red ≤ 14 days, orange ≤ 30 days, green further out; past dates show "Xd ago"

---

## Covered Call CLI

Can also be run directly from the terminal:

```bash
# Single ticker
venv/bin/python3 covered_call_rec.py EW

# Multiple tickers
venv/bin/python3 covered_call_rec.py EW GRMN WMT

# All holdings with 100+ shares
venv/bin/python3 covered_call_rec.py
```

---

## Project Structure

```
investment/
├── holdings.csv                     # Portfolio positions — source of truth
├── send_newsletter_main.py          # Fetches prices, sends email, writes DB
├── generate_dashboard.py            # Generates out/dashboard.html from DB + CSV
├── serve.py                         # Local HTTP server + API endpoints
│                                    #   GET /api/covered-calls?ticker=XX
│                                    #   GET /api/dividends
├── covered_call_rec.py              # Covered call recommendation + blackout engine
├── run_investment.sh                # Entry point: newsletter → dashboard (runs daily)
├── serve_daemon.sh                  # Shell wrapper for launchd (cleans Python env)
├── com.investment.newsletter.plist  # launchd — daily newsletter at 8 AM
├── chart.umd.min.js                 # Bundled Chart.js (no CDN dependency)
├── favicon.svg                      # Dashboard browser tab icon
├── InvestmentDashboard.app/         # macOS login item — auto-starts serve.py
├── .env                             # ⚠ Not committed — email credentials
└── out/
    ├── investment.db                # SQLite price + holding history
    ├── dashboard.html               # Generated dashboard (served by serve.py)
    ├── layer_allocation.png         # Pie chart attached to newsletter
    ├── newsletter.log               # Daily run log
    ├── covered_calls_analysis.md    # Manual covered call notes
    └── volume_analysis.md           # Manual volume notes
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

# Create .env with credentials (see Setup section above)

# Install daily newsletter schedule
cp com.investment.newsletter.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.investment.newsletter.plist

# Seed the database
venv/bin/python3 send_newsletter_main.py

# Generate dashboard
venv/bin/python3 generate_dashboard.py

# Add InvestmentDashboard.app to System Settings → Login Items
```
