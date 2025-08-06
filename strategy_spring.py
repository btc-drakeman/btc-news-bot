import pandas as pd
from analyzer import fetch_ohlcv, fetch_ohlcv_1h, calc_atr, format_price
from strategy import calc_rsi
from notifier import send_telegram
from simulator import add_virtual_trade

# =============================
# 스프링 전략: 필터 강화 + OBV 기반 매수/매도 추정
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

def is_1h_uptrend(df_1h):
    ma60 = df_1h['close'].rolling(window=60).mean().iloc[-1]
    return df_1h['close'].iloc[-1] > ma60

def is_recent_bullish(df):
    recent = df.iloc[-5:]
    return (recent['close'] > recent['open']).sum() >= 3

def is_recent_bearish(df):
    recent = df.iloc[-5:]
    return (recent['close'] < recent['open']).sum() >= 3

def no_recent_big_red(df, threshold=0.02):
    recent = df.iloc[-3:]
    return all((row['open'] - row['close']) / row['open'] < threshold for _, row in recent.iterrows())

def no_recent_big_green(df, threshold=0.02):
    recent = df.iloc[-3:]
    return all((row['close'] - row['open']) / row['open'] < threshold for _, row in recent.iterrows())

def is_last_candle_bullish(df):
    return df['close'].iloc[-1] > df['open'].iloc[-1]

def is_last_candle_bearish(df):
    return df['close'].iloc[-1] < df['open'].iloc[-1]

def calc_obv(df: pd.DataFrame) -> pd.Series:
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i - 1]:
            obv.append(obv[-1] + df['volume'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i - 1]:
            obv.append(obv[-1] - df['volume'].iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

def is_obv_rising(df):
    obv = calc_obv(df)
    return obv.iloc[-1] > obv.rolling(window=10).mean().iloc[-1]

def is_obv_falling(df):
    obv = calc_obv(df)
    return obv.iloc[-1] < obv.rolling(window=10).mean().iloc[-1]

def analyze_spring_signal(symbol: str) -> str | None:
    df = fetch_ohlcv(symbol, interval='15m', limit=200)
    df_1h = fetch_ohlcv_1h(symbol, limit=100)

    if df is None or len(df) < 30 or df_1h is None or len(df_1h) < 60:
        return None

    # 롱 조건 (필터 강화 + OBV 상승)
    if (
        is_spring_compression(df)
        and is_volume_spike(df)
        and is_near_top(df)
        and is_1h_uptrend(df_1h)
        and is_recent_bullish(df)
        and no_recent_big_red(df)
        and is_last_candle_bullish(df)
        and is_obv_rising(df)
    ):
        price = df['close'].iloc[-1]
        atr = calc_atr(df, period=14)
        sl = price - atr * 1.0
        tp = price + atr * 1.6

        entry = {"symbol": symbol, "direction": "LONG", "entry": price, "tp": tp, "sl": sl, "score": 0}
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

    # 숏 조건 (필터 강화 + OBV 하락)
    if (
        is_spring_compression(df)
        and is_volume_spike(df)
        and is_near_bottom(df)
        and not is_1h_uptrend(df_1h)
        and is_recent_bearish(df)
        and no_recent_big_green(df)
        and is_last_candle_bearish(df)
        and is_obv_falling(df)
    ):
        price = df['close'].iloc[-1]
        atr = calc_atr(df, period=14)
        sl = price + atr * 1.0
        tp = price - atr * 1.6

        entry = {"symbol": symbol, "direction": "SHORT", "entry": price, "tp": tp, "sl": sl, "score": 0}
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
