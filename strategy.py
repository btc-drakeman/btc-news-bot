import pandas as pd

def get_trend(df: pd.DataFrame, ema_period=20) -> str:
    """
    EMA 기준 추세 판정 ('UP' or 'DOWN')
    """
    df = df.copy()
    df["ema"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    if df["close"].iloc[-1] > df["ema"].iloc[-1]:
        return 'UP'
    else:
        return 'DOWN'

def entry_signal(df: pd.DataFrame, direction: str, ema_period=20) -> bool:
    """
    direction: 'LONG' 또는 'SHORT'
    - LONG: 직전봉 < EMA, 현재봉 > EMA, 거래량 급증
    - SHORT: 직전봉 > EMA, 현재봉 < EMA, 거래량 급증
    """
    df = df.copy()
    df["ema"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    df["volume_ma"] = df["volume"].rolling(ema_period).mean()
    prev_close = df["close"].iloc[-2]
    curr_close = df["close"].iloc[-1]
    prev_ema = df["ema"].iloc[-2]
    curr_ema = df["ema"].iloc[-1]
    curr_vol = df["volume"].iloc[-1]
    vol_ma = df["volume_ma"].iloc[-1]

    if direction == 'LONG':
        if (
            prev_close < prev_ema and
            curr_close > curr_ema and
            curr_vol > vol_ma * 1.2
        ):
            return True
    elif direction == 'SHORT':
        if (
            prev_close > prev_ema and
            curr_close < curr_ema and
            curr_vol > vol_ma * 1.2
        ):
            return True
    return False
