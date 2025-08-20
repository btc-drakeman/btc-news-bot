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
prev_ema = df["ema"].iloc[-2]
curr_ema = df["ema"].iloc[-1]


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
trend_30 = get_trend(df_30m, 20)
direction = "LONG" if trend_30 == "UP" else "SHORT"


cond_15m = entry_signal_ema_only(df_15m, direction, ema_period=20)
cond_5m = entry_signal_ema_only(df_5m, direction, ema_period=20)


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
return None, None