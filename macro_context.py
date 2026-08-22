#!/usr/bin/env python3
"""
Macro context fetcher for portfolio AI analysis.
Pulls yfinance proxy instruments, FRED API indicators, and RSS headlines.
Results cached in out/macro_cache.json with a 30-minute TTL.
"""
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
CACHE_PATH = PROJECT_DIR / "out" / "macro_cache.json"
CACHE_TTL = 1800  # 30 minutes
TZ = ZoneInfo("America/New_York")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

RSS_URLS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
]


def _safe_float(v, default=None):
    try:
        f = float(v)
        import math
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


# ── yfinance proxies ──────────────────────────────────────────────────────────

def _fetch_yf_proxies() -> dict:
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")

    instruments = {
        "TLT":  "long_duration_bond",
        "GLD":  "gold",
        "^VIX": "vix",
        "UUP":  "dollar",
        "^TNX": "yield_10y",
        "^IRX": "yield_3m",
    }

    result = {}
    tickers = list(instruments.keys())
    try:
        data = yf.download(tickers, period="5d", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True)
        for sym, key in instruments.items():
            try:
                closes = data[sym]["Close"].dropna() if sym in data.columns.get_level_values(0) else None
                if closes is None or len(closes) < 2:
                    tk = yf.Ticker(sym)
                    hist = tk.history(period="5d", interval="1d")
                    closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    last = float(closes.iloc[-1])
                    prev = float(closes.iloc[-2])
                    chg_pct = (last - prev) / prev * 100 if prev else 0.0
                    result[key] = {"price": last, "chg_pct": round(chg_pct, 3)}
            except Exception:
                result[key] = {"price": None, "chg_pct": None}
    except Exception:
        # fallback: fetch individually
        for sym, key in instruments.items():
            try:
                tk = yf.Ticker(sym)
                hist = tk.history(period="5d", interval="1d")
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    last = float(closes.iloc[-1])
                    prev = float(closes.iloc[-2])
                    chg_pct = (last - prev) / prev * 100 if prev else 0.0
                    result[key] = {"price": last, "chg_pct": round(chg_pct, 3)}
                else:
                    result[key] = {"price": None, "chg_pct": None}
            except Exception:
                result[key] = {"price": None, "chg_pct": None}

    return result


def _interp_vix(vix: float) -> str:
    if vix is None:
        return "unavailable"
    if vix < 15:
        return "complacent — low fear"
    if vix < 20:
        return "calm"
    if vix < 25:
        return "elevated caution"
    if vix < 30:
        return "high anxiety"
    return "fear / stress"


def _interp_spread(spread_bps: float) -> str:
    if spread_bps is None:
        return "unavailable"
    if spread_bps > 50:
        return "steep — growth expected"
    if spread_bps > 0:
        return "mildly positive"
    if spread_bps > -50:
        return "flat to slightly inverted"
    return "inverted — recession signal"


def _interp_gld(chg: float) -> str:
    if chg is None:
        return "unavailable"
    if chg > 1.0:
        return "strong demand for inflation hedge"
    if chg > 0.3:
        return "mild inflation hedge demand"
    if chg < -1.0:
        return "inflation hedge selling — risk-on or USD strength"
    return "neutral"


def _interp_dollar(chg: float) -> str:
    if chg is None:
        return "unavailable"
    if chg > 0.5:
        return "strengthening — headwind for multinationals, commodity producers"
    if chg < -0.5:
        return "weakening — tailwind for multinationals, commodities, EM"
    return "roughly flat"


def _interp_tlt(chg: float) -> str:
    if chg is None:
        return "unavailable"
    if chg > 0.5:
        return "rates falling — duration-sensitive assets benefit"
    if chg < -0.5:
        return "rates rising — pressure on long-duration assets, REITs, growth"
    return "rates stable"


# ── FRED ──────────────────────────────────────────────────────────────────────

def _fetch_fred(series_id: str, api_key: str, limit: int = 14) -> list[dict]:
    url = (
        f"{FRED_BASE}?series_id={series_id}"
        f"&api_key={api_key}&file_type=json"
        f"&sort_order=desc&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "investment-ai/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return [o for o in data.get("observations", []) if o.get("value") != "."]


def _fetch_fred_indicators(api_key: str) -> dict:
    result = {"fed_funds": None, "cpi_yoy": None, "spread_10y2y": None, "unemployment": None}
    if not api_key:
        return result

    try:
        obs = _fetch_fred("FEDFUNDS", api_key, 2)
        if obs:
            result["fed_funds"] = _safe_float(obs[0]["value"])
    except Exception:
        pass

    try:
        obs = _fetch_fred("CPIAUCSL", api_key, 14)
        if len(obs) >= 13:
            # YoY = (recent / year_ago - 1) * 100
            recent = _safe_float(obs[0]["value"])
            year_ago = _safe_float(obs[12]["value"])
            if recent and year_ago:
                result["cpi_yoy"] = round((recent / year_ago - 1) * 100, 2)
    except Exception:
        pass

    try:
        obs = _fetch_fred("T10Y2Y", api_key, 2)
        if obs:
            result["spread_10y2y"] = _safe_float(obs[0]["value"])
    except Exception:
        pass

    try:
        obs = _fetch_fred("UNRATE", api_key, 2)
        if obs:
            result["unemployment"] = _safe_float(obs[0]["value"])
    except Exception:
        pass

    return result


# ── RSS headlines ─────────────────────────────────────────────────────────────

def _fetch_headlines(max_items: int = 7) -> list[str]:
    headlines = []
    for url in RSS_URLS:
        if len(headlines) >= max_items:
            break
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 investment-ai/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                xml_bytes = r.read()
            root = ET.fromstring(xml_bytes)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item")
            for item in items:
                title = item.findtext("title", "").strip()
                if title and title not in headlines:
                    headlines.append(title)
                if len(headlines) >= max_items:
                    break
        except Exception:
            continue
    return headlines


# ── Main assembler ────────────────────────────────────────────────────────────

def fetch(force: bool = False) -> dict:
    """Return macro context dict. Uses cache if < 30 min old unless force=True."""
    CACHE_PATH.parent.mkdir(exist_ok=True)
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if time.time() - cached.get("_fetched_at", 0) < CACHE_TTL:
                return cached
        except Exception:
            pass

    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
    fred_key = os.environ.get("FRED_API_KEY", "")

    yf_data = _fetch_yf_proxies()
    fred    = _fetch_fred_indicators(fred_key)
    headlines = _fetch_headlines()

    vix_price = yf_data.get("vix", {}).get("price")
    vix_chg   = yf_data.get("vix", {}).get("chg_pct")
    tlt_chg   = yf_data.get("long_duration_bond", {}).get("chg_pct")
    gld_chg   = yf_data.get("gold", {}).get("chg_pct")
    uup_chg   = yf_data.get("dollar", {}).get("chg_pct")

    tnx  = yf_data.get("yield_10y", {}).get("price")  # already in % (e.g. 4.42)
    irx  = yf_data.get("yield_3m",  {}).get("price")  # already in %

    # FRED T10Y2Y is in percent; if missing, derive from yfinance yields
    spread_pct = fred.get("spread_10y2y")
    if spread_pct is None and tnx and irx:
        spread_pct = round(tnx - irx, 3)
    spread_bps = round(spread_pct * 100, 0) if spread_pct is not None else None

    ctx = {
        "date":          date.today().isoformat(),
        # VIX
        "vix":           vix_price,
        "vix_chg":       vix_chg,
        "vix_interp":    _interp_vix(vix_price),
        # Rates
        "tlt_chg":       tlt_chg,
        "tlt_interp":    _interp_tlt(tlt_chg),
        "yield_10y":     tnx,
        "yield_3m":      irx,
        "spread_bps":    spread_bps,
        "curve_interp":  _interp_spread(spread_bps),
        # Inflation / Gold
        "gld_chg":       gld_chg,
        "gld_interp":    _interp_gld(gld_chg),
        # Dollar
        "uup_chg":       uup_chg,
        "dollar_interp": _interp_dollar(uup_chg),
        # FRED
        "fed_funds":     fred.get("fed_funds"),
        "cpi_yoy":       fred.get("cpi_yoy"),
        "unemployment":  fred.get("unemployment"),
        # Headlines
        "headlines":     headlines,
        # Cache metadata
        "_fetched_at":   time.time(),
    }
    ctx["formatted_block"] = _format_block(ctx)

    CACHE_PATH.write_text(json.dumps(ctx, indent=2))
    return ctx


def _format_block(ctx: dict) -> str:
    def fmt_pct(v, suffix=""):
        return f"{v:+.2f}%{suffix}" if v is not None else "N/A"
    def fmt_val(v, fmt=".2f", suffix=""):
        return f"{v:{fmt}}{suffix}" if v is not None else "N/A"

    lines = [
        f"=== MACRO CONTEXT ({ctx['date']}) ===",
        "",
        "FEAR / VOLATILITY",
        f"  VIX: {fmt_val(ctx['vix'])} ({ctx['vix_interp']})",
        "",
        "RATES",
        f"  Fed Funds Rate: {fmt_val(ctx['fed_funds'], '.2f', '%')}",
        f"  10Y Treasury Yield: {fmt_val(ctx['yield_10y'], '.2f', '%')}",
        f"  3M T-Bill Yield:    {fmt_val(ctx['yield_3m'],  '.2f', '%')}",
        f"  10Y-3M Spread:      {fmt_val(ctx['spread_bps'], '.0f', ' bps')} — {ctx['curve_interp']}",
        f"  TLT (long-duration): {fmt_pct(ctx['tlt_chg'])} — {ctx['tlt_interp']}",
        "",
        "INFLATION",
        f"  CPI YoY: {fmt_val(ctx['cpi_yoy'], '.1f', '%')}",
        f"  GLD (gold ETF): {fmt_pct(ctx['gld_chg'])} — {ctx['gld_interp']}",
        "",
        "US DOLLAR",
        f"  UUP (DXY proxy): {fmt_pct(ctx['uup_chg'])} — {ctx['dollar_interp']}",
        "",
        "LABOR",
        f"  Unemployment: {fmt_val(ctx['unemployment'], '.1f', '%')}",
    ]

    if ctx.get("headlines"):
        lines += ["", "TODAY'S TOP FINANCIAL HEADLINES:"]
        for i, h in enumerate(ctx["headlines"], 1):
            lines.append(f"  {i}. {h}")

    return "\n".join(lines)


if __name__ == "__main__":
    ctx = fetch(force=True)
    print(ctx["formatted_block"])
    print(f"\nFetched at: {datetime.fromtimestamp(ctx['_fetched_at'], tz=TZ).strftime('%H:%M:%S ET')}")
