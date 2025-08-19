from flask import Flask
from threading import Thread
from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS
from analyzer import analyze_multi_tf
from simulator import check_positions
from strategy_spring import analyze_spring_signal
import time, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 Bot running"

def run_one_symbol(symbol):
    try:
        analyze_multi_tf(symbol)
    except Exception as e:
        print(f"❌ analyze_multi_tf({symbol}) 실패: {e}", flush=True)

MAX_WORKERS = 6
PER_SYMBOL_TIMEOUT = 30

def _run_one_symbol(symbol:str)
     try:
         analyze_multi_tf(symbol)
     except Exception as e:
         print(f"❌ analyze_multi_tf({symbol}) 실패: {e}", flush=True)

def strategy_loop():
    print("🚦 멀티프레임 전략 루프 시작", flush=True)
    last_run = 0
    while True:
        try:
            now = time.time()
            if now - last_run >= STRATEGY_INTERVAL_SECONDS:  # 설정값 사용
                last_run = now
                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                    futures = {ex.submit(run_one_symbol, s): s for s in SYMBOLS}
                    for fut in as_completed(futures):
                        s = futures[fut]
                        try:
                            fut.result(timeout=PER_SYMBOL_TIMEOUT)
                        except Exception as e:
                            print(f"⏰ {s} 타임아웃/중단: {e}", flush=True)
                print(f"🧮 라운드 완료: {time.perf_counter()-t0:.2f}s", flush=True)
            time.sleep(1)
        except Exception as e:
            print("루프 에러:", e, flush=True)
            time.sleep(1)

def spring_strategy_loop():
    print("🌱 스프링 전략 루프 시작", flush=True)
    while True:
        try:
            for symbol in SYMBOLS:
                try:
                    analyze_spring_signal(symbol, "5m", 200)
                except Exception as e:
                    print(f"❌ spring({symbol}) 실패: {e}", flush=True)
            time.sleep(30)
        except Exception as e:
            print("스프링 루프 에러:", e, flush=True)
            time.sleep(1)

def monitor_price_loop():
    print("💹 포지션 모니터링 루프 시작", flush=True)
    check_positions()

if __name__ == '__main__':
    t1 = Thread(target=strategy_loop, daemon=True)
    t2 = Thread(target=monitor_price_loop, daemon=True)
    t3 = Thread(target=spring_strategy_loop, daemon=True)
    t1.start(); t2.start(); t3.start()
    app.run(host='0.0.0.0', port=8080)
