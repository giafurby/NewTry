"""
Echter ccxt-Code gegen Antworten im Binance-Format (ohne Netz): Kommen beim Bot die richtigen Zahlen an, und schickt er
die richtigen Anfragen an Binance? Die Antworten folgen der Binance-Spot-API (exchangeInfo, account, order, myTrades).
"""
import json
import urllib.parse

import ccxt
import pytest

from exchange import Broker, make_binance_client

EXCHANGE_INFO = {
    "timezone": "UTC", "serverTime": 1794168000000, "rateLimits": [], "exchangeFilters": [],
    "symbols": [{
        "symbol": "ETHUSDC", "status": "TRADING", "baseAsset": "ETH", "baseAssetPrecision": 8, "quoteAsset": "USDC",
        "quotePrecision": 8, "quoteAssetPrecision": 8, "baseCommissionPrecision": 8, "quoteCommissionPrecision": 8,
        "orderTypes": ["LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"],
        "icebergAllowed": True, "ocoAllowed": True, "otoAllowed": True, "quoteOrderQtyMarketAllowed": True,
        "allowTrailingStop": True, "cancelReplaceAllowed": True, "isSpotTradingAllowed": True,
        "isMarginTradingAllowed": False,
        "filters": [
            {"filterType": "PRICE_FILTER", "minPrice": "0.01000000", "maxPrice": "1000000.00000000", "tickSize": "0.01000000"},
            {"filterType": "LOT_SIZE", "minQty": "0.00010000", "maxQty": "9000.00000000", "stepSize": "0.00010000"},
            {"filterType": "NOTIONAL", "minNotional": "5.00000000", "applyMinToMarket": True,
             "maxNotional": "9000000.00000000", "applyMaxToMarket": False, "avgPriceMins": 5},
            {"filterType": "MAX_NUM_ALGO_ORDERS", "maxNumAlgoOrders": 5},
        ],
        "permissions": [], "permissionSets": [["SPOT"]], "defaultSelfTradePreventionMode": "EXPIRE_MAKER",
        "allowedSelfTradePreventionModes": ["EXPIRE_TAKER", "EXPIRE_MAKER", "EXPIRE_BOTH"],
    }],
}
ACCOUNT = {"makerCommission": 10, "takerCommission": 10, "canTrade": True, "canWithdraw": False, "canDeposit": True,
           "accountType": "SPOT", "updateTime": 1794168000000, "permissions": ["SPOT"],
           "balances": [{"asset": "USDC", "free": "120.50000000", "locked": "0.00000000"},
                        {"asset": "ETH", "free": "0.00002000", "locked": "0.01230000"}]}
MARKET_BUY = {"symbol": "ETHUSDC", "orderId": 28, "orderListId": -1, "clientOrderId": "ntb1", "transactTime": 1794168060000,
              "price": "0.00000000", "origQty": "0.01230000", "executedQty": "0.01230000", "cummulativeQuoteQty": "38.11893000",
              "status": "FILLED", "timeInForce": "GTC", "type": "MARKET", "side": "BUY", "workingTime": 1794168060000,
              "fills": [{"price": "3099.10", "qty": "0.01000000", "commission": "0.00001000", "commissionAsset": "ETH", "tradeId": 56},
                        {"price": "3099.10", "qty": "0.00230000", "commission": "0.00000230", "commissionAsset": "ETH", "tradeId": 57}]}
STOP_NEW = {"symbol": "ETHUSDC", "orderId": 77, "orderListId": -1, "clientOrderId": "ntx1", "transactTime": 1794168061000,
            "price": "2700.00", "origQty": "0.01230000", "executedQty": "0.00000000", "cummulativeQuoteQty": "0.00000000",
            "status": "NEW", "timeInForce": "GTC", "type": "STOP_LOSS_LIMIT", "side": "SELL", "stopPrice": "2780.00",
            "workingTime": -1, "fills": []}
STOP_FILLED = {**STOP_NEW, "executedQty": "0.01230000", "cummulativeQuoteQty": "34.0095", "status": "FILLED",
               "time": 1794168061000, "updateTime": 1794170000000, "isWorking": True}
TRADES = [{"symbol": "ETHUSDC", "id": 901, "orderId": 77, "orderListId": -1, "price": "2765.00", "qty": "0.01230000",
           "quoteQty": "34.0095", "commission": "0.03400950", "commissionAsset": "USDC", "time": 1794170000000,
           "isBuyer": False, "isMaker": False, "isBestMatch": True}]


class FakeBinance:
    """Ersetzt nur die HTTP-Schicht von ccxt; alles andere (Anfragen bauen, Antworten lesen, Fehler zuordnen) ist echt."""

    def __init__(self, client):
        self.client = client
        self.calls = []
        self.cancel_unknown = False

    def __call__(self, url, method="GET", headers=None, body=None):
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        params.update(dict(urllib.parse.parse_qsl(body or "")))
        for key in ("signature", "timestamp", "recvWindow"):
            params.pop(key, None)
        path = parsed.path
        self.calls.append((method, path, params))
        if path.endswith("/exchangeInfo"):
            return EXCHANGE_INFO
        if path.endswith("/account"):
            return ACCOUNT
        if path.endswith("/myTrades"):
            return TRADES
        if path.endswith("/order") and method == "POST":
            return MARKET_BUY if params["type"] == "MARKET" else {**STOP_NEW, "clientOrderId": params["newClientOrderId"]}
        if path.endswith("/order") and method == "DELETE":
            if self.cancel_unknown:                   # Binance: bereits ausgeführte Order kann man nicht stornieren
                error = {"code": -2011, "msg": "Unknown order sent."}
                self.client.handle_errors(400, "Bad Request", url, method, {}, json.dumps(error), error, headers, body)
            return {**STOP_NEW, "status": "CANCELED", "executedQty": "0.00400000", "cummulativeQuoteQty": "11.0600"}
        if path.endswith("/order") and method == "GET":
            return STOP_FILLED
        raise AssertionError(f"unerwartete Anfrage {method} {path}")


@pytest.fixture
def binance():
    client = make_binance_client("key", "secret")
    client.options["adjustForTimeDifference"] = False
    client.enableRateLimit = False
    fake = FakeBinance(client)
    client.fetch = fake
    broker = Broker(client, "USDC", sleep=lambda _s: None)
    found, missing = broker.load_markets(["ETH", "DOGE"])
    return broker, fake, found, missing


def test_markets_from_exchange_info(binance):
    broker, fake, found, missing = binance
    assert found == ["ETH/USDC"] and missing == ["DOGE"]
    info = broker.markets["ETH/USDC"]
    assert (info.base, info.quote, info.amount_step, info.min_cost) == ("ETH", "USDC", 0.0001, 5.0)
    assert broker.supports_stop_limit("ETH/USDC")
    assert all(not call[1].startswith(("/fapi", "/dapi", "/sapi")) for call in fake.calls)   # nur Spot, keine privaten Extras


def test_balances_count_locked_coins(binance):
    broker, fake, *_ = binance
    balances = broker.balances()
    assert balances.free("USDC") == 120.5
    assert balances.free("ETH") == pytest.approx(0.00002) and balances.total("ETH") == pytest.approx(0.01232)


def test_market_buy_request_and_fees(binance):
    broker, fake, *_ = binance
    fill = broker.market_order("ETH/USDC", "buy", 0.012345, "ntb1")
    method, path, params = fake.calls[-1]
    assert (method, path) == ("POST", "/api/v3/order")
    assert params["type"] == "MARKET" and params["side"] == "BUY" and params["quantity"] == "0.0123"
    assert params["newClientOrderId"] == "ntb1" and params["newOrderRespType"] == "FULL"
    assert fill.amount == pytest.approx(0.0123) and fill.price == pytest.approx(3099.10)
    assert fill.fee_base == pytest.approx(0.0000123) and fill.net_amount == pytest.approx(0.0122877)


def test_stop_order_request(binance):
    broker, fake, *_ = binance
    order = broker.place_stop_loss("ETH/USDC", 0.012345, broker.price_to_precision("ETH/USDC", 2780.004),
                                   broker.price_to_precision("ETH/USDC", 2700.009), "ntx42")
    method, path, params = fake.calls[-1]
    assert (method, path) == ("POST", "/api/v3/order")
    assert params == {"symbol": "ETHUSDC", "side": "SELL", "type": "STOP_LOSS_LIMIT", "quantity": "0.0123",
                      "price": "2700.01", "stopPrice": "2780", "timeInForce": "GTC", "newClientOrderId": "ntx42",
                      "newOrderRespType": "FULL"}
    assert str(order["id"]) == "77" and order["clientOrderId"] == "ntx42"


def test_cancel_partial_and_already_filled(binance):
    broker, fake, *_ = binance
    cancelled = broker.cancel_order("ETH/USDC", "77")
    assert fake.calls[-1][:2] == ("DELETE", "/api/v3/order") and fake.calls[-1][2]["orderId"] == "77"
    assert cancelled["status"] == "canceled" and cancelled["filled"] == pytest.approx(0.004)
    fake.cancel_unknown = True
    assert broker.cancel_order("ETH/USDC", "77") is None            # -2011 -> schon ausgeführt/unbekannt


def test_filled_stop_with_real_fees_from_trade_list(binance):
    broker, fake, *_ = binance
    order = broker.get_order("ETH/USDC", "77")
    assert order["status"] == "closed" and order["filled"] == pytest.approx(0.0123)
    fill = broker.stop_fill(order, "ETH/USDC")
    method, path, params = fake.calls[-1]
    assert path == "/api/v3/myTrades" and params["orderId"] == "77"
    assert fill.cost == pytest.approx(34.0095) and fill.fee_quote == pytest.approx(0.0340095) and not fill.fee_note


def test_lookup_by_own_order_number(binance):
    broker, fake, *_ = binance
    broker.find_order("ETH/USDC", "ntb1")
    assert fake.calls[-1][2] == {"symbol": "ETHUSDC", "origClientOrderId": "ntb1"}


def test_ccxt_maps_binance_errors_we_rely_on():
    client = ccxt.binance()
    for code, expected in (("-2011", ccxt.OrderNotFound), ("-2013", ccxt.OrderNotFound), ("-2010", ccxt.ExchangeError),
                           ("-1021", ccxt.InvalidNonce)):
        error = {"code": int(code), "msg": "x"}
        with pytest.raises(expected):
            client.handle_errors(400, "Bad Request", "https://api.binance.com/api/v3/order", "DELETE", {},
                                 json.dumps(error), error, {}, "")
