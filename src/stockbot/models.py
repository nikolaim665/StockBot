from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Headline:
    title: str
    publisher: str
    link: str
    published: datetime | None
    score: float  # VADER compound, -1..1


@dataclass
class Holding:
    broker: str
    broker_symbol: str
    name: str
    isin: str | None
    currency: str  # instrument currency (prices are quoted in this)
    quantity: float
    avg_price: float
    price: float
    value: float  # in account currency
    cost: float  # in account currency
    unrealized_pnl: float  # in account currency
    account_currency: str
    exchange: str | None = None

    # Filled in by enrichment
    yahoo: str | None = None
    chg_1d: float | None = None
    chg_1w: float | None = None
    chg_1m: float | None = None
    sentiment: float | None = None
    headlines: list[Headline] = field(default_factory=list)

    @property
    def pnl_pct(self) -> float | None:
        return self.unrealized_pnl / self.cost if self.cost else None


@dataclass
class AccountSnapshot:
    broker: str
    currency: str
    total_value: float
    cash: float
    invested_value: float
    cost: float
    unrealized_pnl: float
    realized_pnl: float | None
    holdings: list[Holding]
    as_of: datetime | None = None  # None = live
    note: str | None = None
