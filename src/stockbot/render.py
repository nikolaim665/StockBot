"""Terminal rendering with rich."""

from __future__ import annotations

from datetime import datetime

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import AccountSnapshot, Holding
from .sentiment import BEARISH, BULLISH, label

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "GBX": "p", "CHF": "CHF ", "JPY": "¥"}


def money(v: float | None, ccy: str, signed: bool = False) -> str:
    if v is None:
        return "–"
    sym = SYMBOLS.get(ccy, ccy + " ")
    sign = ("+" if v > 0 else "-" if v < 0 else "") if signed else ("-" if v < 0 else "")
    return f"{sign}{sym}{abs(v):,.2f}"


def color(v: float | None) -> str:
    if v is None:
        return "dim"
    return "green" if v > 0 else "red" if v < 0 else "white"


def pct(v: float | None) -> Text:
    if v is None:
        return Text("–", style="dim")
    arrow = "▲" if v > 0 else "▼" if v < 0 else " "
    return Text(f"{arrow}{abs(v) * 100:5.2f}%", style=color(v))


def signed_money(v: float | None, ccy: str) -> Text:
    return Text(money(v, ccy, signed=True), style=color(v))


def sentiment_text(v: float | None) -> Text:
    lab = label(v)
    style = "green" if v is not None and v >= BULLISH else "red" if v is not None and v <= BEARISH else "yellow"
    if v is None:
        return Text("–", style="dim")
    return Text(f"{lab} {v:+.2f}", style=style)


def price_str(v: float, ccy: str) -> str:
    return f"{v:,.2f} {ccy}" if ccy else f"{v:,.2f}"


class Report:
    def __init__(self, snapshots: list[AccountSnapshot], rates: dict[str, float], ccy: str,
                 indices: dict[str, tuple], errors: list[str], show_news: bool):
        self.snaps = snapshots
        self.rates = rates
        self.ccy = ccy
        self.indices = indices
        self.errors = errors
        self.show_news = show_news

    def conv(self, v: float | None, from_ccy: str) -> float | None:
        if v is None:
            return None
        rate = self.rates.get(from_ccy)
        return v * rate if rate is not None else None

    @staticmethod
    def day_pnl(value: float | None, chg: float | None) -> float | None:
        if value is None or chg is None:
            return None
        return value * chg / (1 + chg)

    # -- sections -------------------------------------------------------------

    def header(self) -> Text:
        t = Text()
        t.append(" StockBot ", style="bold black on cyan")
        t.append(f"  {datetime.now():%A %d %B %Y, %H:%M}", style="bold")
        t.append(f"   ·  amounts in {self.ccy}", style="dim")
        return t

    def markets(self) -> Table | None:
        if not self.indices:
            return None
        t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, title="Markets", title_justify="left",
                  title_style="bold")
        for name in self.indices:
            t.add_column(name, justify="right")
        t.add_row(*[f"{v[3]:,.0f}" for v in self.indices.values()])
        t.add_row(*[pct(v[0]) for v in self.indices.values()])
        return t

    def holdings(self) -> Table:
        all_h: list[Holding] = [h for s in self.snaps for h in s.holdings]
        total = sum(self.conv(h.value, h.account_currency) or 0 for h in all_h) or 1
        multi = len({s.broker for s in self.snaps}) > 1

        t = Table(box=box.SIMPLE_HEAVY, title="Holdings", title_justify="left", title_style="bold",
                  header_style="bold cyan", show_footer=False)
        if multi:
            t.add_column("Broker", style="dim")
        t.add_column("Symbol", style="bold")
        t.add_column("Name", max_width=24, no_wrap=True, overflow="ellipsis")
        t.add_column("Qty", justify="right")
        t.add_column("Price", justify="right")
        t.add_column("1D", justify="right")
        t.add_column("1W", justify="right")
        t.add_column("1M", justify="right")
        t.add_column(f"Value", justify="right")
        t.add_column("Today", justify="right")
        t.add_column("P&L", justify="right")
        t.add_column("P&L %", justify="right")
        t.add_column("Weight", justify="right")
        if self.show_news:
            t.add_column("Sentiment", justify="left")

        rows = sorted(all_h, key=lambda h: self.conv(h.value, h.account_currency) or 0, reverse=True)
        for h in rows:
            val = self.conv(h.value, h.account_currency)
            row = []
            if multi:
                row.append(h.broker)
            row += [
                h.yahoo or h.broker_symbol,
                h.name,
                f"{h.quantity:,.4g}" if h.quantity < 1000 else f"{h.quantity:,.0f}",
                price_str(h.price, h.currency),
                pct(h.chg_1d), pct(h.chg_1w), pct(h.chg_1m),
                money(val, self.ccy),
                signed_money(self.day_pnl(val, h.chg_1d), self.ccy),
                signed_money(self.conv(h.unrealized_pnl, h.account_currency), self.ccy),
                pct(h.pnl_pct),
                f"{(val or 0) / total * 100:.1f}%",
            ]
            if self.show_news:
                row.append(sentiment_text(h.sentiment))
            t.add_row(*row)
        return t

    def overview(self) -> Panel:
        t = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style="bold cyan")
        for col in ("Account", "Total value", "Cash", "Invested", "Cost basis", "Unrealised P&L", "Return",
                    "Today (est.)", "As of"):
            t.add_column(col, justify="left" if col in ("Account", "As of") else "right")

        tot = dict(total=0.0, cash=0.0, inv=0.0, cost=0.0, pnl=0.0, day=0.0)
        day_known = False
        for s in self.snaps:
            c = lambda v: self.conv(v, s.currency)  # noqa: E731
            day = [self.day_pnl(self.conv(h.value, h.account_currency), h.chg_1d) for h in s.holdings]
            day_sum = sum(d for d in day if d is not None) if any(d is not None for d in day) else None
            vals = dict(total=c(s.total_value), cash=c(s.cash), inv=c(s.invested_value), cost=c(s.cost),
                        pnl=c(s.unrealized_pnl), day=day_sum)
            for k, v in vals.items():
                tot[k] += v or 0
            day_known |= day_sum is not None
            ret = s.unrealized_pnl / s.cost if s.cost else None
            t.add_row(
                f"{s.broker} ({s.currency})", money(vals["total"], self.ccy), money(vals["cash"], self.ccy),
                money(vals["inv"], self.ccy), money(vals["cost"], self.ccy), signed_money(vals["pnl"], self.ccy),
                pct(ret), signed_money(day_sum, self.ccy),
                f"{s.as_of:%d %b}" if s.as_of else "live",
            )

        if len(self.snaps) > 1:
            t.add_section()
            t.add_row(
                Text("Total", style="bold"), Text(money(tot["total"], self.ccy), style="bold"),
                money(tot["cash"], self.ccy), money(tot["inv"], self.ccy), money(tot["cost"], self.ccy),
                signed_money(tot["pnl"], self.ccy), pct(tot["pnl"] / tot["cost"] if tot["cost"] else None),
                signed_money(tot["day"] if day_known else None, self.ccy), "",
            )

        extras = [t]
        all_h = [h for s in self.snaps for h in s.holdings if h.chg_1d is not None]
        if all_h:
            best = max(all_h, key=lambda h: h.chg_1d)
            worst = min(all_h, key=lambda h: h.chg_1d)
            line = Text("Best: ", style="dim")
            line.append(f"{best.yahoo or best.broker_symbol} ").append(pct(best.chg_1d))
            line.append("    Worst: ", style="dim")
            line.append(f"{worst.yahoo or worst.broker_symbol} ").append(pct(worst.chg_1d))
            if self.show_news:
                scored = [h for s in self.snaps for h in s.holdings if h.sentiment is not None]
                if scored:
                    avg = sum(h.sentiment for h in scored) / len(scored)
                    line.append("    News mood: ", style="dim").append(sentiment_text(avg))
            extras.append(line)
        return Panel(Group(*extras), title="[bold]Portfolio overview", title_align="left", border_style="cyan")

    def news(self) -> Panel | None:
        seen: set[str] = set()
        lines: list[Text] = []
        holdings = sorted((h for s in self.snaps for h in s.holdings),
                          key=lambda h: self.conv(h.value, h.account_currency) or 0, reverse=True)
        for h in holdings:
            key = h.yahoo or h.broker_symbol
            if key in seen or not h.headlines:
                continue
            seen.add(key)
            head = Text(f"{key}", style="bold")
            head.append(f"  {h.name}", style="dim")
            lines.append(head)
            for n in h.headlines:
                dot = "green" if n.score >= BULLISH else "red" if n.score <= BEARISH else "yellow"
                ln = Text("  ● ", style=dot, no_wrap=True, overflow="ellipsis")
                ln.append(n.title, style=f"link {n.link}" if n.link else "")
                meta = n.publisher
                if n.published:
                    meta += f", {n.published.astimezone():%d %b %H:%M}"
                ln.append(f"  ({meta})", style="dim")
                lines.append(ln)
        if not lines:
            return None
        return Panel(Group(*lines), title="[bold]News", title_align="left", border_style="dim")

    def render(self, console: Console) -> None:
        console.print()
        console.print(self.header())
        for e in self.errors:
            console.print(f"[yellow]⚠ {e}")
        console.print()
        if m := self.markets():
            console.print(m)
            console.print()
        if any(s.holdings for s in self.snaps):
            console.print(self.holdings())
        if self.snaps:
            console.print(self.overview())
        if self.show_news and (n := self.news()):
            console.print(n)
        notes = {f"{s.broker}: {s.note}" for s in self.snaps if s.note}
        for note in sorted(notes):
            console.print(f"[dim]{note}")
        console.print("[dim]1D/1W/1M from Yahoo Finance closes · 'Today' estimated from 1D change · "
                      "sentiment = VADER score of recent headlines (indicative only)")
