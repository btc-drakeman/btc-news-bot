import pandas as pd

def get_trend(df: pd.DataFrame, ema_period: int = 20) -> str:
    df = df.copy()
    df["ema"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    return "UP" if df["close"].iloc[-1] > df["ema"].iloc[-1] else "DOWN"

def entry_signal_ema_only(df: pd.DataFrame, direction: str, ema_period: int = 20) -> bool:
    df = df.copy()
    df["ema"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    prev_close = df["close"].iloc[-2]
    curr_close = df["close"].iloc[-1]
    prev_ema   = df["ema"].iloc[-2]
    curr_ema   = df["ema"].iloc[-1]

    if direction == "LONG":
        return prev_close <= prev_ema and curr_close > curr_ema
    else:
        return prev_close >= prev_ema and curr_close < curr_ema

def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def multi_frame_signal(df_30m: pd.DataFrame, df_15m: pd.DataFrame, df_5m: pd.DataFrame):
    """
    개선:
      - RSI 하드 차단 제거(진입 차단 X, 점수에만 반영)
      - EMA 혼조/불일치 페널티 완화
      - 컷 기준 2.5
    """
    trend_30 = get_trend(df_30m, 20)
    direction = "LONG" if trend_30 == "UP" else "SHORT"

    cond_15m = entry_signal_ema_only(df_15m, direction, ema_period=20)
    cond_5m  = entry_signal_ema_only(df_5m,  direction, ema_period=20)

    rsi = _rsi(df_15m["close"], 14)
    rsi_score = 0.0
    if direction == "SHORT" and rsi >= 60:
        rsi_score += 1.0
    if direction == "LONG" and rsi <= 40:
        rsi_score += 1.0

    vol5 = df_5m["volume"]
    volume_check = bool(vol5.iloc[-1] > vol5.rolling(10).mean().iloc[-1])

    raw_score = 0.0
    if cond_15m: raw_score += 1.0
    if cond_5m:  raw_score += 1.0
    if volume_check: raw_score += 0.5
    raw_score += rsi_score

    if not cond_15m and not cond_5m:
        raw_score -= 1.0
    elif cond_15m != cond_5m:
        raw_score -= 0.5

    if raw_score >= 2.5:
        entry_type = (
            f"score={round(raw_score,1)}/"
            f"EMA:{int(cond_15m)}+{int(cond_5m)}/"
            f"RSI:{int(rsi)}/VOL:{int(volume_check)}"
        )
        return direction, entry_type
    return None, None
