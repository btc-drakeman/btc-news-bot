import pandas as pd
from analyzer import fetch_ohlcv, calc_atr, format_price
from strategy import calc_rsi
from notifier import send_telegram
from simulator import add_virtual_trade

# =============================
# 스프링 전략: 돌파 직전 압축 + 볼륨 급증 감지 (리빌딩 버전)
# =============================

def is_spring_compression(df: pd.DataFrame, short_window=10, long_window=20, threshold=0.8) -> bool:
    short_avg_range = (df['high'] - df['low']).rolling(window=short_window).mean().iloc[-1]
    long_avg_range = (df['high'] - df['low']).rolling(window=long_window).mean().iloc[-1]
    return short_avg_range < long_avg_range * threshold

def is_volume_spike(df: pd.DataFrame, short_window=5, long_window=20, multiplier=1.2) -> bool:
    vol_short = df['volume'].rolling(window=short_window).mean().iloc[-1]
    vol_long = df['volume'].rolling(window=long_window).mean().iloc[-1]
    return vol_short > vol_long * multiplier

def is_near_top(df: pd.DataFrame, threshold=0.975) -> bool:
    prev_high = df['high'].iloc[-4:-1].max()
    return df['close'].iloc[-1] >= prev_high * threshold

def is_near_bottom(df: pd.DataFrame, threshold=1.025) -> bool:
    prev_low = df['low'].iloc[-4:-1].min()
    return df['close'].iloc[-1] <= prev_low * threshold

def analyze_spring_signal(symbol: str) -> str | None:
    df = fetch_ohlcv(symbol, interval='1h', limit=100)
    if df is None or len(df) < 30:
        return None

    # 롱 조건
    if (
        is_spring_compression(df)
        and is_volume_spike(df)
        and is_near_top(df)
    ):
        price = df['close'].iloc[-1]
        atr = calc_atr(df, period=14)
        sl = price - atr * 1.2
        tp = price + atr * 2.0

        entry = {"symbol": symbol, "direction": "LONG", "entry": price, "tp": tp, "sl": sl, "score": 0}
        add_virtual_trade(entry)

        msg = (
            f"🌀 스프링 전략: {symbol}\n"
            f"📦 압축: 진폭 감소 + 볼륨 상승\n"
            f"📈 고점 근접 + 선매수 시그널\n"
            f"💵 진입가: ${format_price(price)}\n"
            f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
        )
        send_telegram(msg)
        return msg

    # 숏 조건
    if (
        is_spring_compression(df)
        and is_volume_spike(df)
        and is_near_bottom(df)
    ):
        price = df['close'].iloc[-1]
        atr = calc_atr(df, period=14)
        sl = price + atr * 1.2
        tp = price - atr * 2.0

        entry = {"symbol": symbol, "direction": "SHORT", "entry": price, "tp": tp, "sl": sl, "score": 0}
        add_virtual_trade(entry)

        msg = (
            f"🌀 스프링 전략: {symbol}\n"
            f"📦 압축: 진폭 감소 + 볼륨 상승\n"
            f"📉 저점 근접 + 선매도 시그널\n"
            f"💵 진입가: ${format_price(price)}\n"
            f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
        )
        send_telegram(msg)
        return msg

    return None
