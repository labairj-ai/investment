# Investment Dashboard & Newsletter

A personal investment tracking system that sends a daily email newsletter, maintains a local web dashboard, and provides covered call, dividend, tax, and Buffett analysis tools. Prices are pulled from Yahoo Finance; email is sent via Gmail SMTP.

---

## Deployment

**Production runs on the `optiplex` home server** (Ubuntu 24.04, since 2026-07-12) — this Mac copy is for development.

- Repo on server: `/home/optiplex/investment`, venv rebuilt from `requirements.txt`
- Dashboard: systemd `investment.service` runs `serve.py` on port 5001 — public at **https://optiplex.tailb97cdb.ts.net/** (Tailscale Funnel)
- Newsletter: sent by serve.py's built-in scheduler (~7:15 AM ET); `investment-newsletter.timer` runs `run_investment.sh` at 8 AM as a backstop (flag file `out/last_run_date.txt` prevents double sends)
- Data backup: serve.py's scheduler runs `backup_data.sh` → pushes to `labairj-ai/investment-data` via a write deploy key (`~/.ssh/id_ed25519`, ssh alias `github-data`)
- Server keeps one intentional uncommitted patch: `serve.py` binds `0.0.0.0` instead of `localhost`
- Deploy: commit + push here, then on the server `git pull` (origin uses read-only deploy key via alias `github-inv`); restart `investment.service` only if `serve.py` changed

The old launchd agents from the Mac era are archived in `launchd-disabled-on-mac/`.

---

## What It Does

| Feature | Description |
|---|---|
| **Investment Goals & Strategy** | Dividend goal ($2.5k/mo by 2036) + portfolio value goal ($2M by 2036) with 8-quarter rolling targets; barbell health with L4 recs; live **Recommended Purchases** panel backed by Buffett screener data, layer drift, dividend yield impact, valuation multiples, value trap flags, and earnings calendar |
| **Daily Investment Digest** | Single 7 AM email covering: portfolio snapshot, layer allocation vs target (with drift warnings), holdings performance, upcoming earnings/ex-div events, and the judgment health rubric |
| **Local Dashboard** | Interactive web UI at `http://localhost:5001` with charts, holdings table, and live analysis tools |
| **Add / Manage Positions** | Add new positions directly from the Holdings UI (ticker, shares, avg cost, layer); reassign any holding to a different layer with full retroactive history rewrite; opening lot auto-created in the Tax Lot Tracker on position add |
| **Covered Call Analyzer** | Ranks contracts by expected incremental value vs simply holding the stock (covered-call alpha), not raw premium yield. Floor uses `K + exec_prem ≥ cost × 1.10` so premium participates. Metrics include: CC Alpha (exec premium − expected upside surrendered under blended real-world drift), Regret % (P(stock > strike + premium)), real-world ITM probability, vol-normalised strike distance, IV richness (IV/HV_forecast − 1), and a 0-100 multi-factor score. Ex-div events use extrinsic/dividend economics; earnings events compare strike distance to straddle-implied move. Three-tier fallback (live bids → ask-proxy → Black-Scholes) ensures results when markets are closed. **🤖 AI Analysis** sends top-5 contracts to a local `qwen2.5:7b` model for narrative reasoning |
| **Covered Call Tracker** | Log and track open/closed covered call positions; live mark-to-market option prices (bid/ask mid from yfinance); Unrealized P&L and Today's P&L columns per position; daily change KPI is adjusted mark-to-market; bulk import via `covered_calls.csv`; auto-expires past-expiry positions |
| **Dividend Tracker** | Dividend dates, tax impact by income bracket, monthly income chart, and ticker lookup tool |
| **Earnings Calendar** | Next earnings date per holding shown in Layer Summary and Holdings table |
| **Buffett Screener** | Nightly scan of ~6,500 NYSE + NASDAQ tickers (deduplicated); surfaces stocks passing all 6 Buffett quality criteria; emails only net-new winners (no repeat notifications for stocks already on the list) |
| **Buffett Deep-Dive** | On-demand 13-point Buffett analysis for any ticker — gross margin, expense margins, EPS trend, balance sheet strength, buybacks, and more |
| **Layer Drift Alerts** | Inline in the daily digest: orange warning box when any layer drifts ≥5pp from target; subject line flags the count |
| **Tax Lot Tracker** | Lot-level cost basis per holding; modal shows per-lot ST/LT term, unrealized G/L, days to LT conversion |
| **FIFO Sell Tracker** | Record sales with automatic FIFO lot matching; previews which lots are consumed before confirming; undo support |
| **Realized Gains & Tax** | Dashboard card showing YTD (or all-time) realized gains split by ST/LT — **includes covered call premium income** — with estimated federal tax at editable bracket rates |
| **Tax Loss Harvesting** | Interactive modeler (✂ Tax Harvesting button in the Realized Gains card) — shows all open positions with unrealized gains/losses; check any combination to see real-time net tax impact using IRS ST/LT cross-netting rules, the $3k ordinary-income offset, and bracket-aware rates; selecting winners increases the estimated tax, selecting losers lowers it; wash sale warning (30-day window) included |
| **Private Data Backup** | Daily push of `investment.db`, `holdings.csv`, and `buffett.db` to a separate private GitHub repo |

---

## Requirements

- macOS or Linux (all scripts derive paths from their own location, so the repo can live anywhere; the launchd auto-start is macOS-specific)
- Python 3.9+ with a virtual environment
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled
- **Ollama** (for AI Analysis) — must be running on the server with `qwen2.5:7b` pulled (`ollama pull qwen2.5:7b`); optional, the rest of the dashboard works without it; ~4.7 GB RAM required

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
| 2 | Cash-Flow Engines | SCHD, XOM — dividend payers yielding ≥3%; sub-3% dividend payers belong in L3 Compounders |
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

### LAN access / Raspberry Pi

By default `serve.py` binds to `localhost` and is only reachable from the machine it runs on. To expose the dashboard on your local network (e.g. to view it from a phone), change the bind address at the bottom of `serve.py`:

```python
server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
```

A second instance of this repo runs this way on a Raspberry Pi, where the dashboard is reachable at `http://<pi-ip>:5001` from any device on the LAN. The Pi keeps the `0.0.0.0` bind as a deliberately uncommitted local edit; when pulling updates there, stash it around the pull:

```bash
git stash push -m 'bind 0.0.0.0' serve.py && git pull --ff-only && git stash pop
```

Script changes take effect on the next **↻ Refresh Data** without restarting the server (the refresh endpoint spawns the scripts fresh each time); only changes to `serve.py` itself require a restart.

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /glossary` | Term definitions for every metric in the UI — options mechanics, V2 CC metrics, volatility, portfolio, tax, and Buffett screener (opens in browser, no auth required) |
| `GET /api/covered-calls?ticker=EW` | Live option chain recommendations |
| `GET /api/cc-ai-analysis?ticker=EW` | AI narrative for the top-5 contracts: recommendation, IV context (HV rank + ATM IV), risks, roll strategy, timing (requires `qwen2.5:7b` via Ollama; ~90–120s on CPU) |
| `GET /api/dividends` | Dividend dates, yields, tax impact for all holdings |
| `GET /api/dividend-lookup?ticker=VYM&shares=100` | Dividend info for any ticker |
| `GET /api/dividend-timeline` | Monthly income (Jan–Dec, current year) |
| `GET /api/earnings` | Next earnings dates for all holdings |
| `GET /api/buffett-winners` | Latest Buffett screener results (includes valuation, first_seen, scan_duration, log_tail) |
| `POST /api/buffett-scan` | Start a manual screener run (no-op if already running; returns `{ok, reason}`) |
| `GET /api/buffett-analysis?ticker=KO&mode=annual` | On-demand 13-point Buffett deep-dive; `mode=annual` (default) uses annual filings, `mode=ttm` sums last 4 quarters |
| `GET /api/cc-positions` | All logged covered call positions; includes computed `pnl_total` and `pnl_day` for open positions with mark data; auto-expires past-expiry open positions |
| `POST /api/cc-positions` | Log a new covered call position |
| `POST /api/cc-import` | Import open positions from `covered_calls.csv`; skips duplicates |
| `PATCH /api/cc-positions/<id>` | Update position status / closing details (computes net_premium server-side); also accepts editable core fields (ticker, contracts, strike, expiry, premium_per_contract, opened_date) to correct typos |
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
| `GET /api/tlh-analysis` | Per-ticker unrealized G/L from `cost_lots`; used by the Tax Harvesting modal |
| `POST /api/refresh-dashboard` | Fetch fresh prices, update the DB, and regenerate the dashboard without sending email (backs the **↻ Refresh Data** button) |

---

## Daily Investment Digest

One email per day at **7 AM ET**, covering everything in a single HTML digest:

| Section | What it shows |
|---------|---------------|
| **📈 Portfolio Snapshot** | Total value, daily Δ%, SPY comparison, biggest mover |
| **⚖️ Layer Allocation vs Target** | All 5 layers: actual %, target %, drift (✓/▲/▼); orange warning box + subject-line flag when any layer is ≥5pp off |
| **📋 Holdings Performance** | All holdings grouped by layer, sorted by today's Δ$ |
| **⏰ Upcoming Events** | Earnings 📊 and ex-dividend 💵 dates in the next 3 days; urgency icons (🔴 tomorrow · 🟡 2 days · 🟢 3 days); section omitted if no events |
| **🧠 Judgment Health** | Rubric + automated concentration-dominance flags |

Runs automatically inside `serve.py` as a background thread — **no separate launchd job required**:

1. Checks if today's digest has already sent (`out/last_run_date.txt`)
2. If not and it's ≥ 7 AM ET, runs `send_newsletter_main.py` → `generate_dashboard.py`
3. After success, triggers the **data backup** to the private `investment-data` repo
4. Rechecks every 30 minutes as a safety net

**Logs:** `out/newsletter.log`

To run manually at any time:

```bash
venv/bin/python3 send_newsletter_main.py && venv/bin/python3 generate_dashboard.py
```

To refresh data without sending the email (same as the dashboard's **↻ Refresh Data** button):

```bash
venv/bin/python3 send_newsletter_main.py --no-email && venv/bin/python3 generate_dashboard.py
```

---

## Dashboard Features

### Investment Goals & Strategy Card

Two-column layout: wide left panel for goals, right column for barbell health + investment principles. On narrow screens (≤900px) the columns stack vertically, like the rest of the dashboard.

**Dividend Goal — $2,500/mo by 2036** (left panel, top)
- Current monthly gross and after-tax dividend income vs the $2,500/month target (after-tax rate reflects the selected Tax Bracket)
- Progress bar + percentage of goal reached
- Gap in $/month, years remaining, and required CAGR

**Portfolio Value Goal — $2M by 2036** (left panel, below dividend goal)
- Current portfolio value vs the $2,000,000 target
- Progress bar + required CAGR to reach $2M from today's value

**Quarterly Targets table** (left panel, bottom) — 8 rolling quarters showing both goals side by side:
- Each row: quarter label, dividend target ($/mo), portfolio target ($), status badges (on track / behind)
- For any behind quarter: recommended capital to deploy at current portfolio yield
- Header shows both required CAGRs and current dividend yield

**Layer Allocation vs Target** (right column, top)
- Shows all 5 layers side-by-side with actual weight %, architecture-based target %, and drift
- Drift color-coding: **green ✓** = within 2pp, **orange ▲** = over target, **blue ▼** = under target
- Each layer row has a horizontal progress bar (0–50% scale) with a dark marker line at the target weight, so over/under is instantly visible
- L4 Convexity row is annotated with the Taleb barbell "(10–15% band)"
- Target weights are set in `layer_targets.json` (architecture-based defaults):

| Layer | Name | Target |
|-------|------|--------|
| L1 | Structural Ballast | 35% |
| L2 | Cash-Flow Engines | 22% |
| L3 | Compounders | 30% |
| L4 | Convexity | 10% |
| L5 | Shock Absorbers | 8% |

**Recommended Purchases** (right column, bottom)
- Live recommendation engine that fetches `/api/buffett-winners` and `/api/earnings` on every page load
- Filters the Buffett screener's passing universe to exclude stocks already held and any with high value-trap risk
- Scores remaining candidates by risk level (low › medium › unknown) and valuation (penalizes P/E > 40, EV/EBITDA > 25, P/FCF > 35)
- Groups recommendations by layer, matched to whichever layers are most underweight vs `layer_targets.json` targets
- Each pick shows: risk badge (✓ Low / ⚠ Med / ? Unrated), P/E · P/FCF · EV/EBITDA · dividend yield, screener's layer assignment reason, and any active value trap flags (e.g. *gross margin compressing 2 yrs in a row*)
- Earnings warning (⚠ earnings in Nd) for any pick with an earnings date within 14 days
- L2 Cash-Flow Engine section shows estimated monthly income from deploying the layer gap at current portfolio yield
- Bottom card shows whether organic growth covers the $2M quarterly portfolio target or new capital is needed this quarter

### Header
- **📖 Glossary** (top right) — opens `/glossary` in a new tab; plain-English definitions for every term and metric in the UI, with formulas where relevant. V2 metrics (CC Alpha, Regret %, Score, IV Richness, μ, Exec Premium) are highlighted with a purple NEW badge.
- **↻ Refresh Data button** (top right) — fetches live prices from Yahoo Finance, writes today's portfolio snapshot to the DB, then regenerates `dashboard.html`. No email is sent. Takes 30–60 seconds while prices are fetched; the button shows "Refreshing…" and reloads the page automatically on completion.
- **Tax Bracket dropdown** (top right) — toggles between $150k / $300k / $500k / $750k / $1M+ MFJ income scenarios; updates the after-tax dividend KPI, dividend table tax/net columns, Goals card net income, and the after-tax chart line in real time. Affected elements flash briefly yellow so you can see what changed.

### KPI Cards (top row)
- **Portfolio Value** — total market value
- **Daily Change** — today's P&L vs yesterday's close, using live `fast_info.last_price` vs `fast_info.previous_close` (true 1-day delta, not close-vs-close from the prior morning's snapshot). When open covered call positions have mark-to-market data, today's option P&L is added automatically.
- **SPY Change** — benchmark comparison
- **Total Gain vs Cost** — unrealized P&L vs your average cost across all holdings
- **Est. Annual Dividends (After-Tax)** — after-tax annual dividend income at the selected bracket; subtitle shows gross income and portfolio yield. Updates immediately when the Tax Bracket dropdown changes.
- **Est. Tax Bill** — current year's estimated federal tax (ST + LT); flips to "Final" label in the following year; accounts for stock gains, CC premium income, and any prior-year carryforward amounts

### Charts
- **Portfolio vs SPY cumulative return** — time-weighted return (TWR) anchored to Feb 11, 2026. When new money is added (new positions, additional shares), those capital inflows are treated as external cash flows and excluded from the return calculation — they never show as a percentage gain spike. Both portfolio and SPY start at 0% on the baseline date for a true apples-to-apples comparison.
- Allocation by layer (doughnut)
- Layer weight over time
- Today's layer performance (bar)
- **Dividend Income by Month** — blue bars (received) + green bars (expected) + purple cumulative line (gross) + orange dashed line (after-tax), Jan–Dec of current year

### Layer Summary Table
Columns: **Layer | Value | Weight | Δ$ | Δ% | Next Earnings**

Next Earnings shows the soonest reporting ticker per layer, color-coded red ≤7 days, orange ≤21 days, green further out.

### Holdings Table
Columns: **Ticker | Shares | Avg Cost | Price | Value | Total Gain | Daily Δ | Weight | Next Earnings | Layer | Tax Lots**

Column headers are **sticky** — they float at the top of the viewport as you scroll down the page (applies to Holdings, Dividend, Buffett Screener, and CC Tracker tables).

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
- **📋 All Transactions button** — opens a unified pop-out table showing every tax-impacting event in a single view: stock sales (ST/LT split), covered call closes (net premium), and any prior-year ST lump carryforward. Useful for reconciling with your broker's tax forms.

Estimated tax applies to positive gains only (losses offset within each term bucket). Federal rates only — does not include state taxes.

### Tax Loss Harvesting Modal

Click **✂ Tax Harvesting** in the Realized Gains & Tax card header to open the modeler.

**Harvest Summary panel (top):**
- Four "What you'd realize" buckets: ST Loss, LT Loss, ST Gain, LT Gain — update as you check/uncheck positions
- **Tax Impact** section:
  - *Current est. tax bill* — YTD tax computed from realized gains at your selected bracket
  - *Net ST* / *Net LT* — post–cross-netting amounts per term, color-coded red (owe) / green (save)
  - *Ordinary income offset (≤$3k)* — appears only when a net loss qualifies
  - *Loss carry-forward* — appears when net loss exceeds $3k
  - *Harvest tax impact* — bidirectional: **+$X more owed** (red) when winners dominate, **-$X saved** (green) when losers dominate
  - *Est. tax after harvest* — current tax ± harvest impact; goes up if selecting winners, down if selecting losers
- **Wash sale warning** — flags any position sold within 30 days before or after a substantially identical purchase

**Positions table (bottom):**
- All open positions with unrealized G/L pulled from `cost_lots` table (lot-level aggregated per ticker)
- Columns: checkbox, Ticker, ST Gain, ST Loss, LT Gain, LT Loss, Total G/L — sorted losers-first
- Check any row to include it in the harvest calculation; "Select All Losers" button pre-checks every net-loss position

**IRS netting logic:**
1. ST losses offset ST gains first; excess ST loss absorbs LT gains
2. LT losses offset LT gains first; excess LT loss absorbs ST gains
3. After cross-netting, any remaining net loss offsets up to $3k of ordinary income; the rest carries forward

### Covered Call Position Tracker

**Bulk import:** Edit `covered_calls.csv` with your open positions and click **⬆ Import CSV** in the card header. Skips any position already in the DB (matched on ticker + strike + expiry). Format:

```
ticker,contracts,strike,expiry,premium_per_contract,opened_date,notes
EW,1,100,2026-08-21,0.90,2026-06-22,monthly
NFLX,1,100,2026-07-31,0.24,2026-06-29,
```

**Logging:** Use the **+ Log New Position** form — ticker, contracts, strike, expiry, premium/contract, open date.

**Editing a position:** Click the **✎** button next to the ticker on any open or closed row to correct typos or update position details (ticker, contracts, strike, expiry, premium/contract, open date, notes). Changes are written to the DB immediately.

**Mark-to-market columns (open positions):**
- **Mark** — current option price (bid/ask midpoint from yfinance; fetched on every ↻ Refresh Data)
- **Unrealized P&L** — total gain/loss on the option position since it was sold: `(premium − mark) × contracts × 100`
- **Today's P&L** — option price movement since the previous refresh: `(prev_mark − mark) × contracts × 100`

Today's option P&L is also added to the **Daily Change KPI** at the top of the dashboard. The first refresh after opening a position seeds the baseline; daily delta appears from the second refresh onwards.

**Tickers are normalized** automatically — entering `BRK.B` in the form stores `BRK-B` so yfinance option chain lookups work correctly.

**Closing a position:** Click **Close ▾** on any open row. A modal appears with three close types:
- **Expired Worthless** — option expired OTM; full premium is kept; `closed_price = 0`
- **Bought Back** — enter the buy-back price; net income = (sold − bought) × contracts × 100
- **Assigned** — stock called away at strike; full premium kept; optionally records the stock sale in the FIFO tracker at the strike price (the resulting stock capital gain/loss flows into ST/LT section)

**Auto-expiry:** On every page load, any open position whose expiry date has passed is automatically recorded as expired (full premium kept, `closed_date` set to the actual expiry date). A toast notification appears and prompts you to verify if any were actually assigned.

**Net P&L column:** Closed positions show actual net realized income, with buyback cost called out in red when applicable. The summary bar shows open gross premium and net realized income separately.

**Tax integration:** CC net premium income always flows into the **Short-Term / Ordinary** KPI tile and the EST. ST Tax calculation — premium income is always taxed as ordinary income regardless of how long the position was open.

### Buffett Deep-Dive Analyzer

Type any ticker and click **Analyze** (or press Enter) to run a 13-point Buffett analysis on demand.

**Annual / TTM toggle**: switch between two data modes before analyzing:
- **Annual** (default) — uses the most recent full fiscal-year filing (`stock.financials`). Best for companies with stable, calendar-year reporting.
- **TTM** (trailing 12 months) — sums the last 4 quarters from quarterly filings (`stock.quarterly_financials`, `stock.quarterly_cashflow`); balance sheet metrics use the most recent quarter snapshot. Useful for companies mid-fiscal-year or with significant recent trends.

**Source reference**: the period label under the score bar always shows exactly what data is being used — e.g. `FY 2024 annual (fiscal year ended Sep 28, 2024)` or `TTM as of Q2 2025 (ended Mar 29, 2025) · 4Q summed`. A link to the corresponding SEC EDGAR filings (10-K for annual, 10-Q for TTM) appears in the results footer.

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

The screener runs automatically at **2 AM ET** each night as a background thread inside `serve.py`. It scans NYSE + NASDAQ (~6,500 deduplicated tickers) applying six quality criteria:

| Metric | Threshold |
|---|---|
| Gross Margin | ≥ 40% |
| SG&A / Gross Profit | ≤ 30% |
| Net Income Margin | ≥ 20% |
| Interest / Op. Income | ≤ 15% |
| CapEx / Net Income | ≤ 50% |
| Cash > Total Debt | Yes |

**Smart caching:** tickers whose `mostRecentQuarter` hasn't changed skip the full financial fetch. Valuation metrics (P/E, P/FCF, EV/EBITDA) are always refreshed from current price data even on cache hits, so they're never stale. Cache updates are committed immediately before any flush logic runs, so they survive even if a scan is interrupted mid-run.

**No repeat emails:** The screener emails only when a ticker qualifies for the **first time ever**. Once a ticker appears in `buffett_winner_history` it is never re-notified, regardless of how many subsequent scans it passes. The email fires once per scan run (at completion), not at each intermediate flush.

**Historical tracking:** `buffett_winner_history` records when each ticker first qualified; shown as "since YYYY-MM-DD" in the screener card.

**Dashboard UI:** The screener card shows full live status:
- **Status badge** — ✓ Complete / ⏳ Scanning / ⚠ Incomplete / Never run
- **Progress bar + ETA** — visible while a scan is running; auto-refreshes every 20 seconds
- **▶ Run Scan button** — triggers a manual scan immediately via `POST /api/buffett-scan`; button is disabled while a scan is already running
- **Criteria chips** — the 6 quality filters displayed inline so it's always clear what the screener tests
- **Partial results** — winners found so far appear in the table even before the scan finishes, with a "partial results (X% scanned)" note
- **Scan duration** — how long the last completed scan took
- **Exchange badge** — each winner shows a color-coded **NYSE** (blue) or **NASDAQ** (green) badge next to the ticker in both the screener table and the Recommended Purchases panel
- **Filter bar** — above the table: text search (ticker/company/sector), Exchange chips (NYSE/NASDAQ), Layer chips (L1–L5), Risk chips (Low/Med/High); live match count updates instantly with no refetch
- **Sortable columns** — click any column header to sort ascending/descending; active column highlighted with a purple underline and ▼/▲ arrow; sortable by Ticker, Company, Layer, Trap Risk, Price, Gross %, SG&A %, Net Inc %, Interest %, CapEx %, P/E, P/FCF, EV/EBITDA
- **Log tail panel** — collapsible view of the last 20 lines of `screener.log`, color-coded (red = errors, orange = warnings, blue = section headers)

**Logs:** `out/screener.log`

```bash
venv/bin/python3 buffett_screener.py   # run manually
```

### Covered Call Analyzer
Select any holding with **100+ shares** and click **Get Recommendations**.

**Central question:** does selling this call provide positive expected value vs simply holding the stock?

**Profit floor (per contract, premium counts):**
`K + exec_premium ≥ max(cost × 1.10, price × 1.00)`
Executable fill estimated as `bid + 25% × spread` (not mid).

**Columns:** Expiry | Strike | DTE | Bid | Ask | Mid | Prem% | Ann% | P/L if Called | Δ (delta) | Prob Called | OI | **CC Alpha $** | **Regret %** | **Score**

| Column | What it means |
|---|---|
| **CC Alpha $** | exec_prem − E[max(S_T − K, 0)] under blended real-world drift. Positive = CC adds expected value vs holding. Green / orange / red. |
| **Regret %** | P(S_T > K + exec_prem) — probability the CC underperforms simply holding the stock. Distinct from and lower than assignment probability. |
| **Score** | 0–100 multi-factor: 25% CC Alpha + 15% each of yield, IV richness (IV/HV_forecast−1), liquidity (spread+OI+volume), vol-normalised upside room, inverse regret risk. |

**Volatility header:** shows HV Rank, ATM IV, HV_forecast, IV richness, and blended real-world drift (μ). IV richness > 0 means the option is expensive vs expected realised vol — better environment for selling premium.

**Event flags:**
- **Earnings:** strike distance compared to straddle-implied move (not a blanket block)
- **Ex-div:** extrinsic/dividend ratio — only flags AVOID when dividend ≥ extrinsic (early assignment actually makes economic sense for the holder); OTM contracts downgraded to CAUTION

**DO NOTHING is an explicit candidate** — if the best CC Alpha is negative, the report flags it.

**🤖 AI Analysis** — after loading recommendations, click the purple "🤖 AI Analysis" button to get `qwen2.5:7b` narrative insight from the optiplex. Takes ~90–120 seconds on CPU. The AI panel shows:

| Section | What it covers |
|---|---|
| 🎯 Recommendation | Which contract has the best CC Alpha vs holding outright, given IV richness, regret probability, and portfolio layer |
| 📊 IV Context | Whether current HV rank + IV richness make this a good time to sell premium |
| 🤷 No-Call Case | Whether the evidence supports doing nothing (negative CC Alpha, strong momentum, compressed IV) |
| ⚠️ Risks | Per-contract risks (earnings coverage, ex-div ratio, wide spread, high regret probability) |
| 🔄 Roll Strategy | Roll triggers citing delta, DTE, and CC Alpha decay |
| ⏰ Timing | Entry timing — limit order, time of day, spread guidance |

Requires Ollama running on the optiplex with `qwen2.5:7b` pulled (`ollama pull qwen2.5:7b`). If Ollama is unavailable, the button returns a graceful error.

### Dividend Tracker
Auto-loads on page open. Hit **Refresh** to update; cached 1 hour per day.

**Columns:** Ticker | Status | Ex-Div Date | Pay Date | Amount/Share | This Payout | Annual Income | Est. Tax | Net After-Tax | Yield | Yield on Cost

**Status badges:**
- **UPCOMING** (green) — ex-div date is in the future
- **PAYMENT DUE** (blue) — ex-div has passed, pay date is still in the future (cash not yet received)
- **LAST KNOWN** (grey) — both dates are in the past; sorted most-recent-first

**Pay date sourcing:**
- Individual stocks — from yfinance; dates >90 days after ex-div are discarded (yfinance sometimes returns wrong fiscal-year dates for WMT, GRMN, etc.)
- ETFs (SCHD, SLYV, IGV, etc.) — scraped from stockanalysis.com dividend history when yfinance has no data
- Vanguard / Fidelity mutual funds — estimated as ex-date + 1 business day (typical fund practice); shown with a `~` prefix to indicate the value is estimated

**Dividend Lookup**: enter any ticker + share count to see metrics and projected portfolio impact.

---

## Layer Drift Targets

`layer_targets.json` sets the recommended weight for each layer. Drift vs. these targets is shown in both the dashboard (Layer Allocation vs Target panel) and the daily email digest (inline warning when any layer is ≥5pp off).

**Targets file:** `layer_targets.json` — edit to adjust; defaults reflect the portfolio architecture:

```json
{ "1": 35, "2": 22, "3": 30, "4": 10, "5": 8 }
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

Output columns: Expiry · Strike · DTE · Bid · Ask · Exec · Prem% · Ann% · P/L · Delta · ITM% · Regret% · CCα$ · Liq · Score

Ranked by multi-factor score; if the best `CCα$` is negative, a DO NOTHING warning is printed.

---

## Project Structure

```
investment/
├── holdings.csv                     # Portfolio positions — Stock, Shares, AvgCost, Layer
├── covered_calls.csv                # Bulk-import seed for open covered call positions
├── layer_targets.json               # Target layer allocations (used by dashboard + email digest)
├── backup_data.sh                   # Pushes DB + CSV to private investment-data repo
├── run_server.sh                    # Infinite-loop wrapper around serve.py (used by launchd)
├── send_newsletter_main.py          # Fetches prices, sends email, writes DB
├── generate_dashboard.py            # Generates out/dashboard.html
├── serve.py                         # HTTP server + all API endpoints + schedulers
├── buffett_screener.py              # NYSE Buffett screener — nightly at 2 AM ET
├── covered_call_rec.py              # Covered call recommendation + blackout engine + ai_context() prompt builder
├── ollama_client.py                 # Thin urllib wrapper for Ollama's /api/generate endpoint (qwen2.5:7b, timeout 180s)
├── run_investment.sh                # Manual newsletter entry point
├── chart.umd.min.js                 # Bundled Chart.js (no CDN dependency)
├── favicon.svg                      # Dashboard browser tab icon
├── .env                             # ⚠ Not committed — email credentials
└── out/
    ├── investment.db                # SQLite: price history, cc_positions, cost_lots, sell_transactions
    ├── buffett.db                   # SQLite: Buffett screener cache, winners, history
    ├── dashboard.html               # Generated dashboard (served by serve.py)
    ├── newsletter.log               # Daily digest run log
    ├── screener.log                 # Nightly Buffett screener log
    ├── last_run_date.txt            # Flag — prevents double digest sends
    ├── last_screener_date.txt       # Flag — prevents double screener runs
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
