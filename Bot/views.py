import json
import logging.config
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from time import sleep

import pandas as pd
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
# from dotenv import load_dotenv
from pybit import usdt_perpetual

from .models import Greeting

# load_dotenv()

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    'formatters': {
        'colored': {
            '()': 'colorlog.ColoredFormatter',  # colored output
            # --> %(log_color)s is very important, that's what colors the line
            'format': '[%(asctime)s,%(lineno)s] %(log_color)s[%(message)s]',
            'log_colors': {
                'DEBUG': 'green',
                'INFO': 'cyan',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'bold_red',
            },
        },
        'simple': {
            'format': '[%(asctime)s,%(lineno)s] [%(message)s]',
        },
    },
    "handlers": {
        "console": {
            "class": "colorlog.StreamHandler",
            "level": "INFO",
            "formatter": "colored",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "simple",
            "filename": 'app-log.log',
            "maxBytes": 50 * 1024 * 1024,
            "backupCount": 1
        },
    },
    "root": {"level": "INFO",
             "handlers": ["console", "file"]
             }
})
LOGGER = logging.getLogger()

PROJECT_ROOT = Path(os.path.abspath(os.path.dirname(__file__)))
file_settings = str(PROJECT_ROOT / 'Settings.json')


# Get settings from Setting.json file
def get_settings():
    if os.path.isfile(file_settings):
        with open(file_settings, 'r') as f:
            return json.load(f)
    temp = {"Settings": {
        "APIName": "Please set your API Name",
        "APIKey": "Please set your API Key",
        "APISecret": "Please set your API Secret"}}
    with open(file_settings, 'w') as f:
        json.dump(temp, f, indent=4)
    with open(file_settings, 'r') as f:
        return json.load(f)


def update_settings(settings):
    with open(file_settings, 'w') as f:
        LOGGER.info(f'Updating settings')
        json.dump({"Settings": settings}, f, indent=4)
        LOGGER.info(f"Settings have been successfully updated: {settings}")


websocket_connected = False
settings = get_settings()["Settings"]
api_key = settings['APIKey']
api_secret = settings['APISecret']
pair = settings["Pairs"][0]
side = settings["Side"]
start_units = float(settings["StartUnits"])
unit_price = float(settings["UnitPrice"])
tp_sl_ticks = float(settings["TPSLTicks"])
zone_divider = float(settings["ZoneDivider"])
tick_price = float(settings["TickPrice"])
leverage = float(settings["Leverage"])
base_times1 = float(settings["BaseTimes1"])
base_times2 = float(settings["BaseTimes2"])
base_times3 = float(settings["BaseTimes3"])
recovery_zone_ticks = tp_sl_ticks / zone_divider
# recovery_trades = [{pair: []} for pair in settings["Pairs"]]
recovery_trades = {}
client = usdt_perpetual.HTTP(endpoint='https://api-testnet.bybit.com', api_key=api_key, api_secret=api_secret)
ws = usdt_perpetual.WebSocket(test=True, api_key=api_key, api_secret=api_secret)


def get_tp_sl(unit_price, tp_sl_ticks, tick_price):
    recovery_zone_ticks = tp_sl_ticks / zone_divider
    tp_l = round(unit_price + (tp_sl_ticks * tick_price), 2)
    tp_s = round(unit_price - (tp_sl_ticks * tick_price), 2)
    sl_l = round(unit_price - ((recovery_zone_ticks + tp_sl_ticks) * tick_price), 2)
    sl_s = round(unit_price + ((recovery_zone_ticks + tp_sl_ticks) * tick_price), 2)
    return tp_l, tp_s, sl_l, sl_s


def get_data_frame(pair):
    file_path = str(PROJECT_ROOT / f'{pair}.csv')
    return pd.read_csv(file_path, index_col=None)


# Check on your order and position through WebSocket.
def handle_recovery_order(order):
    # order_id = order["data"][0]["order_id"]
    # pair = order["data"][0]["symbol"]
    order_id = order["order_id"]
    pair = order["Pair"]
    # LOGGER.info(f'RecoveryOrder handler started for: {pair}, OrderID: {order_id}')
    LOGGER.info(f'RecoveryOrder handler started for: {order}')
    while True:
        sleep(12)
        if recovery_trades[pair][2]["Triggered"]:
            break
        try:
            df = get_data_frame(pair=pair)
            df["Price"] = df["Price"].astype(float)
        except:
            continue
        order = client.query_active_order(symbol=pair, order_id=order_id)
        # LOGGER.info(f'Query order: {order}')
        # LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Side: {order["result"]["side"]}')
        if order["result"]["order_status"] == "Cancelled":
            return
        if (order["result"]["side"] == "Buy") and (order["result"]["order_status"] == "Filled"):
            if not recovery_trades[pair][0]["Triggered"]:
                LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Pair: {pair}, Side: {order["result"]["side"]}, PairPrice: {df.iloc[-1]["Price"]}: OrderPrice: {recovery_trades[pair][0]["UnitPrice"]}, 1st RecoveryOrder Condition Matched: {df.iloc[-1]["Price"] <= recovery_trades[pair][0]["UnitPrice"]}')
            elif recovery_trades[pair][0]["Triggered"] and not recovery_trades[pair][1]["Triggered"]:
                LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Pair: {pair}, Side: {order["result"]["side"]}, PairPrice: {df.iloc[-1]["Price"]}: OrderPrice: {recovery_trades[pair][1]["UnitPrice"]}, 2nd RecoveryOrder Condition Matched: {df.iloc[-1]["Price"] >= recovery_trades[pair][0]["UnitPrice"]}')
            elif recovery_trades[pair][1]["Triggered"] and not recovery_trades[pair][2]["Triggered"]:
                LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Pair: {pair}, Side: {order["result"]["side"]}, PairPrice: {df.iloc[-1]["Price"]}: OrderPrice: {recovery_trades[pair][2]["UnitPrice"]}, 3rd RecoveryOrder Condition Matched: {df.iloc[-1]["Price"] <= recovery_trades[pair][0]["UnitPrice"]}')
            if (df.iloc[-1]['Price'] <= recovery_trades[pair][0]["UnitPrice"]) and not recovery_trades[pair][0]["Triggered"]:
                LOGGER.info(f'Placing the 1st recovery order: {recovery_trades[pair][0]["Side"]}')
                # print(f"Switching TP/SL mode to Partial")
                # tp_sl_mode = client.full_partial_position_tp_sl_switch(symbol=pair, tp_sl_mode="Partial")
                # tp_sl_mode = json.loads(json.dumps(tp_sl_mode, indent=4))['result']
                # print(f"TP/SL Mode: {tp_sl_mode}")
                # print(f'Placing new buy limit order at price: {buy_price - buy_less}')
                recovery_trades[pair][0]["Triggered"] = True
                order_buy = client.place_active_order(
                    symbol=pair,
                    side=recovery_trades[pair][0]["Side"],
                    order_type="Market",
                    qty=recovery_trades[pair][0]["Units"],
                    take_profit=recovery_trades[pair][0]["TP"],
                    stop_loss=recovery_trades[pair][0]["SL"],
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order_buy = json.loads(json.dumps(order_buy, indent=4))['result']
                print(f'1st {recovery_trades[pair][0]["Side"]} RecoveryOrder has been placed: {order_buy}')
            elif (df.iloc[-1]['Price'] >= recovery_trades[pair][1]["UnitPrice"]) and (recovery_trades[pair][0]["Triggered"] and not recovery_trades[pair][1]["Triggered"]):
                LOGGER.info(f'Placing the 2nd recovery order: {recovery_trades[pair][0]["Side"]}')
                recovery_trades[pair][1]["Triggered"] = True
                order_buy = client.place_active_order(
                    symbol=pair,
                    side=recovery_trades[pair][1]["Side"],
                    order_type="Market",
                    qty=recovery_trades[pair][1]["Units"],
                    take_profit=recovery_trades[pair][1]["TP"],
                    stop_loss=recovery_trades[pair][1]["SL"],
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order_buy = json.loads(json.dumps(order_buy, indent=4))['result']
                print(f'2nd {recovery_trades[pair][1]["Side"]} RecoveryOrder has been placed: {order_buy}')
            elif (df.iloc[-1]['Price'] <= recovery_trades[pair][2]["UnitPrice"]) and (recovery_trades[pair][1]["Triggered"] and not recovery_trades[pair][2]["Triggered"]):
                LOGGER.info(f'Placing the 3rd recovery order: {recovery_trades[pair][0]["Side"]}')
                recovery_trades[pair][2]["Triggered"] = True
                order_buy = client.place_active_order(
                    symbol=pair,
                    side=recovery_trades[pair][2]["Side"],
                    order_type="Market",
                    qty=recovery_trades[pair][2]["Units"],
                    take_profit=recovery_trades[pair][2]["TP"],
                    stop_loss=recovery_trades[pair][2]["SL"],
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order_buy = json.loads(json.dumps(order_buy, indent=4))['result']
                print(f'3rd {recovery_trades[pair][2]["Side"]} RecoveryOrder has been placed: {order_buy}')
        if (order["result"]["side"] == "Sell") and (order["result"]["order_status"] == "Filled"):
            if not recovery_trades[pair][0]["Triggered"]:
                LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Pair: {pair} Side: {order["result"]["side"]}, PairPrice: {df.iloc[-1]["Price"]}: OrderPrice: {recovery_trades[pair][0]["UnitPrice"]}, 1st RecoveryOrder Condition Matched: {df.iloc[-1]["Price"] >= recovery_trades[pair][0]["UnitPrice"]}')
            elif recovery_trades[pair][0]["Triggered"] and not recovery_trades[pair][1]["Triggered"]:
                LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Pair: {pair}, Side: {order["result"]["side"]}, PairPrice: {df.iloc[-1]["Price"]}: OrderPrice: {recovery_trades[pair][1]["UnitPrice"]}, 2nd RecoveryOrder Condition Matched: {df.iloc[-1]["Price"] <= recovery_trades[pair][0]["UnitPrice"]}')
            elif recovery_trades[pair][1]["Triggered"] and not recovery_trades[pair][2]["Triggered"]:
                LOGGER.info(f'Order Status: {order["result"]["order_status"]}, Pair: {pair}, Side: {order["result"]["side"]}, PairPrice: {df.iloc[-1]["Price"]}: OrderPrice: {recovery_trades[pair][2]["UnitPrice"]}, 3rd RecoveryOrder Condition Matched: {df.iloc[-1]["Price"] >= recovery_trades[pair][0]["UnitPrice"]}')

            if (df.iloc[-1]['Price'] >= recovery_trades[pair][0]["UnitPrice"]) and (not recovery_trades[pair][0]["Triggered"]):
                LOGGER.info(f'Placing the 1st recovery order: {recovery_trades[pair][0]["Side"]}')
                print(f'Status: {order["result"]["order_status"]}')
                # print(f"Switching TP/SL mode to Partial")
                # tp_sl_mode = client.full_partial_position_tp_sl_switch(symbol=pair, tp_sl_mode="Partial")
                # tp_sl_mode = json.loads(json.dumps(tp_sl_mode, indent=4))['result']
                # print(f"TP/SL Mode: {tp_sl_mode}")
                # print(f'Placing new buy limit order at price: {buy_price - buy_less}')
                recovery_trades[pair][0]["Triggered"] = True
                order_sell = client.place_active_order(
                    symbol=pair,
                    side=recovery_trades[pair][0]["Side"],
                    order_type="Market",
                    qty=recovery_trades[pair][0]["Units"],
                    take_profit=recovery_trades[pair][0]["TP"],
                    stop_loss=recovery_trades[pair][0]["SL"],
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order_sell = json.loads(json.dumps(order_sell, indent=4))['result']
                print(f'1st {recovery_trades[pair][0]["Side"]} RecoveryOrder has been placed: {order_sell}')
            elif (df.iloc[-1]['Price'] <= recovery_trades[pair][1]["UnitPrice"]) and (recovery_trades[pair][0]["Triggered"] and not recovery_trades[pair][1]["Triggered"]):
                LOGGER.info(f'Placing the 2nd recovery order: {recovery_trades[pair][0]["Side"]}')
                recovery_trades[pair][1]["Triggered"] = True
                order_sell = client.place_active_order(
                    symbol=pair,
                    side=recovery_trades[pair][1]["Side"],
                    order_type="Market",
                    qty=recovery_trades[pair][1]["Units"],
                    take_profit=recovery_trades[pair][1]["TP"],
                    stop_loss=recovery_trades[pair][1]["SL"],
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order_sell = json.loads(json.dumps(order_sell, indent=4))['result']
                print(f'2nd {recovery_trades[pair][1]["Side"]} RecoveryOrder has been placed: {order_sell}')
            elif (df.iloc[-1]['Price'] >= recovery_trades[pair][2]["UnitPrice"]) and (recovery_trades[pair][1]["Triggered"] and not recovery_trades[pair][2]["Triggered"]):
                LOGGER.info(f'Placing the 3rd recovery order: {recovery_trades[pair][0]["Side"]}')
                recovery_trades[pair][2]["Triggered"] = True
                order_sell = client.place_active_order(
                    symbol=pair,
                    side=recovery_trades[pair][2]["Side"],
                    order_type="Market",
                    qty=recovery_trades[pair][2]["Units"],
                    take_profit=recovery_trades[pair][2]["TP"],
                    stop_loss=recovery_trades[pair][2]["SL"],
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order_sell = json.loads(json.dumps(order_sell, indent=4))['result']
                print(f'3rd {recovery_trades[pair][2]["Side"]} RecoveryOrder has been placed: {order_sell}')


def handle_trade(msg):
    trade_data = msg["data"][0]
    print(f'Trade Data: {msg}')
    # trade_data = json.loads(json.dumps(msg, indent=4))["data"][0]
    df = pd.DataFrame([trade_data])
    df = df.loc[:, ['symbol', 'price']]
    df.columns = ['Symbol', 'Price']
    df["Price"] = df["Price"].astype(float)
    # df["Time"] = pd.to_datetime(df["Time"])
    file_path = str(PROJECT_ROOT / f'{trade_data["symbol"]}.csv')
    df.to_csv(file_path, index=False)
    # if not os.path.isfile(file_path):
    #     data_frame.to_csv(file_path, index=False)
    # else:  # else if exists so append without writing the header
    #     data_frame.to_csv(file_path, mode='a', header=False, index=False)


def handle_orderbook25(msg):
    trade_data = msg["data"][0]
    # trade_data = json.loads(json.dumps(msg, indent=4))["data"][0]
    # print(f'OrderBook Data: {trade_data}')
    df = pd.DataFrame([trade_data])
    df = df.loc[:, ['symbol', 'price']]
    df.columns = ['Symbol', 'Price']
    df["Price"] = df["Price"].astype(float)
    # df["Time"] = pd.to_datetime(df["Time"])
    file_path = str(PROJECT_ROOT / f'{trade_data["symbol"]}.csv')
    df.to_csv(file_path, index=False)
    # if not os.path.isfile(file_path):
    #     data_frame.to_csv(file_path, index=False)
    # else:  # else if exists so append without writing the header
    #     data_frame.to_csv(file_path, mode='a', header=False, index=False)


def handle_kline(msg):
    symbol = str(msg["topic"]).split('.')[-1]
    price = msg["data"][0]["close"]
    trade_data = {"Symbol": symbol, "Price": price}
    # trade_data = json.loads(json.dumps(trade_data, indent=4))["data"][0]
    print(f'Kline Data: {trade_data}')
    df = pd.DataFrame([trade_data])
    # df = df.loc[:, ['symbol', 'price']]
    # df.columns = ['Symbol', 'Price']
    df["Price"] = df["Price"].astype(float)
    # df["Time"] = pd.to_datetime(df["Time"])
    file_path = str(PROJECT_ROOT / f'{trade_data["Symbol"]}.csv')
    df.to_csv(file_path, index=False)
    # if not os.path.isfile(file_path):
    #     data_frame.to_csv(file_path, index=False)
    # else:  # else if exists so append without writing the header
    #     data_frame.to_csv(file_path, mode='a', header=False, index=False)


# Check on your order and position through WebSocket.
def handle_order(msg):
    LOGGER.info(f'Order Status changed: {msg}')
    order = json.loads(json.dumps(msg, indent=4))
    if order["data"][0]["order_status"] == "Cancelled":
        LOGGER.info(f'Order has been cancelled, returning from handle_order')
        return
    # Handle each recovery order in a separate thread
    Thread(target=handle_recovery_order, args=[order]).start()


# Check on your order and position through WebSocket.
def handle_position(msg):
    order = json.loads(json.dumps(msg, indent=4))
    LOGGER.info(f'Setting Leverage {leverage} for: {order["data"][0]["symbol"]}')
    client.set_leverage(symbol=order["data"][0]["symbol"], buy_leverage=leverage, sell_leverage=leverage)
    LOGGER.info(f'Leverage {leverage} has been set for: {order["data"][0]["symbol"]}')


# Subscribe to the execution topics
def get_connected(pair="BTCUSDT"):
    # Subscribe to the topics
    # ws.trade_stream(callback=handle_trade, symbol=pair)
    ws.orderbook_25_stream(callback=handle_orderbook25, symbol=pair)
    # ws.kline_stream(handle_kline, symbol=pair, interval='1')
    # ws.order_stream(handle_order)
    # ws.position_stream(handle_position)
    # print(f'Websocket Market connected: {pair}')


if not websocket_connected:
    # ws.order_stream(handle_order)
    print(f'Websocket connected')
    # Thread(target=get_connected, args=[pair]).start()
    # Start WebSocket for each pair in a separate thread
    [Thread(target=get_connected, args=[p]).start() for p in settings["Pairs"]]
    # get_connected(pair=pair)
    websocket_connected = True


@csrf_exempt
def trades(request):
    account_balance = client.get_wallet_balance(coin='USDT')["result"]["USDT"]["wallet_balance"]
    # account_balance = 50000
    settings = get_settings()["Settings"]
    if request.method == 'POST':
        if "placeorder" in request.POST:
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}')
            print(f"Account Balance: {account_balance}")
            pair = request.POST["Pair"]
            side = request.POST["Side"]
            start_units = float(request.POST["StartUnits"])
            unit_price = float(request.POST["UnitPrice"])
            tp_sl_ticks = float(request.POST["TPSLTicks"])
            zone_divider = float(request.POST["ZoneDivider"])
            tick_price = float(request.POST["TickPrice"])
            leverage = float(request.POST["Leverage"])
            tp_l, tp_s, sl_l, sl_s = get_tp_sl(unit_price, tp_sl_ticks, tick_price)
            if "Buy" in str(request.POST):
                recovery_trades[pair] = [{"Side": "Sell", "Triggered": False, "UnitPrice": round(unit_price - (recovery_zone_ticks * tick_price), 2), "Units": round(start_units * base_times1, 2), "TP": tp_s, "SL": sl_s},
                                         {"Side": "Buy", "Triggered": False, "UnitPrice": unit_price, "Units": start_units * base_times2, "TP": tp_l, "SL": sl_l},
                                         {"Side": "Sell", "Triggered": False, "UnitPrice": round(unit_price - (recovery_zone_ticks * tick_price), 2), "Units": round(start_units * base_times3, 2), "TP": tp_s, "SL": sl_s}]
                LOGGER.info(f'Recovery Trades Dictionary {recovery_trades}')
                order = client.place_active_order(
                    symbol=pair,
                    side=side,
                    order_type="Market",
                    qty=start_units,
                    take_profit=tp_l,
                    stop_loss=sl_l,
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order = json.loads(json.dumps(order, indent=4))["result"]
                order = {"order_id": order["order_id"], "Pair": order["symbol"], "side": order["side"],
                         "order_type": order["order_type"], "price": order["price"],
                         "qty": order["qty"], "order_status": order["order_status"],
                         "TP": order["take_profit"], "SL": order["stop_loss"],
                         "created_time": pd.to_datetime(order["created_time"])
                         }
                LOGGER.info(f"Buy order has been placed: {order}")
                Thread(target=handle_recovery_order, args=[order]).start()
                return render(request, 'trades.html', {"account_balance": account_balance, "settings": settings, "order": order})
            elif "Sell" in str(request.POST):
                recovery_trades[pair] = [
                    {"Side": "Buy", "Triggered": False, "UnitPrice": round(unit_price + (recovery_zone_ticks * tick_price), 2),
                     "Units": round(start_units * base_times1, 2), "TP": tp_l, "SL": sl_l},
                    {"Side": "Sell", "Triggered": False, "UnitPrice": unit_price, "Units": round(start_units * base_times2, 2), "TP": tp_s,
                     "SL": sl_s},
                    {"Side": "Buy", "Triggered": False, "UnitPrice": round(unit_price + (recovery_zone_ticks * tick_price), 2),
                     "Units": round(start_units * base_times3, 2), "TP": tp_l, "SL": sl_l}]
                order = client.place_active_order(
                    symbol=pair,
                    side=side,
                    order_type="Market",
                    qty=start_units,
                    take_profit=tp_s,
                    stop_loss=sl_s,
                    time_in_force="GoodTillCancel",
                    reduce_only=False,
                    close_on_trigger=False
                )
                order = json.loads(json.dumps(order, indent=4))["result"]
                order = {"order_id": order["order_id"], "Pair": order["symbol"], "side": order["side"],
                         "order_type": order["order_type"], "price": order["price"],
                         "qty": order["qty"], "order_status": order["order_status"],
                         "TP": order["take_profit"], "SL": order["stop_loss"],
                         "created_time": pd.to_datetime(order["created_time"])
                         }
                LOGGER.info(f"Sell order has been placed: {order}")
                Thread(target=handle_recovery_order, args=[order]).start()
                return render(request, 'trades.html', {"account_balance": account_balance, "settings": settings, "order": order})
        elif "Buy" in request.body.decode(encoding="utf-8"):
            print(f'RequestBody: {request.body.decode(encoding="utf-8")}, {type(request.body.decode(encoding="utf-8"))}')
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}----{request.body}')
            request_data = json.loads(request.body.decode(encoding="utf-8"))
            print(f"Account Balance: {account_balance}")
            pair = request_data["Pair"]
            side = request_data["Side"]
            unit_price = float(request.POST["UnitPrice"])
            tick_price = float(request.POST["TickPrice"])
            tp_sl_ticks = float(request.POST["TPSLTicks"])
            tp_l, tp_s, sl_l, sl_s = get_tp_sl(unit_price, tp_sl_ticks, tick_price)
            recovery_trades[pair] = [{"Side": "Sell", "Triggered": False, "UnitPrice": round(unit_price - (recovery_zone_ticks * tick_price), 2), "Units": round(start_units * base_times1, 2), "TP": tp_s, "SL": sl_s},
                                     {"Side": "Buy", "Triggered": False, "UnitPrice": unit_price, "Units": round(start_units * base_times2, 2), "TP": tp_l, "SL": sl_l},
                                     {"Side": "Sell", "Triggered": False, "UnitPrice": round(unit_price - (recovery_zone_ticks * tick_price), 2), "Units": round(start_units * base_times3, 2), "TP": tp_s, "SL": sl_s}]
            order = client.place_active_order(
                symbol=pair,
                side=side,
                order_type="Market",
                qty=start_units,
                take_profit=tp_l,
                stop_loss=sl_l,
                time_in_force="GoodTillCancel",
                reduce_only=False,
                close_on_trigger=False
            )
            order = json.loads(json.dumps(order, indent=4))["result"]
            order = {"order_id": order["order_id"], "Pair": order["symbol"], "side": order["side"],
                     "order_type": order["order_type"], "price": order["price"],
                     "qty": order["qty"], "order_status": order["order_status"],
                     "TP": order["take_profit"], "SL": order["stop_loss"],
                     "created_time": pd.to_datetime(order["created_time"])
                     }
            LOGGER.info(f"Buy order has been placed: {order}")
            Thread(target=handle_recovery_order, args=[order]).start()
            return render(request, 'trades.html', {"account_balance": account_balance, "settings": settings, "order": order})
        elif "Sell" in request.body.decode(encoding="utf-8"):
            request_data = json.loads(request.body.decode(encoding="utf-8"))
            print(f'REQUEST METHOD: {request.method}, DATA: {request_data}')
            print(f"Account Balance: {account_balance}")
            pair = request_data["Pair"]
            side = request_data["Side"]
            unit_price = request.POST["UnitPrice"]
            tick_price = request.POST["TickPrice"]
            tp_l, tp_s, sl_l, sl_s = get_tp_sl(unit_price, tp_sl_ticks, tick_price)
            recovery_trades[pair] = [{"Side": "Buy", "Triggered": False, "UnitPrice": round(unit_price + (recovery_zone_ticks * tick_price), 2), "Units": round(start_units * base_times1, 2), "TP": tp_l, "SL": sl_l},
                                     {"Side": "Sell", "Triggered": False, "UnitPrice": unit_price, "Units": round(start_units * base_times2, 2), "TP": tp_s, "SL": sl_s},
                                     {"Side": "Buy", "Triggered": False, "UnitPrice": round(unit_price + (recovery_zone_ticks * tick_price), 2), "Units": round(start_units * base_times3, 2), "TP": tp_l, "SL": sl_l}]
            order = client.place_active_order(
                symbol=pair,
                side=side,
                order_type="Market",
                qty=start_units,
                take_profit=tp_s,
                stop_loss=sl_s,
                time_in_force="GoodTillCancel",
                reduce_only=False,
                close_on_trigger=False
            )
            order = json.loads(json.dumps(order, indent=4))["result"]
            order = {"order_id": order["order_id"], "Pair": order["symbol"], "side": order["side"],
                     "order_type": order["order_type"], "price": order["price"],
                     "qty": order["qty"], "order_status": order["order_status"],
                     "TP": order["take_profit"], "SL": order["stop_loss"],
                     "created_time": pd.to_datetime(order["created_time"])
                     }
            LOGGER.info(f"Sell order has been placed: {order}")
            Thread(target=handle_recovery_order, args=[order]).start()
            return render(request, 'trades.html', {"account_balance": account_balance, "settings": settings, "order": order})
        elif "updatesettings" in str(request.POST):
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}')
            settings = get_settings()["Settings"]
            # Remove Pairs
            [settings["Pairs"].remove(p) for p in settings["Pairs"] if request.POST[p] == ""]
            if request.POST["AddPair"] != "":
                settings["Pairs"].append(request.POST["AddPair"])
            settings["StartUnits"] = float(request.POST["StartUnits"])
            settings["UnitPrice"] = float(request.POST["UnitPrice"])
            settings["TPSLTicks"] = float(request.POST["TPSLTicks"])
            settings["TickPrice"] = float(request.POST["TickPrice"])
            settings["Leverage"] = float(request.POST["Leverage"])
            update_settings(settings=settings)
            return render(request, 'trades.html', {"account_balance": account_balance, "settings": settings})
        # Get trades data
        elif "gettrades" in request.POST:
            pair = request.POST["Pair"]
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}')
            user_trades = client.user_trade_records(symbol=pair)
            user_trades = json.loads(json.dumps(user_trades, indent=4))["result"]["data"]
            user_trades = [
                {"Order No": i, "Order ID": trade["order_id"], "Pair": trade["symbol"], "Side": trade["side"],
                 "Order Type": trade["order_type"], "Price": trade["price"], "Quantity": trade["order_qty"],
                 "Trade Time": pd.to_datetime(trade["trade_time_ms"], unit="ms")
                 } for i, trade in enumerate(user_trades)]
            # LOGGER.info(f'User trades {pair}: {user_trades}')
            return render(request, "trades.html", context={"account_balance": account_balance, "settings": settings, "trades": user_trades})
        # Get active orders
        elif "getorders" in request.POST:
            pair = request.POST["Pair"]
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}')
            user_orders = client.query_active_order(symbol=pair)
            print(f'ORDERS: {user_orders}')
            if user_orders["result"]:
                user_orders = json.loads(json.dumps(user_orders, indent=4))["result"]
                user_orders = [
                    {"No": i, "ID": order["order_id"], "Pair": order["symbol"], "Side": order["side"],
                     "Type": order["order_type"], "Price": order["price"], "Quantity": order["qty"],
                     "Status": order["order_status"],
                     "TP": order["take_profit"], "SL": order["stop_loss"],
                     "Created Time": pd.to_datetime(order["created_time"])
                     } for i, order in enumerate(user_orders)]
                # LOGGER.info(f'User orders {pair}: {user_orders}')
                return render(request, "trades.html", context={"account_balance": account_balance, "settings": settings, "orders": user_orders})
            return render(request, "trades.html", context={"account_balance": account_balance, "settings": settings})
        elif "cancelorders" in request.POST:
            pair = request.POST["Pair"]
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}')
            user_orders = client.query_active_order(symbol=pair)
            if user_orders["result"]:
                print(f'Cancelling active orders')
                client.cancel_all_active_orders(symbol=pair)
                client.cancel_all_conditional_orders(symbol=pair)
                if client.my_position(symbol=pair):
                    try:
                        LOGGER.info(f'Closing Open Position: {pair}')
                        client.close_position(symbol=pair)
                    except:
                        pass
                return render(request, "trades.html", context={"account_balance": account_balance, "settings": settings})
            return render(request, "trades.html", context={"account_balance": account_balance, "settings": settings})
        elif "getpositions" in request.POST:
            pair = request.POST["Pair"]
            print(f'REQUEST METHOD: {request.method}, DATA: {request.POST}')
            positions = client.my_position(symbol=pair)
            positions = json.loads(json.dumps(positions, indent=4))["result"]
            positions = [
                {"No": i, "Pair": order["symbol"], "Side": order["side"],
                 "Size": order["size"], "Position Value": order["position_value"], "Entry Price": order["entry_price"],
                 "Leverage": order["leverage"], "Free Qty": order["free_qty"], "TP": order["take_profit"],
                 "SL": order["stop_loss"],
                 "TS": order["trailing_stop"]
                 } for i, order in enumerate(positions)]
            # print(f'Positions {pair}: {positions}')
            return render(request, "trades.html", context={"account_balance": account_balance, "settings": settings, "positions": positions})
    return render(request, 'trades.html', context={"account_balance": account_balance, "settings": settings})


# Create your views here.
def index(request):
    account_balance = client.get_wallet_balance(coin='USDT')["result"]["USDT"]["wallet_balance"]
    # account_balance = 50000
    if request.method == 'POST' and "trades" in request.POST:
        user_trades = client.user_trade_records(symbol='SOLUSDT')
        # print(f'Trades: {trades}')
        user_trades = json.loads(json.dumps(user_trades, indent=4))["result"]["data"]
        user_trades = [
            {"Order No": i, "Order ID": trade["order_id"], "Pair": trade["symbol"], "Side": trade["side"],
             "Order Type": trade["order_type"], "Price": trade["price"], "Quantity": trade["order_qty"],
             "Trade Time": pd.to_datetime(trade["trade_time_ms"], unit="ms")
             } for i, trade in enumerate(user_trades)]
        # print(f'User trades {symbol}: {user_trades}')
        return render(request, "index.html", context={"account_balance": account_balance, "trades": user_trades})
    return render(request, "index.html", context={"account_balance": account_balance})


def db(request):
    greeting = Greeting()
    greeting.save()
    greetings = Greeting.objects.all()
    return render(request, "db.html", {"greetings": greetings})

# git commit -m "Updated RecoveryZone Orders Handling"

# ByBit TestNet
# email: fadialtalla@outlook.com
# Password: ZRfadi@2022