# -*- coding: utf-8 -*-
import asyncio
import json
import time
import hashlib
import gzip
import hmac
import requests
from flask import Flask, request, jsonify
from functools import wraps
from urllib.parse import urlparse, urlencode
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)

# Cargar variables del archivo .env
load_dotenv()

# Configuración API CoinEx
# Ahora puedes acceder a ellas con os.getenv()

API_KEY = os.getenv("ACCESS_ID")
API_SECRET = os.getenv("SECRET_KEY")

if not API_KEY or not API_SECRET:
    raise ValueError("Faltan las variables de entorno ACCESS_ID o SECRET_KEY")

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
        self.url = "https://api.coinex.com/v2"
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

# Limitador de tasa (Máximo 20 llamadas por segundo)
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

@rate_limiter(10)
def get_futures_market():
    request_path = "/futures/market"
    params = {"market": "BTCUSDT"}
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response

@rate_limiter(10) # Límite de 20 llamadas por segundo
def get_futures_balance():
    request_path = "/assets/futures/balance"
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
    )
    return response

@rate_limiter(10) # Límite de 20 llamadas por segundo
def get_deposit_address():
    request_path = "/assets/deposit-address"
    params = {"ccy": "USDT", "chain": "CSC"}

    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response
@rate_limiter(20)  # Límite de 20 llamadas por segundo
def send_order_to_coinex(market, side, amount, price):
    request_path = "/futures/order"
    data = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": "limit",
        "amount": amount,
        "price": price,
        "client_id": "user1",
        "is_hide": True,  # Corrección si antes estaba como 'is_hiden'
    }
    data_json = json.dumps(data)

    logging.info(f"📤 Enviando orden a CoinEx: {data_json}")
    print(f"📤 Enviando orden a CoinEx: {data_json}")  # 👈 Se imprimirá en los logs de Render

    try:
        response = request_client.request(
            "POST",
            "{url}{request_path}".format(url=request_client.url, request_path=request_path),
            data=data_json,
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")  # 👈 Se imprimirá en los logs de Render

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")  # 👈 Se imprimirá en los logs de Render

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")  # 👈 Se imprimirá en los logs de Render

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")  # 👈 Se imprimirá en los logs de Render

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")  # 👈 Se imprimirá en los logs de Render

    return response

# Variable global para almacenar la última alerta recibida
last_alert = None  

@app.route('/webhook', methods=['POST'])
def webhook():
    global last_alert
    data = request.json
    print("📩 Alerta recibida:", data)

    # Guardar la alerta en la variable global
    last_alert = {
        "market": data.get("market", "BTCUSDT"),
        "side": data.get("side", "buy"),  # 'buy' o 'sell'
        "amount": data.get("amount", 0.01),
        "price": data.get("price", 50000)
    }

    return jsonify({"status": "success", "message": "Alerta recibida"}), 200

def run_code():
    global last_alert

    try:
        print("🔄 Ejecutando run_code()...")  # 👈 Verifica si entra aquí

        if last_alert:
            print(f"🚀 Enviando orden con alerta: {last_alert}")  # 👈 Verifica los datos antes de enviar

            response_4 = send_order_to_coinex(
                last_alert["market"],
                last_alert["side"],
                last_alert["amount"],
                last_alert["price"]
            )

            print(f"🔍 Respuesta de send_order_to_coinex: {response_4}")  # 👈 Ver si se devuelve algo

            if response_4:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_4.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_4.text}")  # 👈 Ver error real

            last_alert = None  # Limpia alerta después de usarla

        else:
            print("⚠️ No hay alertas pendientes.")

    except Exception as e:
        print(f"🔥 Error en run_code(): {str(e)}")


    except Exception as e:
        print("Error:", str(e))
        time.sleep(3)
        run_code()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    run_code()