# strategy.py

import pandas as pd

def calculate_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr

def should_enter_position(df, symbol):
    df['rsi'] = compute_rsi(df['close'])
    df['atr'] = calculate_atr(df)

    long_condition = (df['rsi'].shift(1) <= 40) & (df['rsi'] >= 48)
    short_condition = (df['rsi'].shift(1) >= 60) & (df['rsi'] <= 52)

    if long_condition.iloc[-1]:
        return 'LONG'
    elif short_condition.iloc[-1]:
        return 'SHORT'
    return None

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_tp_sl(entry_price, atr, direction):
    tp_multiplier = 0.8
    sl_multiplier = 0.5

    if direction == 'LONG':
        tp = entry_price + atr * tp_multiplier
        sl = entry_price - atr * sl_multiplier
    elif direction == 'SHORT':
        tp = entry_price - atr * tp_multiplier
        sl = entry_price + atr * sl_multiplier
    else:
        tp, sl = None, None

    return tp, sl
