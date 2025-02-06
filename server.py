from flask import Flask, request
import requests
import hmac
import hashlib
import time
import json
import env
import ngrok

app = Flask(__name__)

listener = ngrok.forward(5000, authtoken_from_env=True)

print(f"Ingress established at {listener.url()}")

# Configuración de API CoinEx
API_KEY = "ACCESS_ID"
API_SECRET = "SECRET_KEY"

COINEX_URL = "https://api.coinex.com/v2"

def send_order(market, side, amount, price):
    url = "https://api.coinex.com/v2"
    params = {
        "market": market,
        "type": side,
        "amount": str(amount),
        "price": str(price),
        "access_id": API_KEY,
        "tonce": str(int(time.time() * 1000))
    }
    sorted_params = sorted(params.items())
    query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
    
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
    side = data.get("side", "buy")  # "buy" o "sell"
    amount = data.get("amount", 0.01)
    price = data.get("price", 50000)

    # Envía la orden a CoinEx
    response = send_order(market, side, amount, price)
    return {"status": "success", "data": response}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)