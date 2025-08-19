# ws_futures.py
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


class CandleStore:
    """심볼×인터벌별 최근 캔들을 메모리에 보관 (확정봉 여부까지 포함)."""
    def __init__(self, maxlen=600):
        self.lock = threading.Lock()
        self.buffers = defaultdict(lambda: deque(maxlen=maxlen))  # key=(symbol, interval)

    def upsert(self, symbol: str, interval: str, kline: dict):
        # kline 예: { "t": 1724022000000, "o":"100","h":"101","l":"99","c":"100.5","v":"123.4", "confirm":true }
        try:
            t = int(kline.get("t") or kline.get("ts"))
            o = float(kline.get("o") or kline.get("open"))
            h = float(kline.get("h") or kline.get("high"))
            l = float(kline.get("l") or kline.get("low"))
            c = float(kline.get("c") or kline.get("close"))
            v = float(kline.get("v") or kline.get("volume"))
            x = bool(kline.get("confirm") if "confirm" in kline else kline.get("x", False))  # 확정봉
        except Exception:
            return
        row = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "x": x}
        with self.lock:
            buf = self.buffers[(symbol, interval)]
            for i in range(len(buf)-1, -1, -1):
                if buf[i]["t"] == t:
                    buf[i] = row
                    break
            else:
                buf.append(row)

    def get_df(self, symbol: str, interval: str, limit: int = 150, only_closed: bool = True) -> pd.DataFrame | None:
        with self.lock:
            arr = list(self.buffers[(symbol, interval)])[-limit:]
        if not arr:
            return None
        if only_closed:
            arr = [r for r in arr if r.get("x", False)]  # 확정봉만 사용
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
    MEXC 선물 WS: sub.kline 구독 → STORE 업데이트 & 5분봉 마감 이벤트 큐잉.
    안정화 포인트:
      - TCP ping 비활성화 (ping_interval=0)
      - 10초 주기 앱 레벨 ping 송신
      - ping 수신 시 즉시 pong 응답
      - 지수형 백오프 재연결
    """
    def __init__(self, symbols, intervals):
        super().__init__(daemon=True)
        self.symbols = symbols
        self.intervals = intervals
        self.ws = None
        self.running = True
        self._hb_thread = None

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
                # 정상 종료 또는 예외 후 재연결 대기
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

    # ---------------------------
    # WS 콜백
    # ---------------------------
    def on_open(self, ws):
        print("🔌 WS 연결됨: 선물 kline 구독 시작", flush=True)
        # 구독
        for s in self.symbols:
            fs = s.replace("USDT", "_USDT")
            for iv in self.intervals:
                sub = {"method": "sub.kline", "param": {"symbol": fs, "interval": iv}}
                try:
                    ws.send(json.dumps(sub))
                except Exception as e:
                    print(f"구독 전송 실패: {s} {iv} → {e}", flush=True)
                time.sleep(0.06)

        # ✅ 앱 레벨 heartbeat 시작 (10초 간격 ping)
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
        # 메시지 파싱
        try:
            data = json.loads(msg)
        except Exception:
            return

        # ✅ 서버 ping → 즉시 pong
        if isinstance(data, dict) and ("ping" in data or data.get("method") == "ping"):
            try:
                ws.send(json.dumps({"method": "pong"}))
            except:
                pass
            return

        # ✅ 서버 pong 가시화(필요시 주석 해제)
        if isinstance(data, dict) and data.get("method") == "pong":
            # print("↔️ pong 수신", flush=True)
            return

        ch = data.get("channel") or data.get("method") or ""
        if "kline" in ch and "data" in data:
            payload = data["data"]
            if isinstance(payload, list):
                # print(f"📥 kline 수신 {len(payload)}개", flush=True)
                for item in payload:
                    self._ingest(item)
            elif isinstance(payload, dict):
                # print("📥 kline 수신 1개", flush=True)
                self._ingest(payload)

    def on_error(self, ws, err):
        print(f"WS 오류: {err}", flush=True)

    def on_close(self, ws, code, msg):
        print(f"WS 종료: code={code}, msg={msg}", flush=True)

    # ---------------------------
    # 내부 처리
    # ---------------------------
    def _ingest(self, item: dict):
        try:
            fsym = item.get("symbol") or item.get("S")        # BTC_USDT
            interval = item.get("interval") or item.get("i")  # Min5, Min15...
            k = item.get("kline") or item                     # kline payload

            if not fsym or not interval or not k:
                return

            symbol = fsym.replace("_USDT", "USDT")
            STORE.upsert(symbol, interval, k)

            # 5분봉 마감 시 이벤트 큐 적재
            is_closed = bool(k.get("confirm") if "confirm" in k else k.get("x", False))
            if interval == "Min5" and is_closed:
                ts = int(k.get("t") or k.get("ts") or 0)
                try:
                    EVENTS.put((symbol, interval, ts), timeout=0.01)
                except:
                    # 큐가 가득 찬 경우 드랍
                    pass
        except Exception:
            pass


# 외부 접근자
def get_ws_df(symbol: str, interval_name: str, limit: int = 150, only_closed: bool = True):
    return STORE.get_df(symbol, interval_name, limit, only_closed)

def get_event_queue():
    return EVENTS
