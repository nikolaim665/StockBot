import pandas as pd
import pytest

from stockbot.market import changes, clean_name, guess_yahoo, mentions
from stockbot.models import Holding
from stockbot.sentiment import label, score


def h(broker, sym, exch=None):
    return Holding(broker, sym, "", None, "", 1, 1, 1, 1, 1, 0, "EUR", exch)


@pytest.mark.parametrize("broker,sym,exch,expected", [
    ("T212", "AAPL_US_EQ", None, "AAPL"),
    ("T212", "BRK.B_US_EQ", None, "BRK-B"),
    ("T212", "VODl_EQ", None, "VOD.L"),
    ("T212", "SAPd_EQ", None, "SAP.DE"),
    ("T212", "ASMLa_EQ", None, "ASML.AS"),
    ("T212", "WEIRD", None, None),
    ("IBKR", "MSFT", "NASDAQ", "MSFT"),
    ("IBKR", "BRK B", "NYSE", "BRK-B"),
    ("IBKR", "BP.", "LSE", "BP.L"),
    ("IBKR", "VWRA", "LSEETF", "VWRA.L"),
    ("IBKR", "SAP", "IBIS", "SAP.DE"),
    ("IBKR", "XYZ", "MOON", None),
])
def test_guess_yahoo(broker, sym, exch, expected):
    assert guess_yahoo(h(broker, sym, exch)) == expected


@pytest.mark.parametrize("raw,clean", [
    ("BERKSHIRE HATHAWAY-CL B", "Berkshire Hathaway"),
    ("ASML Holding N.V.", "ASML"),
    ("MICROSOFT CORP", "Microsoft"),
    ("Vodafone Group PLC", "Vodafone"),
])
def test_clean_name(raw, clean):
    assert clean_name(raw) == clean


def test_mentions():
    assert mentions("Why Nvidia Stock Took a Dive", ["NVDA", "Nvidia"])
    assert not mentions("Social Security COLA is large", ["NVDA", "Nvidia"])


def test_changes():
    s = pd.Series([100.0] * 20 + [90.0, 99.0, 100.0, 110.0])
    d, w, m = changes(s)
    assert d == pytest.approx(0.10)
    assert w == pytest.approx(110 / 100 - 1)
    assert m == pytest.approx(0.10)
    assert changes(pd.Series([1.0])) == (None, None, None)


def test_sentiment():
    assert label(score("Nvidia stock surges after earnings beat")) == "Bullish"
    assert label(score("Shares plunge after profit warning and downgrade")) == "Bearish"
    assert label(None) == "–"
