#!/usr/bin/env python3
"""
Fetch news articles mentioning portfolio holdings from WSJ, MarketWatch,
Barrons, and Yahoo Finance RSS feeds.
Optionally uses a DJ session cookie (WSJ_SESSION in .env) or programmatic
DJ SSO login (WSJ_EMAIL + WSJ_PASSWORD in .env) for subscriber feeds.
Company names cached in out/.company_names.json (7-day TTL) for better matching.
Cache: out/news_cache.json, 30-min TTL.
"""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_DIR  = Path(__file__).resolve().parent
CACHE_PATH   = PROJECT_DIR / "out" / "news_cache.json"
NAMES_CACHE  = PROJECT_DIR / "out" / ".company_names.json"
SESSION_FILE = PROJECT_DIR / "out" / ".wsj_session"
CACHE_TTL    = 1800       # 30 minutes
NAMES_TTL    = 7 * 86400  # 7 days
SESSION_TTL  = 82800      # 23 hours

SIMPLE_UA = "Mozilla/5.0 (compatible; investment-dashboard/1.0)"
CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MAX_PER_TICKER = 6

# Public feeds — no auth required
PUBLIC_FEEDS = [
    ("Yahoo Finance",
     "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
     SIMPLE_UA),
    ("MarketWatch",
     "https://feeds.content.dowjones.io/public/rss/mw_topstories",
     SIMPLE_UA),
    ("DJ Markets",
     "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
     SIMPLE_UA),
    ("WSJ",
     "https://feeds.content.dowjones.io/public/rss/RSSWSJD",
     SIMPLE_UA),
    ("Barrons",
     "https://feeds.content.dowjones.io/public/rss/RSSBarrons",
     SIMPLE_UA),
]

# Subscriber feeds — currently inaccessible (feeds.wsj.com has no DNS outside Dow Jones network)
SUBSCRIBER_FEEDS = []


def _parse_rss(xml_bytes, source):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            url   = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate", "").strip()
            desc  = item.findtext("description", "").strip()
            desc  = re.sub(r"<[^>]+>", " ", desc).strip()
            if title:
                items.append({"title": title, "url": url, "source": source,
                              "pub_date": pub, "_desc": desc})
    except Exception:
        pass
    return items


def _fetch_feed(url, source, ua, cookie=None):
    try:
        h = {"User-Agent": ua, "Accept": "application/rss+xml, text/xml, */*"}
        if cookie:
            h["Cookie"] = f"DJSESSION={cookie}"
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=10) as r:
            return _parse_rss(r.read(), source)
    except Exception:
        return []


# ── Company name cache ────────────────────────────────────────────────────────

def _load_company_names(tickers):
    """Return {ticker: shortname_keywords} using yfinance, cached 7 days."""
    existing = {}
    if NAMES_CACHE.exists():
        try:
            data = json.loads(NAMES_CACHE.read_text())
            if time.time() - data.get("_at", 0) < NAMES_TTL:
                existing = data.get("names", {})
        except Exception:
            pass

    needed = [t for t in tickers if t not in existing]
    if not needed:
        return existing

    try:
        import yfinance as yf
        for t in needed:
            try:
                info = yf.Ticker(t).info
                name = info.get("shortName") or info.get("longName", "")
                # Remove common suffixes that pollute matching
                name = re.sub(r"\b(Inc\.?|Corp\.?|LLC|Ltd\.?|ETF|Fund|Trust|Class [A-Z])\b.*",
                              "", name, flags=re.I).strip().rstrip(",.")
                existing[t] = name if len(name) >= 4 else None
            except Exception:
                existing[t] = None
    except ImportError:
        for t in needed:
            existing[t] = None

    NAMES_CACHE.parent.mkdir(exist_ok=True)
    NAMES_CACHE.write_text(json.dumps({"names": existing, "_at": time.time()}))
    return existing


# ── Ticker matching ───────────────────────────────────────────────────────────

_FUND_RE = re.compile(
    r"\b(etf|fund|index|trust|portfolio|spdr|vanguard|ishares|schwab|invesco|"
    r"fidelity|wisdomtree|dimensional|pimco|blackrock|proshares|direxion|"
    r"grayscale|bitcoin)\b",
    re.IGNORECASE,
)
# Words too common to anchor a company-name match
_GENERIC_WORDS = {"state", "national", "american", "global", "united", "first",
                  "general", "north", "south", "east", "west", "pacific",
                  "strategic", "total", "core", "small", "large", "growth", "value",
                  "price", "prices", "group", "power", "energy", "digital", "media",
                  "tech", "capital", "financial", "services", "solutions", "systems",
                  "health", "valley", "street", "market", "markets", "data", "cloud"}

def _build_matcher(ticker, company_name):
    """
    Return a callable(text) → bool that checks for ticker or company mention.
    ETFs/funds only match by ticker symbol; stocks match by a 2-word name phrase.
    """
    patterns = []

    sym = re.escape(ticker.upper())
    sym_flex = sym.replace(r"\-", r"[-./]?").replace(r"\.", r"[-./]?")
    patterns.append(re.compile(
        rf"(?<![A-Za-z\$])\$?{sym_flex}(?![A-Za-z])", re.IGNORECASE
    ))

    if company_name:
        is_fund = bool(_FUND_RE.search(company_name))
        if not is_fund:
            # First word ≥5 chars that isn't a common English word
            words = [w.rstrip(".,") for w in company_name.split()
                     if len(w.rstrip(".,")) >= 5
                     and w.lower().rstrip(".,") not in _GENERIC_WORDS]
            if words:
                patterns.append(re.compile(re.escape(words[0]), re.IGNORECASE))

    def matches(text):
        for pat in patterns:
            if pat.search(text):
                return True
        return False

    return matches


# ── DJ Session auth ───────────────────────────────────────────────────────────

def _get_dj_session():
    """Return a DJ session cookie string or None."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")

    # Option A: explicit cookie value in .env
    direct = os.environ.get("WSJ_SESSION", "").strip()
    if direct:
        return direct

    # Option B: cached cookie from a previous successful login
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            if time.time() - data.get("_at", 0) < SESSION_TTL:
                return data.get("cookie") or None
        except Exception:
            pass

    # Option C: programmatic DJ SSO login
    email    = os.environ.get("WSJ_EMAIL", "").strip()
    password = os.environ.get("WSJ_PASSWORD", "").strip()
    if email and password:
        return _dj_login(email, password)

    return None


def _dj_login(email, password):
    """
    Authenticate via Dow Jones SSO (Auth0-backed).
    Caches the resulting DJSESSION cookie in SESSION_FILE.
    Returns cookie string or None on failure.
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        session = requests.Session()
        session.headers.update({"User-Agent": CHROME_UA,
                                 "Accept": "text/html,application/xhtml+xml,*/*"})

        # Seed cookies from login page
        session.get("https://accounts.wsj.com/login", timeout=12, allow_redirects=True)

        # POST credentials to DJ Auth0 SSO
        resp = session.post(
            "https://sso.accounts.dowjones.com/usernamepassword/login",
            json={
                "client_id":     "B1VGaC32bsJGMjHG8QkZHutiWdyXCJfb",
                "connection":    "DJldap",
                "username":      email,
                "password":      password,
                "grant_type":    "password",
                "scope":         "openid email offline_access",
                "response_type": "token id_token",
            },
            headers={"Content-Type": "application/json",
                     "Referer": "https://accounts.wsj.com/"},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[NewsAuth] DJ SSO returned HTTP {resp.status_code}")
            return None

        # Parse Auth0 callback form and submit it
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            print("[NewsAuth] No callback form in DJ SSO response")
            return None

        action = form.get("action", "")
        fields = {inp.get("name"): inp.get("value", "")
                  for inp in form.find_all("input") if inp.get("name")}
        session.post(action, data=fields, timeout=15, allow_redirects=True)

        # Extract DJSESSION from cookie jar
        for domain_cookies in session.cookies._cookies.values():
            for path_cookies in domain_cookies.values():
                for name, morsel in path_cookies.items():
                    if "DJSESSION" in name.upper():
                        val = morsel.value
                        SESSION_FILE.parent.mkdir(exist_ok=True)
                        SESSION_FILE.write_text(
                            json.dumps({"cookie": val, "_at": time.time()}))
                        print("[NewsAuth] DJ login successful")
                        return val

        print("[NewsAuth] Login completed but DJSESSION cookie not found")
        return None

    except Exception as e:
        print(f"[NewsAuth] DJ login failed: {e}")
        return None


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch(tickers, force=False):
    """
    Fetch holding-relevant news. Returns:
    {"by_ticker": {ticker: [{title, url, source, pub_date}]}, "_fetched_at": float}
    """
    if not tickers:
        return {"by_ticker": {}, "_fetched_at": time.time()}

    CACHE_PATH.parent.mkdir(exist_ok=True)
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if time.time() - cached.get("_fetched_at", 0) < CACHE_TTL:
                return cached
        except Exception:
            pass

    dj_cookie = _get_dj_session()
    company_names = _load_company_names(tickers)

    # Collect articles from all sources
    all_articles = []
    for source, url, ua in PUBLIC_FEEDS:
        all_articles.extend(_fetch_feed(url, source, ua))

    if dj_cookie:
        for source, url in SUBSCRIBER_FEEDS:
            all_articles.extend(_fetch_feed(url, source, SIMPLE_UA, dj_cookie))

    # Deduplicate by title
    seen = set()
    unique = []
    for a in all_articles:
        key = a.get("title", "")[:100].lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(a)

    # Build per-ticker matchers
    matchers = {t: _build_matcher(t, company_names.get(t)) for t in tickers}

    # Assign broad-feed articles to tickers
    by_ticker = {t: [] for t in tickers}
    for a in unique:
        haystack = a.get("title", "") + " " + a.get("_desc", "")
        for ticker, matches in matchers.items():
            if len(by_ticker[ticker]) < MAX_PER_TICKER and matches(haystack):
                by_ticker[ticker].append({k: v for k, v in a.items()
                                          if not k.startswith("_")})

    # Per-ticker Yahoo Finance RSS for stocks that need more coverage
    name_cache = company_names
    for ticker in tickers:
        n = name_cache.get(ticker) or ""
        is_fund = bool(_FUND_RE.search(n)) if n else False
        if is_fund:
            continue  # skip ETFs — their ticker appears naturally in market articles
        if len(by_ticker[ticker]) >= MAX_PER_TICKER:
            continue  # already has enough
        url = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
               "?s=%s&region=US&lang=en-US" % ticker.replace(".", "-"))
        ticker_arts = _fetch_feed(url, "Yahoo Finance", SIMPLE_UA)
        for a in ticker_arts:
            key = a.get("title", "")[:100].lower()
            if key and key not in seen and len(by_ticker[ticker]) < MAX_PER_TICKER:
                seen.add(key)
                by_ticker[ticker].append({k: v for k, v in a.items()
                                          if not k.startswith("_")})
        time.sleep(0.4)  # avoid rate-limiting

    # Drop tickers with no news
    by_ticker = {t: items for t, items in by_ticker.items() if items}

    result = {"by_ticker": by_ticker, "_fetched_at": time.time()}
    CACHE_PATH.write_text(json.dumps(result, indent=2))
    return result
