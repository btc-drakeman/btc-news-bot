import math
import pandas as pd
from config import SIGMOID_A, SIGMOID_C, P_THRESHOLD

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

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def multi_frame_signal(df_30m: pd.DataFrame, df_15m: pd.DataFrame, df_5m: pd.DataFrame):
    """
    기존 점수 로직 유지 + p-스코어(확률) 변환 + p 컷 적용
      - raw_score 계산은 현 구조 유지
      - p = sigmoid(SIGMOID_A * (raw_score - SIGMOID_C))
      - p >= P_THRESHOLD 이면 신호 발생
      - detail 문자열에 p/raw/조건 요약 포함
    """
    # 30m 방향성
    trend_30 = get_trend(df_30m, 20)
    direction = "LONG" if trend_30 == "UP" else "SHORT"

    # 15m/5m EMA 크로스
    cond_15m = entry_signal_ema_only(df_15m, direction, ema_period=20)
    cond_5m  = entry_signal_ema_only(df_5m,  direction, ema_period=20)

    # RSI 보조(하드 차단 X, 점수에만 반영)
    rsi = _rsi(df_15m["close"], 14)
    rsi_score = 0.0
    if direction == "SHORT" and rsi >= 60:
        rsi_score += 1.0
    if direction == "LONG" and rsi <= 40:
        rsi_score += 1.0

    # 거래량 보조
    vol5 = df_5m["volume"]
    volume_check = bool(vol5.iloc[-1] > vol5.rolling(10).mean().iloc[-1])

    # raw score
    raw_score = 0.0
    if cond_15m: raw_score += 1.0
    if cond_5m:  raw_score += 1.0
    if volume_check: raw_score += 0.5
    raw_score += rsi_score

    # 일관성 패널티
    if not cond_15m and not cond_5m:
        raw_score -= 1.0
    elif cond_15m != cond_5m:
        raw_score -= 0.5

    # p-스코어 변환
    p = _sigmoid(SIGMOID_A * (raw_score - SIGMOID_C))

    # 디버그 로그
    try:
        print(
            f"[DEBUG] direction={direction} raw={raw_score:.2f} p={p:.3f} "
            f"15m={int(cond_15m)} 5m={int(cond_5m)} RSI={rsi:.1f} VOL={int(volume_check)}",
            flush=True
        )
    except Exception:
        pass

    if p >= P_THRESHOLD:
        detail = (
            f"p={p:.2f}/raw={round(raw_score,1)} "
            f"EMA:{int(cond_15m)}+{int(cond_5m)} "
            f"RSI≈{int(rsi)} VOL:{int(volume_check)}"
        )
        return direction, detail

    return None, None
