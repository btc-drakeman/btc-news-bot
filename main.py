from flask import Flask, request
from threading import Thread
from datetime import datetime
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram
import time

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 MEXC 기술 분석 봇 실행 중"

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"🌀 루프 진입: {symbol}")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            else:
                print(f"⚠️ {symbol} 분석 실패 (데이터 부족 또는 계산 오류)")
            time.sleep(3)  # 각 심볼 사이 짧은 대기

        time.sleep(900)  # 전체 심볼 분석 후 15분 대기

if __name__ == '__main__':
    print("🟢 기술 분석 봇 실행 시작")
    thread = Thread(target=analysis_loop)
    thread.start()
    app.run(host='0.0.0.0', port=8080)
