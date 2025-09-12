# analyzer.py — Mean Reversion pipeline (cleaned)
# - WS 우선(부족 시 REST) 데이터 수집
# - strategy.multi_frame_signal() 호출 → raw 점수
# - sigmoid p-score 변환 및 컷
# - 텔레그램 알림: 깔끔 포맷
# - 가상 포지션 기록 (simulator.add_virtual_trade)

import time, math
import pandas as pd
from strategy import multi_frame_signal
from config import (
    SYMBOLS, SL_PCT, TP_PCT, format_price,
    SIGMOID_A, SIGMOID_C, P_THRESHOLD
)
from notifier import send_telegram
from simulator import add_virtual_trade
from http_client import SESSION
from ws_futures import get_ws_df

FUTURES_BASE = "https://contract.mexc.com"


# ---------------------------
# Interval 매핑
# ---------------------------
def _map_interval(iv: str) -> str:
    return {
        "1m": "Min1", "5m": "Min5", "15m": "Min15",
        "30m": "Min30", "1h": "Min60"
    }.get(iv, "Min5")


# ---------------------------
# OHLCV 로딩 (WS 우선, REST 폴백)
# ---------------------------
def fetch_ohlcv(symbol: str, interval: str, limit: int = 150) -> pd.DataFrame:
    ws_iv = _map_interval(interval)
    df_ws = get_ws_df(symbol, ws_iv, limit)
    if df_ws is not None and len(df_ws) >= 30:
        return df_ws

    fsym = symbol.replace("USDT", "_USDT")
    kline_interval = _map_interval(interval)
    last_err = None

    for _ in range(2):
        try:
            r = SESSION.get(
                f"{FUTURES_BASE}/api/v1/contract/kline/{fsym}",
                params={"interval": kline_interval}, timeout=8
            )
            r.raise_for_status()
            raw = r.json().get("data", [])
            if raw:
                df = pd.DataFrame(
                    raw, columns=["ts", "open", "high", "low", "close", "volume", "turnover"]
                )
                for c in ["open", "high", "low", "close", "volume"]:
                    df[c] = df[c].astype(float)
                df["ts"] = pd.to_datetime(df["ts"], unit="ms")
                return df.set_index("ts")
            last_err = "empty-data"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.2)

    raise ValueError(
        f"{symbol} 선물 K라인 데이터 없음 (interval={kline_interval}, err={last_err})"
    )


# ---------------------------
# 메인 분석 (심볼 단위)
# ---------------------------
def analyze_multi_tf(symbol: str):
    print(f"🔍 평균회귀 분석 시작: {symbol}", flush=True)

    # 1) 데이터 수집
    t0 = time.perf_counter()
    df_30 = fetch_ohlcv(symbol, "30m", 150)
    df_15 = fetch_ohlcv(symbol, "15m", 150)
    df_5  = fetch_ohlcv(symbol,  "5m", 150)
    df_1  = fetch_ohlcv(symbol,  "1m", 120)
    print(f"⏱️ 데이터 수집 {symbol}: {time.perf_counter() - t0:.2f}s", flush=True)

    # 2) 전략 신호 계산 (평균회귀 v1)
    t1 = time.perf_counter()
    direction, detail = multi_frame_signal(df_30, df_15, df_5, df_1)
    print(f"⏱️ 시그널 계산 {symbol}: {time.perf_counter() - t1:.2f}s", flush=True)

    # 3) 보호 로직: 데이터 부족/무신호
    if direction == "NONE":
        reason = detail.get("reason") if isinstance(detail, dict) else None
        print(f"📭 {symbol} 신호 없음 (reason={reason})", flush=True)
        print(f"✅ {symbol} 평균회귀 분석 완료", flush=True)
        return None

    # 4) p-score 변환 및 컷
    raw = float(detail.get("raw", 0.0)) if isinstance(detail, dict) else 0.0
    p = 1.0 / (1.0 + math.exp(-SIGMOID_A * (raw - SIGMOID_C)))
    if p < P_THRESHOLD:
        print(f"🚫 컷 미달: raw={raw:.2f}, p={p:.3f} < {P_THRESHOLD}", flush=True)
        print(f"✅ {symbol} 평균회귀 분석 완료", flush=True)
        return None

    # 5) 가격/리스크 산출 (detail 우선, 없으면 백업 룰)
    try:
        price = float(df_5["close"].iloc[-1])
    except Exception:
        price = float(detail.get("entry", 0.0)) if isinstance(detail, dict) else 0.0

    sl = detail.get("sl"); tp = detail.get("tp")
    if sl is None or tp is None or any(
        (isinstance(x, float) and (pd.isna(x))) for x in [sl, tp]
    ):
        if direction == "LONG":
            sl = price * (1 - SL_PCT); tp = price * (1 + TP_PCT)
        else:
            sl = price * (1 + SL_PCT); tp = price * (1 - TP_PCT)

    entry_price = float(detail.get("entry", price)) if isinstance(detail, dict) else price

    # 6) 알림 메시지 (깔끔 포맷)
    p_str = f"{p:.2f}"
    reason = ""
    rsi = float("nan"); volx = 0
    if isinstance(detail, dict):
        reason = detail.get("reason", "")
        rsi = detail.get("RSI", float("nan"))
        vol_flag = detail.get("VOL", 0)
        # VOL 값이 배수(x1.2)인지 여부는 전략 측 산출 방식에 따라 다름 → 간단 표기
        volx = vol_flag if isinstance(vol_flag, (int, float)) else 1

    header = "🎯 Mean Reversion"
    dir_tag = "🟩 LONG" if direction == "LONG" else "🟥 SHORT"

    msg = (
        f"{header}: {symbol}\n"
        f"{dir_tag}  p={p_str}  raw={raw:.2f}\n"
        f"📍 Reason: {reason.replace('mean_reversion|', '') if isinstance(reason, str) else reason}\n"
        f"📊 RSI={(rsi if isinstance(rsi,(int,float)) else float('nan')):.1f} | 1m vol x{volx}\n"
        f"💵 Entry {format_price(entry_price)}\n"
        f"🛑 SL {format_price(sl)} | 🎯 TP {format_price(tp)}"
    )

    # 7) 가상 포지션 기록 + 텔레그램 전송
    add_virtual_trade({
        "symbol": symbol,
        "direction": direction,
        "entry": float(entry_price),
        "tp": float(tp),
        "sl": float(sl),
        "score": float(raw)
    })
    send_telegram(msg)

    print(f"✅ {symbol} 평균회귀 분석 완료", flush=True)
    return msg
