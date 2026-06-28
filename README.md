# Investment Dashboard & Newsletter

A personal investment tracking system that sends a daily email newsletter, maintains a local web dashboard, and provides covered call and dividend analysis. Prices are pulled from Yahoo Finance; email is sent via Gmail SMTP.

---

## What It Does

| Feature | Description |
|---|---|
| **Daily Newsletter** | Fetches closing prices, computes P&L by layer and holding, emails an HTML report each morning at 8 AM |
| **Local Dashboard** | Interactive web UI at `http://localhost:5001/out/dashboard.html` with charts, holdings table, and live analysis tools |
| **Covered Call Analyzer** | Recommends option contracts based on your cost basis, flags blackout windows (earnings, ex-div) |
| **Covered Call Tracker** | Log and track open/closed covered call positions; shows DTE, total premium collected, all-time income |
| **Dividend Tracker** | Dividend dates, tax impact by income bracket, monthly income chart, and ticker lookup tool |
| **Earnings Calendar** | Next earnings date per holding shown in Layer Summary and Holdings table |
| **Buffett Screener** | Nightly scan of ~2,300 NYSE tickers; surfaces stocks passing all 6 Buffett quality criteria with valuation metrics, history tracking, and email alerts for new winners |
| **Portfolio Reminders** | Daily 7 AM email when any holding has earnings or ex-div within 3 days |
| **Layer Drift Alerts** | Daily check of layer weights vs. targets in `layer_targets.json`; emails when any layer drifts ≥5pp |
| **ST/LT Gain Flags** | Holdings table shows ST/LT badge per position once `PurchaseDate` is set in `holdings.csv` |

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

The file has five columns — edit directly or tell Claude to add positions:

```
Stock,Shares,AvgCost,Layer,PurchaseDate
JOBY,100,9.67,4,2023-11-15
EW,100,85.31,3,
...
```

`PurchaseDate` is optional (leave blank for existing positions). When set, the Holdings table shows an **ST** (short-term, <1 year) or **LT** (long-term, ≥1 year) badge on the Total Gain column to flag tax treatment.

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

`serve.py` is a full local API server — it serves static files **and** handles live API endpoints, and runs the daily newsletter automatically as a background thread.

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/covered-calls?ticker=EW` | Live option chain recommendations |
| `GET /api/dividends` | Dividend dates, yields, tax impact for all holdings |
| `GET /api/dividend-lookup?ticker=VYM&shares=100` | Dividend info for any ticker |
| `GET /api/dividend-timeline` | Monthly income (Jan–Dec, current year) |
| `GET /api/earnings` | Next earnings dates for all holdings |
| `GET /api/buffett-winners` | Latest Buffett screener results (includes valuation + first_seen) |
| `GET /api/cc-positions` | All logged covered call positions |
| `POST /api/cc-positions` | Log a new covered call position |
| `PATCH /api/cc-positions/<id>` | Update position status / closing details |

### Auto-start on login (macOS)

The dashboard server is managed by a launchd agent (`com.investment.dashboard`) that starts `serve.py` automatically on login and keeps it alive.

**One-time setup** (if not already loaded):

```bash
launchctl load ~/Library/LaunchAgents/com.investment.dashboard.plist
```

To reload after editing the plist:

```bash
launchctl unload ~/Library/LaunchAgents/com.investment.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.investment.dashboard.plist
```

---

## Daily Newsletter

The newsletter runs automatically inside `serve.py` as a background thread — **no launchd required**. When the server starts:

1. Checks if today's newsletter has already run (`out/last_run_date.txt`)
2. If not and it's ≥ 8 AM ET, runs `send_newsletter_main.py` → `generate_dashboard.py`
3. Rechecks every 30 minutes as a safety net

This means as long as the dashboard server is running (via the launchd agent), the newsletter and dashboard will always be current.

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
- **Est. Annual Dividends** — gross annual dividend income (populated on page load); subtitle shows net after-tax

### Charts
- Portfolio vs SPY cumulative return
- Allocation by layer (doughnut)
- Layer weight over time
- Today's layer performance (bar)
- **Dividend Income by Month** — blue bars (received) + green bars (expected) + purple cumulative line (gross) + orange dashed line (after-tax), Jan–Dec of current year

### Layer Summary Table
Columns: **Layer | Value | Weight | Δ$ | Δ% | Next Earnings**

Next Earnings shows the soonest reporting ticker per layer, color-coded red ≤ 7 days, orange ≤ 21 days, green further out.

### Holdings Table
Columns: **Ticker | Shares | Avg Cost | Price | Value | Total Gain | Daily Δ | Weight | Next Earnings | Purchased**

- Total Gain shows true return vs cost basis, with **ST** / **LT** tax badge when `PurchaseDate` is set
- Next Earnings populated per holding on page load
- Purchased column shows your entry date for tracking holding periods

### Covered Call Analyzer
Select any holding with **100+ shares** from the dropdown and click **Get Recommendations**.

**Info bar:** Current price | Avg Cost/Share | Gain % | 52-week High (date) | Min Strike

**Strike selection logic:**
- Stock not yet up 10% from cost → floor = `avg_cost × 1.10`
- Stock already up ≥ 10% → floor = `current_price × 1.10` (lock in gain + another 10%)
- Ceiling: `current_price × 1.50` (filters out pre-split legacy contracts)

**Columns:** Expiry | Strike | DTE | Bid | Ask | Mid | Prem% | Ann% | P/L if Called | Prob Called | OI

### Covered Call Position Tracker

Below the Covered Call Analyzer is a **Position Tracker** card. Use the expandable form to log a new position (ticker, contracts, strike, expiry, premium/contract, open date). A table shows all open and closed/expired/assigned positions with:
- **DTE** countdown for open positions (red ≤7d, orange ≤21d, green further)
- **Total Premium** = contracts × premium × 100
- Summary bar: open positions count, open premium held, all-time premium collected
- **Close** button → prompts for buy-back cost, marks position closed

**Blackout windows** flagged per contract:
- 📵 **AVOID** (red row) — earnings date falls within the option window
- ⚠️ **CAUTION** (yellow row) — ex-dividend date before expiration (early assignment risk)

**Prob Called** is the Black-Scholes delta, color-coded green < 20%, orange 20–35%, red > 35%.

### Dividend Tracker
Auto-loads on page open (~4 seconds, parallel fetch). Hit **Refresh** to update; cached 1 hour per day.

**Columns:** Ticker | Status | Ex-Div Date | Pay Date | Amount/Share | This Payout | Annual Income | Est. Tax | Net After-Tax | Yield | Yield on Cost

- **UPCOMING** (green) — confirmed future ex-div date
- **LAST KNOWN** (grey) — most recent date; next not yet announced
- Tax type auto-classified: Qualified (18.8% at $500k), Ordinary (e.g. REITs), Federal Exempt (muni funds)
- Footnote shows exact rates for the selected bracket

**Dividend Lookup** (bottom of card): enter any ticker + share count to see dividend metrics and how adding that position would change your portfolio's annual income and after-tax total.

### Buffett Screener

The screener runs automatically at **2 AM ET** each night as a background thread inside `serve.py`. It scans the full NYSE (~2,300 tickers) using Yahoo Finance and applies Warren Buffett's six quality criteria:

| Metric | Threshold | What it measures |
|---|---|---|
| Gross Margin | ≥ 40% | Durable pricing power |
| SG&A / Gross Profit | ≤ 30% | Lean cost structure |
| Net Income Margin | ≥ 20% | True earnings power |
| Interest / Op. Income | ≤ 15% | Low debt burden |
| CapEx / Net Income | ≤ 50% | Capital-light business |
| Cash > Total Debt | Yes | Balance sheet strength |

**Smart caching:** each ticker's `mostRecentQuarter` date is checked before re-fetching. Tickers whose quarter hasn't changed are served from the local cache (`out/buffett.db`) — typical run after the first scan takes a fraction of the time.

**Incremental writes:** winners are flushed to `buffett_winners` every 100 tickers, not just at the end. A crash or kill at ticker 1,500 preserves the winners found up to that point.

**Results** appear in the dashboard's **Buffett Screener** card (sorted by Gross Margin) with quick links to Yahoo Finance, CNBC, and MarketWatch for each ticker. Hit **↻ Refresh** to reload from the latest scan.

**Dashboard scan states:**

| State | What you see |
|---|---|
| Never run | Grey "No scan results yet" message |
| In progress | Live ticker count, partial winner count, and ETA to completion |
| Crashed / killed early | Red warning banner noting the scan was incomplete, with partial winners shown |
| Completed | Full results with timestamp and ticker count |

**Valuation metrics:** each winner now shows **P/E** (trailing), **P/FCF** (market cap ÷ free cash flow), and **EV/EBITDA** alongside the quality criteria — populated on the next nightly scan.

**Historical tracking:** every completed scan writes a `buffett_winner_history` row per winner. The dashboard's First Seen date shows when each ticker first qualified.

**New winner notifications:** every 100 tickers, the screener compares fresh winners against the previous list. Any ticker that qualifies for the first time triggers a Gmail notification with the ticker, company, price, gross/net income margins, and quick links to Yahoo Finance and CNBC. Uses the same `EMAIL_FROM` / `EMAIL_APP_PASSWORD` / `EMAIL_TO` credentials as the daily newsletter — no extra config required. On the very first scan all winners are treated as new; subsequent nightly runs only email genuine additions.

**Logs:** `out/screener.log`

To run manually at any time:

```bash
venv/bin/python3 buffett_screener.py
```

> Only one instance runs at a time — a PID lock file (`out/buffett_screener.lock`) prevents concurrent runs caused by orphaned processes.

---

## Portfolio Reminders (7 AM ET)

`serve.py` runs a daily reminder thread at **7 AM ET**. It scans all holdings for earnings dates and ex-dividend dates within the next 3 days and sends a single digest email listing upcoming events with urgency indicators (🔴 next day · 🟡 2 days · 🟢 3 days) and estimated ex-div payouts.

**Flag file:** `out/last_reminder_date.txt` — prevents double-sends per day.

---

## Layer Drift Alerts

After each successful newsletter run (8 AM), `serve.py` checks whether any layer has drifted ≥ 5 percentage points from its target allocation.

**Targets file:** `layer_targets.json` — created automatically from your current weights on first run. Edit it to define your intended allocations:

```json
{
  "1": 28.5,
  "2": 12.0,
  "3": 35.0,
  "4": 14.5,
  "5": 10.0
}
```

Keys are layer numbers (1–5); values are target percentages. When any layer drifts ≥5pp, an email lists each drifting layer with target, current weight, and direction.

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
├── holdings.csv                     # Portfolio positions — Stock, Shares, AvgCost, Layer, PurchaseDate
├── layer_targets.json               # Target layer allocations for drift alerts (auto-created)
├── send_newsletter_main.py          # Fetches prices, sends email, writes DB
├── generate_dashboard.py            # Generates out/dashboard.html from DB + CSV
├── serve.py                         # Local HTTP server + API endpoints + schedulers
│                                    #   GET/POST /api/cc-positions
│                                    #   PATCH    /api/cc-positions/<id>
│                                    #   GET /api/covered-calls?ticker=XX
│                                    #   GET /api/dividends
│                                    #   GET /api/dividend-lookup?ticker=XX&shares=N
│                                    #   GET /api/dividend-timeline
│                                    #   GET /api/earnings
│                                    #   GET /api/buffett-winners
├── buffett_screener.py              # NYSE Buffett screener — runs nightly at 2 AM ET
├── covered_call_rec.py              # Covered call recommendation + blackout engine
├── run_investment.sh                # Manual entry point: newsletter → dashboard
├── serve_daemon.sh                  # Legacy static file server (superseded by serve.py)
├── com.investment.newsletter.plist  # launchd plist — newsletter at 8 AM (backup)
├── chart.umd.min.js                 # Bundled Chart.js (no CDN dependency)
├── favicon.svg                      # Dashboard browser tab icon
├── InvestmentDashboard.app/         # Legacy macOS app wrapper (superseded by launchd agent)
├── .env                             # ⚠ Not committed — email credentials
└── out/
    ├── investment.db                # SQLite price + holding history
    ├── buffett.db                   # SQLite Buffett screener cache + winners
    ├── dashboard.html               # Generated dashboard (served by serve.py)
    ├── layer_allocation.png         # Pie chart attached to newsletter
    ├── newsletter.log               # Daily newsletter run log
    ├── screener.log                 # Nightly Buffett screener log
    ├── last_run_date.txt            # Flag — prevents double newsletter sends
    ├── last_screener_date.txt       # Flag — prevents double screener runs
    ├── last_reminder_date.txt       # Flag — prevents double reminder emails
    ├── buffett_screener.lock        # PID lock — prevents concurrent screener instances
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

# Seed the database
venv/bin/python3 send_newsletter_main.py

# Generate dashboard
venv/bin/python3 generate_dashboard.py

# Start the server (runs newsletter + screener schedulers automatically)
python3 serve.py

# Or load the launchd agent for auto-start on login
launchctl load ~/Library/LaunchAgents/com.investment.dashboard.plist
```
