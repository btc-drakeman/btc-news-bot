# strategy.py
import math
import pandas as pd
from typing import Tuple, Dict, Any
import stats

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
    return 100 - (100 / (1 + rs))

def _calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]).abs(),
                    (df["high"]-pc).abs(),
                    (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _safe_last(series: pd.Series, default: float = float("nan")) -> float:
    try: return float(series.iloc[-1])
    except Exception: return default

def _slope_positive(series: pd.Series, lookback: int = 5) -> bool:
    return len(series) >= lookback+1 and series.iloc[-1] > series.iloc[-1-lookback]

def _last_n_bars_below(series_close: pd.Series, series_ref: pd.Series, n_min=1, n_max=3) -> bool:
    n = min(len(series_close), n_max)
    if n < n_min: return False
    recent = series_close.iloc[-n:]; ref = series_ref.iloc[-n:]
    return (recent < ref).sum() >= n_min

def _vwap(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).rolling(lookback).sum()
    vv = df["volume"].rolling(lookback).sum()
    return pv / (vv + 1e-12)

def _fib_retracement_ok(df5: pd.DataFrame, lookback: int = 20) -> Tuple[bool, Dict[str, Any]]:
    """간단 버전: 최근 구간 [LL, HH] 대비 현재가 되돌림 비율이 0.382~0.618"""
    ref = df5.iloc[:-1] if len(df5) > 1 else df5
    hh = float(ref['high'].rolling(lookback).max().iloc[-1])
    ll = float(ref['low'].rolling(lookback).min().iloc[-1])
    px = float(df5['close'].iloc[-1])
    if hh <= ll: return False, {"fib": None}
    ratio_down = (hh - px) / (hh - ll + 1e-12)  # 롱 기준
    ok = 0.382 <= ratio_down <= 0.618
    return ok, {"fib_ratio": float(ratio_down)}

# ---------- 캔들 패턴 ----------
def _bullish_engulfing_1m(df1: pd.DataFrame) -> bool:
    if "open" not in df1.columns or len(df1) < 3: return False
    o1, c1 = df1["open"].iloc[-1], df1["close"].iloc[-1]
    o2, c2 = df1["open"].iloc[-2], df1["close"].iloc[-2]
    return (c1 > o1) and (c1 > max(o2, c2)) and (o1 <= min(o2, c2))

def _bearish_engulfing_1m(df1: pd.DataFrame) -> bool:
    if "open" not in df1.columns or len(df1) < 3: return False
    o1, c1 = df1["open"].iloc[-1], df1["close"].iloc[-1]
    o2, c2 = df1["open"].iloc[-2], df1["close"].iloc[-2]
    return (c1 < o1) and (c1 < min(o2, c2)) and (o1 >= max(o2, c2))

# ---------- 추세 ----------
def _trend_up_30m15m(df30: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema50_30 = _ema(df30["close"], 50)
    ema20_15 = _ema(df15["close"], 20); ema50_15 = _ema(df15["close"], 50)
    cond_30 = (_safe_last(df30["close"]) > _safe_last(ema50_30)) and _slope_positive(ema50_30, 5)
    cond_15 = (_safe_last(ema20_15) > _safe_last(ema50_15)) and (_safe_last(df15["close"]) > _safe_last(ema20_15))
    # 보조 가점: 최근 HH/HL or 15m RSI>48
    hh_ok = df30["high"].rolling(6).apply(lambda x: (pd.Series(x).is_monotonic_increasing)).iloc[-1] == 1.0
    hl_ok = df30["low"].rolling(6).apply(lambda x: (pd.Series(x).is_monotonic_increasing)).iloc[-1] == 1.0
    rsi15 = _safe_last(calc_rsi(df15["close"], 14))
    aux = int((hh_ok and hl_ok) or (rsi15 > 48))
    ok = bool(cond_30 and cond_15)
    return ok, {"cond_30": int(cond_30), "cond_15": int(cond_15), "aux": aux}

def _trend_down_30m15m(df30: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema50_30 = _ema(df30["close"], 50)
    ema20_15 = _ema(df15["close"], 20); ema50_15 = _ema(df15["close"], 50)
    cond_30 = (_safe_last(df30["close"]) < _safe_last(ema50_30)) and (not _slope_positive(ema50_30, 5))
    cond_15 = (_safe_last(ema20_15) < _safe_last(ema50_15)) and (_safe_last(df15["close"]) < _safe_last(ema20_15))
    hh_ok = df30["high"].rolling(6).apply(lambda x: (pd.Series(x).is_monotonic_decreasing)).iloc[-1] == 1.0
    hl_ok = df30["low"].rolling(6).apply(lambda x: (pd.Series(x).is_monotonic_decreasing)).iloc[-1] == 1.0
    rsi15 = _safe_last(calc_rsi(df15["close"], 14))
    aux = int((hh_ok and hl_ok) or (rsi15 < 52))  # 숏 보조(느슨)
    ok = bool(cond_30 and cond_15)
    return ok, {"cond_30": int(cond_30), "cond_15": int(cond_15), "aux": aux}

# ---------- 눌림(5m) ----------
def _pullback_long_5m(df5: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20); ema50_5 = _ema(df5["close"], 50)
    atr15 = _calc_atr(df15, 14); ema20_15 = _ema(df15["close"], 20)
    below_ema20_recent = _last_n_bars_below(df5["close"], ema20_5, 1, 3)
    touch_ema50_or_near = (_safe_last(df5["low"]) <= _safe_last(ema50_5)) or \
                          (abs(_safe_last(df5["close"]) - _safe_last(ema20_15)) <= (0.25 * _safe_last(atr15)))
    vol_contract = _safe_last(df5["volume"].iloc[-3:].mean()) < _safe_last(_sma(df5["volume"], 20))
    fib_ok, fib_meta = _fib_retracement_ok(df5, 20)  # 선택
    ok = bool(below_ema20_recent and touch_ema50_or_near and vol_contract)
    return ok, {"below_ema20_recent": int(below_ema20_recent),
                "touch_ema50_or_near": int(touch_ema50_or_near),
                "vol_contract": int(vol_contract),
                "fib_ok": int(fib_ok), "fib": fib_meta.get("fib_ratio")}

def _pullback_short_5m(df5: pd.DataFrame, df15: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_5 = _ema(df5["close"], 20); ema50_5 = _ema(df5["close"], 50)
    atr15 = _calc_atr(df15, 14); ema20_15 = _ema(df15["close"], 20)
    above_ema20_recent = _last_n_bars_below(-df5["close"], -ema20_5, 1, 3)
    touch_ema50_or_near = (_safe_last(df5["high"]) >= _safe_last(ema50_5)) or \
                          (abs(_safe_last(df5["close"]) - _safe_last(ema20_15)) <= (0.25 * _safe_last(atr15)))
    vol_contract = _safe_last(df5["volume"].iloc[-3:].mean()) < _safe_last(_sma(df5["volume"], 20))
    # 간단 숏용 fib
    ref = df5.iloc[:-1] if len(df5) > 1 else df5
    ll = float(ref['low'].rolling(20).min().iloc[-1]); hh = float(ref['high'].rolling(20).max().iloc[-1]); px = float(df5['close'].iloc[-1])
    ratio_up = (px - ll)/(hh - ll + 1e-12)
    fib_ok = 0.382 <= ratio_up <= 0.618
    ok = bool(above_ema20_recent and touch_ema50_or_near and vol_contract)
    return ok, {"above_ema20_recent": int(above_ema20_recent),
                "touch_ema50_or_near": int(touch_ema50_or_near),
                "vol_contract": int(vol_contract),
                "fib_ok": int(fib_ok)}

# ---------- 트리거(1m/5m) ----------
def _trigger_long(df5: pd.DataFrame, df1: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    # 1m 조건
    ema20_1 = _ema(df1["close"], 20)
    v1 = df1["volume"]; vol_ok_1m = _safe_last(v1) > _safe_last(_sma(v1, 20))
    engulf = _bullish_engulfing_1m(df1)
    reclaim_1m = (df1["close"].iloc[-1] > ema20_1.iloc[-1]) and (df1["close"].iloc[-2] <= ema20_1.iloc[-2])
    vwap1 = _vwap(df1, 20); vwap_reclaim = (df1["close"].iloc[-1] > vwap1.iloc[-1]) and (df1["close"].iloc[-2] <= vwap1.iloc[-2])
    micro_hh = df1["close"].iloc[-1] > df1["high"].rolling(8).max().iloc[-2]
    ok_1m = vol_ok_1m and (engulf or reclaim_1m or vwap_reclaim or micro_hh)

    # 5m 보조(기존)
    ema20_5 = _ema(df5["close"], 20)
    reclaim_5m = (_safe_last(df5["close"]) > _safe_last(ema20_5)) and (df5["close"].iloc[-2] <= ema20_5.iloc[-2])
    vol_spike_5m = _safe_last(df5["volume"]) > _safe_last(_sma(df5["volume"], 20)) * 1.2
    ok_5m = reclaim_5m and vol_spike_5m

    ok = bool(ok_1m or ok_5m)
    return ok, {"engulf_1m": int(engulf), "vol_ok_1m": int(vol_ok_1m),
                "reclaim_1m": int(reclaim_1m), "vwap_1m": int(vwap_reclaim),
                "micro_hh": int(micro_hh), "reclaim_5m": int(reclaim_5m), "vol_spike_5m": int(vol_spike_5m)}

def _trigger_short(df5: pd.DataFrame, df1: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    ema20_1 = _ema(df1["close"], 20)
    v1 = df1["volume"]; vol_ok_1m = _safe_last(v1) > _safe_last(_sma(v1, 20))
    engulf = _bearish_engulfing_1m(df1)
    reclaim_1m = (df1["close"].iloc[-1] < ema20_1.iloc[-1]) and (df1["close"].iloc[-2] >= ema20_1.iloc[-2])
    vwap1 = _vwap(df1, 20); vwap_reclaim = (df1["close"].iloc[-1] < vwap1.iloc[-1]) and (df1["close"].iloc[-2] >= vwap1.iloc[-2])
    micro_ll = df1["close"].iloc[-1] < df1["low"].rolling(8).min().iloc[-2]
    ok_1m = vol_ok_1m and (engulf or reclaim_1m or vwap_reclaim or micro_ll)

    ema20_5 = _ema(df5["close"], 20)
    reclaim_5m = (_safe_last(df5["close"]) < _safe_last(ema20_5)) and (df5["close"].iloc[-2] >= ema20_5.iloc[-2])
    vol_spike_5m = _safe_last(df5["volume"]) > _safe_last(_sma(df5["volume"], 20)) * 1.2
    ok_5m = reclaim_5m and vol_spike_5m

    ok = bool(ok_1m or ok_5m)
    return ok, {"engulf_1m": int(engulf), "vol_ok_1m": int(vol_ok_1m),
                "reclaim_1m": int(reclaim_1m), "vwap_1m": int(vwap_reclaim),
                "micro_ll": int(micro_ll), "reclaim_5m": int(reclaim_5m), "vol_spike_5m": int(vol_spike_5m)}

# ---------- 엔트리/리스크 ----------
def _entry_sl_tp_long(df5: pd.DataFrame) -> Tuple[float, float, float]:
    price = _safe_last(df5["close"])
    atr5 = _safe_last(_calc_atr(df5, 14))
    sw_low = df5["low"].rolling(6).min().iloc[-2] if len(df5) >= 6 else df5["low"].min()
    sl = float(sw_low - 0.3 * (atr5 if not math.isnan(atr5) else price*0.01))  # ▶ 0.3×ATR_5m
    r = max(1e-6, price - sl)
    tp = float(price + 1.8 * r)
    return price, sl, tp

def _entry_sl_tp_short(df5: pd.DataFrame) -> Tuple[float, float, float]:
    price = _safe_last(df5["close"])
    atr5 = _safe_last(_calc_atr(df5, 14))
    sw_high = df5["high"].rolling(6).max().iloc[-2] if len(df5) >= 6 else df5["high"].max()
    sl = float(sw_high + 0.3 * (atr5 if not math.isnan(atr5) else price*0.01))
    r = max(1e-6, sl - price)
    tp = float(price - 1.8 * r)
    return price, sl, tp

# ---------- 공개 API ----------
def _coerce_frames(args, kwargs):
    if len(args) == 1 and isinstance(args[0], dict):
        d = args[0]
        return d.get("30m") or d.get("m30"), d.get("15m") or d.get("m15"), d.get("5m") or d.get("m5"), d.get("1m") or d.get("m1")
    elif len(args) >= 4:
        return args[0], args[1], args[2], args[3]
    else:
        return kwargs.get("df30"), kwargs.get("df15"), kwargs.get("df5"), kwargs.get("df1")

def multi_frame_signal(*args, **kwargs) -> Tuple[str, Dict[str, Any]]:
    df30, df15, df5, df1 = _coerce_frames(args, kwargs)
    if any(x is None or len(x) < 30 for x in [df30, df15, df5]) or df1 is None or len(df1) < 3:
        return "NONE", {"raw": 0.0, "15m": 0, "5m": 0, "RSI": float("nan"), "VOL": 0, "reason": "insufficient_data"}

    rsi5 = _safe_last(calc_rsi(df5["close"], 14))

    # LONG
    tr_up, up_info = _trend_up_30m15m(df30, df15)
    pb_long, pb_info_l = _pullback_long_5m(df5, df15)
    tg_long, tg_info_l = _trigger_long(df5, df1)
    room_long = True  # 공간 체크는 기존처럼 느슨하게
    raw_long = 0.0
    if tr_up: raw_long += 1.2 + 0.2*up_info.get("aux", 0)
    if pb_long: raw_long += 1.0 + 0.3*pb_info_l.get("fib_ok", 0)
    if tg_long: raw_long += 1.0
    if room_long: raw_long += 0.3

    # SHORT
    tr_dn, dn_info = _trend_down_30m15m(df30, df15)
    pb_short, pb_info_s = _pullback_short_5m(df5, df15)
    tg_short, tg_info_s = _trigger_short(df5, df1)
    room_short = True
    raw_short = 0.0
    if tr_dn: raw_short += 1.2 + 0.2*dn_info.get("aux", 0)
    if pb_short: raw_short += 1.0 + 0.3*pb_info_s.get("fib_ok", 0)
    if tg_short: raw_short += 1.0
    if room_short: raw_short += 0.3

    if raw_long > raw_short and raw_long >= 2.0:
        direction = "LONG"
        entry, sl, tp = _entry_sl_tp_long(df5)
        f15 = int(up_info.get("cond_15", 0)); f5 = int(tg_info_l.get("reclaim_1m", 0) or tg_info_l.get("micro_hh", 0))
        vol_flag = int(tg_info_l.get("vol_ok_1m", 0))
        raw = float(raw_long); reason = "trend_up & pullback & trigger"
    elif raw_short > raw_long and raw_short >= 2.0:
        direction = "SHORT"
        entry, sl, tp = _entry_sl_tp_short(df5)
        f15 = int(dn_info.get("cond_15", 0)); f5 = int(tg_info_s.get("reclaim_1m", 0) or tg_info_s.get("micro_ll", 0))
        vol_flag = int(tg_info_s.get("vol_ok_1m", 0))
        raw = float(raw_short); reason = "trend_down & pullback & trigger"
    else:
        # 약신호(가끔 보고용) — p컷에서 걸러질 것
        if raw_long >= raw_short:
            direction = "LONG"; entry, sl, tp = _entry_sl_tp_long(df5)
            f15 = int(up_info.get("cond_15", 0)); f5 = int(pb_info_l.get("below_ema20_recent", 0)); vol_flag = 0
            raw = float(raw_long); reason = "weak_long_bias"
        else:
            direction = "SHORT"; entry, sl, tp = _entry_sl_tp_short(df5)
            f15 = int(dn_info.get("cond_15", 0)); f5 = int(pb_info_s.get("above_ema20_recent", 0)); vol_flag = 0
            raw = float(raw_short); reason = "weak_short_bias"

    payload = {"raw": raw, "15m": f15, "5m": f5, "RSI": float(rsi5), "VOL": vol_flag,
               "entry": float(entry), "sl": float(sl), "tp": float(tp), "reason": reason}
    try:
        stats.record("strategy_multi_tf", {"direction": direction, "raw": raw, "f15": f15, "f5": f5,
                                           "rsi5": payload["RSI"], "vol": vol_flag, "reason": reason})
    except Exception: pass
    return direction, payload
