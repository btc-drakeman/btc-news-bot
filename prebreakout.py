# prebreakout.py
# -----------------------------------------
# "큰 캔들이 터지기 직전"을 포착하는 준비(Watch) 알림 모듈
# 조건: 5m Squeeze + HH/LL 근접 + 1m 압력 방향 일치
# 알림: 즉시 진입 X, 스탑-리밋 진입가(레벨±0.1~0.2%)만 제안
# -----------------------------------------

import time
import numpy as np
import pandas as pd
from analyzer import fetch_ohlcv
from notifier import send_telegram
from config import SYMBOLS, format_price, SL_PCT, TP_PCT

# ===== 파라미터(필요시 조정) =====
COOLDOWN_SEC      = 300        # 심볼/방향별 5분 쿨다운
SQUEEZE_SHORT     = 10         # 5m 단기 진폭평균 윈도우
SQUEEZE_LONG      = 40         # 5m 장기 진폭평균 윈도우
SQUEEZE_RATIO_MAX = 0.65       # 단/장 평균 진폭 비율(이하면 Squeeze)
NEAR_TOL          = 0.0025     # HH/LL 까지 거리 허용치(0.25%)
PB_LOOKBACK_1M    = 8          # 1m 압력 집계 윈도우
PB_MARGIN         = 2.0        # 롱/숏 점수 우위 최소 격차
ENTRY_OFFSET      = 0.0015     # 스탑-리밋 오프셋(0.15%)

# 심볼:방향 별 최근 알림시각
_last_watch_ts = {}  # key="BTCUSDT:LONG" -> epoch


# =============== 보조 함수들 =================

def _cooldown_ok(symbol: str, direction: str, sec: int = COOLDOWN_SEC) -> bool:
    key = f"{symbol}:{direction}"
    now = time.time()
    ts = _last_watch_ts.get(key)
    if ts and now - ts < sec:
        return False
    _last_watch_ts[key] = now
    return True


def _squeeze_5m(df5: pd.DataFrame) -> bool:
    rng = (df5["high"] - df5["low"])
    short = float(rng.rolling(SQUEEZE_SHORT).mean().iloc[-1])
    long  = float(rng.rolling(SQUEEZE_LONG ).mean().iloc[-1])
    if long <= 0:
        return False
    ratio = short / long
    return ratio < SQUEEZE_RATIO_MAX


def _levels_5m(df5: pd.DataFrame, lookback: int = 20):
    # 직전 시점 기준 HH/LL (현재 봉 제외)
    hh = float(df5["high"].rolling(lookback).max().iloc[-2])
    ll = float(df5["low"] .rolling(lookback).min().iloc[-2])
    px = float(df5["close"].iloc[-1])
    return hh, ll, px


def _near_levels(px: float, hh: float, ll: float, tol: float = NEAR_TOL):
    near_hh = abs(px - hh) / (hh + 1e-12) <= tol
    near_ll = abs(px - ll) / (ll + 1e-12) <= tol
    return near_hh, near_ll


def _pressure_direction_1m(df1: pd.DataFrame, lookback: int = PB_LOOKBACK_1M):
    """
    1분 '압력' 방향 추정 (롱/숏 점수 비교)
    반환: direction in {"LONG","SHORT","NEUTRAL"}, score_long, score_short, details(dict)
    """
    last = df1.tail(lookback).copy()
    if len(last) < lookback:
        return "NEUTRAL", 0.0, 0.0, {}

    hi, lo, op, cl, vol = last["high"], last["low"], last["open"], last["close"], last["volume"]
    # (안전장치) 0폭 방지
    span = (hi - lo).replace(0, np.nan)
    if span.isna().any():
        return "NEUTRAL", 0.0, 0.0, {}

    # 1) 상/하단 마감 비율
    top_close_ratio = float(((cl - lo) / (span + 1e-12)).clip(0,1).mean())
    bot_close_ratio = float(((hi - cl) / (span + 1e-12)).clip(0,1).mean())

    # 2) Higher Low / Lower High 누적
    hl_cnt = int((lo.diff() > 0).sum())   # 롱 우호
    lh_cnt = int((hi.diff() < 0).sum())   # 숏 우호

    # 3) 업볼륨 vs 다운볼륨
    up_vol   = float(vol[cl > op].sum())
    down_vol = float(vol[cl < op].sum())

    # 4) 의사-델타(틱룰 근사)
    delta_proxy = float((np.sign(cl.diff().fillna(0)) * vol).sum())

    # 5) VWAP 체류(간단 누적)
    pv = (cl * vol)
    vwap = pv.cumsum() / (vol.cumsum() + 1e-12)
    above_vwap = int((cl > vwap).sum())
    below_vwap = int((cl < vwap).sum())

    # 6) 미니 HH/LL
    hh_cnt = int((hi > hi.shift()).sum())
    ll_cnt = int((lo < lo.shift()).sum())

    # 점수 (가중치 단순형)
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

    # 방향 판정
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


def _build_msg(symbol: str, trade_dir: str, level_name: str, level: float,
               planned_entry: float, sl: float, tp: float,
               score_l: float, score_s: float, details: dict):
    emo = "🔼" if trade_dir == "LONG" else "🔽"
    msg = (
        f"⏳ 프리-브레이크아웃(준비): {symbol}\n"
        f"{emo} 방향: {trade_dir}  | 압력 L/S = {round(score_l,1)}/{round(score_s,1)}\n"
        f"📍 레벨: {level_name} = {format_price(level)} (근접)\n"
        f"🧩 5m Squeeze + 1m 압력 일치\n"
        f"💡 제안: Stop-Limit {('Buy' if trade_dir=='LONG' else 'Sell')} "
        f"{format_price(planned_entry)} (추격 금지)\n"
        f"🛑 예시 SL: {format_price(sl)} | 🎯 예시 TP: {format_price(tp)}\n"
        f"ℹ️ 체결 후 1~3분 내 방향 확정 여부 확인 권장"
    )
    return msg


# =============== 공개 함수(메인 훅) =================

def analyze_prebreakout(symbol: str) -> str | None:
    """
    심볼 1개에 대해 '준비 알림'을 필요시 발송.
    반환: 메시지(str) 또는 None
    """
    # 5m / 1m 로드 (WS 버퍼 우선, 부족시 REST 폴백)
    df5 = fetch_ohlcv(symbol, "5m", 200)
    df1 = fetch_ohlcv(symbol, "1m", 400)

    # 1) Squeeze 체크
    if not _squeeze_5m(df5):
        return None

    # 2) 레벨 근접
    hh, ll, px = _levels_5m(df5, lookback=20)
    near_hh, near_ll = _near_levels(px, hh, ll, tol=NEAR_TOL)

    # 3) 1m 압력 방향
    press_dir, score_l, score_s, details = _pressure_direction_1m(df1, PB_LOOKBACK_1M)

    # === LONG 준비 (HH 근접 + 압력 LONG) ===
    if near_hh and press_dir == "LONG":
        if not _cooldown_ok(symbol, "LONG"):
            return None
        planned_entry = hh * (1 + ENTRY_OFFSET)          # HH 위 0.15% 스탑-리밋
        sl = planned_entry * (1 - SL_PCT)                # 예시 SL/TP (config 비율 사용)
        tp = planned_entry * (1 + TP_PCT)
        msg = _build_msg(symbol, "LONG", "HH20", hh, planned_entry, sl, tp, score_l, score_s, details)
        send_telegram(msg)
        return msg

    # === SHORT 준비 (LL 근접 + 압력 SHORT) ===
    if near_ll and press_dir == "SHORT":
        if not _cooldown_ok(symbol, "SHORT"):
            return None
        planned_entry = ll * (1 - ENTRY_OFFSET)          # LL 아래 0.15% 스탑-리밋
        sl = planned_entry * (1 + SL_PCT)
        tp = planned_entry * (1 - TP_PCT)
        msg = _build_msg(symbol, "SHORT", "LL20", ll, planned_entry, sl, tp, score_l, score_s, details)
        send_telegram(msg)
        return msg

    return None


def prebreakout_loop(sleep_sec: int = 60):
    """
    메인에서 스레드로 실행할 루프.
    1분 간격으로 전 심볼 스캔 → 준비 알림(있으면) 전송.
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
