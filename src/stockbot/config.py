"""Configuration: ~/.config/stockbot/config.toml, overridable by environment variables."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "stockbot"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "stockbot"
CONFIG_PATH = Path(os.environ.get("STOCKBOT_CONFIG", CONFIG_DIR / "config.toml"))

TEMPLATE = """\
# StockBot configuration. Keep this file private (chmod 600).

# Currency used for the combined portfolio overview.
display_currency = "EUR"

# Headlines fetched per holding (used for sentiment + the news section).
news_per_stock = 3

# Ignore headlines older than this many days.
news_max_age_days = 7

[trading212]
enabled = true
# "live" (real money) or "demo" (paper trading)
environment = "live"
# Trading 212 app → Settings → API (Beta) → Generate key. Read-only permissions are enough.
# Can also be set via T212_API_KEY / T212_API_SECRET.
api_key = ""
api_secret = ""

[ibkr]
enabled = false
# IBKR Portal → Performance & Reports → Flex Queries:
#   1. Create an Activity Flex Query with sections: Open Positions, Equity Summary in Base, Account Information
#   2. Flex Web Service Configuration → enable, generate a token
# Can also be set via IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID.
flex_token = ""
flex_query_id = ""
# Flex statements reflect the previous close; cache to avoid rate limits.
cache_minutes = 60

# Override how broker tickers map to Yahoo Finance symbols, e.g.
# [symbols]
# "VODl_EQ" = "VOD.L"
[symbols]
"""


@dataclass
class T212Config:
    enabled: bool = True
    environment: str = "live"
    api_key: str = ""
    api_secret: str = ""


@dataclass
class IBKRConfig:
    enabled: bool = False
    flex_token: str = ""
    flex_query_id: str = ""
    cache_minutes: int = 60


@dataclass
class Config:
    display_currency: str = "EUR"
    news_per_stock: int = 3
    news_max_age_days: int = 7
    trading212: T212Config = field(default_factory=T212Config)
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    symbols: dict[str, str] = field(default_factory=dict)


def load(path: Path = CONFIG_PATH) -> Config:
    raw: dict = {}
    if path.exists():
        with path.open("rb") as f:
            raw = tomllib.load(f)

    t = raw.get("trading212", {})
    i = raw.get("ibkr", {})
    cfg = Config(
        display_currency=raw.get("display_currency", "EUR").upper(),
        news_per_stock=int(raw.get("news_per_stock", 3)),
        news_max_age_days=int(raw.get("news_max_age_days", 7)),
        trading212=T212Config(
            enabled=t.get("enabled", True),
            environment=t.get("environment", "live"),
            api_key=os.environ.get("T212_API_KEY", t.get("api_key", "")),
            api_secret=os.environ.get("T212_API_SECRET", t.get("api_secret", "")),
        ),
        ibkr=IBKRConfig(
            enabled=i.get("enabled", False),
            flex_token=os.environ.get("IBKR_FLEX_TOKEN", i.get("flex_token", "")),
            flex_query_id=str(os.environ.get("IBKR_FLEX_QUERY_ID", i.get("flex_query_id", ""))),
            cache_minutes=int(i.get("cache_minutes", 60)),
        ),
        symbols=dict(raw.get("symbols", {})),
    )
    return cfg


def write_template(path: Path = CONFIG_PATH) -> bool:
    """Create the config template. Returns False if it already exists."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE)
    path.chmod(0o600)
    return True
