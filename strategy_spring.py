import pandas as pd
from analyzer import fetch_ohlcv
from config import SL_PCT, TP_PCT, format_price
from notifier import send_telegram
from simulator import add_virtual_trade

def is_spring_compression(df: pd.DataFrame, short_window=10, long_window=20, threshold=0.8) -> bool:
    short_avg = (df["high"] - df["low"]).rolling(short_window).mean().iloc[-1]
    long_avg  = (df["high"] - df["low"]).rolling(long_window).mean().iloc[-1]
    return bool(short_avg < long_avg * threshold)

def is_volume_spike(df: pd.DataFrame, short_window=5, long_window=20, mult=1.2) -> bool:
    v_s = df["volume"].rolling(short_window).mean().iloc[-1]
    v_l = df["volume"].rolling(long_window).mean().iloc[-1]
    return bool(v_s > v_l * mult)

def is_near_bottom(df: pd.DataFrame, threshold=1.025) -> bool:
    recent = df.iloc[-20:]
    low_min = recent["low"].min()
    curr = df["close"].iloc[-1]
    return bool(curr <= low_min * threshold)

def is_near_top(df: pd.DataFrame, threshold=0.975) -> bool:
    recent = df.iloc[-20:]
    high_max = recent["high"].max()
    curr = df["close"].iloc[-1]
    return bool(curr >= high_max * threshold)

def analyze_spring_signal(symbol: str, interval: str = "5m", limit: int = 200):
    df = fetch_ohlcv(symbol, interval, limit)
    price = float(df["close"].iloc[-1])

    # LONG: 돌파 재시도
    if is_spring_compression(df) and is_volume_spike(df) and is_near_top(df):
        sl = price * (1 - SL_PCT)
        tp = price * (1 + TP_PCT)
        entry = {"symbol": symbol, "direction": "LONG", "entry": price,
                 "tp": tp, "sl": sl, "score": 0}
        add_virtual_trade(entry)
        msg = (
            f"🌀 스프링 전략: {symbol}\n"
            f"📦 압축: 진폭 감소 + 볼륨 상승\n"
            f"📈 고점 돌파 시도 + 필터 통과\n"
            f"💵 진입가: ${format_price(price)}\n"
            f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
        )
        send_telegram(msg)
        return msg

    # SHORT: 붕괴 재시도
    if is_spring_compression(df) and is_volume_spike(df) and is_near_bottom(df):
        sl = price * (1 + SL_PCT)
        tp = price * (1 - TP_PCT)
        entry = {"symbol": symbol, "direction": "SHORT", "entry": price,
                 "tp": tp, "sl": sl, "score": 0}
        add_virtual_trade(entry)
        msg = (
            f"🌀 스프링 전략: {symbol}\n"
            f"📦 압축: 진폭 감소 + 볼륨 상승\n"
            f"📉 저점 붕괴 시도 + 필터 통과\n"
            f"💵 진입가: ${format_price(price)}\n"
            f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
        )
        send_telegram(msg)
        return msg

    return None
