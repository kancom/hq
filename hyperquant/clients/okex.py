
import re
import zlib
import datetime as dt

from hyperquant.api import OrderBookDirection, Direction
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
            #~ "name": "code",
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
        result["Content-Type"] = "application/x-www-form-urlencoded"
        return result

re_symbol = re.compile(r'spot_([^_]+_[^_]+)_')
re_symbol_interval = re.compile(r'spot_([^_]+_[^_]+)_kline_([^$]+)')


class OkexWSConverterV1(WSConverter):
    # Main params:
    base_url = "wss://real.okex.com:10440/ws/v{version}"

    IS_SUBSCRIPTION_COMMAND_SUPPORTED = True

    endpoint_lookup = {
        Endpoint.TRADE: "ok_sub_spot_{symbol}_deals",
        Endpoint.CANDLE: "ok_sub_spot_{symbol}_kline_{interval}",
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
            "status": "code",
            "error": "message",
        },
        Trade: [
            ParamName.ITEM_ID,
            ParamName.PRICE,
            ParamName.AMOUNT,
            ParamName.TIMESTAMP,
            ParamName.DIRECTION,
            ParamName.SYMBOL,
        ],
        Candle: [
            ParamName.TIMESTAMP,
            ParamName.PRICE_OPEN,
            ParamName.PRICE_HIGH,
            ParamName.PRICE_LOW,
            ParamName.PRICE_CLOSE,
            ParamName.AMOUNT,
            ParamName.SYMBOL,
            ParamName.INTERVAL,
        ]
    }

    subs_notification = "addChannel"

    is_source_in_milliseconds = True

    #~ time adjustment in trades
    #~ there is no DST
    TZ_offset = 8
    
    params = None

    def parse(self, endpoint, data):
        def adjust_time(str_time):
            """
            As far as the exchange is in Hong-Kong, it seems that
            time is in HKT tz. Here comes datetime adjustment
            This must be refactored to skip unnecessary calculations
            """
            hk_datetime = dt.datetime.utcnow() + dt.timedelta(hours=self.TZ_offset)
            hk_date_str = hk_datetime.strftime("%Y-%m-%d")
            tz_offset_str = "{0:+03d}00".format(self.TZ_offset)
            trade_dt = dt.datetime.strptime(hk_date_str+str_time+tz_offset_str,
                                  "%Y-%m-%d%H:%M:%S%z")
            return int(trade_dt.timestamp()) * 1000
        channel = data["channel"]
        if channel == self.subs_notification:
            return
        symbol = None
        data = data["data"][0]
        if "deals" in channel:
            endpoint = Endpoint.TRADE
            data[3] = adjust_time(data[3])
            data[4] = Direction.name_by_value[ OrderBookDirection.value_by_name[data[4]]]
            re_mo = re_symbol.search(channel)
            if re_mo:
                symbol = re_mo.group(1)
                data.append(symbol)
        elif "kline" in channel:
            endpoint = Endpoint.CANDLE
            data[0] = int(data[0])
            re_mo = re_symbol_interval.search(channel)
            if re_mo:
                symbol = re_mo.group(1)
                data.append(symbol)
                interval = re_mo.group(2)
                data.append(interval)
        data = tuple(data)
        return super().parse(endpoint, data)

    def _generate_subscription(self, endpoint, symbol=None, **params):
        if params and not self.params:
            self.params = params
        if not params and self.params:
            params = self.params
        for lookup in self.param_value_lookup:
            if lookup in params:
                val = params[lookup]
                n_val = self.param_value_lookup[lookup].get(val, val)
                params[lookup] = n_val
        return super()._generate_subscription(endpoint, symbol, **params)


class OkexWSClient(WSClient):

    platform_id = Platform.OKEX
    version = "1"

    _converter_class_by_version = {
        "1": OkexWSConverterV1,
    }

    def _send_subscribe(self, subscriptions):
        for channel in subscriptions:
            event_data = {
                "event": "addChannel",
                "channel": channel,}
            self._send(event_data)

    def _on_message(self, binmessage):
        #~ https://github.com/okcoin-okex/API-docs-OKEx.com/tree/master/demo
        def inflate(data):
            decompress = zlib.decompressobj(
                    -zlib.MAX_WBITS  # see above
            )
            inflated = decompress.decompress(data)
            inflated += decompress.flush()
            return inflated
        message = inflate(binmessage).decode('utf8')[1:-1]
        return super()._on_message(message)

