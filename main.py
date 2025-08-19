from flask import Flask
from threading import Thread
from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS, WS_INTERVALS   # ← WS_INTERVALS 추가
from analyzer import analyze_multi_tf
from simulator import check_positions
from strategy_spring import analyze_spring_signal
from ws_futures import FuturesWS   # ← 추가
import time, datetime

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 Bot running"

def strategy_loop():
    print("🚦 멀티프레임 전략 루프 시작")
    last_run = 0
    while True:
        try:
            now = time.time()
            if now - last_run >= STRATEGY_INTERVAL_SECONDS:
                last_run = now
                for symbol in SYMBOLS:
                    try:
                        analyze_multi_tf(symbol)
                    except Exception as e:
                        print(f"❌ analyze_multi_tf({symbol}) 실패: {e}")
            time.sleep(1)
        except Exception as e:
            print("루프 에러:", e)
            time.sleep(1)

def spring_strategy_loop():
    print("🌱 스프링 전략 루프 시작")
    while True:
        try:
            for symbol in SYMBOLS:
                try:
                    analyze_spring_signal(symbol, "5m", 200)
                except Exception as e:
                    print(f"❌ spring({symbol}) 실패: {e}")
            time.sleep(30)
        except Exception as e:
            print("스프링 루프 에러:", e)
            time.sleep(1)

def monitor_price_loop():
    print("💹 포지션 모니터링 루프 시작")
    check_positions()

if __name__ == '__main__':
    # 🔌 선물 WS 먼저 켠다 (데이터 버퍼 쌓이기 시작)
    ws_thread = FuturesWS(SYMBOLS, WS_INTERVALS)
    ws_thread.start()

    t1 = Thread(target=strategy_loop, daemon=True)
    t2 = Thread(target=monitor_price_loop, daemon=True)
    t3 = Thread(target=spring_strategy_loop, daemon=True)
    t1.start(); t2.start(); t3.start()
    app.run(host='0.0.0.0', port=8080)
