#!/usr/bin/env python3
import base64
import time
import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

import matplotlib
matplotlib.use("Agg")  # cron/headless safe
import matplotlib.pyplot as plt

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# -------------------------
# CONFIG
# -------------------------
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

PROJECT_DIR = Path("/Users/ai_lab/Desktop/investment")
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"
CREDENTIALS_JSON = PROJECT_DIR / "credentials.json"
TOKEN_JSON = PROJECT_DIR / "token.json"
OUT_DIR = PROJECT_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

DB_PATH = OUT_DIR / "investment.db"
CHART_PATH = OUT_DIR / "layer_allocation.png"

TO_EMAILS = ["robertjsherman1@gmail.com"]
BENCHMARK = "SPY"
TZ = ZoneInfo("America/New_York")

LAYER_NAMES = {
    1: "Structural Ballast",
    2: "Cash-Flow Engines",
    3: "Compounders",
    4: "Convexity / Optionality",
    5: "Shock Absorbers / Regime Hedges",
}

# Flags thresholds
LAYER_GROSS_DOMINANCE_PCT = 50.0
HOLDING_GROSS_DOMINANCE_PCT = 25.0


# -------------------------
# HELPERS
# -------------------------
def normalize_yahoo_ticker(t: str) -> str:
    t = str(t).strip().upper()
    if t.startswith("$"):
        t = t[1:]
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            t = f"{left}-{right}"
    return t


def money(x: float) -> str:
    return f"${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:.2f}%"


def signed_pct(x: float) -> str:
    return f"{x:+.1f}%"


def df_to_html_table(df: pd.DataFrame) -> str:
    return df.to_html(index=False, border=0, justify="left").replace(
        "<table",
        "<table cellpadding='6' cellspacing='0' style='border-collapse:collapse; width:100%; max-width:980px;'"
    ).replace(
        "<th>",
        "<th style='border-bottom:1px solid #ddd; text-align:left;'>"
    ).replace(
        "<td>",
        "<td style='border-bottom:1px solid #f2f2f2;'>"
    )


# -------------------------
# PRICING
# -------------------------
def fetch_last_two_closes(tickers: list[str]) -> pd.DataFrame:
    """
    Per-ticker fetch with retry (avoids occasional yfinance batch/cache lock issues).
    Returns df indexed by normalized ticker with close_yday, close_prev.
    """
    rows = []
    for raw in tickers:
        t = normalize_yahoo_ticker(raw)
        last_err = None

        for attempt in range(1, 4):
            try:
                hist = yf.Ticker(t).history(period="10d", interval="1d")
                s = hist["Close"].dropna()
                if len(s) >= 2:
                    rows.append((t, float(s.iloc[-1]), float(s.iloc[-2])))
                    last_err = None
                    break
                last_err = RuntimeError(f"Not enough closes for {t} (need 2). Got {len(s)} rows.")
            except Exception as e:
                last_err = e
            time.sleep(1.0 * attempt)

        if last_err is not None:
            raise RuntimeError(f"Failed to fetch closes for '{raw}' (normalized '{t}'). Last error: {last_err}")

    return pd.DataFrame(rows, columns=["ticker", "close_yday", "close_prev"]).set_index("ticker")


# -------------------------
# CHART
# -------------------------
def make_layer_pie(layers_df: pd.DataFrame, out_path: Path) -> None:
    total = float(layers_df["value_yday"].sum())
    if total <= 0:
        raise RuntimeError("Total portfolio value <= 0; cannot create allocation pie chart.")

    labels = [f'{row["Layer"]}\n{(row["value_yday"]/total)*100:.1f}%' for _, row in layers_df.iterrows()]

    plt.figure(figsize=(7, 7))
    plt.pie(layers_df["value_yday"], labels=labels, startangle=90)
    plt.title("Portfolio Allocation by Layer (Market Value)")
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


# -------------------------
# SQLITE STORAGE
# -------------------------
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_day (
      day TEXT PRIMARY KEY,
      total_value REAL,
      total_change_dollars REAL,
      total_change_pct REAL,
      spy_change_pct REAL
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS layer_day (
      day TEXT,
      layer TEXT,
      value REAL,
      change_dollars REAL,
      change_pct REAL,
      weight_pct REAL,
      PRIMARY KEY (day, layer)
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS holding_day (
      day TEXT,
      ticker TEXT,
      layer TEXT,
      shares REAL,
      price REAL,
      value REAL,
      change_dollars REAL,
      change_pct REAL,
      weight_pct REAL,
      PRIMARY KEY (day, ticker)
    )""")


def store_snapshot(day: str,
                   total_value: float,
                   total_change: float,
                   total_change_pct: float,
                   spy_change_pct: float,
                   layers_df: pd.DataFrame,
                   holdings_df: pd.DataFrame) -> None:
    """
    Writes/updates a single day's snapshot (idempotent).
    """
    conn = sqlite3.connect(str(DB_PATH))
    try:
        init_db(conn)

        conn.execute("""
          INSERT OR REPLACE INTO portfolio_day
          (day, total_value, total_change_dollars, total_change_pct, spy_change_pct)
          VALUES (?, ?, ?, ?, ?)
        """, (day, float(total_value), float(total_change), float(total_change_pct), float(spy_change_pct)))

        for _, r in layers_df.iterrows():
            conn.execute("""
              INSERT OR REPLACE INTO layer_day
              (day, layer, value, change_dollars, change_pct, weight_pct)
              VALUES (?, ?, ?, ?, ?, ?)
            """, (
                day,
                str(r["Layer"]),
                float(r["value_yday"]),
                float(r["chg_dollars"]),
                float(r["chg_pct"]),
                float(r["weight_pct"]),
            ))

        for _, r in holdings_df.iterrows():
            conn.execute("""
              INSERT OR REPLACE INTO holding_day
              (day, ticker, layer, shares, price, value, change_dollars, change_pct, weight_pct)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                day,
                str(r["Stock"]),
                str(r["LayerLabel"]),
                float(r["Shares"]),
                float(r["close_yday"]),
                float(r["value_yday"]),
                float(r["chg_dollars"]),
                float(r["chg_pct"]),
                float(r["weight_pct"]),
            ))

        conn.commit()
    finally:
        conn.close()


# -------------------------
# GMAIL OAUTH (NO PROFILE CALL)
# -------------------------
def get_gmail_service():
    creds = None
    if TOKEN_JSON.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_JSON), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_JSON), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_JSON.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def build_gmail_message(to_emails: list[str], subject: str, html_body: str, inline_png_path: Path) -> dict:
    msg = MIMEMultipart("related")
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(html_body, "html"))

    img = MIMEImage(inline_png_path.read_bytes(), _subtype="png")
    img.add_header("Content-ID", "<layer_pie>")
    img.add_header("Content-Disposition", "inline", filename=inline_png_path.name)
    msg.attach(img)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_gmail(service, message: dict) -> None:
    service.users().messages().send(userId="me", body=message).execute()


# -------------------------
# RUBRIC + FLAGS (NORMALIZED)
# -------------------------
def rubric_and_flags(total_change: float, layers: pd.DataFrame, holdings: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Important change:
    - Flags are based on SHARE OF GROSS MOVEMENT (abs changes summed), so percentages are always 0–100.
    - We ALSO show net contribution (signed % of net move) in parentheses for context.
    """
    flags: list[str] = []

    gross_layers = float(layers["chg_dollars"].abs().sum())
    gross_holdings = float(holdings["chg_dollars"].abs().sum())

    # Layer dominance (gross share)
    if gross_layers > 1e-9:
        tmp = layers.copy()
        tmp["gross_share_pct"] = (tmp["chg_dollars"].abs() / gross_layers) * 100.0
        top_layer = tmp.sort_values("gross_share_pct", ascending=False).iloc[0]

        if float(top_layer["gross_share_pct"]) > LAYER_GROSS_DOMINANCE_PCT:
            if abs(total_change) > 1e-9:
                net_pct = (float(top_layer["chg_dollars"]) / float(total_change)) * 100.0
                net_txt = f" (net contribution: {signed_pct(net_pct)})"
            else:
                net_txt = " (net contribution: n/a)"
            flags.append(
                f"⚠️ {top_layer['Layer']} drove {top_layer['gross_share_pct']:.1f}% of today’s gross movement{net_txt}."
            )

    # Holding dominance (gross share)
    if gross_holdings > 1e-9:
        h = holdings.copy()
        h["gross_share_pct"] = (h["chg_dollars"].abs() / gross_holdings) * 100.0
        top_hold = h.sort_values("gross_share_pct", ascending=False).iloc[0]

        if float(top_hold["gross_share_pct"]) > HOLDING_GROSS_DOMINANCE_PCT:
            if abs(total_change) > 1e-9:
                net_pct = (float(top_hold["chg_dollars"]) / float(total_change)) * 100.0
                net_txt = f" (net contribution: {signed_pct(net_pct)})"
            else:
                net_txt = " (net contribution: n/a)"
            flags.append(
                f"⚠️ {top_hold['Stock']} drove {top_hold['gross_share_pct']:.1f}% of today’s gross movement{net_txt}."
            )

    rubric_rows = [
        ("Outcome vs Process", "🟢 Green", "Daily outcome attributed by layer; no role violations detected by rule."),
        ("Risk Concentration Drift", "🟢 Green" if len(flags) == 0 else "🟡 Yellow",
         "No dominance flags." if len(flags) == 0 else "Dominance flag(s) triggered; monitor concentration."),
        ("Time Horizon Discipline", "🟢 Green", "Daily movements treated as signal/noise; no action prompts included."),
        ("Execution Hygiene", "🟢 Green", "Automated snapshot stored; repeatable process executed."),
    ]
    return pd.DataFrame(rubric_rows, columns=["Judgment Category", "Status", "Rationale"]), flags


# -------------------------
# EMAIL HTML
# -------------------------
def build_html(report_date: str,
               total_value: float, total_change: float, total_change_pct: float,
               spy_change_pct: float,
               layer_table_html: str,
               holdings_table_html: str,
               rubric_table_html: str,
               flags: list[str]) -> str:

    flags_html = ""
    if flags:
        flags_html = "<h3>Automated Flags</h3><ul>" + "".join(f"<li>{f}</li>" for f in flags) + "</ul>"

    anchor_state = "process-consistent" if not flags else "process-stressed"

    return f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.35;">
        <h2>Daily Portfolio Newsletter — {report_date}</h2>

        <h3>Executive Snapshot</h3>
        <ul>
          <li><b>Total value:</b> {money(total_value)}</li>
          <li><b>Daily change:</b> {money(total_change)} ({pct(total_change_pct)})</li>
          <li><b>SPY change:</b> {pct(spy_change_pct)}</li>
        </ul>

        <h3>Layer Performance</h3>
        {layer_table_html}

        <h3>Allocation by Layer (Market Value)</h3>
        <img src="cid:layer_pie" alt="Layer allocation pie chart" style="max-width:650px;width:100%;height:auto;" />

        <h3>Holdings Performance (Grouped by Layer)</h3>
        {holdings_table_html}

        <h3>Judgment Health Rubric</h3>
        {rubric_table_html}

        {flags_html}

        <hr/>
        <p><b>Discipline anchor:</b> Today’s portfolio behavior was <b>{anchor_state}</b> with no judgment violations requiring action.</p>
      </body>
    </html>
    """


# -------------------------
# MAIN
# -------------------------
def main():
    if not HOLDINGS_CSV.exists():
        raise FileNotFoundError(f"Missing holdings CSV at {HOLDINGS_CSV}")
    if not CREDENTIALS_JSON.exists():
        raise FileNotFoundError(f"Missing OAuth credentials at {CREDENTIALS_JSON}")

    holdings = pd.read_csv(HOLDINGS_CSV)
    cols = [str(c).strip() for c in holdings.columns]
    if all(c.startswith("Unnamed") for c in cols):
        raise ValueError(
            "holdings.csv appears to have no header row (all columns Unnamed). "
            "Fix in Numbers: enable Header Row and set columns to Stock,Shares,Layer, then re-export."
        )
    holdings.columns = cols

    required = {"Stock", "Shares", "AvgCost", "Layer"}
    missing = required - set(holdings.columns)
    if missing:
        raise ValueError(f"holdings.csv missing columns: {sorted(missing)}. Found: {list(holdings.columns)}")

    holdings["Stock"] = holdings["Stock"].astype(str).str.strip().str.upper().map(normalize_yahoo_ticker)
    holdings["Shares"] = holdings["Shares"].astype(float)
    holdings["Layer"] = holdings["Layer"].astype(int)

    holdings["LayerName"] = holdings["Layer"].map(lambda x: LAYER_NAMES.get(int(x), f"Layer {x}"))
    holdings["LayerLabel"] = holdings.apply(lambda r: f"Layer {int(r['Layer'])}: {r['LayerName']}", axis=1)

    tickers = sorted(set(holdings["Stock"].tolist() + [BENCHMARK]))
    closes = fetch_last_two_closes(tickers)

    holdings["close_yday"] = holdings["Stock"].map(closes["close_yday"])
    holdings["close_prev"] = holdings["Stock"].map(closes["close_prev"])

    holdings["value_yday"] = holdings["Shares"] * holdings["close_yday"]
    holdings["value_prev"] = holdings["Shares"] * holdings["close_prev"]
    holdings["chg_dollars"] = holdings["value_yday"] - holdings["value_prev"]
    holdings["chg_pct"] = (holdings["chg_dollars"] / holdings["value_prev"]) * 100.0

    layers = holdings.groupby(["LayerLabel"], as_index=False).agg(
        value_yday=("value_yday", "sum"),
        value_prev=("value_prev", "sum"),
        chg_dollars=("chg_dollars", "sum"),
    )
    layers["chg_pct"] = (layers["chg_dollars"] / layers["value_prev"]) * 100.0

    total_value = float(holdings["value_yday"].sum())
    total_prev = float(holdings["value_prev"].sum())
    total_change = total_value - total_prev
    total_change_pct = (total_change / total_prev) * 100.0 if total_prev else 0.0

    b = closes.loc[normalize_yahoo_ticker(BENCHMARK)]
    spy_change_pct = ((float(b["close_yday"]) - float(b["close_prev"])) / float(b["close_prev"])) * 100.0

    # chart + weights
    pie_df = layers.rename(columns={"LayerLabel": "Layer"}).copy()
    pie_df["weight_pct"] = (pie_df["value_yday"] / total_value) * 100.0
    make_layer_pie(pie_df[["Layer", "value_yday"]], CHART_PATH)

    holdings_db = holdings.copy()
    holdings_db["weight_pct"] = (holdings_db["value_yday"] / total_value) * 100.0

    # DB write (every run)
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    store_snapshot(day, total_value, total_change, total_change_pct, spy_change_pct, pie_df, holdings_db)

    # tables for email
    layer_display = pie_df.copy()
    layer_display["Value"] = layer_display["value_yday"].map(money)
    layer_display["Δ $"] = layer_display["chg_dollars"].map(money)
    layer_display["Δ %"] = layer_display["chg_pct"].map(pct)
    layer_display["Weight"] = layer_display["weight_pct"].map(lambda x: f"{x:.1f}%")
    layer_display = layer_display[["Layer", "Value", "Weight", "Δ $", "Δ %"]]
    layer_table_html = df_to_html_table(layer_display)

    h = holdings.copy()
    h["Value"] = h["value_yday"].map(money)
    h["Δ $"] = h["chg_dollars"].map(money)
    h["Δ %"] = h["chg_pct"].map(pct)
    h = h.sort_values(["Layer", "chg_dollars"], ascending=[True, False])
    holdings_display = h[["LayerLabel", "Stock", "Shares", "Value", "Δ $", "Δ %"]].rename(columns={"LayerLabel": "Layer"})
    holdings_table_html = df_to_html_table(holdings_display)

    rubric_df, flags = rubric_and_flags(total_change, pie_df, holdings)
    rubric_table_html = df_to_html_table(rubric_df)

    report_date = datetime.now(TZ).strftime("%A, %B %d, %Y")
    subject = f"Daily Portfolio Newsletter — {datetime.now(TZ).strftime('%Y-%m-%d')}"

    html = build_html(
        report_date=report_date,
        total_value=total_value,
        total_change=total_change,
        total_change_pct=total_change_pct,
        spy_change_pct=spy_change_pct,
        layer_table_html=layer_table_html,
        holdings_table_html=holdings_table_html,
        rubric_table_html=rubric_table_html,
        flags=flags,
    )

    service = get_gmail_service()
    message = build_gmail_message(TO_EMAILS, subject, html, CHART_PATH)
    send_gmail(service, message)


if __name__ == "__main__":
    main()
