# Investment Dashboard & Newsletter

A personal investment tracking system that sends a daily email newsletter, maintains a local web dashboard, and provides a covered call analyzer. Prices are pulled from Yahoo Finance; email is sent via Gmail SMTP.

---

## What It Does

| Feature | Description |
|---|---|
| **Daily Newsletter** | Fetches closing prices, computes P&L by layer and holding, emails an HTML report each morning |
| **Local Dashboard** | Interactive web UI at `http://localhost:5001/out/dashboard.html` — portfolio value, cumulative return vs SPY, layer allocation, holdings table with total gain vs cost basis |
| **Covered Call Analyzer** | In-dashboard tool that fetches live option chains and recommends contracts based on your cost basis and a 10% profit floor |

---

## Requirements

- macOS (launchd automation is macOS-specific)
- Python 3.9+
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled
- Homebrew Python (for the dashboard login item): `/opt/homebrew/opt/python@3.14/bin/python3.14`

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/labairj-ai/investment.git
cd ~/Desktop/investment
```

### 2. Create the virtual environment

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install pandas yfinance matplotlib python-dotenv
```

### 3. Create `.env`

Copy the template below and fill in your credentials. This file is gitignored and never committed.

```
EMAIL_FROM=you@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_TO=recipient@gmail.com
```

> **Gmail App Password**: Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), generate a password for "Mail", and paste the 16-character code above.

### 4. Populate `holdings.csv`

The file has four columns:

```
Stock,Shares,AvgCost,Layer
JOBY,100,9.67,4
EW,100,85.31,3
...
```

**Layer definitions:**

| Layer | Name |
|---|---|
| 1 | Structural Ballast |
| 2 | Cash-Flow Engines |
| 3 | Compounders |
| 4 | Convexity / Optionality |
| 5 | Shock Absorbers / Regime Hedges |

### 5. Run the newsletter once to seed the database

```bash
venv/bin/python3 send_newsletter_main.py
```

This fetches prices, stores history in `out/investment.db`, generates `out/layer_allocation.png`, and sends the email. Subsequent runs on the same day are blocked by a flag file.

### 6. Generate the dashboard

```bash
venv/bin/python3 generate_dashboard.py
```

Output: `out/dashboard.html`

---

## Running the Dashboard

### Manual (interactive)

```bash
python3 serve.py
```

Opens `http://localhost:5001/out/dashboard.html` automatically in your browser. Press `Ctrl+C` to stop.

### Auto-start on login (macOS)

The repo includes `InvestmentDashboard.app` — a background macOS app that starts the server silently on login.

**One-time setup:**

```bash
open ~/Desktop/investment/InvestmentDashboard.app
```

Then add it to **System Settings → General → Login Items** so it runs automatically on every login.

---

## Automating the Daily Newsletter (macOS launchd)

The repo includes `com.investment.newsletter.plist` which schedules `run_investment.sh` at **8:00 AM daily**.

**Install:**

```bash
cp com.investment.newsletter.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.investment.newsletter.plist
```

**Check it loaded:**

```bash
launchctl list | grep investment
```

**Logs:** `out/newsletter.log`

---

## Covered Call Analyzer

Available in the dashboard for any holding with **100+ shares**. Select a ticker and click **Get Recommendations**.

**Strike selection logic:**
- If the stock is **not yet up 10%** from your cost: minimum strike = `avg_cost × 1.10`
- If the stock is **already up ≥ 10%**: minimum strike = `current_price × 1.10` (lock in gain + another 10%)

Results are ranked by annualized premium return and show:
- Strike, expiration, DTE
- Bid / Ask / Mid premium
- Premium % and annualized return
- Total P&L if called away vs your cost basis
- **Prob Called** — Black-Scholes delta (≈ probability of assignment), color-coded green / orange / red

Can also be run from the command line:

```bash
# Single ticker
venv/bin/python3 covered_call_rec.py EW

# Multiple tickers
venv/bin/python3 covered_call_rec.py EW GRMN JOBY

# All holdings with 100+ shares
venv/bin/python3 covered_call_rec.py
```

---

## Project Structure

```
investment/
├── holdings.csv                  # Portfolio positions (source of truth)
├── send_newsletter_main.py       # Fetches prices, sends email, writes to DB
├── generate_dashboard.py         # Generates out/dashboard.html from DB
├── serve.py                      # Local HTTP server + /api/covered-calls endpoint
├── covered_call_rec.py           # Covered call recommendation engine
├── run_investment.sh             # Entry point: newsletter → dashboard (run daily)
├── serve_daemon.sh               # Shell wrapper for launchd dashboard server
├── com.investment.newsletter.plist  # launchd plist — daily newsletter at 8AM
├── chart.umd.min.js              # Bundled Chart.js (no CDN dependency)
├── favicon.svg                   # Dashboard browser tab icon
├── InvestmentDashboard.app/      # macOS login item — auto-starts serve.py
├── .env                          # ⚠ Not committed — email credentials
└── out/
    ├── investment.db             # SQLite price history
    ├── dashboard.html            # Generated dashboard (open via serve.py)
    ├── layer_allocation.png      # Pie chart attached to newsletter email
    ├── newsletter.log            # Daily run log
    ├── covered_calls_analysis.md # Manual covered call notes
    └── volume_analysis.md        # Manual volume notes
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
# Create .env with credentials
# Install launchd plist (see Automating section above)
# Add InvestmentDashboard.app to Login Items
```
