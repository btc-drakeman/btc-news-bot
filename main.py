from flask import Flask
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram
import time

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"

def loop():
    while True:
        for symbol in SYMBOLS:
            print(f"🔍 분석 시작: {symbol}")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
        time.sleep(600)  # 10분 간격

if __name__ == '__main__':
    Thread(target=loop).start()
    app.run(host='0.0.0.0', port=8080)
