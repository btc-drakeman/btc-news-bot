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

def entry_signal_ema_only(df, direction, ema_period=20):
    df = df.copy()
    df["ema"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    prev_close = df["close"].iloc[-2]
    curr_close = df["close"].iloc[-1]
    prev_ema = df["ema"].iloc[-2]
    curr_ema = df["ema"].iloc[-1]
    if direction == 'LONG':
        return prev_close < prev_ema and curr_close > curr_ema
    else:
        return prev_close > prev_ema and curr_close < curr_ema

def multi_frame_signal(df_30m, df_15m, df_5m):
    trend_30m = get_trend(df_30m)
    direction = 'LONG' if trend_30m == 'UP' else 'SHORT'
    cond_15m = entry_signal_ema_only(df_15m, direction)
    cond_5m  = entry_signal_ema_only(df_5m, direction)
    if cond_15m or cond_5m:
        if cond_15m and cond_5m:
            entry_type = '30m+15m+5m'
        elif cond_15m:
            entry_type = '30m+15m'
        else:
            entry_type = '30m+5m'
        return direction, entry_type
    return None, None
