# ws_futures.py
import json, threading, time
from collections import defaultdict, deque
import pandas as pd

try:
    import websocket  # pip install websocket-client
except ImportError:
    websocket = None

WS_URL = "wss://contract.mexc.com/edge"

class CandleStore:
    """심볼×인터벌별 최근 캔들을 메모리에 보관."""
    def __init__(self, maxlen=600):
        self.lock = threading.Lock()
        self.buffers = defaultdict(lambda: deque(maxlen=maxlen))  # key=(symbol, interval)

    def upsert(self, symbol: str, interval: str, kline: dict):
        """
        kline 예시(메시지 포맷은 서버 측 업데이트에 따라 일부 차이 존재):
        { "t": 1724022000000, "o":"100","h":"101","l":"99","c":"100.5","v":"123.4", "confirm":true }
        """
        try:
            t = int(kline.get("t") or kline.get("ts"))
            o = float(kline.get("o") or kline.get("open"))
            h = float(kline.get("h") or kline.get("high"))
            l = float(kline.get("l") or kline.get("low"))
            c = float(kline.get("c") or kline.get("close"))
            v = float(kline.get("v") or kline.get("volume"))
        except Exception:
            return

        row = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
        with self.lock:
            buf = self.buffers[(symbol, interval)]
            # 같은 타임스탬프 있으면 교체
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
    """MEXC 선물 WS: sub.kline 구독하고 STORE에 반영."""
    def __init__(self, symbols, intervals):
        super().__init__(daemon=True)
        self.symbols = symbols
        self.intervals = intervals
        self.ws = None
        self.running = True

    def run(self):
        if websocket is None:
            print("⚠️ websocket-client 미설치: WS 비활성화(REST만 사용).", flush=True)
            return
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                print(f"WS 재연결 대기: {e}", flush=True)
            time.sleep(3)

    def stop(self):
        self.running = False
        try:
            if self.ws: self.ws.close()
        except: pass

    # --- handlers ---
    def on_open(self, ws):
        print("🔌 WS 연결됨: 선물 kline 구독 시작", flush=True)
        for s in self.symbols:
            fs = s.replace("USDT", "_USDT")
            for iv in self.intervals:
                sub = {"method": "sub.kline", "param": {"symbol": fs, "interval": iv}}
                ws.send(json.dumps(sub))

    def on_message(self, ws, msg):
        try:
            data = json.loads(msg)
        except Exception:
            return
        ch = data.get("channel") or data.get("method") or ""
        # 보통 push.kline 채널로 오며, payload는 dict 또는 list
        if "kline" in ch and "data" in data:
            payload = data["data"]
            if isinstance(payload, list):
                for item in payload:
                    self._ingest(item)
            elif isinstance(payload, dict):
                self._ingest(payload)

    def _ingest(self, item: dict):
        try:
            fsym = item.get("symbol") or item.get("S")  # BTC_USDT
            interval = item.get("interval") or item.get("i")
            k = item.get("kline") or item
            symbol = fsym.replace("_USDT", "USDT")
            STORE.upsert(symbol, interval, k)
        except Exception:
            pass

    def on_error(self, ws, err):
        print(f"WS 오류: {err}", flush=True)

    def on_close(self, ws, code, msg):
        print(f"WS 종료: code={code}, msg={msg}", flush=True)

# 외부 접근용
def get_ws_df(symbol: str, interval_name: str, limit: int = 150):
    return STORE.get_df(symbol, interval_name, limit)
