# -*- coding: utf-8 -*-
from flask import Flask, request
import hashlib
import json
import time
import hmac
from urllib.parse import urlparse, urlencode
import env
import os

import requests

app = Flask(__name__)


API_KEY = "ACCESS_ID"  # Replace with your access id
API_SECRET = "SECRET_KEY"  # Replace with your secret key


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
        self.url = "wss://socket.coinex.com/v2/futures"
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


def get_futures_market():
    request_path = "/futures/market"
    params = {"market": "BTCUSDT"}
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response


def get_futures_balance():
    request_path = "/assets/futures/balance"
    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
    )
    return response


def get_deposit_address():
    request_path = "/assets/deposit-address"
    params = {"ccy": "USDT", "chain": "CSC"}

    response = request_client.request(
        "GET",
        "{url}{request_path}".format(url=request_client.url, request_path=request_path),
        params=params,
    )
    return response


def put_limit():
    request_path = "/futures/order"
    data = {
        "market": "BTCUSDT",
        "market_type": "FUTUREs",
        "side": "buy",
        "type": "market",
        "amount": "10000",
        "price": "1",
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


def run_code():
    try:
        response_1 = get_futures_market().json()
        print(response_1)

        response_2 = get_futures_balance().json()
        print(response_2)

        response_3 = get_deposit_address().json()
        print(response_3)

        response_4 = put_limit().json()
        print(response_4)

    except Exception as e:
        print("Error:" + str(e))
        time.sleep(3)
        run_code()

def send_order(market, side, amount, price):
    url = "ss://socket.coinex.com/v2/futures"  # Ajusta la URL
    params = {
        "market": market,
        "type": side,
        "amount": str(amount),
        "price": str(price),
        "access_id": API_KEY,
        "tonce": str(int(time.time() * 1000))
    }
    query_string = urlencode(params)
    
    sign = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": sign
    }
    
    response = requests.post(url, json=params, headers=headers)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Alerta recibida:", data)

    # Extrae los datos de TradingView
    market = data.get("market", "BTCUSDT")
    market_type = data.get("market_type", "FUTURES")
    side = data.get("side", "buy")  # "buy" o "sell"
    amount = data.get("amount", 0.01)
    price = data.get("price", 50000)
    time = data.get("time", "00:00")

    # Envía la orden a CoinEx
    response = send_order(market, side, amount, price)
    return {"status": "success", "data": response}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    run_code()
    app.run(host='0.0.0.0', port=5000)
    
