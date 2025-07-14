import pandas as pd

def analyze_indicators(df: pd.DataFrame) -> tuple:
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["volume_ma"] = df["volume"].rolling(20).mean()

    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    up_move = high.diff()
    down_move = low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    plus_di = 100 * (plus_dm.rolling(14).mean() / df["atr"])
    minus_di = 100 * (minus_dm.rolling(14).mean() / df["atr"])
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df["adx"] = dx.rolling(14).mean()

    # 📌 EMA 돌파 조건 적용
    prev_close = df["close"].iloc[-2]
    curr_close = df["close"].iloc[-1]
    prev_ema = df["ema20"].iloc[-2]
    curr_ema = df["ema20"].iloc[-1]

    curr_vol = df["volume"].iloc[-1]
    vol_ma = df["volume_ma"].iloc[-1]
    curr_adx = df["adx"].iloc[-1]

    # ✅ 롱 조건
    if (
        prev_close < prev_ema and curr_close > curr_ema and
        curr_vol > vol_ma * 2 and
        curr_adx > 25
    ):
        return 'LONG', 4

    # ✅ 숏 조건
    if (
        prev_close > prev_ema and curr_close < curr_ema and
        curr_vol > vol_ma * 2 and
        curr_adx > 25
    ):
        return 'SHORT', 4

    return 'NONE', 0
