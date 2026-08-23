#!/usr/bin/env python3
"""
Macro context fetcher for portfolio AI analysis.
Pulls yfinance proxy instruments, FRED API indicators, and RSS headlines.
Results cached in out/macro_cache.json with a 30-minute TTL.
"""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
CACHE_PATH = PROJECT_DIR / "out" / "macro_cache.json"
CACHE_TTL = 1800  # 30 minutes
TZ = ZoneInfo("America/New_York")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

CONGRESS_API_BASE = "https://api.congress.gov/v3"
BILLS_CACHE_PATH  = PROJECT_DIR / "out" / "bills_cache.json"
BILLS_CACHE_TTL   = 6 * 3600  # 6 hours — bill status changes slowly

_BILL_TYPE_DISPLAY = {
    "hr": "H.R.", "s": "S.", "hjres": "H.J.Res.", "sjres": "S.J.Res.",
    "hconres": "H.Con.Res.", "sconres": "S.Con.Res.", "hres": "H.Res.", "sres": "S.Res.",
}
_BILL_TYPE_PATH = {
    "hr": "house-bill", "s": "senate-bill",
    "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution", "sres": "senate-resolution",
}

RSS_URLS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
]

GOVTRACK_RSS_URLS = [
    ("introduced", "https://www.govtrack.us/congress/bills/browse?status=introduced&format=rss"),
    ("floor_vote", "https://www.govtrack.us/congress/bills/browse?status=vote&format=rss"),
]

# Keyword filter: bill titles must match to be included (unless floor-active stage)
_MARKET_TITLE_RE = re.compile(
    r"\b(tax|taxat|tariff|trade|fiscal|budget|appropriat|deficit|debt|revenue|spending"
    r"|reconciliat|finance|financial|bank|banking|credit|securit|invest|retirement"
    r"|401|IRA|pension|annuit"
    r"|energy|oil|gas|electric|grid|renewable|solar|wind|carbon|climate|nuclear|LNG|emission"
    r"|health|healthcare|pharma|drug|Medicare|Medicaid|hospital|FDA|insur"
    r"|defense|military|NDAA|intelligence|armed forces|DoD|national security"
    r"|tech|technology|artificial intelligence|semiconductor|chip|cyber|digital|broadband|internet"
    r"|import|export|sanction|customs|foreign invest|CFIUS"
    r"|labor|employ|wage|worker|union|workforce"
    r"|housing|mortgage|real estate|HUD|infrastructure|transport|flood|disaster"
    r"|agriculture|food|farm|crop)\b",
    re.IGNORECASE
)
_FLOOR_ACTIVE_STAGES = {"Floor vote", "Floor-bound", "Passed chamber", "Signed into law", "Vetoed"}

# Editorial sources — secondary context only; note potential political framing bias
LEGISLATIVE_MEDIA_URLS = [
    "https://rss.politico.com/congress.xml",
    "https://thehill.com/homenews/senate/feed/",
    "https://rollcall.com/feed/",
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


def _bill_stage(action_text: str) -> str:
    t = action_text.lower()
    if any(w in t for w in ["signed by president", "became public law", "enacted", "public law"]):
        return "Signed into law"
    if "vetoed" in t:
        return "Vetoed"
    if any(w in t for w in ["passed senate", "passed house", "senate agreed", "house agreed"]):
        return "Passed chamber"
    if any(w in t for w in ["roll call", "on passage", "on motion", "yeas and nays",
                             "failed of passage", "cloture"]):
        return "Floor vote"
    if any(w in t for w in ["placed on calendar", "calendar", "rule providing"]):
        return "Floor-bound"
    if any(w in t for w in ["markup", "reported", "ordered to be reported"]):
        return "Committee markup"
    if any(w in t for w in ["referred", "committee", "hearing", "subcommittee"]):
        return "In committee"
    if "introduced" in t:
        return "Introduced"
    return "Active"


def _fetch_crs_summary(congress: int, bill_type: str, number: str, api_key: str) -> str:
    """Fetch most recent CRS summary from Congress.gov API. Returns plain text ≤600 chars."""
    url = (
        f"{CONGRESS_API_BASE}/bill/{congress}/{bill_type.lower()}/{number}/summaries"
        f"?api_key={api_key}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "investment-ai/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        summaries = data.get("summaries", [])
        if summaries:
            text = summaries[-1].get("text", "")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:600]
    except Exception:
        pass
    return ""


def _normalize_bill_title(title: str) -> str:
    """Normalize for deduplication — strips year/act suffix, lowercases, collapses whitespace."""
    t = re.sub(r"\s+act\b.*", "", title, flags=re.IGNORECASE).strip()
    return re.sub(r"\W+", " ", t).lower().strip()


def _fetch_congress_api_bills(api_key: str, days_back: int = 30, max_bills: int = 40) -> list:
    """Fetch recently active bills from Congress.gov official API.
    Filters to market-relevant titles; always includes floor-active stages.
    Deduplicates House/Senate companion bills. Returns up to 15 bills.
    CRS summaries fetched for up to 8 bills with hasSummary=true."""
    if not api_key:
        return []
    from_date = (date.today() - timedelta(days=days_back)).isoformat() + "T00:00:00Z"
    url = (
        f"{CONGRESS_API_BASE}/bill"
        f"?fromDateTime={from_date}"
        f"&sort=updateDate+desc"
        f"&limit={max_bills}"
        f"&api_key={api_key}"
    )
    raw = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "investment-ai/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        congress_num = (date.today().year - 1789) // 2 + 1
        for b in data.get("bills", []):
            btype  = b.get("type", "").lower()
            bnum   = str(b.get("number", ""))
            action = b.get("latestAction", {})
            action_text = action.get("text", "")
            display_id  = f"{_BILL_TYPE_DISPLAY.get(btype, btype.upper())} {bnum}".strip()
            cgnum  = b.get("congress", congress_num)
            path   = _BILL_TYPE_PATH.get(btype, btype)
            last2  = cgnum % 100
            last1  = cgnum % 10
            suffix = "th" if last2 in range(11, 14) else {1: "st", 2: "nd", 3: "rd"}.get(last1, "th")
            human_url = f"https://www.congress.gov/bill/{cgnum}{suffix}-congress/{path}/{bnum}"
            raw.append({
                "bill_id":       display_id,
                "title":         b.get("title", ""),
                "introduced":    b.get("introducedDate", ""),
                "latest_action": action_text,
                "action_date":   action.get("actionDate", ""),
                "stage":         _bill_stage(action_text),
                "url":           human_url,
                "summary":       "",
                "source":        "Congress.gov",
                "has_summary":   bool(b.get("hasSummary")),
                "btype": btype, "bnum": bnum, "cgnum": cgnum,
            })
    except Exception:
        pass

    # Filter: keep floor-active stages always; committee bills only if market-relevant title
    # Deduplicate companion bills by normalized title (keep first encountered)
    seen_titles: set = set()
    filtered = []
    for entry in raw:
        nt = _normalize_bill_title(entry["title"])
        if nt in seen_titles:
            continue
        seen_titles.add(nt)
        if (entry["stage"] in _FLOOR_ACTIVE_STAGES
                or _MARKET_TITLE_RE.search(entry["title"])):
            filtered.append(entry)
        if len(filtered) >= 15:
            break

    # Fetch CRS summaries for top eligible bills (cap at 8 to limit latency)
    summary_count = 0
    for entry in filtered:
        if entry.pop("has_summary", False) and summary_count < 8:
            btype = entry.pop("btype", "")
            bnum  = entry.pop("bnum",  "")
            cgnum = entry.pop("cgnum", "")
            entry["summary"] = _fetch_crs_summary(cgnum, btype, bnum, api_key)
            summary_count += 1
            time.sleep(0.2)
        else:
            entry.pop("btype", None)
            entry.pop("bnum",  None)
            entry.pop("cgnum", None)

    return filtered


def _fetch_govtrack_bills(max_items: int = 10) -> list:
    """Non-partisan fallback: recently introduced and floor-vote bills from GovTrack."""
    bills = []
    seen  = set()
    for stage_label, url in GOVTRACK_RSS_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 investment-ai/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                root = ET.fromstring(r.read())
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                desc = item.findtext("description", "").strip()
                desc = re.sub(r"<[^>]+>", " ", desc).strip()
                bills.append({
                    "bill_id":       "",
                    "title":         title,
                    "introduced":    "",
                    "latest_action": "",
                    "action_date":   item.findtext("pubDate", "").strip()[:16],
                    "stage":         "Floor vote" if stage_label == "floor_vote" else "Introduced",
                    "url":           item.findtext("link", "").strip(),
                    "summary":       desc[:500] if desc else "",
                    "source":        "GovTrack",
                })
                if len(bills) >= max_items:
                    return bills
        except Exception:
            continue
    return bills


def _fetch_legislative_media(max_items: int = 8) -> list:
    """Legislative headlines from editorial sources (Politico, The Hill, Roll Call).
    Secondary context only — reflects editorial framing, not official record."""
    items = []
    seen  = set()
    for url in LEGISLATIVE_MEDIA_URLS:
        if len(items) >= max_items:
            break
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 investment-ai/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                root = ET.fromstring(r.read())
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append({
                    "title": title,
                    "date":  item.findtext("pubDate", "").strip(),
                    "link":  item.findtext("link", "").strip(),
                })
                if len(items) >= max_items:
                    break
        except Exception:
            continue
    return items


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
    fred_key     = os.environ.get("FRED_API_KEY", "")
    congress_key = os.environ.get("CONGRESS_API_KEY", "")

    yf_data   = _fetch_yf_proxies()
    fred      = _fetch_fred_indicators(fred_key)
    headlines = _fetch_headlines()

    # Official bill data — separate 6-hour cache so summary fetches don't slow every macro refresh
    official_bills = []
    bills_cached   = False
    if not force and BILLS_CACHE_PATH.exists():
        try:
            bc = json.loads(BILLS_CACHE_PATH.read_text())
            if time.time() - bc.get("_fetched_at", 0) < BILLS_CACHE_TTL:
                official_bills = bc.get("bills", [])
                bills_cached   = True
        except Exception:
            pass
    if not bills_cached:
        if congress_key:
            official_bills = _fetch_congress_api_bills(congress_key)
        if not official_bills:
            official_bills = _fetch_govtrack_bills()
        BILLS_CACHE_PATH.parent.mkdir(exist_ok=True)
        BILLS_CACHE_PATH.write_text(
            json.dumps({"bills": official_bills, "_fetched_at": time.time()}, indent=2)
        )

    media_coverage = _fetch_legislative_media()

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
        "headlines":          headlines,
        # Official bill record (Congress.gov API or GovTrack fallback)
        "official_bills":     official_bills,
        # Editorial media coverage (secondary context)
        "legislative_media":  media_coverage,
        # Backwards compat alias
        "legislative_bills":  official_bills or media_coverage,
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

    if ctx.get("official_bills"):
        lines += ["", "BILLS UNDER REVIEW — OFFICIAL RECORD:"]
        for b in ctx["official_bills"][:12]:
            id_str = f"[{b['bill_id']}] " if b.get("bill_id") else ""
            stage  = f" — {b['stage']}" if b.get("stage") else ""
            dt     = (b.get("action_date") or b.get("introduced") or "")[:10]
            date_s = f" ({dt})" if dt else ""
            lines.append(f"  {id_str}{b['title']}{stage}{date_s}")
            if b.get("summary"):
                lines.append(f"    CRS Summary: {b['summary'][:300]}")
            if b.get("latest_action") and b.get("stage") in (
                "Floor vote", "Passed chamber", "Signed into law", "Vetoed"
            ):
                lines.append(f"    Action: {b['latest_action']}")

    if ctx.get("legislative_media"):
        lines += ["", "LEGISLATIVE MEDIA COVERAGE (editorial — secondary):"]
        for b in ctx["legislative_media"][:6]:
            lines.append(f"  - {b['title']}")

    return "\n".join(lines)


if __name__ == "__main__":
    ctx = fetch(force=True)
    print(ctx["formatted_block"])
    print(f"\nFetched at: {datetime.fromtimestamp(ctx['_fetched_at'], tz=TZ).strftime('%H:%M:%S ET')}")
