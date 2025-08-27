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
    m = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30", "1h": "Min60"}
    return m.get(iv, "Min5")

def fetch_ohlcv(symbol: str, interval: str, limit: int = 150) -> pd.DataFrame:
    # WS 먼저
    ws_iv = _map_interval(interval)
    df_ws = get_ws_df(symbol, ws_iv, limit)
    if df_ws is not None and len(df_ws) >= 30:
        return df_ws

    # REST 폴백
    fsym = symbol.replace("USDT", "_USDT")
    kline_interval = _map_interval(interval)

    last_err = None
    for _ in range(2):
        try:
            r = SESSION.get(
                f"{FUTURES_BASE}/api/v1/contract/kline/{fsym}",
                params={"interval": kline_interval},
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
    # ✅ 추가: 1분 데이터도 로드해서 strategy로 전달 (이전에는 None이라 무조건 insufficient_data)
    df_1  = fetch_ohlcv(symbol,  "1m", 150)
    print(f"⏱️ 데이터 수집 {symbol}: {time.perf_counter()-t0:.2f}s", flush=True)

    t1 = time.perf_counter()
    # ✅ 변경: df_1을 4번째 인자로 전달
    direction, detail = multi_frame_signal(df_30, df_15, df_5, df_1)
    print(f"⏱️ 시그널 계산 {symbol}: {time.perf_counter()-t1:.2f}s", flush=True)

    # ✅ 추가: NONE/데이터부족 알림 차단 (스팸 방지)
    if direction == "NONE" or (isinstance(detail, dict) and detail.get("reason") == "insufficient_data"):
        print(f"📭 {symbol} 전략 신호 없음 (reason={detail.get('reason') if isinstance(detail, dict) else None})", flush=True)
        print(f"✅ {symbol} 전략 분석 완료", flush=True)
        return None

    price = df_5["close"].iloc[-1]

    # LONG/SHORT일 때만 SL/TP 산출
    if direction == "LONG":
        sl = price * (1 - SL_PCT)
        tp = price * (1 + TP_PCT)
    elif direction == "SHORT":
        sl = price * (1 + SL_PCT)
        tp = price * (1 - TP_PCT)
    else:
        # 혹시 모를 예외 방지
        print(f"📭 {symbol} 미지원 방향: {direction}", flush=True)
        print(f"✅ {symbol} 전략 분석 완료", flush=True)
        return None

    entry = {
        "symbol": symbol, "direction": direction, "entry": float(price),
        "tp": float(tp), "sl": float(sl), "score": 0
    }
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
