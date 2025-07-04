# main.py

from flask import Flask
from threading import Thread
import time
from config import SYMBOLS
from analyzer import analyze_symbol

app = Flask(__name__)

@app.route('/')
def index():
    return "🚀 Crypto Analyzer Bot is running."

# 기술 분석 루프
def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"🌀 루프 진입: {symbol}")  # ✅ 루프 확인용 로그
            analyze_symbol(symbol)
            time.sleep(3)
        time.sleep(600)


if __name__ == "__main__":
    # Flask 서버 + 분석 루프 병렬 실행
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop, daemon=True).start()

    # 메인 스레드는 유휴 상태 유지
    while True:
        time.sleep(60)
