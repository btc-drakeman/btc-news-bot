# strategy.py — Mean Reversion v2 (adaptive R + split TP + trail)
# 기존: 평균회귀(횡보장 전용) 고정 R:R=1:1.8
# 변경: ① 과이탈 강화(가변 진입 조건) ② Adaptive R(1.8~2.6) ③ 2단계 청산 + ATR 트레일
# analyzer.py는 multi_frame_signal(df30, df15, df5, df1) 호출을 기대하므로 시그니처 유지.

import math
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd
import stats  # 텔레메트리(호출 시그니처 차이 있어도 try/except로 무시)

# =========================
# 유틸
# =========================
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def _sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window=window, min_periods=max(2, window//2)).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss.replace(0, 1e-12))
    return 100 - (100 / (1 + rs))

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]).abs(),
                    (df["high"]-pc).abs(),
                    (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _vwap(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).rolling(lookback).sum()
    vv = df["volume"].rolling(lookback).sum()
    return pv / (vv + 1e-12)

def _bb(close: pd.Series, period: int = 20, k: float = 2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = ma + k*sd
    lower = ma - k*sd
    width = (upper - lower) / (ma + 1e-12)
    return upper, ma, lower, width

def _safe_last(x, default=float("nan")):
    try:
        return float(x.iloc[-1])
    except Exception:
        return default

# =========================
# 설정값(튜닝 포인트)
# =========================

# (1) 횡보장 필터: BB폭/ATR가 평소 대비 작고, 15m 추세 기울기 완만
RANGE_BBW_MAX = 0.75    # 현재 BB 폭 <= 과거 중앙값 * 0.75
RANGE_ATR_MAX = 0.75    # 현재 ATR <= 과거 중앙값 * 0.75
SLOPE_EPS     = 0.001   # 15m EMA34 기울기(절대) 허용 최대(평탄함)

# (2) 과이탈 기본 요구치(가변화 전 base)
VWAP_DEV_MIN_BASE  = 0.008   # 0.8%
MA_DEV_MIN_BASE    = 0.006   # 0.6%

# (3) 오실레이터 극단값: RSI 기준
RSI_BUY_MAX   = 35.0    # 이하면 과매도(롱 후보)
RSI_SELL_MIN  = 65.0    # 이상이면 과매수(숏 후보)

# (4) 1분 확인: 반전 캔들 + 거래량
ONE_MIN_VOL_K = 1.00    # 1m 마지막 봉 거래량 ≥ 롤링 중앙값*1.0
ONE_MIN_LOOK  = 20

# (5) R:R(익절배수) — Adaptive 범위
RR_BASE = 1.8
RR_MAX  = 2.6

# (6) 트레일링 ATR 배수 (분할 이후 잔여 물량 보호)
TRAIL_ATR_K = 0.8

# (7) SL 계산시 ATR 계수 + 스윙 버퍼
SL_ATR_K     = 0.8
SWING_ATR_K  = 0.2

# =========================
# 평균회귀용 조건 (정교화)
# =========================
def _range_regime(df15: pd.DataFrame, df5: pd.DataFrame) -> Tuple[bool, Dict[str, Any]]:
    # 5m BB, ATR 기준으로 변동성 축소 확인
    _, _, _, bbw = _bb(df5["close"], 20, 2.0)
    atr5 = _atr(df5, 14)

    bbw_med = float(bbw.rolling(50).median().iloc[-1])
    atr_med = float(atr5.rolling(50).median().iloc[-1])

    bbw_ratio = float(bbw.iloc[-1] / (bbw_med + 1e-12))
    atr_ratio = float(atr5.iloc[-1] / (atr_med + 1e-12))

    # 15m 추세 기울기 완만(평탄) 여부
    ema34_15 = _ema(df15["close"], 34)
    slope = float(ema34_15.iloc[-1] - ema34_15.iloc[-4]) / (abs(ema34_15.iloc[-4]) + 1e-12)

    ok = (bbw_ratio <= RANGE_BBW_MAX) and (atr_ratio <= RANGE_ATR_MAX) and (abs(slope) <= SLOPE_EPS)
    meta = {"bbw_ratio": round(bbw_ratio, 3), "atr_ratio": round(atr_ratio, 3), "slope": round(slope, 5)}
    return ok, meta

def _required_deviation(bbw_ratio: float) -> Tuple[float, float]:
    """
    BB 폭이 매우 좁을수록(=횡보 심화) 요구 괴리폭을 더 키운다.
    bbw_ratio ~ 0.5일 때 요구치가 약 +0.4%p 정도 가산되도록.
    """
    # 가산치: (목표 최소치 - bbw_ratio) * 계수, 하한 0
    add = max(0.0, (0.9 - min(1.2, bbw_ratio)) * 0.008)  # bbw_ratio가 작을수록 add ↑ (최대 ~0.008=0.8%p)
    vwap_req = VWAP_DEV_MIN_BASE + add
    ma_req   = MA_DEV_MIN_BASE + add * 0.8
    return vwap_req, ma_req

def _deviation_setup(df5: pd.DataFrame, vwap_req: float, ma_req: float) -> Tuple[str, Dict[str, Any]]:
    # VWAP/MA 대비 괴리 체크 + 볼린저 터치/이탈 확인
    vwap = _vwap(df5, 20)
    u, ma, l, _ = _bb(df5["close"], 20, 2.0)

    px   = _safe_last(df5["close"])
    vwp  = _safe_last(vwap)
    base = max(vwp, 1e-12)
    dev_vwap = (px - vwp) / base
    dev_ma   = (px - _safe_last(ma)) / (abs(_safe_last(ma)) + 1e-12)

    touch_low  = px <= _safe_last(l)
    touch_up   = px >= _safe_last(u)
    over_low   = px < _safe_last(l) - 0.25*(_safe_last(u) - _safe_last(l))
    over_up    = px > _safe_last(u) + 0.25*(_safe_last(u) - _safe_last(l))

    # 롱: 하단 과이탈 + 음의 괴리 충분
    if (dev_vwap <= -vwap_req or dev_ma <= -ma_req) and (touch_low or over_low):
        return "LONG", {
            "dev_vwap": round(float(dev_vwap), 4),
            "dev_ma": round(float(dev_ma), 4),
            "band": "lower" if touch_low else ("over_lower" if over_low else "none")
        }
    # 숏: 상단 과이탈 + 양의 괴리 충분
    if (dev_vwap >= vwap_req or dev_ma >= ma_req) and (touch_up or over_up):
        return "SHORT", {
            "dev_vwap": round(float(dev_vwap), 4),
            "dev_ma": round(float(dev_ma), 4),
            "band": "upper" if touch_up else ("over_upper" if over_up else "none")
        }
    return "NONE", {"dev_vwap": round(float(dev_vwap), 4), "dev_ma": round(float(dev_ma), 4), "band": "none"}

def _osc_filter(df5: pd.DataFrame, direction_hint: str) -> Tuple[bool, Dict[str, Any]]:
    rsi = _rsi(df5["close"], 14)
    r = _safe_last(rsi)
    if direction_hint == "LONG":
        ok = (r <= RSI_BUY_MAX)
    elif direction_hint == "SHORT":
        ok = (r >= RSI_SELL_MIN)
    else:
        ok = False
    return ok, {"rsi": round(r, 1)}

def _confirm_1m(df1: pd.DataFrame, direction: str) -> Tuple[bool, Dict[str, Any]]:
    if df1 is None or len(df1) < ONE_MIN_LOOK + 2:
        return False, {"reason": "insufficient_1m"}

    vol = df1["volume"]
    vol_med = float(vol.rolling(ONE_MIN_LOOK).median().iloc[-1])
    vol_ok = float(vol.iloc[-1]) >= vol_med * ONE_MIN_VOL_K

    o1, c1, h1, l1 = df1["open"].iloc[-1], df1["close"].iloc[-1], df1["high"].iloc[-1], df1["low"].iloc[-1]
    o2, c2 = df1["open"].iloc[-2], df1["close"].iloc[-2]

    if direction == "LONG":
        # 직전 음봉 → 현재 양봉 전환 or 직전 고점 상향
        candle_ok = (c1 > o1 and c2 <= o2) or (c1 > h1)
    else:
        # 직전 양봉 → 현재 음봉 전환 or 직전 저점 하향
        candle_ok = (c1 < o1 and c2 >= o2) or (c1 < l1)

    ok = bool(vol_ok and candle_ok)
    return ok, {"vol_last_over_med": round(float(vol.iloc[-1] / (vol_med + 1e-12)), 2),
                "candle": int(candle_ok)}

# =========================
# 엔트리/리스크
# =========================
def _adaptive_rr(dev_mag: float, base: float = RR_BASE, rr_max: float = RR_MAX) -> float:
    """
    dev_mag(절대 괴리, 예: 0.012 = 1.2%)가 클수록 R:R 상향.
    dev 1% → +0.4배(예: 1.8 → 2.2) 정도로 스케일.
    """
    return float(base + min(rr_max - base, max(0.0, dev_mag) * 40.0))

def _entry_sl_tp(df5: pd.DataFrame,
                 direction: str,
                 dev_mag: float,
                 bbw_ratio: float) -> Tuple[float, float, float, float, float, float]:
    """
    반환: entry, sl, tp2(최종), tp1(분할1), trail_atr, r_multiple
    - SL: 스윙 극값 ± ATR 버퍼 & ATR 계수 방식(더 보수적)
    - TP1: 1.0R, TP2: Adaptive RR * R
    - trail_atr: 잔여 물량 보호용
    """
    px = _safe_last(df5["close"])
    atr_series = _atr(df5, 14)
    atr5 = _safe_last(atr_series)
    if math.isnan(atr5) or atr5 <= 0:
        atr5 = px * 0.01  # 안전장치

    # 스윙 기준점: 직전 6봉 extreme
    if len(df5) >= 6:
        sw_low  = df5["low"].rolling(6).min().iloc[-2]
        sw_high = df5["high"].rolling(6).max().iloc[-2]
    else:
        sw_low, sw_high = df5["low"].min(), df5["high"].max()

    if direction == "LONG":
        # 스윙 저점에 ATR 버퍼를 빼고, px - ATR*K 와 비교하여 더 낮은 SL 채택
        swing_based = float(sw_low - SWING_ATR_K * atr5)
        atr_based   = float(px - SL_ATR_K * atr5)
        sl = float(min(swing_based, atr_based))
        r  = max(1e-6, px - sl)
        rr = _adaptive_rr(dev_mag)
        tp1 = float(px + 1.0 * r)
        tp2 = float(px + rr  * r)
    else:
        swing_based = float(sw_high + SWING_ATR_K * atr5)
        atr_based   = float(px + SL_ATR_K * atr5)
        sl = float(max(swing_based, atr_based))
        r  = max(1e-6, sl - px)
        rr = _adaptive_rr(dev_mag)
        tp1 = float(px - 1.0 * r)
        tp2 = float(px - rr  * r)

    trail_atr = float(TRAIL_ATR_K * atr5)
    return float(px), float(sl), float(tp2), float(tp1), float(trail_atr), float(rr)

# =========================
# 공개 API (analyzer가 호출)
# =========================
def multi_frame_signal(df30: pd.DataFrame,
                       df15: pd.DataFrame,
                       df5:  pd.DataFrame,
                       df1:  pd.DataFrame) -> Tuple[str, Dict[str, Any]]:
    # 데이터 충분성 체크
    if any(x is None or len(x) < 60 for x in [df15, df5]) or df1 is None or len(df1) < 25:
        return "NONE", {"raw": 0.0, "15m": 0, "5m": 0, "RSI": float("nan"), "VOL": 0, "reason": "insufficient_data"}

    # 1) 횡보장 필터
    range_ok, range_meta = _range_regime(df15, df5)
    bbw_ratio = float(range_meta.get("bbw_ratio", 1.0))

    # 2) 가변 요구 괴리 폭 산출(횡보 심할수록 요구치 상향)
    vwap_req, ma_req = _required_deviation(bbw_ratio)

    # 3) 괴리/밴드 이탈로 방향 힌트
    direction_hint, dev_meta = _deviation_setup(df5, vwap_req=vwap_req, ma_req=ma_req)
    if direction_hint == "NONE":
        return "NONE", {
            "raw": 0.0, "15m": int(range_ok), "5m": 0, "RSI": float("nan"), "VOL": 0,
            "reason": "no_deviation",
            "meta": {"range": range_meta, "dev": dev_meta}
        }

    # 4) 오실레이터 극단값 필터
    osc_ok, osc_meta = _osc_filter(df5, direction_hint)
    if not osc_ok:
        return "NONE", {
            "raw": 0.0, "15m": int(range_ok), "5m": 0, "RSI": float(osc_meta.get("rsi", float("nan"))),
            "VOL": 0, "reason": "osc_reject",
            "meta": {"range": range_meta, "dev": dev_meta, "osc": osc_meta}
        }

    # 5) 1분 확인(반전+볼륨)
    micro_ok, micro_meta = _confirm_1m(df1, direction_hint)
    if not micro_ok:
        return "NONE", {
            "raw": 0.0, "15m": int(range_ok), "5m": 1, "RSI": float(osc_meta.get("rsi", float("nan"))),
            "VOL": 0, "reason": "micro_fail",
            "meta": {"range": range_meta, "dev": dev_meta, "osc": osc_meta, "micro": micro_meta}
        }

    # 6) RAW 점수 (p-score는 analyzer에서 sigmoid로 변환/컷)
    # 가중치: 횡보장 여부(1.0), 괴리 강도(0.8~1.2), 오실레이터 일치(0.8), 1m 확인(1.0)
    dev_mag = max(abs(dev_meta.get("dev_vwap", 0.0)), abs(dev_meta.get("dev_ma", 0.0)))
    raw = 0.0
    raw += 1.0 if range_ok else 0.6
    raw += 0.8 + min(0.4, dev_mag * 20.0)  # dev 1%면 +0.2 보너스
    raw += 0.8
    raw += 1.0

    # 7) 엔트리/리스크 (Adaptive R + 분할TP + 트레일)
    entry, sl, tp2, tp1, trail_atr, rr = _entry_sl_tp(df5, direction_hint, dev_mag, bbw_ratio)

    payload = {
        "raw": float(round(raw, 2)),
        "15m": int(range_ok),                  # analyzer에서 cond_15m 자리로 사용
        "5m":  1,                              # deviation 세팅 성공 표시
        "RSI": float(osc_meta.get("rsi", float("nan"))),
        "VOL": int(micro_meta.get("vol_last_over_med", 0) >= 1.0),

        # 가격 레벨
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp2),          # 하위호환 위해 최종 TP를 tp로 유지
        "tp1": float(tp1),         # 분할 1차
        "tp2": float(tp2),         # 분할 2차(최종)
        "trail_atr": float(trail_atr),

        # 메타/진단
        "rr_ratio": float(round(rr, 2)),
        "R": float(round(abs(entry - sl), 6)),
        "reason": f"mean_reversion|band={dev_meta.get('band')}|dev={dev_mag:.3f}|bbw={bbw_ratio:.3f}",
        "meta": {
            "range": range_meta,
            "dev": dev_meta,
            "osc": osc_meta,
            "micro": micro_meta,
            "req_deviation": {"vwap_req": vwap_req, "ma_req": ma_req}
        },
    }

    direction = "LONG" if direction_hint == "LONG" else "SHORT"

    # 텔레메트리(시그니처 차이는 무시)
    try:
        stats.record("mean_reversion_v2", {
            "direction": direction,
            "raw": payload["raw"],
            "rsi": payload["RSI"],
            "range_ok": bool(range_ok),
            "rr": payload["rr_ratio"],
            "bbw": bbw_ratio,
            "dev": float(dev_mag),
        })
    except Exception:
        pass

    return direction, payload
