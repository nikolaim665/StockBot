"""Fake accounts so the tool can be tried without API keys (market data is still real)."""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import AccountSnapshot, Holding


def _h(broker, sym, name, isin, ccy, qty, avg, price, acct_ccy, fx=1.0, exch=None):
    value = qty * price * fx
    cost = qty * avg * fx
    return Holding(broker, sym, name, isin, ccy, qty, avg, price, value, cost, value - cost, acct_ccy, exch)


def snapshots() -> list[AccountSnapshot]:
    t212 = [
        _h("T212", "AAPL_US_EQ", "Apple", "US0378331005", "USD", 12, 190.0, 344.6, "EUR", 0.894),
        _h("T212", "NVDA_US_EQ", "NVIDIA", "US67066G1040", "USD", 20, 95.0, 190.0, "EUR", 0.894),
        _h("T212", "ASMLa_EQ", "ASML Holding", "NL0010273215", "EUR", 3, 640.0, 700.0, "EUR"),
        _h("T212", "VODl_EQ", "Vodafone", "GB00BH4HKS39", "GBX", 900, 72.0, 119.1, "EUR", 0.0114),
    ]
    ibkr = [
        _h("IBKR", "MSFT", "MICROSOFT CORP", "US5949181045", "USD", 8, 310.0, 520.0, "USD", exch="NASDAQ"),
        _h("IBKR", "VWRA", "VANGUARD FTSE ALL-WORLD", "IE00BK5BQT80", "USD", 40, 110.0, 150.0, "USD", exch="LSEETF"),
        _h("IBKR", "BRK B", "BERKSHIRE HATHAWAY-CL B", "US0846707026", "USD", 5, 360.0, 480.0, "USD", exch="NYSE"),
    ]

    def snap(broker, ccy, hs, cash, as_of=None, note=None):
        inv = sum(h.value for h in hs)
        cost = sum(h.cost for h in hs)
        return AccountSnapshot(broker, ccy, inv + cash, cash, inv, cost, inv - cost, None, hs, as_of, note)

    return [
        snap("T212", "EUR", t212, 412.50),
        snap("IBKR", "USD", ibkr, 1250.00, datetime.now() - timedelta(days=1), "demo data"),
    ]
