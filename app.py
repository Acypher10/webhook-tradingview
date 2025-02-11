# -*- coding: utf-8 -*-
import asyncio
import websockets
import json
import time
import hashlib
import gzip
import hmac
import requests
from flask import Flask, request, jsonify
from functools import wraps
from urllib.parse import urlparse, urlencode

# Configuración API CoinEx
WS_URL = "wss://socket.coinex.com/v2/futures"  # WebSocket para futuros
API_KEY = "ACCESS_ID"  # Reemplaza con tu Access ID
API_SECRET = "SECRET_KEY"  # Reemplaza con tu Secret Key
API_URL = "https://api.coinex.com/v2/futures/order"  # URL para órdenes en futuros
FINISHED_ORDERS_URL = "https://api.coinex.com/v2/futures/order/list-finished-order"  # URL para órdenes finalizadas

app = Flask(__name__)

class RequestsClient(object):
    HEADERS = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "X-COINEX-KEY": "",
        "X-COINEX-SIGN": "",
        "X-COINEX-TIMESTAMP": "",
    }

    def __init__(self):
        self.access_id = API_KEY
        self.secret_key = API_SECRET
        self.url = API_URL
        self.headers = self.HEADERS.copy()

    # Generate your signature string
    def gen_sign(self, method, request_path, body, timestamp):
        prepared_str = f"{method}{request_path}{body}{timestamp}"
        signature = hmac.new(
            bytes(self.secret_key, 'latin-1'), 
            msg=bytes(prepared_str, 'latin-1'), 
            digestmod=hashlib.sha256
        ).hexdigest().lower()
        return signature

    def get_common_headers(self, signed_str, timestamp):
        headers = self.HEADERS.copy()
        headers["X-COINEX-KEY"] = self.access_id
        headers["X-COINEX-SIGN"] = signed_str
        headers["X-COINEX-TIMESTAMP"] = timestamp
        headers["Content-Type"] = "application/json; charset=utf-8"
        return headers

    def request(self, method, url, params={}, data=""):
        req = urlparse(url)
        request_path = req.path

        timestamp = str(int(time.time() * 1000))
        if method.upper() == "GET":
            # If params exist, query string needs to be added to the request path
            if params:
                for item in params:
                    if params[item] is None:
                        del params[item]
                        continue
                request_path = request_path + "?" + urlencode(params)

            signed_str = self.gen_sign(
                method, request_path, body="", timestamp=timestamp
            )
            response = requests.get(
                url,
                params=params,
                headers=self.get_common_headers(signed_str, timestamp),
            )

        else:
            signed_str = self.gen_sign(
                method, request_path, body=data, timestamp=timestamp
            )
            response = requests.post(
                url, data, headers=self.get_common_headers(signed_str, timestamp)
            )

        if response.status_code != 200:
            raise ValueError(response.text)
        return response


request_client = RequestsClient()

# Limitador de tasa (Máximo 30 llamadas por segundo)
def rate_limiter(max_calls_per_second):
    interval = 1.0 / max_calls_per_second
    def decorator(func):
        last_time_called = [0.0]
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.perf_counter() - last_time_called[0]
            wait_time = interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            result = func(*args, **kwargs)
            last_time_called[0] = time.perf_counter()
            return result
        return wrapper
    return decorator

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("📩 Alerta recibida:", data)

    # Extraer datos de TradingView
    market = data.get("market", "BTCUSDT")
    side = data.get("side", "buy")  # 'buy' o 'sell'
    amount = data.get("amount", 0.01)
    price = data.get("price", 50000)

    # Enviar orden a CoinEx
    response = send_order_to_coinex(market, side, amount, price)
    print("📤 Respuesta de CoinEx:", response)

    # Obtener órdenes finalizadas
    finished_orders = get_finished_orders(market)
    return jsonify({"order_response": response, "finished_orders": finished_orders})

async def ping(conn):
    param = {"method": "server.ping", "params": {}, "id": 1}
    while True:
        await conn.send(json.dumps(param))
        await asyncio.sleep(3)

async def auth(conn):
    timestamp = int(time.time() * 1000)
    prepared_str = f"{timestamp}"
    signed_str = hmac.new(
        bytes(API_SECRET, "latin-1"),
        msg=bytes(prepared_str, "latin-1"),
        digestmod=hashlib.sha256,
    ).hexdigest().lower()
    
    param = {
        "method": "server.sign",
        "params": {
            "access_id": API_KEY,
            "signed_str": signed_str,
            "timestamp": timestamp,
        },
        "id": 1,
    }
    await conn.send(json.dumps(param))
    res = await conn.recv()
    res = gzip.decompress(res)
    print("🔑 Autenticación:", json.loads(res))

async def subscribe_depth(conn):
    param = {
        "method": "depth.subscribe",
        "params": {"market_list": [["BTCUSDT", 5, "0", True]]},
        "id": 1,
    }
    await conn.send(json.dumps(param))
    res = await conn.recv()
    res = gzip.decompress(res)
    print("📊 Suscripción Depth:", json.loads(res))

async def subscribe_asset(conn):
    param = {"method": "balance.subscribe", "params": {"ccy_list": ["USDT"]}, "id": 1}
    await conn.send(json.dumps(param))
    res = await conn.recv()
    res = gzip.decompress(res)
    print("💰 Suscripción Balance:", json.loads(res))

async def main():
    try:
        async with websockets.connect(
            uri=WS_URL, compression=None, ping_interval=None
        ) as conn:
            await auth(conn)
            await subscribe_depth(conn)
            await subscribe_asset(conn)
            asyncio.create_task(ping(conn))

            while True:
                res = await conn.recv()
                res = gzip.decompress(res)
                res = json.loads(res)
                print("📡 Mensaje WebSocket:", res)
    except Exception as e:
        print(f"❌ Error en WebSocket: {e}")

@rate_limiter(30)
def get_futures_market():
    request_path = "/futures/market"
    params = {"market": "BTCUSDT"}
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response

@rate_limiter(30)
def get_futures_balance():
    request_path = "/assets/futures/balance"
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
    )
    return response

@rate_limiter(30)
def get_deposit_address():
    request_path = "/assets/deposit-address"
    params = {"ccy": "USDT", "chain": "CSC"}

    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response

@rate_limiter(30)  # Límite de 30 llamadas por segundo
def send_order_to_coinex(market, side, amount, price):
    request_path = "/futures/order"
    data = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": "limit",
        "amount": str(amount),
        "price": str(price),
        "client_id": "user1",
        "is_hide": True,
    }
    data = json.dumps(data)
    response = request_client.request(
        "POST",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        data=data,
    )
    return response

@rate_limiter(30)  # Límite de 30 llamadas por segundo
def get_finished_orders(market, side):
    """ Obtiene las órdenes finalizadas de futuros en CoinEx """
    request_path = "/futures/finished-order"
    data = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "page": 1,
        "limit": 10,  # Puedes ajustar la cantidad de órdenes retornadas
    }
    data = json.dumps(data)
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        data=data,
    )
    return response


def run_code():
    try:
        response_1 = get_futures_market().json()
        print(response_1)

        response_2 = get_futures_balance().json()
        print(response_2)

        response_3 = get_deposit_address().json()
        print(response_3)

        response_4 = send_order_to_coinex().json()
        print(response_4)

        response_5 = get_finished_orders().json()
        print(response_4)

    except Exception as e:
        print("Error:" + str(e))
        time.sleep(3)
        run_code()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host='0.0.0.0', port=5000)
    run_code()
