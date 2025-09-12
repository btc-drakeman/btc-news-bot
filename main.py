from flask import Flask, jsonify
from threading import Thread
import threading
import time, datetime
import queue

from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS, WS_INTERVALS
from analyzer import analyze_multi_tf
from simulator import check_positions
from ws_futures import FuturesWS, get_event_queue
from prebreakout import prebreakout_loop  # 사용 안 하려면 아래 ENABLE_PREBREAKOUT=False 로 꺼도 됨

# ====== 런타임 상태 ======
app = Flask(__name__)
START_TS = time.time()
HEARTBEAT = {}            # {"event": ts, "strategy": ts, "monitor": ts, "prebreakout": ts, "ws": ts}
THREADS = {}              # {"event": Thread, "strategy": Thread, ...}
THREAD_FACTORIES = {}     # 재시작용 팩토리
HEARTBEAT_LOCK = threading.Lock()

# 옵션: 프리브레이크아웃 루프 켜기/끄기
ENABLE_PREBREAKOUT = False   # 필요 없다면 False 로

# 하트비트 갱신
def beat(name: str):
    with HEARTBEAT_LOCK:
        HEARTBEAT[name] = time.time()

def last_beat(name: str) -> float:
    with HEARTBEAT_LOCK:
        return HEARTBEAT.get(name, 0.0)

def safe_sleep(sec: float):
    # 짧게 나눠 자면서 KeyboardInterrupt 등 신호 대응성 확보
    end = time.time() + sec
    while time.time() < end:
        time.sleep(min(0.25, end - time.time()))

# ====== 워커 구현 ======
def strategy_worker():
    print("🚦 평균회귀 전략 루프 시작")
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
                        print(f"❌ analyze_multi_tf({symbol}) 실패: {e}", flush=True)
            beat("strategy")
            safe_sleep(1.0)
        except Exception as e:
            print(f"[strategy] 루프 에러: {e}", flush=True)
            safe_sleep(5.0)  # 잠깐 쉬고 자동 재시작

def event_worker():
    print("⚡ 이벤트 기반 분석 루프 시작", flush=True)
    q = get_event_queue()
    last_seen = {}  # (symbol, interval) -> last_closed_ts
    while True:
        try:
            try:
                # 블로킹 타임아웃으로 영구 정지 방지
                item = q.get(timeout=20)
            except queue.Empty:
                beat("event")
                continue

            symbol, interval, ts = item

            # 5분봉만 처리
            if interval != "Min5":
                beat("event")
                continue

            key = (symbol, interval)
            if last_seen.get(key) == ts:
                beat("event")
                continue
            last_seen[key] = ts

            analyze_multi_tf(symbol)  # 5분봉 마감 즉시 분석
            beat("event")
        except Exception as e:
            print(f"[event] 루프 에러: {e}", flush=True)
            safe_sleep(1.0)

def monitor_worker():
    print("💹 포지션 모니터링 루프 시작")
    # check_positions() 가 내부 루프일 수도 있어 방어적으로 감싸기
    while True:
        try:
            check_positions()
            beat("monitor")
            safe_sleep(1.0)
        except Exception as e:
            print(f"[monitor] 루프 에러: {e}", flush=True)
            safe_sleep(3.0)

def prebreakout_worker():
    print("🔭 프리-브레이크아웃 루프 시작 (wrapper)")
    # 내부에 while True 가 있으므로 예외 시 밖에서 재시작됨
    try:
        prebreakout_loop(sleep_sec=60)
    except Exception as e:
        print(f"[prebreakout] 종료/에러: {e}", flush=True)
    finally:
        # 하트비트가 끊기면 워치독이 재시작
        pass

# ====== WS 스레드 관리 ======
def start_ws() -> Thread:
    t = FuturesWS(SYMBOLS, WS_INTERVALS)
    t.daemon = True
    t.start()
    # 간단 WS 하트비트: 스레드가 살아 있으면 beat
    def ws_heartbeat():
        while t.is_alive():
            beat("ws")
            safe_sleep(5.0)
    hb = Thread(target=ws_heartbeat, daemon=True)
    hb.start()
    return t

# ====== 스레드 시작/팩토리 ======
def start_thread(name: str, target, *args, **kwargs) -> Thread:
    th = Thread(target=target, args=args, kwargs=kwargs, daemon=True, name=name)
    th.start()
    THREADS[name] = th
    return th

def register_factory(name: str, factory):
    THREAD_FACTORIES[name] = factory

# ====== 워치독 ======
def watchdog_worker():
    print("🛡️ 워치독 시작")
    while True:
        try:
            now = time.time()

            # 1) WS 스레드 체크
            ws_th = THREADS.get("ws")
            if (ws_th is None) or (not ws_th.is_alive()) or (now - last_beat("ws") > 30):
                print("🔁 WS 재시작 시도...", flush=True)
                try:
                    THREADS["ws"] = THREAD_FACTORIES["ws"]()
                    beat("ws")
                except Exception as e:
                    print(f"[watchdog] WS 재시작 실패: {e}", flush=True)

            # 2) 이벤트 루프 체크 (최근 120초 이내 하트비트 없으면 재시작)
            if now - last_beat("event") > 120:
                print("🔁 event 루프 재시작 시도...", flush=True)
                try:
                    THREADS["event"] = THREAD_FACTORIES["event"]()
                    beat("event")
                except Exception as e:
                    print(f"[watchdog] event 재시작 실패: {e}", flush=True)

            # 3) 전략 루프 체크 (주기*2 초 이상 정지 시 재시작)
            if now - last_beat("strategy") > max(STRATEGY_INTERVAL_SECONDS * 2, 180):
                print("🔁 strategy 루프 재시작 시도...", flush=True)
                try:
                    THREADS["strategy"] = THREAD_FACTORIES["strategy"]()
                    beat("strategy")
                except Exception as e:
                    print(f"[watchdog] strategy 재시작 실패: {e}", flush=True)

            # 4) 모니터 루프 체크 (120초 이상 정지 시 재시작)
            if now - last_beat("monitor") > 120:
                print("🔁 monitor 루프 재시작 시도...", flush=True)
                try:
                    THREADS["monitor"] = THREAD_FACTORIES["monitor"]()
                    beat("monitor")
                except Exception as e:
                    print(f"[watchdog] monitor 재시작 실패: {e}", flush=True)

            # 5) 프리브레이크 (선택)
            if ENABLE_PREBREAKOUT and (now - last_beat("prebreakout") > 180):
                # prebreakout_loop 내부 하트비트를 얻기 어렵지만, 스레드 죽었으면 재가동
                th = THREADS.get("prebreakout")
                if (th is None) or (not th.is_alive()):
                    print("🔁 prebreakout 루프 재시작 시도...", flush=True)
                    try:
                        THREADS["prebreakout"] = THREAD_FACTORIES["prebreakout"]()
                        beat("prebreakout")
                    except Exception as e:
                        print(f"[watchdog] prebreakout 재시작 실패: {e}", flush=True)

            safe_sleep(5.0)
        except Exception as e:
            print(f"[watchdog] 에러: {e}", flush=True)
            safe_sleep(3.0)

# ====== HTTP 라우트 ======
@app.route("/")
def home():
    return "🟢 Bot running"

@app.route("/health")
def health():
    now = time.time()
    uptime = int(now - START_TS)
    with HEARTBEAT_LOCK:
        hb = {k: round(now - v, 1) for k, v in HEARTBEAT.items()}
    threads = {k: (v.is_alive() if isinstance(v, Thread) else False) for k, v in THREADS.items()}
    return jsonify({
        "status": "ok",
        "uptime_sec": uptime,
        "heartbeat_age_sec": hb,        # 각 워커 최근 하트비트로부터 경과시간(초)
        "threads_alive": threads,       # 스레드 살아있는지
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    })

# ====== 부트스트랩 ======
if __name__ == '__main__':
    # WS
    def ws_factory():
        return start_ws()
    register_factory("ws", ws_factory)
    THREADS["ws"] = ws_factory()
    time.sleep(2)

    # Event
    def event_factory():
        return start_thread("event", event_worker)
    register_factory("event", event_factory)
    THREADS["event"] = event_factory()

    # Strategy
    def strategy_factory():
        return start_thread("strategy", strategy_worker)
    register_factory("strategy", strategy_factory)
    THREADS["strategy"] = strategy_factory()

    # Monitor
    def monitor_factory():
        return start_thread("monitor", monitor_worker)
    register_factory("monitor", monitor_factory)
    THREADS["monitor"] = monitor_factory()

    # Prebreakout (선택)
    if ENABLE_PREBREAKOUT:
        def prebreakout_factory():
            return start_thread("prebreakout", prebreakout_worker)
        register_factory("prebreakout", prebreakout_factory)
        THREADS["prebreakout"] = prebreakout_factory()

    # Watchdog
    def watchdog_factory():
        return start_thread("watchdog", watchdog_worker)
    THREADS["watchdog"] = watchdog_factory()

    # Flask
    app.run(host='0.0.0.0', port=8080)
