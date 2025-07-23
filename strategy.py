import pandas as pd

def get_trend(df: pd.DataFrame) -> str:
    """
    30분봉 등에서 추세 방향을 문자열로 반환 ('UP' or 'DOWN')
    """
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    if df["close"].iloc[-1] > df["ema20"].iloc[-1]:
        return 'UP'
    else:
        return 'DOWN'

def entry_signal(df: pd.DataFrame, direction: str) -> bool:
    """
    5분봉에서 지정 방향(LONG/SHORT) 진입 신호 판별
    direction: 'LONG' 또는 'SHORT'
    """
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["volume_ma"] = df["volume"].rolling(20).mean()
    prev_close = df["close"].iloc[-2]
    curr_close = df["close"].iloc[-1]
    prev_ema = df["ema20"].iloc[-2]
    curr_ema = df["ema20"].iloc[-1]
    curr_vol = df["volume"].iloc[-1]
    vol_ma = df["volume_ma"].iloc[-1]

    if direction == 'LONG':
        # 직전봉 < EMA, 현재봉 > EMA, 거래량 급증
        if (
            prev_close < prev_ema and
            curr_close > curr_ema and
            curr_vol > vol_ma * 1.2
        ):
            return True
    elif direction == 'SHORT':
        # 직전봉 > EMA, 현재봉 < EMA, 거래량 급증
        if (
            prev_close > prev_ema and
            curr_close < curr_ema and
            curr_vol > vol_ma * 1.2
        ):
            return True
    return False
