import pandas as pd

def analyze_indicators(df: pd.DataFrame) -> tuple:
    close = df['close']
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    ema = close.ewm(span=20, adjust=False).mean()
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    adx_n = 14
    high = df['high']
    low = df['low']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(adx_n).mean()
    up_move = high.diff()
    down_move = low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    plus_di = 100 * (plus_dm.rolling(adx_n).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(adx_n).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(adx_n).mean()

    latest_rsi = rsi.iloc[-1]
    prev_macd_hist = macd_hist.iloc[-2]
    latest_macd_hist = macd_hist.iloc[-1]
    latest_adx = adx.iloc[-1]

    if latest_rsi < 35 and prev_macd_hist < 0 and latest_macd_hist > 0 and latest_adx > 20:
        return 'LONG', 3
    else:
        return 'NONE', 0

# ✅ direction 추가: 'LONG' 또는 'SHORT'
def generate_trade_plan(price: float, leverage: int = 20, direction: str = 'LONG'):
    entry_low = price * 0.998
    entry_high = price * 1.002

    risk_unit = 0.005 * 20 / leverage
    reward_unit = 0.015 * 20 / leverage

    if direction == 'SHORT':
        stop_loss = price * (1 + risk_unit)
        take_profit = price * (1 - reward_unit)
    else:  # 기본은 LONG
        stop_loss = price * (1 - risk_unit)
        take_profit = price * (1 + reward_unit)

    return {
        'entry_range': f"${entry_low:,.2f} ~ ${entry_high:,.2f}",
        'stop_loss': f"${stop_loss:,.2f}",
        'take_profit': f"${take_profit:,.2f}"
    }

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

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
