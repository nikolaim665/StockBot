"""Market data (Yahoo Finance via yfinance): symbol resolution, price changes, FX, news."""

from __future__ import annotations

import json
import logging
import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from .config import CACHE_DIR
from .models import Headline, Holding

warnings.filterwarnings("ignore", module="yfinance")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

MARKET_INDICES = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "STOXX 600": "^STOXX",
    "FTSE 100": "^FTSE",
    "DAX": "^GDAXI",
}

# Trading 212 ticker suffix (lowercase letter before "_EQ") -> Yahoo suffix
T212_SUFFIX = {
    "l": ".L",  # London
    "d": ".DE",  # Xetra
    "p": ".PA",  # Paris
    "a": ".AS",  # Amsterdam
    "e": ".MC",  # Madrid
    "m": ".MI",  # Milan
    "s": ".SW",  # Swiss
    "b": ".BR",  # Brussels
    "i": ".IR",  # Dublin
}

# IBKR listingExchange -> Yahoo suffix
IBKR_EXCHANGE_SUFFIX = {
    **dict.fromkeys(["NASDAQ", "NYSE", "ARCA", "AMEX", "BATS", "NYSEARCA", "PINK", "IEX", "CBOE", "NMS"], ""),
    "LSE": ".L", "LSEETF": ".L",
    "IBIS": ".DE", "IBIS2": ".DE", "XETRA": ".DE", "FWB": ".F", "FWB2": ".F",
    "SBF": ".PA", "AEB": ".AS", "BM": ".MC", "BME": ".MC", "BVME": ".MI", "BVME.ETF": ".MI",
    "EBS": ".SW", "SWX": ".SW", "ENEXT.BE": ".BR", "ISED": ".IR",
    "TSE": ".TO", "VENTURE": ".V", "ASX": ".AX", "SEHK": ".HK", "SFB": ".ST", "CPH": ".CO",
    "OSE": ".OL", "HEX": ".HE",
}

_SYMBOL_CACHE = CACHE_DIR / "symbols.json"


def _load_cache(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(path: Path, data: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True))
    except OSError:
        pass


def guess_yahoo(h: Holding) -> str | None:
    """Heuristic broker-ticker -> Yahoo symbol."""
    if h.broker == "T212":
        t = h.broker_symbol
        m = re.fullmatch(r"(.+)_US_EQ", t)
        if m:
            return m.group(1).replace("_", "-").replace(".", "-")
        m = re.fullmatch(r"(.+?)([a-z])_EQ", t)
        if m and m.group(2) in T212_SUFFIX:
            return m.group(1).rstrip(".") + T212_SUFFIX[m.group(2)]
        return None
    if h.broker == "IBKR":
        sym = h.broker_symbol.strip()
        suffix = IBKR_EXCHANGE_SUFFIX.get((h.exchange or "").upper())
        if suffix is None:
            return None
        if suffix == "":
            return sym.replace(" ", "-").replace(".", "-")
        return sym.rstrip(".").replace(" ", "-") + suffix
    return None


def _isin_lookup(isin: str) -> str | None:
    try:
        quotes = yf.Search(isin, max_results=5, news_count=0).quotes
    except Exception:
        return None
    for q in quotes:
        if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", None):
            return q["symbol"]
    return None


def _closes(symbols: list[str], period: str = "3mo") -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    df = yf.download(
        sorted(set(symbols)), period=period, interval="1d",
        auto_adjust=False, progress=False, threads=True, group_by="column",
    )
    if df is None or df.empty:
        return pd.DataFrame()
    close = df["Close"]
    if isinstance(close, pd.Series):  # single symbol
        close = close.to_frame(name=symbols[0])
    return close


def _pct(series: pd.Series, back: int) -> float | None:
    s = series.dropna()
    if len(s) <= back:
        return None
    prev = s.iloc[-1 - back]
    return float(s.iloc[-1] / prev - 1) if prev else None


def changes(series: pd.Series) -> tuple[float | None, float | None, float | None]:
    return _pct(series, 1), _pct(series, 5), _pct(series, 21)


def enrich_prices(holdings: list[Holding], overrides: dict[str, str]) -> dict[str, tuple]:
    """Resolve Yahoo symbols, fill 1D/1W/1M changes. Returns index changes too."""
    cache = _load_cache(_SYMBOL_CACHE)
    for h in holdings:
        h.yahoo = overrides.get(h.broker_symbol) or cache.get(f"{h.broker}:{h.broker_symbol}") or guess_yahoo(h)

    symbols = [h.yahoo for h in holdings if h.yahoo] + list(MARKET_INDICES.values())
    closes = _closes(symbols)

    def has_data(sym: str | None) -> bool:
        return bool(sym) and sym in closes.columns and closes[sym].dropna().size > 1

    # Fallback: ISIN lookup for anything the heuristic got wrong
    missing = [h for h in holdings if not has_data(h.yahoo) and h.isin and h.broker_symbol not in overrides]
    if missing:
        with ThreadPoolExecutor(8) as ex:
            found = list(ex.map(lambda h: _isin_lookup(h.isin), missing))
        retry = {}
        for h, sym in zip(missing, found):
            if sym:
                h.yahoo = sym
                retry[sym] = h
        if retry:
            extra = _closes(list(retry))
            closes = pd.concat([closes, extra.drop(columns=[c for c in extra.columns if c in closes.columns])], axis=1)

    for h in holdings:
        if has_data(h.yahoo):
            h.chg_1d, h.chg_1w, h.chg_1m = changes(closes[h.yahoo])
            cache[f"{h.broker}:{h.broker_symbol}"] = h.yahoo
    _save_cache(_SYMBOL_CACHE, cache)

    return {
        name: changes(closes[sym]) + (float(closes[sym].dropna().iloc[-1]),)
        for name, sym in MARKET_INDICES.items()
        if has_data(sym)
    }


def fx_rates(currencies: set[str], target: str) -> dict[str, float]:
    """Multipliers to convert each currency into `target`."""
    rates = {target: 1.0}
    need = [c for c in currencies if c and c != target]
    if not need:
        return rates
    pairs = {c: f"{c}{target}=X" for c in need}
    closes = _closes(list(pairs.values()), period="5d")
    for c, sym in pairs.items():
        if sym in closes.columns and closes[sym].dropna().size:
            rates[c] = float(closes[sym].dropna().iloc[-1])
    return rates


_NAME_NOISE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|holdings?|group|plc|ltd|limited|n\.?v|s\.?a|se|ag|"
    r"ucits|etf|acc|dist|adr|class [a-c]|cl [a-c]|-cl [a-c]|the)\b\.?",
    re.I,
)


def clean_name(name: str) -> str:
    """'BERKSHIRE HATHAWAY-CL B' -> 'Berkshire Hathaway', 'ASML Holding N.V.' -> 'ASML'."""
    n = _NAME_NOISE.sub(" ", name.replace(",", " "))
    n = re.sub(r"[-–]\s*$|\s+", " ", n).strip(" -.")
    return n.title() if n.isupper() and len(n) > 5 else n


_JUNK = re.compile(r"stock price, news|price today|quote (&|and) history|stock chart, market cap|price, news, quote|tokenized", re.I)


def mentions(title: str, keywords: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", title, re.I) for k in keywords if k)


def _yahoo_news(symbol: str, keywords: list[str], limit: int, cutoff: datetime) -> list[dict]:
    try:
        items = yf.Search(symbol, max_results=1, news_count=20).news
    except Exception:
        return []
    out = []
    for n in items:
        title = n.get("title") or ""
        ts = n.get("providerPublishTime")
        published = datetime.fromtimestamp(ts, timezone.utc) if ts else None
        if not title or (published and published < cutoff):
            continue
        if not mentions(title, keywords) or _JUNK.search(title):
            continue  # generic market piece that merely tags the ticker
        out.append({"title": title, "publisher": n.get("publisher", ""),
                    "link": n.get("link", ""), "published": published})
        if len(out) >= limit:
            break
    return out


def _google_news(query: str, limit: int, max_age_days: int, cutoff: datetime) -> list[dict]:
    import httpx
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    try:
        r = httpx.get(
            "https://news.google.com/rss/search",
            params={"q": f'"{query}" stock when:{max_age_days}d', "hl": "en-IE", "gl": "IE", "ceid": "IE:en"},
            timeout=10,
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception:
        return []
    out = []
    for item in root.iterfind("./channel/item"):
        title = item.findtext("title") or ""
        publisher = item.findtext("source") or ""
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            published = None
        if (published and published < cutoff) or _JUNK.search(title):
            continue
        out.append({"title": title, "publisher": publisher, "link": item.findtext("link") or "",
                    "published": published})
        if len(out) >= limit:
            break
    return out


def fetch_news(symbol: str, name: str, count: int, max_age_days: int) -> list[dict]:
    """Relevant recent headlines: Yahoo first, topped up from Google News by company name."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    company = clean_name(name)
    base = symbol.split(".")[0].split("-")[0]
    out = _yahoo_news(symbol, [base if len(base) > 1 else "", company], count, cutoff)
    if len(out) < count and company:
        seen = {n["title"].lower() for n in out}
        for n in _google_news(company, count * 2, max_age_days, cutoff):
            if n["title"].lower() not in seen:
                out.append(n)
            if len(out) >= count:
                break
    out.sort(key=lambda n: n["published"] or cutoff, reverse=True)
    return out


def enrich_news(holdings: list[Holding], count: int, max_age_days: int, scorer) -> None:
    targets = {h.yahoo: h.name for h in holdings if h.yahoo}
    with ThreadPoolExecutor(8) as ex:
        futures = {s: ex.submit(fetch_news, s, n, count, max_age_days) for s, n in targets.items()}
        results = {s: f.result() for s, f in futures.items()}
    for h in holdings:
        items = results.get(h.yahoo, [])
        h.headlines = [Headline(score=scorer(i["title"]), **i) for i in items]
        h.sentiment = sum(x.score for x in h.headlines) / len(h.headlines) if h.headlines else None
