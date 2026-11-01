"""stockbot – morning portfolio summary in the terminal."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from rich.console import Console

from . import config as config_mod
from .brokers import BrokerError
from .models import AccountSnapshot


def _brokers(cfg: config_mod.Config, only: str | None, errors: list[str]):
    from .brokers.ibkr_flex import IBKRFlex
    from .brokers.trading212 import Trading212

    out = []
    for key, enabled, factory, sub in (
        ("t212", cfg.trading212.enabled, Trading212, cfg.trading212),
        ("ibkr", cfg.ibkr.enabled, IBKRFlex, cfg.ibkr),
    ):
        if (only and only != key) or (not only and not enabled):
            continue
        try:
            out.append(factory(sub))
        except BrokerError as e:
            errors.append(str(e))
    return out


def _fetch(brokers, errors: list[str]) -> list[AccountSnapshot]:
    def run(b):
        try:
            return b.snapshot()
        except BrokerError as e:
            errors.append(str(e))
            return None

    with ThreadPoolExecutor(len(brokers) or 1) as ex:
        return [s for s in ex.map(run, brokers) if s is not None]


def _daily_guard() -> bool:
    """True if the --daily run should go ahead (first run today)."""
    stamp = config_mod.CACHE_DIR / "last_daily"
    today = date.today().isoformat()
    try:
        if stamp.read_text().strip() == today:
            return False
    except OSError:
        pass
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(today)
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stockbot", description="Portfolio summary for Trading 212 + IBKR.")
    p.add_argument("command", nargs="?", choices=["summary", "init"], default="summary",
                   help="'init' creates the config file; default shows the summary")
    p.add_argument("-b", "--broker", choices=["t212", "ibkr"], help="only this broker")
    p.add_argument("-c", "--currency", help="display currency (default from config)")
    p.add_argument("--no-news", action="store_true", help="skip news + sentiment (faster)")
    p.add_argument("--daily", action="store_true", help="only run once per day (for shell startup)")
    p.add_argument("--demo", action="store_true", help="use fake accounts with real market data")
    args = p.parse_args(argv)
    console = Console()

    if args.command == "init":
        if config_mod.write_template():
            console.print(f"Created [bold]{config_mod.CONFIG_PATH}[/] – add your API keys there.")
        else:
            console.print(f"Config already exists at [bold]{config_mod.CONFIG_PATH}[/]")
        return 0

    if args.daily and not _daily_guard():
        return 0

    cfg = config_mod.load()
    ccy = (args.currency or cfg.display_currency).upper()
    errors: list[str] = []

    with console.status("Fetching accounts…"):
        if args.demo:
            from .demo import snapshots as demo_snapshots

            snaps = demo_snapshots()
        else:
            if not config_mod.CONFIG_PATH.exists() and not any(
                (cfg.trading212.api_key, cfg.ibkr.flex_token)
            ):
                console.print("No config found. Run [bold]stockbot init[/] first, or try [bold]stockbot --demo[/].")
                return 1
            snaps = _fetch(_brokers(cfg, args.broker, errors), errors)

    if not snaps:
        for e in errors:
            console.print(f"[red]✗ {e}")
        console.print("[red]No account data available.")
        return 1

    from . import market
    from .render import Report

    holdings = [h for s in snaps for h in s.holdings]
    with console.status("Fetching market data…"):
        indices = market.enrich_prices(holdings, cfg.symbols)
        rates = market.fx_rates({s.currency for s in snaps} | {h.account_currency for h in holdings}, ccy)
    missing_fx = sorted(c for c in {s.currency for s in snaps} if c not in rates)
    if missing_fx:
        errors.append(f"No FX rate for {', '.join(missing_fx)} → {ccy}; those values are omitted")
    unresolved = [h.broker_symbol for h in holdings if h.chg_1d is None]
    if unresolved:
        errors.append(f"No Yahoo price data for {', '.join(unresolved)} (add overrides under [symbols])")

    show_news = not args.no_news
    if show_news:
        from .sentiment import score

        with console.status("Fetching news…"):
            market.enrich_news(holdings, cfg.news_per_stock, cfg.news_max_age_days, score)

    Report(snaps, rates, ccy, indices, errors, show_news).render(console)
    return 0


if __name__ == "__main__":
    sys.exit(main())
