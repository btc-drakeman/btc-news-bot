# analyzer.py

import requests
import pandas as pd
import time
from strategy import multi_frame_signal
from config import SYMBOLS, SL_PCT, TP_PCT, format_price
from notifier import send_telegram
from simulator import add_virtual_trade
from http_client import SESSION
from ws_futures import get_ws_df

FUTURES_BASE = "https://contract.mexc.com"

def _map_interval(iv: str) -> str:
    # REST/WS 공통 명칭
    m = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30", "1h": "Min60"}
    return m.get(iv, "Min5")

def fetch_ohlcv(symbol: str, interval: str, limit: int = 150) -> pd.DataFrame:
    """
    1) WS 버퍼 우선 사용(확정봉만)
    2) 부족하면 선물 REST 폴백
       * 중요: 파라미터 이름은 'interval' (이전 'type' → ❌)
       * limit 파라미터는 미지원이라 제거 (start/end 미지정 시 최근 2000개 반환)
    """
    # WS 먼저
    ws_iv = _map_interval(interval)
    df_ws = get_ws_df(symbol, ws_iv, limit)
    if df_ws is not None and len(df_ws) >= 30:
        return df_ws

    # REST 폴백
    fsym = symbol.replace("USDT", "_USDT")
    kline_interval = _map_interval(interval)

    # 재시도(가벼운) – API가 가끔 빈 data를 줄 때 방어
    last_err = None
    for _ in range(2):
        try:
            r = SESSION.get(
                f"{FUTURES_BASE}/api/v1/contract/kline/{fsym}",
                params={"interval": kline_interval},  # ✅ 'interval' 사용, limit 제거
                timeout=8
            )
            r.raise_for_status()
            raw = r.json().get("data", [])
            if raw:
                df = pd.DataFrame(raw, columns=[
                    "ts", "open", "high", "low", "close", "volume", "turnover"
                ])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)
                df["ts"] = pd.to_datetime(df["ts"], unit="ms")
                return df.set_index("ts")
            last_err = "empty-data"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.2)

    raise ValueError(f"{symbol} 선물 K라인 데이터 없음 (interval={kline_interval}, err={last_err})")

def analyze_multi_tf(symbol: str):
    print(f"🔍 멀티프레임 전략 분석 시작: {symbol}", flush=True)
    t0 = time.perf_counter()
    df_30 = fetch_ohlcv(symbol, "30m", 150)
    df_15 = fetch_ohlcv(symbol, "15m", 150)
    df_5  = fetch_ohlcv(symbol,  "5m", 150)
    print(f"⏱️ 데이터 수집 {symbol}: {time.perf_counter()-t0:.2f}s", flush=True)

    t1 = time.perf_counter()
    signal = multi_frame_signal(df_30, df_15, df_5, symbol=symbol)
    print(f"⏱️ 시그널 계산 {symbol}: {time.perf_counter()-t1:.2f}s", flush=True)

    if signal == (None, None):
        print(f"📭 {symbol} 전략 신호 없음", flush=True)
        print(f"✅ {symbol} 전략 분석 완료", flush=True)
        return None

    direction, detail = signal
    price = df_5["close"].iloc[-1]

    if direction == "LONG":
        sl = price * (1 - SL_PCT)
        tp = price * (1 + TP_PCT)
    else:
        sl = price * (1 + SL_PCT)
        tp = price * (1 - TP_PCT)

    entry = {
        "symbol": symbol, "direction": direction, "entry": float(price),
        "tp": float(tp), "sl": float(sl), "score": 0
    }
    add_virtual_trade(entry)

    # detail 안에 p/raw/조건 요약 포함됨
    msg = (
        f"📊 멀티프레임: {symbol}\n"
        f"🧭 방향: {direction} ({detail})\n"
        f"💵 진입: ${format_price(price)}\n"
        f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
    )
    send_telegram(msg)
    print(f"✅ {symbol} 전략 분석 완료", flush=True)
    return msg
