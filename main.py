from flask import Flask
from threading import Thread
from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS, WS_INTERVALS   # ← WS_INTERVALS 추가
from analyzer import analyze_multi_tf
from simulator import check_positions
from ws_futures import FuturesWS, get_event_queue  # ← 추가
from prebreakout import prebreakout_loop
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

# === 이벤트 워커 추가 ===
def event_loop():
    print("⚡ 이벤트 기반 분석 루프 시작", flush=True)
    q = get_event_queue()
    last_seen = {}  # (symbol, interval) -> last_closed_ts
    while True:
        try:
            symbol, interval, ts = q.get()

            # 🔒 5분봉만 처리, 나머지(1m 등)는 무시
            if interval != "Min5":
                continue

            key = (symbol, interval)
            if last_seen.get(key) == ts:
                continue
            last_seen[key] = ts

            analyze_multi_tf(symbol)  # 5분봉 마감 즉시 멀티프레임 분석
        except Exception as e:
            print("이벤트 루프 에러:", e, flush=True)
            time.sleep(0.2)

def monitor_price_loop():
    print("💹 포지션 모니터링 루프 시작")
    check_positions()

# === __main__ 아래 시작부에서 WS + 이벤트 워커 스타트 ===
if __name__ == '__main__':
    # 1) WS 시작 + 워밍업
    ws_thread = FuturesWS(SYMBOLS, WS_INTERVALS)
    ws_thread.start()
    time.sleep(2)

    # 2) 이벤트 워커 시작
    t0 = Thread(target=event_loop, daemon=True); t0.start()

    # 3) (선택) 5분 주기 루프는 백업용으로 유지하거나 주기를 늘려도 됨
    t1 = Thread(target=strategy_loop, daemon=True)
    t2 = Thread(target=monitor_price_loop, daemon=True)
    t1.start(); t2.start()
    tX = Thread(target=prebreakout_loop, daemon=True); tX.start()

    app.run(host='0.0.0.0', port=8080)
