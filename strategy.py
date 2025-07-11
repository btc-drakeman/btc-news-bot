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

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def should_enter_position(df):
    df['rsi'] = compute_rsi(df['close'])
    df['atr'] = calculate_atr(df)

    long_cond = (df['rsi'].shift(1) <= 40) & (df['rsi'] >= 48)
    short_cond = (df['rsi'].shift(1) >= 60) & (df['rsi'] <= 52)

    if long_cond.iloc[-1]:
        return 'LONG'
    elif short_cond.iloc[-1]:
        return 'SHORT'
    return None

def is_pre_entry_signal(df):
    df['rsi'] = compute_rsi(df['close'])
    df['volume_ma'] = df['volume'].rolling(21).mean()

    rsi_now = df['rsi'].iloc[-1]
    rsi_prev = df['rsi'].iloc[-2]
    rsi_delta = rsi_now - rsi_prev
    vol_now = df['volume'].iloc[-1]
    vol_ma = df['volume_ma'].iloc[-1]

    long_pre = (
        rsi_prev <= 40 and 45 <= rsi_now < 48 and
        rsi_delta > 0 and vol_now > vol_ma
    )
    short_pre = (
        rsi_prev >= 60 and 55 >= rsi_now > 52 and
        rsi_delta < 0 and vol_now > vol_ma
    )

    if long_pre:
        return 'LONG'
    elif short_pre:
        return 'SHORT'
    return None

def calculate_tp_sl(entry_price, atr, direction):
    # Bybit 선물 기준: 레버리지 고려하여 폭 설정
    tp_multiplier = 1.2
    sl_multiplier = 1.8

    if direction == 'LONG':
        tp = entry_price + atr * tp_multiplier
        sl = entry_price - atr * sl_multiplier
    elif direction == 'SHORT':
        tp = entry_price - atr * tp_multiplier
        sl = entry_price + atr * sl_multiplier
    else:
        tp, sl = None, None

    return round(tp, 4), round(sl, 4)

def analyze_indicators(symbol, df, price):
    df['rsi'] = compute_rsi(df['close'])
    df['atr'] = calculate_atr(df)
    direction = should_enter_position(df)

    if not direction:
        return None

    atr = df['atr'].iloc[-1]
    tp, sl = calculate_tp_sl(price, atr, direction)

    message = f"""
🚨 {symbol} 진입 시그널 발생! (Bybit 선물 기준)
📈 방향: {direction}
💰 현재가: ${price:.4f}
📏 ATR: {atr:.4f}

🎯 익절가: ${tp}
🛑 손절가: ${sl}
"""
    return message.strip()
