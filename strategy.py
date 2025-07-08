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

    latest_rsi = rsi.iloc[-1]
    latest_macd_hist = macd_hist.iloc[-1]
    latest_ema_slope = ema.diff().iloc[-1]

    long_score = 0
    short_score = 0

    if latest_rsi < 30:
        long_score += 1
    elif latest_rsi > 70:
        short_score += 1

    if latest_macd_hist > 0:
        long_score += 1
    elif latest_macd_hist < 0:
        short_score += 1

    if latest_ema_slope > 0:
        long_score += 1
    elif latest_ema_slope < 0:
        short_score += 1

    if long_score >= 2:
        return 'LONG', long_score
    elif short_score >= 2:
        return 'SHORT', short_score
    else:
        return 'NONE', 0