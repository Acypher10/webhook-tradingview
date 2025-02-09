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

# Configuración API CoinEx
WS_URL = "wss://socket.coinex.com/v2/futures"  # WebSocket para futuros
API_KEY = "TU_ACCESS_ID"  # Reemplaza con tu Access ID
API_SECRET = "TU_SECRET_KEY"  # Reemplaza con tu Secret Key
API_URL = "https://api.coinex.com/v2/futures/order"  # URL para órdenes en futuros
FINISHED_ORDERS_URL = "https://api.coinex.com/v2/futures/order/list-finished-order"  # URL para órdenes finalizadas

app = Flask(__name__)

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

@rate_limiter(30)  # Límite de 30 llamadas por segundo
def send_order_to_coinex(market, side, amount, price):
    timestamp = int(time.time() * 1000)
    params = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": "limit",
        "amount": str(amount),
        "price": str(price),
        "client_id": "user1",
        "is_hide": True,
    }
    # Ordenar los parámetros alfabéticamente
    sorted_params = sorted(params.items())
    query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
    # Generar firma HMAC-SHA256
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Authorization": signature,
    }
    response = requests.post(API_URL, json=params, headers=headers)
    return response.json()

@rate_limiter(30)  # Límite de 30 llamadas por segundo
def get_finished_orders(market):
    """ Obtiene las órdenes finalizadas de futuros en CoinEx """
    timestamp = int(time.time() * 1000)
    params = {
        "market": market,
        "page": 1,
        "limit": 10,  # Puedes ajustar la cantidad de órdenes retornadas
        "start_time": timestamp - 86400000,  # Últimas 24 horas
        "end_time": timestamp,
    }
    sorted_params = sorted(params.items())
    query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Authorization": signature,
    }
    response = requests.get(FINISHED_ORDERS_URL, params=params, headers=headers)
    
    try:
        data = response.json()
        print("📜 Órdenes Finalizadas:", json.dumps(data, indent=4))
        return data
    except Exception as e:
        print(f"❌ Error al obtener órdenes finalizadas: {e}")
        return None

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

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host='0.0.0.0', port=5000)
