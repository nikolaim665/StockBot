"""Interactive Brokers via the Flex Web Service.

Read-only and token based: no TWS / IB Gateway needed. Data reflects the last
statement (normally the previous close), which suits a morning summary.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import httpx

from ..config import CACHE_DIR, IBKRConfig
from ..models import AccountSnapshot, Holding
from . import BrokerError

SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
IN_PROGRESS_CODES = {"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021"}


class IBKRFlex:
    name = "IBKR"

    def __init__(self, cfg: IBKRConfig, client: httpx.Client | None = None, cache_dir: Path = CACHE_DIR):
        if not cfg.flex_token or not cfg.flex_query_id:
            raise BrokerError("IBKR Flex token/query id not configured")
        self.cfg = cfg
        self._client = client or httpx.Client(timeout=30, headers={"User-Agent": "stockbot/0.1"})
        self._cache = cache_dir / f"ibkr_flex_{cfg.flex_query_id}.xml"

    def snapshot(self) -> AccountSnapshot:
        return parse(self._statement_xml())

    # -- fetching -------------------------------------------------------------

    def _statement_xml(self) -> str:
        if self._cache.exists() and time.time() - self._cache.stat().st_mtime < self.cfg.cache_minutes * 60:
            return self._cache.read_text()
        xml = self._fetch()
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        self._cache.write_text(xml)
        self._cache.chmod(0o600)
        return xml

    def _call(self, url: str, q: str) -> str:
        try:
            r = self._client.get(url, params={"t": self.cfg.flex_token, "q": q, "v": "3"})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise BrokerError(f"IBKR Flex request failed: {e}") from e
        return r.text

    def _fetch(self) -> str:
        root = ET.fromstring(self._call(SEND_URL, self.cfg.flex_query_id))
        if root.findtext("Status") != "Success":
            raise BrokerError(f"IBKR Flex: {root.findtext('ErrorMessage') or 'request failed'}")
        ref, url = root.findtext("ReferenceCode"), root.findtext("Url")

        delay = 2.0
        for _ in range(8):
            time.sleep(delay)
            body = self._call(url, ref)
            if "<FlexQueryResponse" in body[:500]:
                return body
            resp = ET.fromstring(body)
            code = resp.findtext("ErrorCode") or ""
            if code not in IN_PROGRESS_CODES:
                raise BrokerError(f"IBKR Flex: {resp.findtext('ErrorMessage') or body[:200]}")
            delay = min(delay * 1.5, 10)
        raise BrokerError("IBKR Flex: statement not ready, try again shortly")


# -- parsing -------------------------------------------------------------------


def _f(el: ET.Element, attr: str, default: float = 0.0) -> float:
    v = el.get(attr)
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y%m%d;%H%M%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def parse(xml: str) -> AccountSnapshot:
    root = ET.fromstring(xml)
    statements = root.findall(".//FlexStatement")
    if not statements:
        raise BrokerError("IBKR Flex: no FlexStatement in response")

    holdings: list[Holding] = []
    total = cash = 0.0
    base_ccy = ""
    as_of: datetime | None = None

    for st in statements:
        info = st.find("AccountInformation")
        acct_ccy = info.get("currency", "") if info is not None else ""
        first = len(holdings)

        for p in st.iterfind("OpenPositions/OpenPosition"):
            if p.get("levelOfDetail", "SUMMARY") not in ("SUMMARY", ""):
                continue  # skip per-lot rows
            if p.get("assetCategory", "STK") not in ("STK", "ETF", "FUND"):
                continue
            fx = _f(p, "fxRateToBase", 1.0) or 1.0
            qty = _f(p, "position")
            value = _f(p, "positionValue") * fx
            cost = _f(p, "costBasisMoney") * fx
            pnl = _f(p, "fifoPnlUnrealized", (value - cost) / fx) * fx
            holdings.append(
                Holding(
                    broker=IBKRFlex.name,
                    broker_symbol=p.get("symbol", "?"),
                    name=p.get("description") or p.get("symbol", "?"),
                    isin=p.get("isin") or None,
                    currency=p.get("currency", ""),
                    quantity=qty,
                    avg_price=_f(p, "costBasisPrice"),
                    price=_f(p, "markPrice"),
                    value=value,
                    cost=cost,
                    unrealized_pnl=pnl,
                    account_currency=acct_ccy,
                    exchange=p.get("listingExchange") or None,
                )
            )
            as_of = as_of or _date(p.get("reportDate"))

        eq = st.findall("EquitySummaryInBase/EquitySummaryByReportDateInBase")
        if eq:
            last = eq[-1]
            total += _f(last, "total")
            cash += _f(last, "cash")
            as_of = _date(last.get("reportDate")) or as_of
        else:
            total += sum(h.value for h in holdings[first:])
        base_ccy = base_ccy or acct_ccy

    as_of = as_of or _date(statements[0].get("toDate"))
    invested = sum(h.value for h in holdings)
    if not base_ccy and holdings:
        base_ccy = holdings[0].currency
    for h in holdings:
        h.account_currency = h.account_currency or base_ccy

    return AccountSnapshot(
        broker=IBKRFlex.name,
        currency=base_ccy,
        total_value=total or invested,
        cash=cash,
        invested_value=invested,
        cost=sum(h.cost for h in holdings),
        unrealized_pnl=sum(h.unrealized_pnl for h in holdings),
        realized_pnl=None,
        holdings=holdings,
        as_of=as_of,
        note="Flex statement (previous close)",
    )
