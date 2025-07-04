# ✅ newsbot.py (최종 — 현물 분석 + 레버리지 손익폭 안내 + 이모지 정리)
import time
from flask import Flask
from threading import Thread
from datetime import datetime

from config import BOT_TOKEN, USER_IDS, API_URL
from newsbot_utils import send_telegram, SYMBOLS, analyze_symbol

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"📊 analyze_symbol() 호출됨: {symbol}")
            try:
                result = analyze_symbol(symbol)
                if result:
                    print(f"📨 텔레그램 전송 메시지:\n{result}")
                    send_telegram(result)
            except Exception as e:
                print(f"❌ 분석 중 오류 발생 ({symbol}): {e}")
            time.sleep(3)
        time.sleep(600)

if __name__ == '__main__':
    print("📡 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080, threaded=True)).start()
    Thread(target=analysis_loop, daemon=True).start()
    while True:
        time.sleep(60)
