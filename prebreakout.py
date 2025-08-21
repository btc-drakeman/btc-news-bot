# prebreakout.py
# -----------------------------------------
# "큰 캔들이 터지기 직전" 사전예측(Watch) 알림 v6
# 조건: (5m 압축) + (볼륨 lull→uptick) + (15m/5m 추세 일치)
#     + (HH/LL 근접) + (1m 미세확인)
# 진입: 선행 Limit(레벨±0.1*ATR) + Fallback Stop-Limit
# -----------------------------------------

import time
import numpy as np
import pandas as pd
from analyzer import fetch_ohlcv
from notifier import send_telegram
from config import SYMBOLS, format_price, SL_PCT, TP_PCT

# ===== 파라미터 =====
COOLDOWN_SEC       = 300        # 심볼/방향별 쿨다운
NEAR_TOL_BPS       = 25.0       # HH/LL 근접 허용치(bps: 0.25%)
VOLUME_LULL_K      = 0.80       # lull: 직전 3봉 평균 ≤ 0.8 * 30봉 중앙값
VOLUME_UPTICK_K    = 1.20       # uptick: 마지막 봉 ≥ 1.2 * 30봉 중앙값
BBW_RATIO_MAX      = 0.60       # BB폭(현재) ≤ 50봉 중앙값 * 0.60
ATR_RATIO_MAX      = 0.70       # ATR(현재) ≤ 50봉 중앙값 * 0.70
EMA_FAST           = 34         # 15m 추세 판단용
EMA_SLOW           = 89
ONE_MIN_LOOKBACK   = 20         # 1m 미세확인용 롤링
MICRO_VOL_MIN      = 1.00       # 1m 마지막 봉 거래량 ≥ med*1.00
PREENTRY_ATR_BUF   = 0.10       # 선행 리밋 버퍼: 레벨 ± 0.10*ATR(5m)
FALLBACK_ATR_BUF   = 0.02       # Fallback 스탑-리밋: 레벨 ± 0.02*ATR(5m)
FAILFAST_ATR_MOVE  = 0.20       # 체결 후 180초 내 ±0.2*ATR 진행 없으면 컷 권고
FAILFAST_DEADLINE  = 180        # 초
PB_MARGIN          = 2.0        # (기존 1m 압력 점수 우위 최소 격차 사용)

_last_watch_ts = {}  # key="BTCUSDT:LONG" -> epoch

# ---------- 공용 지표 ----------
def ema(s: pd.Series, span: int):
    return s.ewm(span=span, adjust=False).mean()

def calc_atr(df: pd.DataFrame, period: int = 14):
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def bb_width(close: pd.Series, period: int = 20, k: float = 2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = ma + k * sd
    lower = ma - k * sd
    return (upper - lower) / (ma + 1e-12)

# ---------- 보조 ----------
def _cooldown_ok(symbol: str, direction: str, sec: int = COOLDOWN_SEC) -> bool:
    key = f"{symbol}:{direction}"
    now = time.time()
    ts = _last_watch_ts.get(key)
    if ts and now - ts < sec:
        return False
    _last_watch_ts[key] = now
    return True

def _levels_5m(df5: pd.DataFrame, lookback: int = 20):
    ref = df5.iloc[:-1]  # 완료봉 기준
    hh = float(ref['high'].rolling(lookback).max().iloc[-1])
    ll = float(ref['low'] .rolling(lookback).min().iloc[-1])
    px = float(df5['close'].iloc[-1])
    return hh, ll, px

def _near_bps(price: float, level: float, max_bps: float) -> (bool, float):
    bps = abs(price - level) / max(price, 1e-12) * 1e4
    return (bps <= max_bps), bps

# ---------- v6: 조건 묶음 ----------
def _compression_ok(df5: pd.DataFrame) -> (bool, dict):
    atr = calc_atr(df5, 14)
    bbw = bb_width(df5['close'], 20, 2.0)

    med_bbw = bbw.rolling(50).median().iloc[-1]
    med_atr = atr.rolling(50).median().iloc[-1]
    bbw_ratio = float(bbw.iloc[-1] / (med_bbw + 1e-12))
    atr_ratio = float(atr.iloc[-1] / (med_atr + 1e-12))
    ok = (bbw_ratio <= BBW_RATIO_MAX) and (atr_ratio <= ATR_RATIO_MAX)
    return ok, {"bbw": float(bbw.iloc[-1]), "bbw_ratio": bbw_ratio, "atr_ratio": atr_ratio}

def _volume_lull_then_uptick(df5: pd.DataFrame) -> (bool, dict):
    vol = df5['volume']
    base = vol.rolling(30).median().iloc[-1]
    lull = (vol.iloc[-4:-1].mean() <= base * VOLUME_LULL_K)
    uptick = (vol.iloc[-1] >= base * VOLUME_UPTICK_K)
    return (lull and uptick), {
        "base_med": float(base),
        "last_over_med": float(vol.iloc[-1] / (base + 1e-12)),
        "lull_mean_over_med": float(vol.iloc[-4:-1].mean() / (base + 1e-12))
    }

def _trend_agree(df15: pd.DataFrame, df5: pd.DataFrame) -> (str, dict):
    e34_15 = float(ema(df15['close'], EMA_FAST).iloc[-1])
    e89_15 = float(ema(df15['close'], EMA_SLOW).iloc[-1])
    e34_5  = ema(df5['close'], EMA_FAST)
    slope5 = float(e34_5.iloc[-1] - e34_5.iloc[-4])

    if e34_15 > e89_15 and slope5 > 0:
        return "LONG", {"ema34_15": e34_15, "ema89_15": e89_15, "slope5": slope5}
    if e34_15 < e89_15 and slope5 < 0:
        return "SHORT", {"ema34_15": e34_15, "ema89_15": e89_15, "slope5": slope5}
    return "FLAT", {"ema34_15": e34_15, "ema89_15": e89_15, "slope5": slope5}

def _micro_confirm_1m(df1: pd.DataFrame, direction: str) -> (bool, dict):
    if len(df1) < ONE_MIN_LOOKBACK + 2:
        return False, {"reason": "insufficient_1m"}
    vol = df1['volume']
    med = float(vol.rolling(ONE_MIN_LOOKBACK).median().iloc[-1])
    v_ok = float(vol.iloc[-1]) >= med * MICRO_VOL_MIN
    hi_prev = float(df1['high'].iloc[-2])
    lo_prev = float(df1['low'].iloc[-2])
    c_last = float(df1['close'].iloc[-1])
    if direction == "LONG":
        p_ok = (c_last > hi_prev)
    elif direction == "SHORT":
        p_ok = (c_last < lo_prev)
    else:
        return False, {"reason": "flat_direction"}
    return (p_ok and v_ok), {"vol_last_over_med": (vol.iloc[-1] / (med + 1e-12)), "c_last": c_last, "hi_prev": hi_prev, "lo_prev": lo_prev}

# ---------- (기존) 1m 압력 점수 재사용 ----------
def _pressure_direction_1m(df1: pd.DataFrame, lookback: int = 8):
    last = df1.tail(lookback).copy()
    if len(last) < lookback:
        return "NEUTRAL", 0.0, 0.0, {}

    hi, lo, op, cl, vol = last["high"], last["low"], last["open"], last["close"], last["volume"]
    span = (hi - lo).replace(0, np.nan)
    if span.isna().any():
        return "NEUTRAL", 0.0, 0.0, {}

    top_close_ratio = float(((cl - lo) / (span + 1e-12)).clip(0,1).mean())
    bot_close_ratio = float(((hi - cl) / (span + 1e-12)).clip(0,1).mean())
    hl_cnt = int((lo.diff() > 0).sum())
    lh_cnt = int((hi.diff() < 0).sum())
    up_vol   = float(vol[cl > op].sum())
    down_vol = float(vol[cl < op].sum())
    delta_proxy = float((np.sign(cl.diff().fillna(0)) * vol).sum())
    pv = (cl * vol)
    vwap = pv.cumsum() / (vol.cumsum() + 1e-12)
    above_vwap = int((cl > vwap).sum())
    below_vwap = int((cl < vwap).sum())
    hh_cnt = int((hi > hi.shift()).sum())
    ll_cnt = int((lo < lo.shift()).sum())

    score_long = 0.0
    score_long += 1.0 if top_close_ratio >= 0.70 else 0.0
    score_long += 1.0 if hl_cnt >= lookback//2 else 0.0
    score_long += 1.0 if up_vol > down_vol else 0.0
    score_long += 1.0 if delta_proxy > 0 else 0.0
    score_long += 0.5 if above_vwap >= lookback//2 else 0.0
    score_long += 0.5 if hh_cnt >= lookback//2 else 0.0

    score_short = 0.0
    score_short += 1.0 if bot_close_ratio >= 0.70 else 0.0
    score_short += 1.0 if lh_cnt >= lookback//2 else 0.0
    score_short += 1.0 if down_vol > up_vol else 0.0
    score_short += 1.0 if delta_proxy < 0 else 0.0
    score_short += 0.5 if below_vwap >= lookback//2 else 0.0
    score_short += 0.5 if ll_cnt >= lookback//2 else 0.0

    if score_long - score_short >= PB_MARGIN:
        direction = "LONG"
    elif score_short - score_long >= PB_MARGIN:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    details = {
        "top_close_ratio": round(top_close_ratio, 3),
        "bot_close_ratio": round(bot_close_ratio, 3),
        "hl_cnt": hl_cnt, "lh_cnt": lh_cnt,
        "up_vol": round(up_vol, 3), "down_vol": round(down_vol, 3),
        "delta_proxy": round(delta_proxy, 3),
        "above_vwap": above_vwap, "below_vwap": below_vwap,
        "hh_cnt": hh_cnt, "ll_cnt": ll_cnt
    }
    return direction, float(score_long), float(score_short), details

def _build_msg(symbol: str, d: dict):
    emo = "🔼" if d["direction"] == "LONG" else "🔽"
    level_name = "HH20" if d["direction"] == "LONG" else "LL20"
    msg = (
        f"⏳ 프리-브레이크아웃 v6(준비): {symbol}\n"
        f"{emo} 방향: {d['direction']} | 점수: {d['score']}/6.0 | dist {d['dist_bps']:.1f}bp\n"
        f"📍 레벨: {level_name} = {format_price(d['ref_level'])}\n"
        f"📦 압축: BBw_ratio={d['meta']['compression']['bbw_ratio']:.2f}, ATR_ratio={d['meta']['compression']['atr_ratio']:.2f}\n"
        f"🔊 볼륨: last/med={d['meta']['volume']['last_over_med']:.2f}, lull_mean/med={d['meta']['volume']['lull_mean_over_med']:.2f}\n"
        f"🧭 추세(15m/5m): EMA34 vs 89, slope5={d['meta']['trend']['slope5']:.2f}\n"
        f"🧩 1m 확인: ok (last_over_med={d['meta']['micro']['vol_last_over_med']:.2f})\n"
        f"💡 선행 Limit: {format_price(d['pre_entry'])} | Fallback SLmt: {format_price(d['stop_entry'])}\n"
        f"🛑 예시 SL: {format_price(d['sl'])} | 🎯 TP1: {format_price(d['tp1'])} / TP2: {format_price(d['tp2'])}\n"
        f"⏱️ 체결 후 {FAILFAST_DEADLINE}초 내 ±{int(FAILFAST_ATR_MOVE*100)}%*ATR 진행 없으면 강제 종료 권장"
    )
    return msg

# =============== 공개 함수(메인 훅) =================
def analyze_prebreakout(symbol: str) -> str | None:
    """
    기존 인터페이스 유지.
    5m 마감 이벤트 or 1분 루프에서 호출 가능.
    """
    # 데이터 로드
    df5  = fetch_ohlcv(symbol, "5m", 200)
    df15 = fetch_ohlcv(symbol, "15m", 200)
    df1  = fetch_ohlcv(symbol, "1m",  80)

    for df in (df5, df15, df1):
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)

    # 1) 압축
    comp_ok, comp_meta = _compression_ok(df5)
    if not comp_ok:
        return None

    # 2) 볼륨 패턴
    vol_ok, vol_meta = _volume_lull_then_uptick(df5)
    if not vol_ok:
        return None

    # 3) 상위 추세 동의
    trend_dir, trend_meta = _trend_agree(df15, df5)
    if trend_dir == "FLAT":
        return None

    # 4) 레벨 근접
    hh, ll, px = _levels_5m(df5, 20)
    if trend_dir == "LONG":
        near_ok, dist_bps = _near_bps(px, hh, NEAR_TOL_BPS)
        if not near_ok:
            return None
        direction = "LONG"
        ref_level = hh
    else:
        near_ok, dist_bps = _near_bps(px, ll, NEAR_TOL_BPS)
        if not near_ok:
            return None
        direction = "SHORT"
        ref_level = ll

    # 5) 1m 미세확인 + (기존 압력 점수) 교차검증
    micro_ok, micro_meta = _micro_confirm_1m(df1, direction)
    if not micro_ok:
        return None
    press_dir, score_l, score_s, press_meta = _pressure_direction_1m(df1, lookback=8)
    if press_dir != direction:
        return None

    # 쿨다운
    if not _cooldown_ok(symbol, direction):
        return None

    # 엔트리/리스크
    atr5 = float(calc_atr(df5, 14).iloc[-1])
    if direction == "LONG":
        pre_entry  = float(max(px, ref_level - PREENTRY_ATR_BUF * atr5))
        stop_entry = float(ref_level + FALLBACK_ATR_BUF * atr5)
        sl = float(ref_level - 1.0 * atr5)
        r  = pre_entry - sl
        tp1 = float(pre_entry + 1.8 * r)
        tp2 = float(pre_entry + 3.0 * r)
        level_name = "HH20"
    else:
        pre_entry  = float(min(px, ref_level + PREENTRY_ATR_BUF * atr5))
        stop_entry = float(ref_level - FALLBACK_ATR_BUF * atr5)
        sl = float(ref_level + 1.0 * atr5)
        r  = sl - pre_entry
        tp1 = float(pre_entry - 1.8 * r)
        tp2 = float(pre_entry - 3.0 * r)
        level_name = "LL20"

    # 점수(가중치): 압축2 + 볼륨1.5 + 추세1 + 레벨근접0.5 + 1m확인1 = 6
    score = 2.0 + 1.5 + 1.0 + (0.5 if dist_bps <= 12.0 else 0.25) + 1.0

    payload = {
        "direction": direction,
        "ref_level": float(ref_level),
        "dist_bps": float(dist_bps),
        "pre_entry": float(pre_entry),
        "stop_entry": float(stop_entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "score": float(round(score, 2)),
        "meta": {
            "compression": comp_meta,
            "volume": vol_meta,
            "trend": trend_meta,
            "micro": micro_meta,
            "press": press_meta,
        }
    }

    msg = _build_msg(symbol, payload)
    send_telegram(msg)
    return msg

def prebreakout_loop(sleep_sec: int = 60):
    """
    기존 루프 유지.
    WS 기반이면 5m 마감 이벤트에서 analyze_prebreakout(symbol) 호출 권장.
    """
    print("🔭 프리-브레이크아웃 루프 시작")
    while True:
        try:
            for s in SYMBOLS:
                try:
                    analyze_prebreakout(s)
                except Exception as e:
                    print(f"❌ prebreakout({s}) 실패: {e}")
            time.sleep(sleep_sec)
        except Exception as e:
            print("프리브레이크 루프 에러:", e)
            time.sleep(1)
