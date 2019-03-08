

from hyperquant.api import Platform, Interval, ErrorCode
from hyperquant.clients import PrivatePlatformRESTClient, RESTConverter
from hyperquant.clients import Endpoint, ParamName, Trade, Error, Candle
from hyperquant.clients import WSClient, WSConverter


class OkexRESTConverterV1(RESTConverter):
    base_url = "https://www.okex.com/api/v{version}/"

    endpoint_lookup = {
        Endpoint.TRADE: "trades.do",
        Endpoint.TRADE_HISTORY: "trades.do",
        Endpoint.CANDLE: "kline.do",
    }

    history_endpoint_lookup = None

    param_name_lookup = {
        ParamName.LIMIT: "size",   # not supported for trades
        ParamName.IS_USE_MAX_LIMIT: None,
        ParamName.SORTING: None,  # not supported
        ParamName.FROM_ITEM: "since",  # not supported for candles
        ParamName.TO_ITEM: None,  # not supported
        ParamName.FROM_TIME: "since",  # not supported for trades
        ParamName.TO_TIME: None,  # not supported
        ParamName.INTERVAL: "type",

    }
    param_value_lookup = {
        ParamName.INTERVAL: {
            Interval.MIN_1: "1min",
            Interval.MIN_3: "3min",
            Interval.MIN_5: "5min",
            Interval.MIN_15: "15min",
            Interval.MIN_30: "30min",
            Interval.HRS_1: "1hour",
            Interval.HRS_2: "2hour",
            Interval.HRS_4: "4hour",
            Interval.HRS_6: "6hour",
            Interval.HRS_8: None,
            Interval.HRS_12: "12hour",
            Interval.DAY_1: "1day",
            Interval.DAY_3: None,
            Interval.WEEK_1: "1week",
            Interval.MONTH_1: None,
        },
    }

    param_lookup_by_class = {
        Error: {
            "name": "code",
            #~ "message": "message",
        },
        Trade: {
            "tid": ParamName.ITEM_ID,
            "date_ms": ParamName.TIMESTAMP,
            "price": ParamName.PRICE,
            "amount": ParamName.AMOUNT,
            "type": ParamName.DIRECTION,
        },
        Candle: [
            ParamName.TIMESTAMP,
            ParamName.PRICE_OPEN,
            ParamName.PRICE_HIGH,
            ParamName.PRICE_LOW,
            ParamName.PRICE_CLOSE,
            ParamName.TRADES_COUNT,
        ],
    }

    error_code_by_platform_error_code = {
        10012: ErrorCode.WRONG_SYMBOL,
        10000: ErrorCode.WRONG_PARAM,
        10001: ErrorCode.RATE_LIMIT,
    }

    is_source_in_milliseconds = True


class OkexRESTClient(PrivatePlatformRESTClient):
    platform_id = Platform.OKEX
    version = "1"
    _converter_class_by_version = {
        "1": OkexRESTConverterV1,
    }

    @property
    def headers(self):
        result = super().headers
        #~ result["Content-Type"] = "application/x-www-form-urlencoded"
        return result

    def fetch_trades_history(self, symbol, limit=None, from_item=None,
                           sorting=None, from_time=None, to_time=None, **kwargs):
        return super().fetch_trades_history(symbol, limit, from_item, sorting=sorting,
                                          from_time=from_time, to_time=to_time, **kwargs)


class OkexWSConverterV1(WSConverter):
    # Main params:
    base_url = "wss://real.okex.com:10440/ws/v{version}"

    IS_SUBSCRIPTION_COMMAND_SUPPORTED = True

    endpoint_lookup = {
        Endpoint.TRADE: "trade:{symbol}",
        # Endpoint.TRADE: lambda params: "trade:" + params[Param.SYMBOL] if Param.SYMBOL in params else "trade",
    }

    param_lookup_by_class = {
        Error: {
            "status": "code",
            "error": "message",
        },
        Trade: {
            "trdMatchID": ParamName.ITEM_ID,
            "timestamp": ParamName.TIMESTAMP,
            "symbol": ParamName.SYMBOL,
            "price": ParamName.PRICE,
            "size": ParamName.AMOUNT,
            "side": ParamName.DIRECTION,
        },
    }
    event_type_param = "table"

    is_source_in_timestring = True

    def parse(self, endpoint, data):
        if data:
            endpoint = data.get(self.event_type_param)
            if "error" in data:
                result = self.parse_error(data)
                if "request" in data:
                    result.message += "request: " + json.dumps(data["request"])
                return result
            if "data" in data:
                data = data["data"]
        return super().parse(endpoint, data)

    def _parse_item(self, endpoint, item_data):
        result = super()._parse_item(endpoint, item_data)

        # (For Trade)
        if hasattr(result, ParamName.SYMBOL) and result.symbol[0] == ".":
            # # ".ETHUSD" -> "ETHUSD"
            # result.symbol = result.symbol[1:]
            # https://www.Okex.com/api/explorer/#!/Trade/Trade_get Please note
            # that indices (symbols starting with .) post trades at intervals to
            # the trade feed. These have a size of 0 and are used only to indicate
            # a changing price.
            return None

        # Convert direction
        if result and isinstance(result, Trade):
            result.direction = Direction.BUY if result.direction == "Buy" else (
                Direction.SELL if result.direction == "Sell" else None)
            result.price = str(result.price)
            result.amount = str(result.amount)
        return result


class OkexWSClient(WSClient):

    platform_id = Platform.OKEX
    version = "1"

    _converter_class_by_version = {
        "1": OkexWSConverterV1,
    }

    def _send_subscribe(self, subscriptions):
        for channel, symbol in subscriptions:
            trading_pair_symbol = "t" + symbol
            event_data = {
                "event": "subscribe",
                "channel": channel,
                "symbol": trading_pair_symbol}
            self._send(event_data)

    def _parse(self, endpoint, data):
        if isinstance(data, list) and len(data) > 1 and data[1] == "hb":
            # Heartbeat. skip for now...
            return None
        return super()._parse(endpoint, data)
