# main.py

from flask import Flask, request
from threading import Thread
from datetime import datetime
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 MEXC 기술 분석 봇 실행 중"

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"ἰ0 루프 진입: {symbol}")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            else:
                send_telegram(f"⚠️ {symbol} 분석 실패 (데이터 부족 또는 계산 오류)")

if __name__ == '__main__':
    print("🔍 분석 시작: BTCUSDT")
    thread = Thread(target=analysis_loop)
    thread.start()
    app.run(host='0.0.0.0', port=8080)
