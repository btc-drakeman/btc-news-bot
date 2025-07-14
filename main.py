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
            try:
                print(f"\n🔍 분석 시작: {symbol}")
                result = analyze_symbol(symbol)
                if result:
                    if isinstance(result, list):
                        for msg in result:
                            send_telegram(msg)
                    else:
                        send_telegram(result)
                print(f"✅ {symbol} 분석 완료")
            except Exception as e:
                print(f"❌ {symbol} 분석 중 오류 발생: {e}")
        time.sleep(900)  # 15분 간격

if __name__ == '__main__':
    Thread(target=loop, daemon=True).start()  # 백그라운드 스레드 실행
    app.run(host='0.0.0.0', port=8080)
