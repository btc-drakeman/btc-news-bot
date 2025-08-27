# strategy.py
# ==========================================
# Trend + Pullback + Trigger (30m/15m + 5m + 1m)
# - 30m & 15m: 추세 확정
# - 5m: 눌림 감지
# - 1m or 5m: 트리거(재가속) 확인
# analyzer 호환: multi_frame_signal()은 (direction, payload_dict) 두 값 반환
# payload에는 최소 키 포함: raw, 15m, 5m, RSI, VOL, entry, sl, tp, reason
# ==========================================

import math
import pandas as pd
from typing import Tuple, Dict, Any

from config import SIGMOID_A, SIGMOID_C, P_THRESHOLD  # 호환성 유지용
import stats  # 텔레메트리(있으면 기록)

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
    high = df["high"]; low = df["low"]; close = df["close"]; pc = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - pc).abs(),
        (low - pc).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _last_n_bars_below(series_close: pd.Series, series_ref: pd.Series, n_min=1, n_max=3) -> bool:
    n = min(len(series_close), n_max)
    if n < n_min:
        return False
    recent = series_close.iloc[-n:]
    ref = series_ref.iloc[-n:]
    return (recent < ref).sum() >= n_min

def _slope_positive(series: pd.Series, lookback: int = 5) -> bool:
    if len(series) < lookback + 1:
        return False
    return series.iloc[-1] > series.iloc[-1 - lookback]

def _room_to_swing_up(df30: pd.DataFrame, atr_mult: float = 0.6) -> bool:
    atr30 = _calc_atr(df30, period=14)
    if len(df30) < 20:  # 데이터 부족 시 패스
        return True
    recent_high = df30["high"].rolling(20).max().iloc[-1]
    dist = recent_high - df30["close"].iloc[-1]
    a = atr30.iloc[-1]
    return dist >= (a * atr_mult if not math.isnan(a) else 0)

def _room_to_swing_down(df30: pd.DataFrame, atr_mult: float = 0.6) -> bool:
    atr30 = _calc_atr(df30, period=14)
    if len(df30) < 20:
        return True
    recent_low = df30["low"].rolling(20).min().iloc[-1]
    dist = df30["close"].iloc[-1] - recent_low
    a = atr30.iloc[-1]
    return dist >= (a * atr_mult if not math.isnan(a) else 0)

def _bullish_engulfing_1m(df1: pd.DataFrame) -> bool:
    if "open" not in df1.columns or len(df1) < 3:
        return False
    o1, c1 = df1["open"].iloc[-1], df1["close"].iloc[-1]
    o2, c2 = df1["open"].iloc[-2], df1["close"].iloc[-2]
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
        return float(series.iloc[-1])
    except Exception:
        return default

# ---------- 추세 / 눌림 / 트리거 ----------

def _trend_up_30m15m(df30: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema50_30 = _ema(df30["close"], 50)
    ema20_15 = _ema(df15["close"], 20)
    ema50_15 = _ema(df15["close"], 50)
    cond_30 = (_safe_last(df30["close"]) > _safe_last(ema50_30)) and _slope_positive(ema50_30, 5)
    cond_15 = (_safe_last(ema20_15) > _safe_last(ema50_15)) and (_safe_last(df15["close"]) > _safe_last(ema20_15))
    return bool(cond_30 and cond_15), {"cond_30": int(cond_30), "cond_15": int(cond_15)}

def _trend_down_30m15m(df30: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema50_30 = _ema(df30["close"], 50)
    ema20_15 = _ema(df15["close"], 20)
    ema50_15 = _ema(df15["close"], 50)
    cond_30 = (_safe_last(df30["close"]) < _safe_last(ema50_30)) and (not _slope_positive(ema50_30, 5))
    cond_15 = (_safe_last(ema20_15) < _safe_last(ema50_15)) and (_safe_last(df15["close"]) < _safe_last(ema20_15))
    return bool(cond_30 and cond_15), {"cond_30": int(cond_30), "cond_15": int(cond_15)}

def _pullback_long_5m(df5: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    ema50_5 = _ema(df5["close"], 50)
    vol = df5["volume"]
    atr15 = _calc_atr(df15, 14)
    ema20_15 = _ema(df15["close"], 20)

    below_ema20_recent = _last_n_bars_below(df5["close"], ema20_5, n_min=1, n_max=3)
    touch_ema50_or_near = (_safe_last(df5["low"]) <= _safe_last(ema50_5))
    anchor_near = abs(_safe_last(df5["close"]) - _safe_last(ema20_15)) <= (0.25 * _safe_last(atr15))
    vol_contract = _safe_last(vol.iloc[-3:].mean()) < _safe_last(_sma(vol, 20))

    ok = bool(below_ema20_recent and (touch_ema50_or_near or anchor_near) and vol_contract)
    return ok, {
        "below_ema20_recent": int(below_ema20_recent),
        "touch_ema50_or_near": int(touch_ema50_or_near or anchor_near),
        "vol_contract": int(vol_contract),
    }

def _pullback_short_5m(df5: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    ema50_5 = _ema(df5["close"], 50)
    vol = df5["volume"]
    atr15 = _calc_atr(df15, 14)
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
    }

def _trigger_long(df5: pd.DataFrame, df1: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    reclaim_5m = (_safe_last(df5["close"]) > _safe_last(ema20_5)) and (df5["close"].iloc[-2] <= ema20_5.iloc[-2])
    vol_spike = _vol_spike(df5["volume"], window=20, mult=1.2)
    engulf_1m = _bullish_engulfing_1m(df1) if df1 is not None and len(df1) > 2 else False
    ok = bool((reclaim_5m and vol_spike) or engulf_1m)
    return ok, {"reclaim_5m": int(reclaim_5m), "vol_spike": int(vol_spike), "engulf_1m": int(engulf_1m)}

def _trigger_short(df5: pd.DataFrame, df1: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20)
    reclaim_5m = (_safe_last(df5["close"]) < _safe_last(ema20_5)) and (df5["close"].iloc[-2] >= ema20_5.iloc[-2])
    vol_spike = _vol_spike(df5["volume"], window=20, mult=1.2)
    engulf_1m = _bearish_engulfing_1m(df1) if df1 is not None and len(df1) > 2 else False
    ok = bool((reclaim_5m and vol_spike) or engulf_1m)
    return ok, {"reclaim_5m": int(reclaim_5m), "vol_spike": int(vol_spike), "engulf_1m": int(engulf_1m)}

def _entry_sl_tp_long(df5: pd.DataFrame) -> Tuple[float, float, float]:
    price = _safe_last(df5["close"])
    atr5 = _safe_last(_calc_atr(df5, 14))
    sw_low = df5["low"].rolling(6).min().iloc[-2] if len(df5) >= 6 else df5["low"].min()
    sl = float(min(sw_low, price - (0.8 * atr5) if not math.isnan(atr5) else price * 0.01))
    risk = max(1e-6, price - sl)
    tp = price + (1.8 * risk)
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
    try:
        ema = _ema(df["close"], ema_period)
        return "UP" if df["close"].iloc[-1] > ema.iloc[-1] else "DOWN"
    except Exception:
        return "DOWN"

def entry_signal_ema_only(df: pd.DataFrame, direction: str, ema_period: int = 20) -> bool:
    """하위 호환: 이름 유지, 동작은 '재돌파'"""
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
    multi_frame_signal(df30, df15, df5, df1)
    또는 multi_frame_signal({"30m":df30,"15m":df15,"5m":df5,"1m":df1})
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

def multi_frame_signal(*args, **kwargs) -> Tuple[str, Dict[str, Any]]:
    """
    반환을 (direction, payload_dict) 두 값으로 고정하여 analyzer 언팩과 호환.
    payload 최소 키: raw, 15m, 5m, RSI, VOL, entry, sl, tp, reason
    """
    df30, df15, df5, df1 = _coerce_frames(args, kwargs)

    # ✅ 변경: 데이터 부족 시 entry/sl/tp를 넣지 않음(스팸 방지)
    if any(x is None or len(x) < 30 for x in [df30, df15, df5]) or df1 is None or len(df1) < 3:
        return "NONE", {
            "raw": 0.0, "15m": 0, "5m": 0, "RSI": float("nan"), "VOL": 0,
            "reason": "insufficient_data"
        }

    rsi5 = _safe_last(calc_rsi(df5["close"], 14))

    # LONG 쪽
    tr_up, up_info = _trend_up_30m15m(df30, df15)
    pb_long, pb_info_l = _pullback_long_5m(df5, df15)
    tg_long, tg_info_l = _trigger_long(df5, df1)
    room_long = _room_to_swing_up(df30, 0.6)

    raw_long = 0.0
    if tr_up: raw_long += 1.2
    if pb_long: raw_long += 1.0
    if tg_long: raw_long += 1.0
    if room_long: raw_long += 0.5

    # SHORT 쪽
    tr_dn, dn_info = _trend_down_30m15m(df30, df15)
    pb_short, pb_info_s = _pullback_short_5m(df5, df15)
    tg_short, tg_info_s = _trigger_short(df5, df1)
    room_short = _room_to_swing_down(df30, 0.6)

    raw_short = 0.0
    if tr_dn: raw_short += 1.2
    if pb_short: raw_short += 1.0
    if tg_short: raw_short += 1.0
    if room_short: raw_short += 0.5

    # 선택 및 payload 구성
    if raw_long > raw_short and raw_long >= 2.0:
        direction = "LONG"
        entry, sl, tp = _entry_sl_tp_long(df5)
        f15 = int(up_info.get("cond_15", 0))
        f5  = int(tg_info_l.get("reclaim_5m", 0) or tg_info_l.get("engulf_1m", 0))
        vol_flag = int(tg_info_l.get("vol_spike", 0))
        raw = float(raw_long)
        reason = "trend_up & pullback & trigger"
    elif raw_short > raw_long and raw_short >= 2.0:
        direction = "SHORT"
        entry, sl, tp = _entry_sl_tp_short(df5)
        f15 = int(dn_info.get("cond_15", 0))
        f5  = int(tg_info_s.get("reclaim_5m", 0) or tg_info_s.get("engulf_1m", 0))
        vol_flag = int(tg_info_s.get("vol_spike", 0))
        raw = float(raw_short)
        reason = "trend_down & pullback & trigger"
    else:
        # 약한 바이어스만 리포트
        if raw_long >= raw_short:
            direction = "LONG"
            entry, sl, tp = _entry_sl_tp_long(df5)
            f15 = int(up_info.get("cond_15", 0))
            f5  = int(pb_info_l.get("below_ema20_recent", 0))
            vol_flag = 0
            raw = float(raw_long)
            reason = "weak_long_bias"
        else:
            direction = "SHORT"
            entry, sl, tp = _entry_sl_tp_short(df5)
            f15 = int(dn_info.get("cond_15", 0))
            f5  = int(pb_info_s.get("above_ema20_recent", 0))
            vol_flag = 0
            raw = float(raw_short)
            reason = "weak_short_bias"

    payload = {
        "raw": raw,
        "15m": f15,
        "5m": f5,
        "RSI": float(rsi5),
        "VOL": vol_flag,
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp),
        "reason": reason,
    }

    # 선택적 텔레메트리
    try:
        stats.record("strategy_multi_tf", {
            "direction": direction, "raw": raw, "f15": f15, "f5": f5,
            "rsi5": payload["RSI"], "vol": vol_flag, "reason": reason,
        })
    except Exception:
        pass

    return direction, payload
