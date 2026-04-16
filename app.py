import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

TOKEN = os.environ.get("8656831052:AAEIniFQa5dTA3GTAPMhepC4Y5iHTde4idg")
CHAT_ID = os.environ.get("7505401062")

EXCLUDED = {
    "BTC", "ETH", "SOL", "XRP", "DOGE",
    "BNB", "ADA", "TRX", "LINK", "LTC"
}

last_alert_time = {}

def send_telegram(msg):
    if not TOKEN or not CHAT_ID:
        print("텔레그램 환경변수 없음")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
        print("텔레그램:", r.status_code, r.text)
    except Exception as e:
        print("텔레그램 오류:", e)

def get_spot_symbols():
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    data = requests.get(url, timeout=10).json()

    spot_map = {}
    for s in data["symbols"]:
        symbol = s["symbol"]

        if not symbol.endswith("USDT"):
            continue

        base = s.get("baseAsset", symbol[:-4])
        if base in EXCLUDED:
            continue

        status = str(s.get("status", ""))
        if status not in {"1", "ENABLED", "TRADING"}:
            continue

        spot_map[base] = symbol

    return spot_map

def get_futures_bases():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    data = requests.get(url, timeout=10).json()

    futures = set()
    for c in data.get("data", []):
        if c.get("quoteCoin") == "USDT" and c.get("settleCoin") == "USDT":
            base = c.get("baseCoin")
            if base and base not in EXCLUDED:
                futures.add(base)

    return futures

def get_top_symbols(n=50):
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=10).json()

    sorted_symbols = sorted(
        data,
        key=lambda x: float(x["quoteVolume"]),
        reverse=True
    )

    return [x["symbol"] for x in sorted_symbols[:n]]

def get_final_symbols():
    spot = get_spot_symbols()
    futures = get_futures_bases()
    top = set(get_top_symbols(50))

    final = []
    for base, symbol in spot.items():
        if base in futures and symbol in top:
            final.append(symbol)

    return final[:15]

def get_kline(symbol):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit=30"
    return requests.get(url, timeout=10).json()

def check_signal(symbol):
    try:
        data = get_kline(symbol)

        if not isinstance(data, list) or len(data) < 5:
            return

        volumes = [float(x[5]) for x in data]
        prices = [float(x[4]) for x in data]

        recent_vol = volumes[-1]
        prev_vol = volumes[-2]
        avg_vol = sum(volumes[:-1]) / len(volumes[:-1])
        price_change = (prices[-1] - prices[-2]) / prices[-2] * 100

        print(f"{symbol} | {price_change:.2f}%")

        if avg_vol <= 0:
            return

        # 필요하면 여기 숫자 튜닝
        is_signal = (
            recent_vol > avg_vol * 2
            and recent_vol > prev_vol
            and price_change > 0.7
        )

        if not is_signal:
            return

        now = time.time()
        if symbol in last_alert_time and now - last_alert_time[symbol] < 600:
            return

        last_alert_time[symbol] = now

        send_telegram(
            f"{symbol} 🚀 급등 감지\n"
            f"1분 변동률: {price_change:.2f}%\n"
            f"최근 거래량: {recent_vol:.2f}\n"
            f"평균 거래량: {avg_vol:.2f}"
        )

    except Exception as e:
        print(symbol, "오류:", e)

def detect_loop():
    while True:
        try:
            symbols = get_final_symbols()
            print("최종 감시 종목:", symbols)

            for s in symbols:
                check_signal(s)
                time.sleep(0.2)

            print("한 바퀴 끝 -> 60초 대기")
            time.sleep(60)

        except Exception as e:
            print("detect_loop 오류:", e)
            time.sleep(30)

@app.route("/")
def home():
    return "bot is running", 200

@app.route("/health")
def health():
    return "ok", 200

def start_background_loop():
    thread = threading.Thread(target=detect_loop, daemon=True)
    thread.start()

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)