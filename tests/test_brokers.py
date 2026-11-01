import httpx
import pytest

from stockbot.brokers import BrokerError
from stockbot.brokers import ibkr_flex, trading212
from stockbot.config import IBKRConfig, T212Config

T212_SUMMARY = {
    "id": 123,
    "currency": "EUR",
    "totalValue": 1500.0,
    "cash": {"availableToTrade": 100.0, "reservedForOrders": 0.0, "inPies": 0.0},
    "investments": {"currentValue": 1400.0, "totalCost": 1000.0, "unrealizedProfitLoss": 400.0,
                    "realizedProfitLoss": 25.0},
}
T212_POSITIONS = [
    {
        "instrument": {"ticker": "AAPL_US_EQ", "name": "Apple", "isin": "US0378331005", "currency": "USD"},
        "quantity": 5, "averagePricePaid": 150.0, "currentPrice": 300.0,
        "walletImpact": {"currency": "EUR", "currentValue": 1400.0, "totalCost": 1000.0,
                         "unrealizedProfitLoss": 400.0, "fxImpact": -10.0},
    }
]


def test_t212_parse():
    s = trading212.parse(T212_SUMMARY, T212_POSITIONS)
    assert s.currency == "EUR" and s.total_value == 1500 and s.cash == 100
    assert s.unrealized_pnl == 400 and s.realized_pnl == 25
    h = s.holdings[0]
    assert (h.broker_symbol, h.currency, h.account_currency) == ("AAPL_US_EQ", "USD", "EUR")
    assert h.value == 1400 and h.pnl_pct == pytest.approx(0.4)


def _t212(handler):
    client = httpx.Client(base_url="https://x/api/v0", transport=httpx.MockTransport(handler))
    return trading212.Trading212(T212Config(api_key="k", api_secret="s"), client=client)


def test_t212_snapshot_via_http():
    def handler(req):
        return httpx.Response(200, json=T212_SUMMARY if req.url.path.endswith("summary") else T212_POSITIONS)

    assert _t212(handler).snapshot().holdings[0].name == "Apple"


def test_t212_auth_error():
    with pytest.raises(BrokerError, match="401"):
        _t212(lambda req: httpx.Response(401)).snapshot()


def test_t212_requires_keys():
    with pytest.raises(BrokerError):
        trading212.Trading212(T212Config())


FLEX_XML = """<FlexQueryResponse queryName="pos" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1" fromDate="20261030" toDate="20261030" period="LastBusinessDay">
  <AccountInformation accountId="U1" currency="USD" />
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase reportDate="20261029" cash="400" stock="5000" total="5400" />
    <EquitySummaryByReportDateInBase reportDate="20261030" cash="500" stock="6000" total="6500" />
  </EquitySummaryInBase>
  <OpenPositions>
    <OpenPosition accountId="U1" currency="USD" fxRateToBase="1" assetCategory="STK" symbol="MSFT"
      description="MICROSOFT CORP" isin="US5949181045" listingExchange="NASDAQ" reportDate="20261030"
      position="10" markPrice="500" positionValue="5000" costBasisPrice="300" costBasisMoney="3000"
      fifoPnlUnrealized="2000" levelOfDetail="SUMMARY" />
    <OpenPosition accountId="U1" currency="GBP" fxRateToBase="1.3" assetCategory="STK" symbol="VWRA"
      description="VANGUARD FTSE ALL-WORLD" isin="IE00BK5BQT80" listingExchange="LSEETF" reportDate="20261030"
      position="10" markPrice="100" positionValue="1000" costBasisPrice="80" costBasisMoney="800"
      fifoPnlUnrealized="200" levelOfDetail="SUMMARY" />
    <OpenPosition accountId="U1" currency="USD" fxRateToBase="1" assetCategory="STK" symbol="MSFT"
      position="10" positionValue="5000" costBasisMoney="3000" levelOfDetail="LOT" />
    <OpenPosition accountId="U1" currency="USD" fxRateToBase="1" assetCategory="OPT" symbol="MSFT 261120C"
      position="1" positionValue="50" levelOfDetail="SUMMARY" />
  </OpenPositions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""


def test_flex_parse():
    s = ibkr_flex.parse(FLEX_XML)
    assert s.currency == "USD" and s.total_value == 6500 and s.cash == 500
    assert [h.broker_symbol for h in s.holdings] == ["MSFT", "VWRA"]  # LOT + options skipped
    vwra = s.holdings[1]
    assert vwra.value == pytest.approx(1300) and vwra.cost == pytest.approx(1040)
    assert vwra.unrealized_pnl == pytest.approx(260) and vwra.account_currency == "USD"
    assert s.as_of.strftime("%Y%m%d") == "20261030"


def test_flex_fetch_polls_until_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(ibkr_flex.time, "sleep", lambda s: None)
    calls = {"get": 0}

    def handler(req):
        if "SendRequest" in req.url.path:
            return httpx.Response(200, text="<FlexStatementResponse><Status>Success</Status>"
                                  "<ReferenceCode>42</ReferenceCode><Url>https://ib/GetStatement</Url>"
                                  "</FlexStatementResponse>")
        calls["get"] += 1
        if calls["get"] == 1:
            return httpx.Response(200, text="<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019"
                                  "</ErrorCode><ErrorMessage>in progress</ErrorMessage></FlexStatementResponse>")
        return httpx.Response(200, text=FLEX_XML)

    cfg = IBKRConfig(enabled=True, flex_token="t", flex_query_id="1")
    b = ibkr_flex.IBKRFlex(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)), cache_dir=tmp_path)
    assert len(b.snapshot().holdings) == 2 and calls["get"] == 2
    # Second call is served from the cache
    b.snapshot()
    assert calls["get"] == 2


def test_flex_error():
    def handler(req):
        return httpx.Response(200, text="<FlexStatementResponse><Status>Fail</Status><ErrorCode>1015"
                              "</ErrorCode><ErrorMessage>Token is invalid.</ErrorMessage></FlexStatementResponse>")

    cfg = IBKRConfig(enabled=True, flex_token="bad", flex_query_id="1", cache_minutes=0)
    b = ibkr_flex.IBKRFlex(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(BrokerError, match="Token is invalid"):
        b.snapshot()
