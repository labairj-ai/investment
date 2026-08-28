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
from email.utils import parsedate_to_datetime
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

MAX_PER_TICKER = 10

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
    ("CNBC",
     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147",
     CHROME_UA),
    ("CNBC Investing",
     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135",
     CHROME_UA),
    ("Reuters Business",
     "https://feeds.reuters.com/reuters/businessNews",
     SIMPLE_UA),
]

# Subscriber RSS feeds — require DJSESSION cookie; fail silently if unavailable
SUBSCRIBER_FEEDS = [
    ("WSJ US Business",  "https://feeds.content.dowjones.io/public/rss/WSJUSBusinessFeed"),
    ("WSJ Markets",      "https://feeds.content.dowjones.io/public/rss/WSJMarketsFeed"),
    ("WSJ Tech",         "https://feeds.content.dowjones.io/public/rss/WSJTechnologyFeed"),
    ("Barrons Stocks",   "https://feeds.content.dowjones.io/public/rss/RSSBarronsStocks"),
]

# Article body fetching
MAX_BODY_CHARS = 2500
BODY_TIMEOUT   = 12

# Selectors tried in order; first match with ≥150 chars of text wins
_BODY_SELECTORS = [
    # WSJ / Barrons / MarketWatch
    "[class*='article-wrap__body']",
    "[class*='article__body']",
    "[class*='articleBody']",
    ".article-content",
    ".wsj-snippet-body",
    "section[class*='body']",
    "div[class*='article-body']",
    "div[data-type='paragraph']",
    # CNBC
    "div.ArticleBody-articleBody",
    "div[class*='ArticleBody']",
    # Reuters
    "div[class*='article-body']",
    "article[class*='article-body']",
    # Motley Fool / 247WallSt / generic
    "div.article-body",
    "div#article-body",
    "article",
    "main",
]

# DJ domains blocked by Cloudflare bot protection — skip direct HTTP fetching
_CF_BLOCKED_DOMAINS = ("wsj.com", "barrons.com", "marketwatch.com")


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
                              "pub_date": pub, "excerpt": desc})
    except Exception:
        pass
    return items


def _fetch_feed(url, source, ua, cookie=None):
    try:
        h = {"User-Agent": ua, "Accept": "application/rss+xml, text/xml, */*"}
        if cookie:
            h["Cookie"] = cookie  # full Cookie header string
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

_PAREN_TICKER_RE = re.compile(r'(.{0,60}?)\(([A-Z]{1,5})\)', re.IGNORECASE)

def _parenthetical_mismatch(title, ticker, company_name):
    """
    Return True if the title contains (TICKER) but the company name immediately
    before the parenthetical belongs to a different company.
    E.g. "Itaú Unibanco (VLY) ..." should not match VLY / Valley National.
    """
    sym = ticker.upper()
    for m in _PAREN_TICKER_RE.finditer(title):
        if m.group(2).upper() != sym:
            continue
        prefix = m.group(1).strip()
        if not prefix or not company_name:
            return False
        company_words = [w.lower().rstrip(".,") for w in company_name.split()
                         if len(w.rstrip(".,")) >= 4
                         and w.lower().rstrip(".,") not in _GENERIC_WORDS]
        if not company_words:
            return False
        prefix_lower = prefix.lower()
        if not any(w in prefix_lower for w in company_words):
            return True
    return False


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
        if _parenthetical_mismatch(text, ticker, company_name):
            return False
        for pat in patterns:
            if pat.search(text):
                return True
        return False

    return matches


# ── DJ Session auth ───────────────────────────────────────────────────────────

def _get_dj_cookies():
    """
    Return a full Cookie header string for DJ properties, or None.
    Priority: browser-extracted tokens (WSJ_TAC + WSJ_TR) → WSJ_SESSION →
              cached programmatic login → fresh programmatic login.
    """
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")

    parts = []

    # Piano.io subscriber access token — primary gate for subscriber content
    tac = os.environ.get("WSJ_TAC", "").strip()
    if tac:
        parts.append(f"__tac={tac}")

    # Dow Jones user token
    tr = os.environ.get("WSJ_TR", "").strip()
    if tr:
        parts.append(f"TR={tr}")

    # Legacy explicit DJSESSION value
    direct = os.environ.get("WSJ_SESSION", "").strip()
    if direct:
        parts.append(f"DJSESSION={direct}")

    if parts:
        return "; ".join(parts)

    # Cached session from a previous programmatic login
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            if time.time() - data.get("_at", 0) < SESSION_TTL:
                cached = data.get("cookie")
                if cached:
                    return f"DJSESSION={cached}"
        except Exception:
            pass

    # Programmatic DJ SSO login (fallback)
    email    = os.environ.get("WSJ_EMAIL", "").strip()
    password = os.environ.get("WSJ_PASSWORD", "").strip()
    if email and password:
        session_cookie = _dj_login(email, password)
        if session_cookie:
            return f"DJSESSION={session_cookie}"

    return None


# Keep legacy alias so any external callers aren't broken
def _get_dj_session():
    return _get_dj_cookies()


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


# ── Article body fetching ─────────────────────────────────────────────────────

def _fetch_article_body(url, cookie=None):
    """
    Fetch full article text. Skips DJ domains (Cloudflare-blocked).
    Returns '' on failure or inaccessible URLs.
    """
    if not url:
        return ""
    # DJ properties are blocked by Cloudflare bot detection under requests
    if any(d in url for d in _CF_BLOCKED_DOMAINS):
        return ""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    try:
        headers = {
            "User-Agent": CHROME_UA,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Referer": "https://www.google.com/",
        }
        if cookie:
            headers["Cookie"] = cookie
        resp = requests.get(url, headers=headers, timeout=BODY_TIMEOUT,
                            allow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove nav, header, footer, scripts, ads before extracting
        for tag in soup(["nav", "header", "footer", "script", "style",
                          "aside", "figure", "noscript"]):
            tag.decompose()
        for sel in _BODY_SELECTORS:
            el = soup.select_one(sel)
            if el:
                paras = [p.get_text(" ", strip=True) for p in el.find_all("p")]
                text  = " ".join(p for p in paras if len(p) > 40)
                if len(text) > 150:
                    return text[:MAX_BODY_CHARS]
    except Exception:
        pass
    return ""


def enrich_with_bodies(by_ticker, cookie=None, max_per_ticker=3):
    """
    Adds 'body' field to the top articles in by_ticker (in-place + returned).
    Only hits DJ domains. Rate-limited to avoid 429s.
    """
    if not cookie:
        cookie = _get_dj_session()
    for items in by_ticker.values():
        for item in items[:max_per_ticker]:
            if item.get("body"):
                continue
            body = _fetch_article_body(item.get("url", ""), cookie)
            if body:
                item["body"] = body
            time.sleep(0.5)
    return by_ticker


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

    dj_cookie = _get_dj_cookies()
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

    # Keep only articles from the last 24 hours
    cutoff = time.time() - 86400
    def _pub_ts(s):
        try:
            return parsedate_to_datetime(s).timestamp()
        except Exception:
            return 0
    unique = [a for a in unique if _pub_ts(a.get("pub_date", "")) >= cutoff]

    # Build per-ticker matchers
    matchers = {t: _build_matcher(t, company_names.get(t)) for t in tickers}

    # Assign broad-feed articles to tickers
    by_ticker = {t: [] for t in tickers}
    for a in unique:
        haystack = a.get("title", "") + " " + a.get("excerpt", "")
        for ticker, matches in matchers.items():
            if len(by_ticker[ticker]) < MAX_PER_TICKER and matches(haystack):
                by_ticker[ticker].append({k: v for k, v in a.items()})

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
        matcher = matchers[ticker]
        for a in ticker_arts:
            if _pub_ts(a.get("pub_date", "")) < cutoff:
                continue
            haystack = a.get("title", "") + " " + a.get("excerpt", "")
            if not matcher(haystack):
                continue
            key = a.get("title", "")[:100].lower()
            if key and key not in seen and len(by_ticker[ticker]) < MAX_PER_TICKER:
                seen.add(key)
                by_ticker[ticker].append({k: v for k, v in a.items()})
        time.sleep(0.4)  # avoid rate-limiting

    # Drop tickers with no news
    by_ticker = {t: items for t, items in by_ticker.items() if items}

    result = {"by_ticker": by_ticker, "_fetched_at": time.time()}
    CACHE_PATH.write_text(json.dumps(result, indent=2))
    return result
