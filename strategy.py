# strategy.py
# ==========================================
# Trend + Pullback + Trigger (30m/15m + 5m + 1m)
# - 30m & 15m: 추세 확정
# - 5m: 눌림 감지
# - 1m or 5m: 트리거(재가속) 확인
# 반환: analyzer의 기존 로그 포맷과 호환되도록
#   - direction: "LONG"/"SHORT"/"NONE"
#   - raw: float (점수형)
#   - flags: dict("15m":0/1, "5m":0/1, "30m":0/1, "1m":0/1)
#   - RSI: float (기본 5m RSI)
#   - VOL: 0/1 (트리거 시 볼륨 스파이크)
#   - entry/sl/tp: float (참고용)
# ==========================================

import math
import pandas as pd
from typing import Tuple, Dict, Any

from config import SIGMOID_A, SIGMOID_C, P_THRESHOLD  # 호환성 유지용 (사용 여부 무관)
import stats  # 텔레메트리 기록용 (있어도 되고 없어도 됨)

# ---------- 유틸 ----------

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def _sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window=window, min_periods=max(1, window//2)).mean()

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss.replace(0, 1e-12))
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    # df: columns open, high, low, close
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _last_n_bars_below(series_close: pd.Series, series_ref: pd.Series, n_min=1, n_max=3) -> bool:
    """최근 1~3봉 동안 종가가 ref(예: EMA20) 아래에 있었는지"""
    n = min(len(series_close), n_max)
    if n < n_min:
        return False
    recent = series_close.iloc[-n:]
    ref = series_ref.iloc[-n:]
    below = (recent < ref).sum()
    return (below >= n_min)

def _slope_positive(series: pd.Series, lookback: int = 5) -> bool:
    if len(series) < lookback + 1:
        return False
    return series.iloc[-1] > series.iloc[-1 - lookback]

def _room_to_swing_up(df30: pd.DataFrame, atr_mult: float = 0.6) -> bool:
    """롱: 최근 30m 스윙 하이까지 여유(>= 0.6*ATR_30m)"""
    atr30 = _calc_atr(df30, period=14)
    if len(df30) < 20:
        return True  # 데이터 부족시 패스
    recent_high = df30["high"].rolling(20).max().iloc[-1]
    dist = recent_high - df30["close"].iloc[-1]
    return dist >= (atr30.iloc[-1] * atr_mult if not math.isnan(atr30.iloc[-1]) else 0)

def _room_to_swing_down(df30: pd.DataFrame, atr_mult: float = 0.6) -> bool:
    """숏: 최근 30m 스윙 로우까지 여유(>= 0.6*ATR_30m)"""
    atr30 = _calc_atr(df30, period=14)
    if len(df30) < 20:
        return True
    recent_low = df30["low"].rolling(20).min().iloc[-1]
    dist = df30["close"].iloc[-1] - recent_low
    return dist >= (atr30.iloc[-1] * atr_mult if not math.isnan(atr30.iloc[-1]) else 0)

def _bullish_engulfing_1m(df1: pd.DataFrame) -> bool:
    """1m 강한 양봉/엔걸핑(간이판). open 컬럼 없으면 스킵"""
    if "open" not in df1.columns or len(df1) < 3:
        return False
    o1, c1 = df1["open"].iloc[-1], df1["close"].iloc[-1]
    o2, c2 = df1["open"].iloc[-2], df1["close"].iloc[-2]
    # 현재 양봉 + 이전 캔들을 감싸는/돌파하는 강세
    return (c1 > o1) and (c1 > max(o2, c2)) and (o1 <= min(o2, c2))

def _bearish_engulfing_1m(df1: pd.DataFrame) -> bool:
    if "open" not in df1.columns or len(df1) < 3:
        return False
    o1, c1 = df1["open"].iloc[-1], df1["close"].iloc[-1]
    o2, c2 = df1["open"].iloc[-2], df1["close"].iloc[-2]
    return (c1 < o1) and (c1 < min(o2, c2)) and (o1 >= max(o2, c2))

def _vol_spike(series_vol: pd.Series, window: int = 20, mult: float = 1.2) -> bool:
    v = series_vol.iloc[-1]
    base = _sma(series_vol, window=window).iloc[-1]
    if math.isnan(base) or base == 0:
        return False
    return v > (base * mult)

def _safe_last(series: pd.Series, default: float = float("nan")) -> float:
    try:
        val = series.iloc[-1]
        return float(val)
    except Exception:
        return default

# ---------- 추세 / 눌림 / 트리거 판단 ----------

def _trend_up_30m15m(df30: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema50_30 = _ema(df30["close"], 50)
    ema20_15 = _ema(df15["close"], 20)
    ema50_15 = _ema(df15["close"], 50)

    cond_30 = (_safe_last(df30["close"]) > _safe_last(ema50_30)) and _slope_positive(ema50_30, 5)
    cond_15 = (_safe_last(ema20_15) > _safe_last(ema50_15)) and (_safe_last(df15["close"]) > _safe_last(ema20_15))
    ok = bool(cond_30 and cond_15)
    return ok, {
        "ema50_30": _safe_last(ema50_30),
        "ema20_15": _safe_last(ema20_15),
        "ema50_15": _safe_last(ema50_15),
        "cond_30": int(cond_30),
        "cond_15": int(cond_15),
    }

def _trend_down_30m15m(df30: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema50_30 = _ema(df30["close"], 50)
    ema20_15 = _ema(df15["close"], 20)
    ema50_15 = _ema(df15["close"], 50)

    cond_30 = (_safe_last(df30["close"]) < _safe_last(ema50_30)) and (not _slope_positive(ema50_30, 5))
    cond_15 = (_safe_last(ema20_15) < _safe_last(ema50_15)) and (_safe_last(df15["close"]) < _safe_last(ema20_15))
    ok = bool(cond_30 and cond_15)
    return ok, {
        "ema50_30": _safe_last(ema50_30),
        "ema20_15": _safe_last(ema20_15),
        "ema50_15": _safe_last(ema50_15),
        "cond_30": int(cond_30),
        "cond_15": int(cond_15),
    }

def _pullback_long_5m(df5: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    ema50_5 = _ema(df5["close"], 50)
    vol = df5["volume"]
    atr15 = _calc_atr(df15, period=14)
    ema20_15 = _ema(df15["close"], 20)

    below_ema20_recent = _last_n_bars_below(df5["close"], ema20_5, n_min=1, n_max=3)
    touch_ema50_or_near = (_safe_last(df5["low"]) <= _safe_last(ema50_5))
    # 15m 앵커 근처
    anchor_near = abs(_safe_last(df5["close"]) - _safe_last(ema20_15)) <= (0.25 * _safe_last(atr15))
    vol_contract = _safe_last(vol.iloc[-3:].mean()) < _safe_last(_sma(vol, 20))

    ok = bool(below_ema20_recent and (touch_ema50_or_near or anchor_near) and vol_contract)
    return ok, {
        "below_ema20_recent": int(below_ema20_recent),
        "touch_ema50_or_near": int(touch_ema50_or_near or anchor_near),
        "vol_contract": int(vol_contract),
        "ema20_5": _safe_last(ema20_5),
        "ema50_5": _safe_last(ema50_5),
        "ema20_15": _safe_last(ema20_15),
    }

def _pullback_short_5m(df5: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    ema50_5 = _ema(df5["close"], 50)
    vol = df5["volume"]
    atr15 = _calc_atr(df15, period=14)
    ema20_15 = _ema(df15["close"], 20)

    above_ema20_recent = _last_n_bars_below(-df5["close"], -ema20_5, n_min=1, n_max=3)  # == 최근 1~3봉 EMA20 위
    touch_ema50_or_near = (_safe_last(df5["high"]) >= _safe_last(ema50_5))
    anchor_near = abs(_safe_last(df5["close"]) - _safe_last(ema20_15)) <= (0.25 * _safe_last(atr15))
    vol_contract = _safe_last(vol.iloc[-3:].mean()) < _safe_last(_sma(vol, 20))

    ok = bool(above_ema20_recent and (touch_ema50_or_near or anchor_near) and vol_contract)
    return ok, {
        "above_ema20_recent": int(above_ema20_recent),
        "touch_ema50_or_near": int(touch_ema50_or_near or anchor_near),
        "vol_contract": int(vol_contract),
        "ema20_5": _safe_last(ema20_5),
        "ema50_5": _safe_last(ema50_5),
        "ema20_15": _safe_last(ema20_15),
    }

def _trigger_long(df5: pd.DataFrame, df1: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    reclaim_5m = (_safe_last(df5["close"]) > _safe_last(ema20_5)) and (df5["close"].iloc[-2] <= ema20_5.iloc[-2])
    vol_spike = _vol_spike(df5["volume"], window=20, mult=1.2)
    engulf_1m = _bullish_engulfing_1m(df1) if df1 is not None and len(df1) > 2 else False
    ok = bool((reclaim_5m and vol_spike) or engulf_1m)
    return ok, {
        "reclaim_5m": int(reclaim_5m),
        "vol_spike": int(vol_spike),
        "engulf_1m": int(engulf_1m),
    }

def _trigger_short(df5: pd.DataFrame, df1: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    reclaim_5m = (_safe_last(df5["close"]) < _safe_last(ema20_5)) and (df5["close"].iloc[-2] >= ema20_5.iloc[-2])
    vol_spike = _vol_spike(df5["volume"], window=20, mult=1.2)
    engulf_1m = _bearish_engulfing_1m(df1) if df1 is not None and len(df1) > 2 else False
    ok = bool((reclaim_5m and vol_spike) or engulf_1m)
    return ok, {
        "reclaim_5m": int(reclaim_5m),
        "vol_spike": int(vol_spike),
        "engulf_1m": int(engulf_1m),
    }

def _entry_sl_tp_long(df5: pd.DataFrame) -> Tuple[float, float, float]:
    price = _safe_last(df5["close"])
    atr5 = _safe_last(_calc_atr(df5, 14))
    # 최근 스윙 로우 근처로 SL
    sw_low = df5["low"].rolling(6).min().iloc[-2] if len(df5) >= 6 else df5["low"].min()
    sl = float(min(sw_low, price - (0.8 * atr5) if not math.isnan(atr5) else price * 0.01))
    risk = max(1e-6, price - sl)
    tp = price + (1.8 * risk)  # 기본 1.8R
    return price, sl, tp

def _entry_sl_tp_short(df5: pd.DataFrame) -> Tuple[float, float, float]:
    price = _safe_last(df5["close"])
    atr5 = _safe_last(_calc_atr(df5, 14))
    sw_high = df5["high"].rolling(6).max().iloc[-2] if len(df5) >= 6 else df5["high"].max()
    sl = float(max(sw_high, price + (0.8 * atr5) if not math.isnan(atr5) else price * 1.01))
    risk = max(1e-6, sl - price)
    tp = price - (1.8 * risk)
    return price, sl, tp

# ---------- 공개 API (기존 시그니처 유지) ----------

def get_trend(df: pd.DataFrame, ema_period: int = 20) -> str:
    """단일 프레임 추세 (하위 호환; 다른 모듈이 쓸 수 있어 유지)"""
    try:
        ema = _ema(df["close"], ema_period)
        return "UP" if df["close"].iloc[-1] > ema.iloc[-1] else "DOWN"
    except Exception:
        return "DOWN"

def entry_signal_ema_only(df: pd.DataFrame, direction: str, ema_period: int = 20) -> bool:
    """
    하위 호환용. 이름은 그대로 두되, '눌림 후 재돌파'로 동작.
    - direction: "LONG"/"SHORT"
    - df는 보통 5m 프레임이 들어온다고 가정
    """
    try:
        ema = _ema(df["close"], ema_period)
        if direction.upper() == "LONG":
            return (df["close"].iloc[-1] > ema.iloc[-1]) and (df["close"].iloc[-2] <= ema.iloc[-2])
        else:
            return (df["close"].iloc[-1] < ema.iloc[-1]) and (df["close"].iloc[-2] >= ema.iloc[-2])
    except Exception:
        return False

def _coerce_frames(args, kwargs) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    analyzer와의 호환성 위해 유연한 인자 처리:
      - multi_frame_signal(df30, df15, df5, df1)
      - multi_frame_signal({"30m":df30, "15m":df15, "5m":df5, "1m":df1})
    """
    if len(args) == 1 and isinstance(args[0], dict):
        d = args[0]
        df30 = d.get("30m") or d.get("m30")
        df15 = d.get("15m") or d.get("m15")
        df5  = d.get("5m")  or d.get("m5")
        df1  = d.get("1m")  or d.get("m1")
    elif len(args) >= 4:
        df30, df15, df5, df1 = args[0], args[1], args[2], args[3]
    else:
        df30 = kwargs.get("df30"); df15 = kwargs.get("df15"); df5 = kwargs.get("df5"); df1 = kwargs.get("df1")
    return df30, df15, df5, df1

def multi_frame_signal(*args, **kwargs) -> Dict[str, Any]:
    """
    핵심 판단:
      - trend && pullback && trigger를 점수화.
      - LONG/SHORT 양 방향 점수 산출 후 더 높은 쪽 채택.
      - analyzer가 쓰는 필드 유지: direction/raw/15m/5m/RSI/VOL
    """
    df30, df15, df5, df1 = _coerce_frames(args, kwargs)
    # 안전장치
    if any(x is None or len(x) < 30 for x in [df30, df15, df5]) or df1 is None or len(df1) < 3:
        return {
            "direction": "NONE",
            "raw": 0.0,
            "flags": {"30m": 0, "15m": 0, "5m": 0, "1m": 0},
            "RSI": float("nan"),
            "VOL": 0,
            "entry": float("nan"),
            "sl": float("nan"),
            "tp": float("nan"),
            "reason": "insufficient_data",
        }

    # 공통 지표
    rsi5 = _safe_last(calc_rsi(df5["close"], 14))

    # ---------- LONG 측정 ----------
    tr_up, up_info = _trend_up_30m15m(df30, df15)
    pb_long, pb_info_l = _pullback_long_5m(df5, df15)
    tg_long, tg_info_l = _trigger_long(df5, df1)
    room_long = _room_to_swing_up(df30, 0.6)

    raw_long = 0.0
    if tr_up: raw_long += 1.2     # 추세 가중
    if pb_long: raw_long += 1.0   # 눌림
    if tg_long: raw_long += 1.0   # 트리거
    if room_long: raw_long += 0.5 # 끝물 방지 여유

    # ---------- SHORT 측정 ----------
    tr_dn, dn_info = _trend_down_30m15m(df30, df15)
    pb_short, pb_info_s = _pullback_short_5m(df5, df15)
    tg_short, tg_info_s = _trigger_short(df5, df1)
    room_short = _room_to_swing_down(df30, 0.6)

    raw_short = 0.0
    if tr_dn: raw_short += 1.2
    if pb_short: raw_short += 1.0
    if tg_short: raw_short += 1.0
    if room_short: raw_short += 0.5

    # 선택
    if raw_long > raw_short and raw_long >= 2.0:
        direction = "LONG"
        entry, sl, tp = _entry_sl_tp_long(df5)
        flags = {
            "30m": int(up_info.get("cond_30", 0)),
            "15m": int(up_info.get("cond_15", 0)),
            "5m": int(tg_info_l.get("reclaim_5m", 0) or tg_info_l.get("engulf_1m", 0)),
            "1m": int(tg_info_l.get("engulf_1m", 0)),
        }
        vol_flag = int(tg_info_l.get("vol_spike", 0))
        raw = float(raw_long)
        reason = "trend_up & pullback & trigger"
    elif raw_short > raw_long and raw_short >= 2.0:
        direction = "SHORT"
        entry, sl, tp = _entry_sl_tp_short(df5)
        flags = {
            "30m": int(dn_info.get("cond_30", 0)),
            "15m": int(dn_info.get("cond_15", 0)),
            "5m": int(tg_info_s.get("reclaim_5m", 0) or tg_info_s.get("engulf_1m", 0)),
            "1m": int(tg_info_s.get("engulf_1m", 0)),
        }
        vol_flag = int(tg_info_s.get("vol_spike", 0))
        raw = float(raw_short)
        reason = "trend_down & pullback & trigger"
    else:
        # 아무쪽도 확신 부족 → 방향만 더 높은 쪽으로 리포트, 신호는 없는 셈
        if raw_long >= raw_short:
            direction = "LONG"
            raw = float(raw_long)
            entry, sl, tp = _entry_sl_tp_long(df5)
            flags = {
                "30m": int(up_info.get("cond_30", 0)),
                "15m": int(up_info.get("cond_15", 0)),
                "5m": int(pb_info_l.get("below_ema20_recent", 0)),
                "1m": 0,
            }
            vol_flag = 0
            reason = "weak_long_bias"
        else:
            direction = "SHORT"
            raw = float(raw_short)
            entry, sl, tp = _entry_sl_tp_short(df5)
            flags = {
                "30m": int(dn_info.get("cond_30", 0)),
                "15m": int(dn_info.get("cond_15", 0)),
                "5m": int(pb_info_s.get("above_ema20_recent", 0)),
                "1m": 0,
            }
            vol_flag = 0
            reason = "weak_short_bias"

    # analyzer가 찍는 디버그 키를 최대한 맞춘다
    # - '15m'과 '5m'는 기존 로그와 동일 키로 전달
    out = {
        "direction": direction,
        "raw": raw,
        "flags": {
            "30m": int(flags.get("30m", 0)),
            "15m": int(flags.get("15m", 0)),
            "5m": int(flags.get("5m", 0)),
            "1m": int(flags.get("1m", 0)),
        },
        "RSI": float(rsi5),            # 기본 5m RSI
        "VOL": int(vol_flag),          # 트리거 시 볼륨 스파이크
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp),
        "reason": reason,
    }

    # 선택적 텔레메트리 (stats 모듈 있을 때만)
    try:
        stats.record("strategy_multi_tf", {
            "direction": direction,
            "raw": raw,
            "f15": out["flags"]["15m"],
            "f5": out["flags"]["5m"],
            "rsi5": out["RSI"],
            "vol": out["VOL"],
            "reason": reason,
        })
    except Exception:
        pass

    return out
