# StockBot

A terminal morning briefing for your **Trading 212** and **Interactive Brokers** portfolios:

- every holding in one table – price, 1D / 1W / 1M change, value, today's P&L, total P&L, weight
- a **news sentiment** score per stock (VADER on recent headlines from Yahoo Finance / Google News)
- a **portfolio overview** per broker and combined, converted to one display currency
- major indices (S&P 500, Nasdaq, STOXX 600, FTSE 100, DAX)
- the latest headlines per holding (clickable in most terminals)

Read-only: it never places orders.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
ln -s "$PWD/.venv/bin/stockbot" ~/.local/bin/stockbot   # put it on your PATH
```

Try it with fake accounts (real market data) before adding keys:

```bash
stockbot --demo
```

## Configure

```bash
stockbot init        # creates ~/.config/stockbot/config.toml (chmod 600)
```

### Trading 212
App → **Settings → API (Beta)** → generate a key. Read-only permissions (account data, portfolio) are enough.
Put the key and secret into `[trading212]`, or export `T212_API_KEY` / `T212_API_SECRET`.
Set `environment = "demo"` to use a paper account.

### Interactive Brokers (Flex Web Service – no TWS/Gateway needed)
1. Client Portal → **Performance & Reports → Flex Queries** → create an **Activity Flex Query** with the sections
   **Open Positions** (summary level), **Equity Summary in Base**, and **Account Information**. Period: *Last Business Day*. Format: XML.
2. **Flex Web Service Configuration** → enable it and generate a token.
3. Put the token and the query ID into `[ibkr]` and set `enabled = true`
   (or export `IBKR_FLEX_TOKEN` / `IBKR_FLEX_QUERY_ID`).

Flex data reflects the previous close, and it is cached for `cache_minutes` (default 60).

## Usage

```bash
stockbot                 # full summary
stockbot --no-news       # skip news/sentiment (faster)
stockbot -b ibkr         # one broker only
stockbot -c USD          # display in another currency
```

### Run automatically every morning
Add to `~/.bashrc`. This shows the summary in the first terminal you open each day:

```bash
command -v stockbot >/dev/null && stockbot --daily
```

## Symbol mapping
Broker tickers are mapped to Yahoo Finance symbols (`AAPL_US_EQ` → `AAPL`, `VODl_EQ` → `VOD.L`, IBKR `BP.`@LSE → `BP.L`),
with an ISIN lookup as fallback. If one is wrong or missing, add an override:

```toml
[symbols]
"VODl_EQ" = "VOD.L"
```

## Notes
- Market data and news come from Yahoo Finance (via `yfinance`) and Google News RSS. They are unofficial, and for personal use only.
- "Today" P&L is estimated from each stock's last daily change.
- Sentiment is a simple lexicon score of headlines. Treat it as a hint, not advice.

## Development
```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
