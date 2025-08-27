# analyzer.py
import time, math
import pandas as pd
from strategy import multi_frame_signal
from config import SYMBOLS, SL_PCT, TP_PCT, format_price, SIGMOID_A, SIGMOID_C, P_THRESHOLD
from notifier import send_telegram
from simulator import add_virtual_trade
from http_client import SESSION
from ws_futures import get_ws_df

FUTURES_BASE = "https://contract.mexc.com"

def _map_interval(iv: str) -> str:
    return {"1m":"Min1","5m":"Min5","15m":"Min15","30m":"Min30","1h":"Min60"}.get(iv, "Min5")

def fetch_ohlcv(symbol: str, interval: str, limit: int = 150) -> pd.DataFrame:
    ws_iv = _map_interval(interval)
    df_ws = get_ws_df(symbol, ws_iv, limit)
    if df_ws is not None and len(df_ws) >= 30:
        return df_ws
    fsym = symbol.replace("USDT", "_USDT"); kline_interval = _map_interval(interval)
    last_err = None
    for _ in range(2):
        try:
            r = SESSION.get(f"{FUTURES_BASE}/api/v1/contract/kline/{fsym}",
                            params={"interval": kline_interval}, timeout=8)
            r.raise_for_status()
            raw = r.json().get("data", [])
            if raw:
                df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume","turnover"])
                for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
                df["ts"]=pd.to_datetime(df["ts"], unit="ms"); return df.set_index("ts")
            last_err="empty-data"
        except Exception as e:
            last_err=str(e)
        time.sleep(0.2)
    raise ValueError(f"{symbol} 선물 K라인 데이터 없음 (interval={kline_interval}, err={last_err})")

def analyze_multi_tf(symbol: str):
    print(f"🔍 멀티프레임 전략 분석 시작: {symbol}", flush=True)
    t0 = time.perf_counter()
    df_30 = fetch_ohlcv(symbol, "30m", 150)
    df_15 = fetch_ohlcv(symbol, "15m", 150)
    df_5  = fetch_ohlcv(symbol,  "5m", 150)
    df_1  = fetch_ohlcv(symbol,  "1m", 150)
    print(f"⏱️ 데이터 수집 {symbol}: {time.perf_counter()-t0:.2f}s", flush=True)

    t1 = time.perf_counter()
    direction, detail = multi_frame_signal(df_30, df_15, df_5, df_1)
    print(f"⏱️ 시그널 계산 {symbol}: {time.perf_counter()-t1:.2f}s", flush=True)

    # NONE/데이터부족 차단
    if direction == "NONE" or (isinstance(detail, dict) and detail.get("reason") == "insufficient_data"):
        print(f"📭 {symbol} 전략 신호 없음 (reason={detail.get('reason') if isinstance(detail, dict) else None})", flush=True)
        print(f"✅ {symbol} 전략 분석 완료", flush=True)
        return None

    # p-컷(원래 기준 복구)
    raw = float(detail.get("raw", 0.0)) if isinstance(detail, dict) else 0.0
    p = 1.0 / (1.0 + math.exp(-SIGMOID_A * (raw - SIGMOID_C)))
    if p < P_THRESHOLD:
        print(f"🚫 컷 미달: raw={raw:.2f}, p={p:.3f} < {P_THRESHOLD}", flush=True)
        print(f"✅ {symbol} 전략 분석 완료", flush=True)
        return None

    price = df_5["close"].iloc[-1]

    # strategy 제공 SL/TP 우선 사용, 없으면 백업 규칙(퍼센트)
    sl = detail.get("sl"); tp = detail.get("tp")
    if sl is None or tp is None or (isinstance(sl, float) and math.isnan(sl)) or (isinstance(tp, float) and math.isnan(tp)):
        if direction == "LONG":
            sl = price * (1 - SL_PCT); tp = price * (1 + TP_PCT)
        else:
            sl = price * (1 + SL_PCT); tp = price * (1 - TP_PCT)

    entry = {"symbol": symbol, "direction": direction, "entry": float(price),
             "tp": float(tp), "sl": float(sl), "score": 0}
    add_virtual_trade(entry)

    msg = (
        f"📊 멀티프레임: {symbol}\n"
        f"🧭 방향: {direction} ({detail})\n"
        f"💵 진입: ${format_price(price)}\n"
        f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
    )
    send_telegram(msg)
    print(f"✅ {symbol} 전략 분석 완료", flush=True)
    return msg
