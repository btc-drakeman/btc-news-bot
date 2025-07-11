# ✅ strategy.py
import pandas as pd

def calc_rsi(close, length=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(length).mean()
    loss = -delta.where(delta < 0, 0).rolling(length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return hist

def calc_adx(df):
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr14 = tr.rolling(window=14).sum()
    plus_di = 100 * (plus_dm.rolling(window=14).sum() / tr14)
    minus_di = 100 * (minus_dm.rolling(window=14).sum() / tr14)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(window=14).mean()

def is_strong_entry_signal(df):
    if len(df) < 50:
        return False
    
    rsi = calc_rsi(df['close'])
    if rsi.iloc[-1] >= 35:
        return False

    macd_hist = calc_macd(df['close']).dropna()
    if len(macd_hist) < 2 or macd_hist.iloc[-2] > 0 or macd_hist.iloc[-1] <= 0:
        return False

    adx = calc_adx(df).dropna()
    if adx.iloc[-1] <= 20:
        return False

    return True

def generate_trade_plan(df: pd.DataFrame, direction: str = 'LONG', leverage: int = 10):
    price = df['close'].iloc[-1]
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean().iloc[-1]

    entry_low = price * 0.995
    entry_high = price * 1.005
    atr_multiplier = 1.8 * (20 / leverage)

    if direction.upper() == 'SHORT':
        stop_loss = price + (atr * atr_multiplier)
        take_profit = price - (atr * atr_multiplier * 1.2)
    else:
        stop_loss = price - (atr * atr_multiplier)
        take_profit = price + (atr * atr_multiplier * 1.2)

    return {
        'price': price,
        'entry_range': f"${entry_low:,.4f} ~ ${entry_high:,.4f}",
        'stop_loss': f"${stop_loss:,.4f}",
        'take_profit': f"${take_profit:,.4f}",
        'atr': round(atr, 4)
    }
