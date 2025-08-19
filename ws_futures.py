# ws_futures.py (전체 교체본)
import json, threading, time
from collections import defaultdict, deque
from queue import Queue
import pandas as pd

try:
    import websocket  # pip install websocket-client
except ImportError:
    websocket = None

WS_URL = "wss://contract.mexc.com/edge"

# 5분봉 마감(confirm) 이벤트 큐
EVENTS = Queue(maxsize=10000)

# interval → milliseconds
INTERVAL_MS = {
    "Min1": 60_000,
    "Min5": 300_000,
    "Min15": 900_000,
    "Min30": 1_800_000,
    "Min60": 3_600_000,
    "Hour4": 14_400_000,
    "Hour8": 28_800_000,
    "Day1": 86_400_000,
    "Week1": 604_800_000,
    "Month1": 2_592_000_000,  # 대략치
}

class CandleStore:
    """심볼×인터벌별 최근 캔들을 메모리에 보관 (확정봉 여부까지 포함)."""
    def __init__(self, maxlen=600):
        self.lock = threading.Lock()
        self.buffers = defaultdict(lambda: deque(maxlen=maxlen))  # key=(symbol, interval)

    def upsert(self, symbol: str, interval: str, kline: dict):
        """
        kline 예(MEXC): {
          "t": 1587448800,      # 윈도우 시작(초) ← ms로 변환 필요
          "o": 6894.5, "h": 6910.5, "l": 6885, "c": 6885,
          "q": 1611754,         # 총 거래량 (volume)
          "interval": "Min60", "symbol": "BTC_USDT"
        }
        """
        try:
            t = int(kline.get("t") or kline.get("ts"))
            if t < 10_000_000_000:  # seconds → ms
                t *= 1000
            o = float(kline.get("o"))
            h = float(kline.get("h"))
            l = float(kline.get("l"))
            c = float(kline.get("c"))
            v = float(kline.get("v") if kline.get("v") is not None else kline.get("q"))  # ✅ q 매핑
        except Exception:
            return
        # 마감 여부는 여기선 안 박고, get_df에서 필터링 없이 리턴 (이벤트는 별도 판정)
        row = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
        with self.lock:
            buf = self.buffers[(symbol, interval)]
            for i in range(len(buf)-1, -1, -1):
                if buf[i]["t"] == t:
                    buf[i] = row
                    break
            else:
                buf.append(row)

    def get_df(self, symbol: str, interval: str, limit: int = 150) -> pd.DataFrame | None:
        with self.lock:
            arr = list(self.buffers[(symbol, interval)])[-limit:]
        if not arr:
            return None
        df = pd.DataFrame(arr)
        df["ts"] = pd.to_datetime(df["t"], unit="ms")
        df = df.set_index("ts")[["o","h","l","c","v"]].rename(
            columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"}
        )
        return df

STORE = CandleStore()

class FuturesWS(threading.Thread):
    """
    MEXC 선물 WS: sub.kline 구독 → STORE 업데이트 & 5분봉 '시간기반' 마감 이벤트 큐잉.
      - ✅ TCP ping 비활성화 (ping_interval=0), 10초 주기 앱 ping/pong
      - ✅ 확정봉: server_ts(또는 local) ≥ open_t + interval_ms → closed
      - ✅ v 대신 q를 volume으로 사용, t(초)를 ms로 변환
    """
    def __init__(self, symbols, intervals):
        super().__init__(daemon=True)
        self.symbols = symbols
        self.intervals = intervals
        self.ws = None
        self.running = True
        self._hb_thread = None
        self._closed_once = set()  # (symbol, interval, open_t_ms) 중복 방지

    def run(self):
        if websocket is None:
            print("⚠️ websocket-client 미설치: WS 비활성화(REST만 사용).", flush=True)
            return

        backoff = 3
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )
                # ✅ TCP ping 끄고(App ping만 사용)
                self.ws.run_forever(ping_interval=0)
                backoff = min(backoff + 3, 30)
                print(f"WS 재연결 대기 {backoff}s", flush=True)
            except Exception as e:
                print(f"WS 재연결 예외: {e}", flush=True)
                backoff = min(backoff + 3, 30)
            time.sleep(backoff)

    def stop(self):
        self.running = False
        try:
            if self.ws:
                self.ws.close()
        except:
            pass

    def on_open(self, ws):
        print("🔌 WS 연결됨: 선물 kline 구독 시작", flush=True)
        for s in self.symbols:
            fs = s.replace("USDT", "_USDT")
            for iv in self.intervals:
                sub = {"method": "sub.kline", "param": {"symbol": fs, "interval": iv}}
                try:
                    ws.send(json.dumps(sub))
                except Exception as e:
                    print(f"구독 전송 실패: {s} {iv} → {e}", flush=True)
                time.sleep(0.05)

        # 앱 레벨 heartbeat (10초 간격 ping)
        def heartbeat():
            while self.running and self.ws is ws:
                try:
                    ws.send(json.dumps({"method": "ping"}))
                except Exception as e:
                    print(f"HB 전송 실패: {e}", flush=True)
                    return
                time.sleep(10)
        self._hb_thread = threading.Thread(target=heartbeat, daemon=True)
        self._hb_thread.start()

    def on_message(self, ws, msg):
        try:
            data = json.loads(msg)
        except Exception:
            return

        # 서버 pong
        if isinstance(data, dict) and data.get("channel") == "pong":
            return

        # 서버 ping → pong
        if isinstance(data, dict) and ("ping" in data or data.get("method") == "ping"):
            try:
                ws.send(json.dumps({"method": "pong"}))
            except:
                pass
            return

        ch = data.get("channel") or data.get("method") or ""
        if "kline" in ch and "data" in data:
            server_ts_ms = int(data.get("ts") or 0)  # ms (문서 예시 기준)
            payload = data["data"]
            if isinstance(payload, list):
                for item in payload:
                    self._ingest(item, server_ts_ms)
            elif isinstance(payload, dict):
                self._ingest(payload, server_ts_ms)

    def on_error(self, ws, err):
        print(f"WS 오류: {err}", flush=True)

    def on_close(self, ws, code, msg):
        print(f"WS 종료: code={code}, msg={msg}", flush=True)

    # ---------------------------
    # 내부 처리
    # ---------------------------
    def _ingest(self, k: dict, server_ts_ms: int):
        try:
            fsym = k.get("symbol") or k.get("S")        # BTC_USDT
            interval = k.get("interval") or k.get("i")  # Min5, Min15...
            if not fsym or not interval:
                return
            symbol = fsym.replace("_USDT", "USDT")

            # 버퍼 반영 (초→ms, q→v 매핑은 CandleStore에서 처리)
            STORE.upsert(symbol, interval, k)

            # === 확정봉 판정 (시간기반) ===
            open_t = int(k.get("t") or 0)
            open_ms = open_t * 1000 if open_t < 10_000_000_000 else open_t
            int_ms = INTERVAL_MS.get(interval, 300_000)  # 기본 5m
            now_ms = server_ts_ms if server_ts_ms else int(time.time() * 1000)

            # 마감 판정: 이제 시간이 캔들 윈도우를 초과했는가?
            if now_ms >= open_ms + int_ms - 1500:  # 1.5s 여유
                key = (symbol, interval, open_ms)
                if key not in self._closed_once:
                    self._closed_once.add(key)
                    # 이벤트 큐 적재
                    try:
                        EVENTS.put((symbol, interval, open_ms), timeout=0.05)
                        print(f"📦 확정봉 감지 → 이벤트 큐 적재: {symbol} {interval} @{open_ms}", flush=True)
                    except:
                        print("⚠️ 이벤트 큐가 가득 차 드랍됨", flush=True)
        except Exception as e:
            print(f"_ingest 예외: {e}", flush=True)

# 외부 접근자
def get_ws_df(symbol: str, interval_name: str, limit: int = 150):
    return STORE.get_df(symbol, interval_name, limit)

def get_event_queue():
    return EVENTS
