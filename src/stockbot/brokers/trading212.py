"""Trading 212 Public API (v0) – read-only use: account summary + open positions."""

from __future__ import annotations

import httpx

from ..config import T212Config
from ..models import AccountSnapshot, Holding
from . import BrokerError

BASE_URLS = {
    "live": "https://live.trading212.com/api/v0",
    "demo": "https://demo.trading212.com/api/v0",
}


class Trading212:
    name = "T212"

    def __init__(self, cfg: T212Config, client: httpx.Client | None = None):
        if not cfg.api_key or not cfg.api_secret:
            raise BrokerError("Trading 212 API key/secret not configured")
        if cfg.environment not in BASE_URLS:
            raise BrokerError(f"Unknown Trading 212 environment: {cfg.environment!r}")
        self._client = client or httpx.Client(
            base_url=BASE_URLS[cfg.environment],
            auth=(cfg.api_key, cfg.api_secret),
            timeout=20,
        )

    def _get(self, path: str):
        try:
            r = self._client.get(path)
        except httpx.HTTPError as e:
            raise BrokerError(f"Trading 212 request failed: {e}") from e
        if r.status_code == 401:
            raise BrokerError("Trading 212 rejected the API key/secret (401)")
        if r.status_code == 403:
            raise BrokerError("Trading 212 API key lacks permission for " + path)
        if r.status_code == 429:
            raise BrokerError("Trading 212 rate limit hit – try again in a few seconds")
        if r.is_error:
            raise BrokerError(f"Trading 212 {path} → HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def snapshot(self) -> AccountSnapshot:
        summary = self._get("/equity/account/summary")
        positions = self._get("/equity/positions")
        return parse(summary, positions)


def parse(summary: dict, positions: list[dict]) -> AccountSnapshot:
    ccy = summary.get("currency", "")
    holdings: list[Holding] = []
    for p in positions:
        inst = p.get("instrument", {})
        wi = p.get("walletImpact", {})
        holdings.append(
            Holding(
                broker=Trading212.name,
                broker_symbol=inst.get("ticker", "?"),
                name=inst.get("name") or inst.get("ticker", "?"),
                isin=inst.get("isin"),
                currency=inst.get("currency", ""),
                quantity=float(p.get("quantity", 0)),
                avg_price=float(p.get("averagePricePaid", 0)),
                price=float(p.get("currentPrice", 0)),
                value=float(wi.get("currentValue", 0)),
                cost=float(wi.get("totalCost", 0)),
                unrealized_pnl=float(wi.get("unrealizedProfitLoss", 0)),
                account_currency=wi.get("currency", ccy),
            )
        )

    inv = summary.get("investments", {})
    cash = summary.get("cash", {})
    return AccountSnapshot(
        broker=Trading212.name,
        currency=ccy,
        total_value=float(summary.get("totalValue", 0)),
        cash=float(cash.get("availableToTrade", 0)) + float(cash.get("reservedForOrders", 0)),
        invested_value=float(inv.get("currentValue", sum(h.value for h in holdings))),
        cost=float(inv.get("totalCost", sum(h.cost for h in holdings))),
        unrealized_pnl=float(inv.get("unrealizedProfitLoss", sum(h.unrealized_pnl for h in holdings))),
        realized_pnl=inv.get("realizedProfitLoss"),
        holdings=holdings,
    )
