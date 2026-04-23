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
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)

# Cargar variables del archivo .env
load_dotenv()

# Configuración API CoinEx
# Ahora puedes acceder a ellas con os.getenv()

API_KEY = os.getenv("ACCESS_ID")
API_SECRET = os.getenv("SECRET_KEY")
AZURE_FUNCTION_URL = os.getenv("AZURE_FUNCTION_URL")

if not API_KEY or not API_SECRET:
    raise ValueError("Faltan las variables de entorno ACCESS_ID o SECRET_KEY")

if not AZURE_FUNCTION_URL:
    raise ValueError("AZURE_FUNCTION_URL not set")

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

@rate_limiter(10) # Límite de 10 llamadas por segundo
def get_futures_market():
    request_path = "/futures/market"
    params = {"market": "BTCUSDT"}
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response

@rate_limiter(10) # Límite de 10 llamadas por segundo
def get_futures_balance():
    request_path = "/assets/futures/balance"
    logging.info(f"📤 Obteniendo balance en CoinEx")
    print(f"📤 Obteniendo balance en CoinEx")

    try:
        response = request_client.request(
            "GET",
            "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")

    return response

@rate_limiter(20) # Límite de 20 llamadas por segundo
def close_position():
    request_path = "/futures/close-position"
    data = {"market": "BTCUSDT",
              "market_type": "FUTURES",
              "type": "market",
              "amount": None,
              "client_id": "user1",
              "is_hide": True
              }
    data_json = json.dumps(data)
    
    logging.info(f"📤 Cerrando posiciones en CoinEx: {data_json}")
    print(f"📤 Cerrando posiciones en CoinEx: {data_json}")

    try:
        response = request_client.request(
            "POST",
            "{url}{request_path}".format(url=request_client.url, request_path=request_path),
            data=data_json,
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")

    return response

@rate_limiter(20) # Límite de 20 llamadas por segundo
def cancel_all_orders(side):
    request_path = "/futures/cancel-all-order"
    data = {"market": "BTCUSDT", 
              "market_type": "FUTURES",
              "side": side,
              }
    data_json = json.dumps(data)
    
    logging.info(f"📤 Cancelando todas las órdenes en CoinEx: {data_json}")
    print(f"📤 Cancelando todas las órdenes en CoinEx: {data_json}")
    
    try:
        response = request_client.request(
            "POST",
            "{url}{request_path}".format(url=request_client.url, request_path=request_path),
            data=data_json,
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")

    return response

@rate_limiter(10) # Límite de 10 llamadas por segundo
def adjust_position_leverage():
    request_path = "/futures/adjust-position-leverage"
    data = {"market": "BTCUSDT", 
              "market_type": "FUTURES",
              "margin_mode": "isolated",
              "leverage": 5
              }
    data_json = json.dumps(data)

    logging.info(f"📤 Ajustando apalancamiento en CoinEx: {data_json}")
    print(f"📤 Ajustando apalancamiento en CoinEx: {data_json}")

    try:
        response = request_client.request(
            "POST",
            "{url}{request_path}".format(url=request_client.url, request_path=request_path),
            data=data_json,
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")

    return response

@rate_limiter(20) # Límite de 20 llamadas por segundo
def set_position_stop_loss(sl_price):
    request_path = "/futures/set-position-stop-loss"
    data = {"market": "BTCUSDT", 
              "market_type": "FUTURES",
              "stop_loss_type": "latest_price",
              "stop_loss_price": sl_price
              }
    data_json = json.dumps(data)

    logging.info(f"📤 Enviando stop loss: {data_json}")
    print(f"📤 Enviando stop loss: {data_json}")  # 👈 Ver en logs de Render

    try:
        response = request_client.request(
            "POST",
            f"{request_client.url}{request_path}",
            data=data_json,
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")  # 👈 Log en Render

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")  # 👈 Log en Render

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")  # 👈 Log en Render

    return response

@rate_limiter(20) # Límite de 20 llamadas por segundo
def set_position_take_profit(tp_price):
    request_path = "/futures/set-position-take-profit"
    data = {"market": "BTCUSDT", 
              "market_type": "FUTURES",
              "take_profit_type": "latest_price",
              "take_profit_price": tp_price
              }
    data_json = json.dumps(data)

    logging.info(f"📤 Enviando take profit: {data_json}")
    print(f"📤 Enviando take profit: {data_json}")  # 👈 Ver en logs de Render

    try:
        response = request_client.request(
            "POST",
            f"{request_client.url}{request_path}",
            data=data_json,
        )

        logging.info(f"✅ Respuesta HTTP: {response.status_code}")
        print(f"✅ Respuesta HTTP: {response.status_code}")  # 👈 Log en Render

        try:
            response_data = response.json()
            logging.info(f"📌 Respuesta JSON de CoinEx: {response_data}")
            print(f"📌 Respuesta JSON de CoinEx: {response_data}")

            if "code" in response_data and response_data["code"] != 0:
                logging.error(f"❌ Error de CoinEx: {response_data['message']}")
                print(f"❌ Error de CoinEx: {response_data['message']}")  # 👈 Log en Render

        except ValueError:
            logging.error(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")
            print(f"❌ Error: CoinEx no devolvió JSON. Respuesta cruda: {response.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"🚨 Error de conexión con CoinEx: {str(e)}")
        print(f"🚨 Error de conexión con CoinEx: {str(e)}")  # 👈 Log en Render

    return response

@rate_limiter(20)  # Límite de 20 llamadas por segundo
def send_order_to_coinex(market, side, amount):
    
    request_path = "/futures/order"
    data = {
        "market": market,
        "market_type": "FUTURES",
        "side": side,
        "type": "market",
        "amount": amount,
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

event_pipeline = []

def log_event(step, data):
    global event_pipeline

    event = {
        "step": step,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }

    event_pipeline.append(event)

events = []

def push_event(step, data):
    events.append({
        "step": step,
        "timestamp": time.time(),
        "data": data
    })

# Variable global para almacenar la última alerta recibida
last_alert = None 

# === VARIABLES DE CONTROL DE RIESGO ===
max_consecutive_losses = 3     # Stop de 2–3 pérdidas consecutivas
max_daily_loss_pct = 0.07      # Stop diario 7%
max_total_loss_pct = 0.25      # Stop general 25%

risk_state = {
    "consecutive_losses": 0,
    "daily_loss": 0.0,
    "start_balance": None,
    "last_balance": None,
    "paused": False,
    "pause_reason": "",
    "pause_time": None
}

def reset_daily_if_needed(current_time, current_balance):
    """🔄 Reinicia las variables de riesgo cada 24 horas"""
    global risk_state

    if risk_state["pause_time"] is None:
        return

    # Si han pasado más de 24 horas desde el último stop → reset
    if current_time - risk_state["pause_time"] >= timedelta(hours=24):
        print("⏰ 24h cumplidas. Reset automático de reglas de riesgo.")
        risk_state["consecutive_losses"] = 0
        risk_state["daily_loss"] = 0.0
        risk_state["start_balance"] = current_balance
        risk_state["paused"] = False
        risk_state["pause_reason"] = ""
        risk_state["pause_time"] = None

def check_risk_limits(current_balance):
    """✅ Verifica si los límites de riesgo fueron alcanzados"""
    global risk_state

    if risk_state["start_balance"] is None:
        risk_state["start_balance"] = current_balance
        risk_state["last_balance"] = current_balance

    # Calcular pérdida diaria
    daily_loss = (risk_state["start_balance"] - current_balance) / risk_state["start_balance"]

    # Calcular pérdida total
    total_loss = (risk_state["last_balance"] - current_balance) / risk_state["last_balance"]

    # Guardar en estado
    risk_state["daily_loss"] = daily_loss

    # Revisar consecutivas
    if risk_state["consecutive_losses"] >= max_consecutive_losses:
        risk_state["paused"] = True
        risk_state["pause_reason"] = f"❌ Stop por {max_consecutive_losses} pérdidas consecutivas"
        risk_state["pause_time"] = datetime.now()
        return False

    # Revisar stop diario
    if daily_loss >= max_daily_loss_pct:
        risk_state["paused"] = True
        risk_state["pause_reason"] = f"❌ Stop diario alcanzado ({daily_loss:.2%})"
        risk_state["pause_time"] = datetime.now()
        return False

    # Revisar stop general
    if total_loss >= max_total_loss_pct:
        risk_state["paused"] = True
        risk_state["pause_reason"] = f"❌ Stop general alcanzado ({total_loss:.2%})"
        risk_state["pause_time"] = datetime.now()
        return False

    return True


@app.route('/webhook', methods=['POST'])
def webhook():
    global last_alert
    data = request.json
    print("📩 Alerta recibida:", data)

    # Obtener balance de CoinEx
    response = get_futures_balance()

    if response.status_code == 200:
        response_data = response.json()

        if response_data.get("code") == 0:
            balance_data = response_data.get("data", [])

            if isinstance(balance_data, list) and len(balance_data) > 0:
                first_entry = balance_data[0]  # ✅ Accede al primer elemento

                if isinstance(first_entry, dict):
                    balance = float(first_entry.get("available", 0))
                    margin = float(first_entry.get("margin", 0))  # ✅ Extrae margin correctamente
                    total_balance = balance + margin  # ✅ Balance total sumando margin
                    print(f"✅ Balance disponible: {balance}, Margin: {margin}, Total: {total_balance}")
                    push_event("balance", {"balance": balance,"margin": margin,"total": total_balance})
                else:
                    print("⚠️ Error: El primer elemento de 'data' no es un diccionario válido.")
                    return jsonify({"error": "Formato inválido en balance"}), 500
            else:
                print(f"⚠️ La respuesta de CoinEx no tiene datos de balance.")
                return jsonify({"error": "Sin datos de balance"}), 500
        else:
            print(f"❌ Error en respuesta de CoinEx: {response_data.get('message', 'Desconocido')}")
            return jsonify({"error": "Error en respuesta de CoinEx"}), 500
    else:
        print(f"❌ Error HTTP al obtener balance: {response.status_code}")
        return jsonify({"error": "Error HTTP al obtener balance"}), response.status_code

    # Convertir amount a número y verificar que sea válido
    amount = float(data.get("amount", 0))
    price = float(data.get("price", 50000))
    side = data.get("side", "buy").lower()

    # Calcular SL y TP según el lado de la orden
    if side == "buy":
        sl_price = price * 0.9966  # -1%
        tp_price = price * 1.0102  # +3%
    elif side == "sell":
        sl_price = price * 1.0034  # +1%
        tp_price = price * 0.9898  # -3%
    else:
        print("⚠️ Error: 'side' inválido. Debe ser 'buy' o 'sell'.")
        return jsonify({"status": "error", "message": "Side inválido"}), 400

    last_alert = {
        "market": data.get("market", "BTCUSDT"),
        "side": side,
        "amount": amount,
        "price": price,
        "sl_price": sl_price,
        "tp_price": tp_price,
    }

    print(f"🚀 Orden recibida: {last_alert}")
    run_code()

    return jsonify({"status": "success", "message": "Alerta recibida"}), 200


def run_code():
    global last_alert, risk_state

    print("🏁 run_code() ha sido llamado")  # 👈 VERIFICA SI SE EJECUTA

    try:
        print("🔄 Ejecutando run_code()...")  # 👈 Verifica si entra aquí

        if risk_state["paused"]:
            print(f"⏸️ Operaciones pausadas: {risk_state['pause_reason']}")
            reset_daily_if_needed(datetime.now(), risk_state["last_balance"])
            return
        
        if last_alert:
            
            print(f"🚀 Obteniendo balance...")  # 👈 Verifica los datos antes de enviar
            
            response_0 = get_futures_balance()
            
            print(f"🔍 Respuesta de close_position: {response_0}")  # 👈 Ver si se devuelve algo

            if response_0.status_code == 200:
                response_data = response_0.json()

                if response_data.get("code") == 0:
                    data = response_data.get("data", [])

                    if isinstance(data, list) and len(data) > 0:  
                        first_entry = data[0]  # ✅ Accede al primer elemento

                        if isinstance(first_entry, dict):
                            balance = float(first_entry.get("available", 0))
                            margin = float(first_entry.get("margin", 0))  # ✅ Extrae margin correctamente
                            total_balance = balance + margin  # ✅ Balance total sumando margin
                            print(f"✅ Balance disponible: {balance}, Margin: {margin}, Total: {total_balance}")
                            log_event("balance", {"available": balance,"margin": margin,"total": total_balance})

                            # 🔄 Reset automático si han pasado 24h
                            reset_daily_if_needed(datetime.now(), total_balance)

                            # ✅ Verificar límites de riesgo
                            if not check_risk_limits(total_balance):
                                print("⚠️ Límite alcanzado. No se envía la orden.")
                                return
                        else:
                            print("⚠️ El primer elemento de 'data' no es un diccionario válido.")
                            return
                    else:
                        print(f"⚠️ La respuesta de CoinEx no tiene datos de balance.")
                        return
                else:
                    print(f"❌ Error en la respuesta de CoinEx: {response_data.get('message', 'Desconocido')}")
                    return
            else:
                print(f"❌ Error HTTP al obtener balance: {response_0.status_code}")
                return

            # Ajustar amount según balance y lado de la orden
            amount = last_alert["amount"]

            # ✅ Ajustar cantidad según balance y tipo de operación
            if last_alert["side"] == "buy":
                amount = (total_balance / float(last_alert["price"])) * 5  # Compra: usar balance para obtener cantidad
            elif last_alert["side"] == "sell":
                amount = (total_balance / float(last_alert["price"])) * 5  # Venta: usar todo el balance disponible
            else:
                print("⚠️ Error: 'side' inválido. Debe ser 'buy' o 'sell'.")
                return

            # 🔥 Aplicar un offset del 2% para evitar "balance_not_enough"
            offset_percentage = 0.02  # 2% de margen de seguridad
            amount *= (1 - offset_percentage)  # Reduce un 2% la cantidad

            # Actualizar la alerta con el nuevo amount
            last_alert["amount"] = round(amount, 6)  # Redondear para evitar errores de precisión

            print(f"🚀 Monto ajustado para la orden: {last_alert['amount']} {last_alert['market']}")

            print(f"🚀 Cancelando posición...")  # 👈 Verifica los datos antes de enviar
            
            response_1 = close_position()
            
            print(f"🔍 Respuesta de close_position: {response_1}")  # 👈 Ver si se devuelve algo
            
            print(f"🚀 Cancelando todas las órdenes...")  # 👈 Verifica los datos antes de enviar
            
            response_2 = cancel_all_orders(
                last_alert["side"]
            )
            
            print(f"🔍 Respuesta de cancel_all_orders: {response_2}")  # 👈 Ver si se devuelve algo

            print(f"🚀 Ajustando apalancamiento...")  # 👈 Verifica los datos antes de enviar
            
            response_3 = adjust_position_leverage()
            
            print(f"🔍 Respuesta de adjust_position_leverage: {response_3}")  # 👈 Ver si se devuelve algo
            
            print(f"🚀 Enviando orden con alerta: {last_alert}")  # 👈 Verifica los datos antes de enviar

            response_4 = send_order_to_coinex(
                last_alert["market"],
                last_alert["side"],
                last_alert["amount"],
            )

            print(f"🔍 Respuesta de send_order_to_coinex: {response_4}")  # 👈 Ver si se devuelve algo


            if response_4.status_code == 200:
                response_data_1 = response_4.json()

                if response_data_1.get("code") == 0:
                    data = response_data_1.get("data", [])

                    if isinstance(data, list) and len(data) > 0:  
                        first_entry = data[0]  # Para respuestas donde "data" es una lista
                        print("📌 Data es una lista:", first_entry)
                        avg_entry_price = float(first_entry.get("last_filled_price", 0))
                        filled_value = float(first_entry.get("filled_value", 0))
                        log_event("order", {"market": data.get("market"),"side": data.get("side"),"entry_price": avg_entry_price,"filled_value": filled_value,"order_id": data.get("order_id")})
                        push_event("order_executed", {"price": avg_entry_price,"value": filled_value,"side": last_alert["side"]})
                    elif isinstance(data, dict):
                        print("📌 Data es un diccionario:", data)  # Para respuestas donde "data" es un diccionario
                        avg_entry_price = float(data.get("last_filled_price", 0))
                        filled_value = float(data.get("filled_value", 0))
                        log_event("order", {"market": data.get("market"),"side": data.get("side"),"entry_price": avg_entry_price,"filled_value": filled_value,"order_id": data.get("order_id")})
                        push_event("order_executed", {"price": avg_entry_price,"value": filled_value,"side": last_alert["side"]})
                    else:
                        print("⚠️ Formato inesperado de 'data':", data)
                else:
                    print(f"❌ Error en la respuesta de CoinEx: {response_data_1.get('message', 'Desconocido')}")
                    return
            else:
                print(f"❌ Error HTTP al obtener datos de la orden: {response_4.status_code}")
                return
            
            print(f"🔍 Precio de entrada recibido: {avg_entry_price}")
            print(f"📦 Monto operado: {filled_value}")

            # === PARÁMETROS DE RIESGO Y CÁLCULO DE ROI ===
            balance = total_balance  # Tu balance real sin apalancamiento
            risk_pct_gain = 0.085     # 8.5% ganancia
            risk_pct_loss = 0.025     # 2.5% pérdida

            roi_gain = balance * risk_pct_gain  # Ej: 3 USDT + 1
            roi_loss = balance * risk_pct_loss  # Ej: 1 USDT

            btc_size = filled_value / avg_entry_price  # Cantidad real de BTC operado

            # === CÁLCULO DE TP/SL ===
        
            if last_alert["side"] == "buy":
                tp_price = avg_entry_price + (roi_gain / btc_size)
                sl_price = avg_entry_price - (roi_loss / btc_size)
            elif last_alert["side"] == "sell":
                tp_price = avg_entry_price - (roi_gain / btc_size)
                sl_price = avg_entry_price + (roi_loss / btc_size)
            else:
                print("⚠️ Error: 'side' inválido. Debe ser 'buy' o 'sell'")
                return

            # === GUARDAR EN LA ALERTA Y REDONDEAR ===
            last_alert["tp_price"] = round(tp_price, 2)
            last_alert["sl_price"] = round(sl_price, 2)

            # === MOSTRAR RESULTADO ===
            print("📊 Cálculo de TP y SL:")
            print(f"  🔸 Take Profit: {last_alert['tp_price']}  (+{roi_gain:.2f} USDT)")
            print(f"  🔸 Stop Loss  : {last_alert['sl_price']}  (-{roi_loss:.2f} USDT)")
            
            response_5 = set_position_stop_loss(
                last_alert["sl_price"]
            )

            print(f"🔍 Respuesta de set_position_stop_loss: {response_5}")  # 👈 Ver si se devuelve algo
            log_event("stop_loss", {"price": last_alert["sl_price"],"response": response_5.json() if response_5 else None})
            push_event("stop_loss", response_5.json())

            response_6 = set_position_take_profit(
                last_alert["tp_price"]
            )

            print(f"🔍 Respuesta de set_position_take_profit: {response_6}")  # 👈 Ver si se devuelve algo
            log_event("take_profit", {"price": last_alert["tp_price"],"response": response_6.json() if response_6 else None})
            push_event("take_profit", response_6.json())

            if response_1:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_1.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_1.text}")  # 👈 Ver error real

            if response_2:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_2.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_2.text}")  # 👈 Ver error real

            if response_3:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_3.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_3.text}")  # 👈 Ver error real

            if response_4:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_4.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_4.text}")  # 👈 Ver error real

            if response_5:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_5.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_5.text}")  # 👈 Ver error real

            if response_6:
                try:
                    print(f"✅ Respuesta JSON de CoinEx: {response_6.json()}")  # 👈 Imprime la respuesta JSON real
                except Exception as e:
                    print(f"❌ Error al leer JSON de CoinEx: {str(e)} - Respuesta cruda: {response_6.text}")  # 👈 Ver error real

            # === EVALUAR RESULTADO DE LA OPERACIÓN ===
            if risk_state["last_balance"] is not None:
                if total_balance < risk_state["last_balance"]:
                    risk_state["consecutive_losses"] += 1
                    print(f"📉 Pérdida detectada. Consecutivas: {risk_state['consecutive_losses']}")
                else:
                    risk_state["consecutive_losses"] = 0
                    print("📈 Ganancia detectada. Reset de consecutivas.")

            # ✅ EVENTO FINAL
            final_payload = {
                "status": "completed",
                "alert": last_alert,
                "events": event_pipeline,
                "summary": {
                    "balance": total_balance,
                    "side": last_alert["side"],
                    "amount": last_alert["amount"],
                    "tp": last_alert.get("tp_price"),
                    "sl": last_alert.get("sl_price")
                }
            }

            print("📦 FINAL PAYLOAD:", final_payload)

            # 🚀 Enviar a Azure
            requests.post(AZURE_FUNCTION_URL,json=final_payload)

            risk_state["last_balance"] = total_balance

            event_pipeline.clear()

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