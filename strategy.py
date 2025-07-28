import pandas as pd

# 기존 EMA 추세 판단
def get_trend(df: pd.DataFrame, ema_period=20) -> str:
    df = df.copy()
    df["ema"] = df["close"].ewm(span=ema_period, adjust=False).mean()
    if df["close"].iloc[-1] > df["ema"].iloc[-1]:
        return 'UP'
    else:
        return 'DOWN'

# EMA 돌파 조건
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

# RSI 계산
def calc_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# 볼린저밴드 돌파 여부
def is_bollinger_breakout(df):
    ma = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    last_close = df['close'].iloc[-1]
    return last_close > upper.iloc[-1] or last_close < lower.iloc[-1]

# 거래량 평균보다 높은지
def is_volume_spike(df):
    recent = df['volume'].iloc[-1]
    avg = df['volume'].rolling(window=20).mean().iloc[-1]
    return recent > avg * 1.5

# 최종 시그널
def multi_frame_signal(df_30m, df_15m, df_5m):
    trend_30m = get_trend(df_30m)
    direction = 'LONG' if trend_30m == 'UP' else 'SHORT'

    # EMA 조건
    cond_15m = entry_signal_ema_only(df_15m, direction)
    cond_5m  = entry_signal_ema_only(df_5m, direction)

    # 추가 보조지표들
    df_5m = df_5m.copy()
    df_5m["rsi"] = calc_rsi(df_5m)
    rsi = df_5m["rsi"].iloc[-1]

    rsi_check = direction == "LONG" and rsi < 35 or direction == "SHORT" and rsi > 65
    bollinger_check = is_bollinger_breakout(df_5m)
    volume_check = is_volume_spike(df_5m)

    # 신호 점수 기반
    score = 0
    if cond_15m: score += 1
    if cond_5m: score += 1
    if rsi_check: score += 1
    if bollinger_check: score += 1
    if volume_check: score += 1

    if score >= 2:
        entry_type = f"score={score}/EMA:{cond_15m}+{cond_5m}/RSI:{int(rsi)}/VOL:{volume_check}"
        return direction, entry_type
    else:
        return None, None
