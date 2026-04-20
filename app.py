import csv
import os
import threading
import time
import traceback
import subprocess
from typing import Dict, List, Optional, Set

import requests
from flask import Flask

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

EXCLUDED = {
    "BTC", "ETH", "SOL", "XRP", "DOGE",
    "BNB", "ADA", "TRX", "LINK", "LTC"
}

last_alert_time: Dict[str, float] = {}
spot_loop_started = False
onchain_loop_started = False

CURRENT_SYMBOLS: List[str] = []
LAST_SYMBOL_UPDATE_TIME = 0.0

SIGNAL_INTERVAL = 60            # 1분마다 체크하되, 판단은 5분/15분봉 기준
ONCHAIN_INTERVAL = 600          # 온체인: 10분
SIGNAL_COOLDOWN = 1800          # 일반 시세 알림 재알림 제한 (30분)
ONCHAIN_CHART_COOLDOWN = 1800   # 온체인-차트 결합 알림 재알림 제한 (30분)
OPPOSITE_SIDE_LOCK = 900        # 반대 방향 금지 시간 (15분)
ONCHAIN_DETAIL_CSV = "seed_outflows_hub_candidates.csv"
SYMBOL_REFRESH_INTERVAL = 900   # 감시 종목 Top50 재선정 주기 (15분)
TOP_SYMBOL_COUNT = 50

SIGNAL_INTERVAL_5M = "5m"
TREND_INTERVAL_15M = "15m"

# 20배 기준으로 너무 잦은 신호를 줄인 값
FIVE_MIN_VOL_MULTIPLIER = 2.5   # 최근 2개 5분봉 거래량이 평균의 2.5배 이상
FIVE_MIN_MIN_CHANGE = 0.35      # 각 5분봉 최소 변동률(%)
FIVE_MIN_TOTAL_CHANGE = 0.90    # 최근 2개 5분봉 누적 변동률(%)

# 선행 진입(시작 직후 포착) - 기존 확정 신호와 분리
LEAD_VOL_MULTIPLIER = 2.0       # 최근 1개 5분봉 거래량이 평균의 2배 이상
LEAD_MIN_CHANGE = 0.55          # 최근 1개 5분봉 최소 변동률(%)
LEAD_PREV_MAX_OPPOSITE = 0.25   # 직전 봉이 강한 반대 봉이면 선행 진입 제외

# 선물가 vs 공정가(괴리) 필터
LEAD_MAX_BASIS_PCT = 0.25       # 선행 진입은 괴리 0.25% 이하여야 허용
CONFIRM_MAX_BASIS_PCT = 0.40    # 확정 진입은 괴리 0.40% 이하여야 허용

# 휩쏘(가짜 돌파/긴 꼬리) 필터
MIN_BODY_RATIO = 0.45           # 몸통이 전체 레인지의 45% 이상
MAX_OPPOSITE_WICK_RATIO = 0.35  # 반대 꼬리가 전체 레인지의 35% 이하
MAX_SAME_WICK_RATIO = 0.40      # 진행 방향 꼬리도 과도하면 제외
MIN_CLOSE_POSITION = 0.60       # LONG이면 종가가 봉 상단 60% 이상 / SHORT이면 하단 40% 이하
MAX_RANGE_PCT = 3.50            # 단일 5분봉 레인지가 너무 크면 과열로 제외


def send_telegram(msg: str) -> None:
    if not TOKEN or not CHAT_ID:
        print("텔레그램 환경변수 없음", flush=True)
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10,
        )
        print(f"텔레그램 전송: {r.status_code}", flush=True)
    except Exception as e:
        print(f"텔레그램 오류: {e}", flush=True)


def get_spot_symbols() -> Dict[str, str]:
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    data = requests.get(url, timeout=10).json()

    spot_map: Dict[str, str] = {}

    for s in data.get("symbols", []):
        symbol = s.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue

        base = s.get("baseAsset", symbol[:-4])
        if base in EXCLUDED:
            continue

        status = str(s.get("status", ""))
        if status not in {"1", "ENABLED", "TRADING"}:
            continue

        spot_map[base] = symbol

    return spot_map


def get_futures_bases() -> Set[str]:
    url = "https://contract.mexc.com/api/v1/contract/detail"
    data = requests.get(url, timeout=10).json()

    futures: Set[str] = set()

    for c in data.get("data", []):
        if c.get("quoteCoin") == "USDT" and c.get("settleCoin") == "USDT":
            base = c.get("baseCoin")
            if base and base not in EXCLUDED:
                futures.add(base)

    return futures


def get_top_symbols(n: int = 50) -> List[str]:
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=10).json()

    usdt_data = [x for x in data if x.get("symbol", "").endswith("USDT")]
    sorted_symbols = sorted(
        usdt_data,
        key=lambda x: float(x.get("quoteVolume", 0)),
        reverse=True,
    )
    return [x["symbol"] for x in sorted_symbols[:n]]


def get_final_symbols() -> List[str]:
    spot = get_spot_symbols()
    futures = get_futures_bases()
    top = set(get_top_symbols(TOP_SYMBOL_COUNT))

    final: List[str] = []
    for base, symbol in spot.items():
        if base in futures and symbol in top:
            final.append(symbol)

    return sorted(final)[:TOP_SYMBOL_COUNT]


def update_symbols_if_needed(force: bool = False) -> List[str]:
    global CURRENT_SYMBOLS, LAST_SYMBOL_UPDATE_TIME

    now = time.time()
    if not force and CURRENT_SYMBOLS and (now - LAST_SYMBOL_UPDATE_TIME) < SYMBOL_REFRESH_INTERVAL:
        return CURRENT_SYMBOLS

    print("[SYMBOL UPDATE] Top50 재선정 시작", flush=True)
    new_symbols = get_final_symbols()

    added = sorted(set(new_symbols) - set(CURRENT_SYMBOLS))
    removed = sorted(set(CURRENT_SYMBOLS) - set(new_symbols))

    CURRENT_SYMBOLS = new_symbols
    LAST_SYMBOL_UPDATE_TIME = now

    print(f"[SYMBOL UPDATE] 감시 종목 수={len(CURRENT_SYMBOLS)}", flush=True)
    if added:
        print(f"[SYMBOL UPDATE] 추가: {added}", flush=True)
    if removed:
        print(f"[SYMBOL UPDATE] 제거: {removed}", flush=True)

    return CURRENT_SYMBOLS


def get_kline(symbol: str, interval: str = "5m", limit: int = 40):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    return requests.get(url, timeout=10).json()


def get_futures_price_map() -> Dict[str, dict]:
    url = "https://contract.mexc.com/api/v1/contract/ticker"
    data = requests.get(url, timeout=10).json()

    price_map: Dict[str, dict] = {}

    for row in data.get("data", []):
        symbol_raw = str(row.get("symbol") or "").upper()
        if not symbol_raw:
            continue

        base = symbol_raw.replace("_USDT", "").replace("USDT", "")
        if not base or base in EXCLUDED:
            continue

        try:
            last_price = float(row.get("lastPrice") or row.get("last_price") or 0)
            fair_price = float(row.get("fairPrice") or row.get("fair_price") or 0)
            index_price = float(row.get("indexPrice") or row.get("index_price") or 0)
        except (TypeError, ValueError):
            continue

        ref_price = fair_price if fair_price > 0 else index_price
        if last_price <= 0 or ref_price <= 0:
            continue

        basis_pct = (last_price - ref_price) / ref_price * 100
        price_map[base] = {
            "last_price": last_price,
            "fair_price": fair_price,
            "index_price": index_price,
            "ref_price": ref_price,
            "basis_pct": basis_pct,
        }

    return price_map


def get_cooldown_key(symbol: str, side: str, prefix: str = "signal") -> str:
    return f"{prefix}:{symbol}:{side}"


def get_opposite_side(side: str) -> str:
    return "SHORT" if side == "LONG" else "LONG"


def is_opposite_direction_locked(symbol: str, side: str, prefix: str) -> bool:
    opposite_key = get_cooldown_key(symbol, get_opposite_side(side), prefix=prefix)
    opposite_time = last_alert_time.get(opposite_key)
    if opposite_time is None:
        return False
    return (time.time() - opposite_time) < OPPOSITE_SIDE_LOCK


def get_trend_direction_15m(closes: List[float]) -> str:
    if len(closes) < 4:
        return "NONE"

    c1 = closes[-2]
    c2 = closes[-3]
    c3 = closes[-4]

    if c1 > c2 > c3:
        return "LONG"
    if c1 < c2 < c3:
        return "SHORT"
    return "NONE"


def build_candle(row: list) -> Optional[dict]:
    try:
        o = float(row[1])
        h = float(row[2])
        l = float(row[3])
        c = float(row[4])
        v = float(row[5])
    except (TypeError, ValueError, IndexError):
        return None

    if min(o, h, l, c) <= 0:
        return None

    candle_range = max(h - l, 1e-12)
    body = abs(c - o)
    upper_wick = max(h - max(o, c), 0.0)
    lower_wick = max(min(o, c) - l, 0.0)
    change_pct = (c - o) / o * 100
    range_pct = (h - l) / l * 100 if l > 0 else 0.0
    body_ratio = body / candle_range
    close_pos = (c - l) / candle_range

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "range": candle_range,
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "change_pct": change_pct,
        "range_pct": range_pct,
        "body_ratio": body_ratio,
        "close_pos": close_pos,
    }


def is_valid_trend_candle(candle: dict, side: str) -> bool:
    if candle["range_pct"] > MAX_RANGE_PCT:
        return False
    if candle["body_ratio"] < MIN_BODY_RATIO:
        return False

    if side == "LONG":
        if candle["change_pct"] <= 0:
            return False
        if (candle["lower_wick"] / candle["range"]) > MAX_OPPOSITE_WICK_RATIO:
            return False
        if (candle["upper_wick"] / candle["range"]) > MAX_SAME_WICK_RATIO:
            return False
        if candle["close_pos"] < MIN_CLOSE_POSITION:
            return False
        return True

    if side == "SHORT":
        if candle["change_pct"] >= 0:
            return False
        if (candle["upper_wick"] / candle["range"]) > MAX_OPPOSITE_WICK_RATIO:
            return False
        if (candle["lower_wick"] / candle["range"]) > MAX_SAME_WICK_RATIO:
            return False
        if candle["close_pos"] > (1 - MIN_CLOSE_POSITION):
            return False
        return True

    return False


def is_basis_ok(side: str, basis_pct: Optional[float], max_pct: float) -> bool:
    if basis_pct is None:
        return True
    if side == "LONG" and basis_pct > max_pct:
        return False
    if side == "SHORT" and basis_pct < -max_pct:
        return False
    return True


def check_long_signal(
    recent_candle: dict,
    prev_candle: dict,
    avg_vol: float,
    trend_direction: str,
    basis_pct: Optional[float],
) -> bool:
    recent_vol = recent_candle["volume"]
    prev_vol = prev_candle["volume"]
    recent_change = recent_candle["change_pct"]
    prev_change = prev_candle["change_pct"]
    total_change = recent_change + prev_change

    return (
        avg_vol > 0
        and trend_direction == "LONG"
        and recent_vol > avg_vol * FIVE_MIN_VOL_MULTIPLIER
        and prev_vol > avg_vol * FIVE_MIN_VOL_MULTIPLIER
        and recent_vol >= prev_vol * 0.85
        and recent_change > FIVE_MIN_MIN_CHANGE
        and prev_change > FIVE_MIN_MIN_CHANGE
        and total_change > FIVE_MIN_TOTAL_CHANGE
        and is_valid_trend_candle(recent_candle, "LONG")
        and is_valid_trend_candle(prev_candle, "LONG")
        and is_basis_ok("LONG", basis_pct, CONFIRM_MAX_BASIS_PCT)
    )


def check_short_signal(
    recent_candle: dict,
    prev_candle: dict,
    avg_vol: float,
    trend_direction: str,
    basis_pct: Optional[float],
) -> bool:
    recent_vol = recent_candle["volume"]
    prev_vol = prev_candle["volume"]
    recent_change = recent_candle["change_pct"]
    prev_change = prev_candle["change_pct"]
    total_change = recent_change + prev_change

    return (
        avg_vol > 0
        and trend_direction == "SHORT"
        and recent_vol > avg_vol * FIVE_MIN_VOL_MULTIPLIER
        and prev_vol > avg_vol * FIVE_MIN_VOL_MULTIPLIER
        and recent_vol >= prev_vol * 0.85
        and recent_change < -FIVE_MIN_MIN_CHANGE
        and prev_change < -FIVE_MIN_MIN_CHANGE
        and total_change < -FIVE_MIN_TOTAL_CHANGE
        and is_valid_trend_candle(recent_candle, "SHORT")
        and is_valid_trend_candle(prev_candle, "SHORT")
        and is_basis_ok("SHORT", basis_pct, CONFIRM_MAX_BASIS_PCT)
    )


def check_long_lead_signal(
    recent_candle: dict,
    prev_candle: dict,
    avg_vol: float,
    trend_direction: str,
    basis_pct: Optional[float],
) -> bool:
    recent_vol = recent_candle["volume"]
    recent_change = recent_candle["change_pct"]

    return (
        avg_vol > 0
        and trend_direction != "SHORT"
        and recent_vol > avg_vol * LEAD_VOL_MULTIPLIER
        and recent_change > LEAD_MIN_CHANGE
        and is_valid_trend_candle(recent_candle, "LONG")
        and prev_candle["change_pct"] > -LEAD_PREV_MAX_OPPOSITE
        and prev_candle["body_ratio"] >= 0.25
        and is_basis_ok("LONG", basis_pct, LEAD_MAX_BASIS_PCT)
    )


def check_short_lead_signal(
    recent_candle: dict,
    prev_candle: dict,
    avg_vol: float,
    trend_direction: str,
    basis_pct: Optional[float],
) -> bool:
    recent_vol = recent_candle["volume"]
    recent_change = recent_candle["change_pct"]

    return (
        avg_vol > 0
        and trend_direction != "LONG"
        and recent_vol > avg_vol * LEAD_VOL_MULTIPLIER
        and recent_change < -LEAD_MIN_CHANGE
        and is_valid_trend_candle(recent_candle, "SHORT")
        and prev_candle["change_pct"] < LEAD_PREV_MAX_OPPOSITE
        and prev_candle["body_ratio"] >= 0.25
        and is_basis_ok("SHORT", basis_pct, LEAD_MAX_BASIS_PCT)
    )


def analyze_symbol(symbol: str, futures_price_map: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    data_5m = get_kline(symbol, interval=SIGNAL_INTERVAL_5M, limit=40)
    data_15m = get_kline(symbol, interval=TREND_INTERVAL_15M, limit=20)

    if not isinstance(data_5m, list) or len(data_5m) < 16:
        return None
    if not isinstance(data_15m, list) or len(data_15m) < 6:
        return None

    recent_candle = build_candle(data_5m[-2])
    prev_candle = build_candle(data_5m[-3])
    if not recent_candle or not prev_candle:
        return None

    closes_15m = [float(x[4]) for x in data_15m]
    volumes_5m = [float(x[5]) for x in data_5m]
    avg_window = volumes_5m[-14:-4]
    if not avg_window:
        return None
    avg_vol = sum(avg_window) / len(avg_window)

    base = symbol[:-4]
    price_info = (futures_price_map or {}).get(base, {})
    basis_pct = price_info.get("basis_pct")
    last_price = price_info.get("last_price")
    fair_price = price_info.get("fair_price")
    index_price = price_info.get("index_price")
    ref_price = price_info.get("ref_price")

    trend_direction = get_trend_direction_15m(closes_15m)
    is_long = check_long_signal(recent_candle, prev_candle, avg_vol, trend_direction, basis_pct)
    is_short = check_short_signal(recent_candle, prev_candle, avg_vol, trend_direction, basis_pct)
    is_lead_long = False if is_long else check_long_lead_signal(recent_candle, prev_candle, avg_vol, trend_direction, basis_pct)
    is_lead_short = False if is_short else check_short_lead_signal(recent_candle, prev_candle, avg_vol, trend_direction, basis_pct)

    total_change = recent_candle["change_pct"] + prev_candle["change_pct"]

    return {
        "symbol": symbol,
        "trend_direction": trend_direction,
        "recent_change": recent_candle["change_pct"],
        "prev_change": prev_candle["change_pct"],
        "total_change": total_change,
        "recent_vol": recent_candle["volume"],
        "prev_vol": prev_candle["volume"],
        "avg_vol": avg_vol,
        "recent_body_ratio": recent_candle["body_ratio"],
        "prev_body_ratio": prev_candle["body_ratio"],
        "recent_close_pos": recent_candle["close_pos"],
        "prev_close_pos": prev_candle["close_pos"],
        "recent_range_pct": recent_candle["range_pct"],
        "prev_range_pct": prev_candle["range_pct"],
        "last_price": last_price,
        "fair_price": fair_price,
        "index_price": index_price,
        "ref_price": ref_price,
        "basis_pct": basis_pct,
        "is_long": is_long,
        "is_short": is_short,
        "is_lead_long": is_lead_long,
        "is_lead_short": is_lead_short,
    }


def format_basis_lines(analysis: dict) -> str:
    basis_pct = analysis.get("basis_pct")
    last_price = analysis.get("last_price")
    fair_price = analysis.get("fair_price")
    ref_price = analysis.get("ref_price")

    if basis_pct is None or last_price is None or ref_price is None:
        return "괴리: 데이터 없음"

    fair_display = fair_price if fair_price and fair_price > 0 else ref_price
    return (
        f"선물가: {last_price:.6f}\n"
        f"공정가: {fair_display:.6f}\n"
        f"괴리율: {basis_pct:.3f}%"
    )


def send_signal_alert(analysis: dict) -> None:
    now = time.time()
    symbol = analysis["symbol"]
    basis_lines = format_basis_lines(analysis)

    if analysis["is_long"]:
        key = get_cooldown_key(symbol, "LONG", prefix="signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            print(f"{symbol} | LONG 쿨다운 중", flush=True)
            return
        if is_opposite_direction_locked(symbol, "LONG", prefix="signal"):
            print(f"{symbol} | SHORT 알림 직후라 LONG 잠금", flush=True)
            return

        last_alert_time[key] = now
        send_telegram(
            f"{symbol} 🚀 LONG 신호\n"
            f"모드: 확정 진입\n"
            f"15분 방향: {analysis['trend_direction']}\n"
            f"최근 5분 변동률: {analysis['recent_change']:.2f}%\n"
            f"이전 5분 변동률: {analysis['prev_change']:.2f}%\n"
            f"최근 2개 5분 누적: {analysis['total_change']:.2f}%\n"
            f"최근 거래량: {analysis['recent_vol']:.2f}\n"
            f"이전 거래량: {analysis['prev_vol']:.2f}\n"
            f"평균 거래량: {analysis['avg_vol']:.2f}\n"
            f"최근 몸통비율: {analysis['recent_body_ratio']:.2f} / 이전 몸통비율: {analysis['prev_body_ratio']:.2f}\n"
            f"{basis_lines}"
        )
        return

    if analysis["is_short"]:
        key = get_cooldown_key(symbol, "SHORT", prefix="signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            print(f"{symbol} | SHORT 쿨다운 중", flush=True)
            return
        if is_opposite_direction_locked(symbol, "SHORT", prefix="signal"):
            print(f"{symbol} | LONG 알림 직후라 SHORT 잠금", flush=True)
            return

        last_alert_time[key] = now
        send_telegram(
            f"{symbol} 🔻 SHORT 신호\n"
            f"모드: 확정 진입\n"
            f"15분 방향: {analysis['trend_direction']}\n"
            f"최근 5분 변동률: {analysis['recent_change']:.2f}%\n"
            f"이전 5분 변동률: {analysis['prev_change']:.2f}%\n"
            f"최근 2개 5분 누적: {analysis['total_change']:.2f}%\n"
            f"최근 거래량: {analysis['recent_vol']:.2f}\n"
            f"이전 거래량: {analysis['prev_vol']:.2f}\n"
            f"평균 거래량: {analysis['avg_vol']:.2f}\n"
            f"최근 몸통비율: {analysis['recent_body_ratio']:.2f} / 이전 몸통비율: {analysis['prev_body_ratio']:.2f}\n"
            f"{basis_lines}"
        )
        return

    if analysis["is_lead_long"]:
        key = get_cooldown_key(symbol, "LONG", prefix="lead_signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            print(f"{symbol} | 선행 LONG 쿨다운 중", flush=True)
            return
        if is_opposite_direction_locked(symbol, "LONG", prefix="signal") or is_opposite_direction_locked(symbol, "LONG", prefix="lead_signal"):
            print(f"{symbol} | SHORT 알림 직후라 선행 LONG 잠금", flush=True)
            return

        last_alert_time[key] = now
        send_telegram(
            f"{symbol} ⚡ 선행 LONG 신호\n"
            f"모드: 시작 직후 진입\n"
            f"15분 방향: {analysis['trend_direction']}\n"
            f"최근 5분 변동률: {analysis['recent_change']:.2f}%\n"
            f"최근 거래량: {analysis['recent_vol']:.2f}\n"
            f"이전 거래량: {analysis['prev_vol']:.2f}\n"
            f"평균 거래량: {analysis['avg_vol']:.2f}\n"
            f"최근 몸통비율: {analysis['recent_body_ratio']:.2f} / 종가위치: {analysis['recent_close_pos']:.2f}\n"
            f"{basis_lines}"
        )
        return

    if analysis["is_lead_short"]:
        key = get_cooldown_key(symbol, "SHORT", prefix="lead_signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            print(f"{symbol} | 선행 SHORT 쿨다운 중", flush=True)
            return
        if is_opposite_direction_locked(symbol, "SHORT", prefix="signal") or is_opposite_direction_locked(symbol, "SHORT", prefix="lead_signal"):
            print(f"{symbol} | LONG 알림 직후라 선행 SHORT 잠금", flush=True)
            return

        last_alert_time[key] = now
        send_telegram(
            f"{symbol} ⚡ 선행 SHORT 신호\n"
            f"모드: 시작 직후 진입\n"
            f"15분 방향: {analysis['trend_direction']}\n"
            f"최근 5분 변동률: {analysis['recent_change']:.2f}%\n"
            f"최근 거래량: {analysis['recent_vol']:.2f}\n"
            f"이전 거래량: {analysis['prev_vol']:.2f}\n"
            f"평균 거래량: {analysis['avg_vol']:.2f}\n"
            f"최근 몸통비율: {analysis['recent_body_ratio']:.2f} / 종가위치: {analysis['recent_close_pos']:.2f}\n"
            f"{basis_lines}"
        )


def check_signal(symbol: str, futures_price_map: Optional[Dict[str, dict]] = None) -> None:
    try:
        analysis = analyze_symbol(symbol, futures_price_map=futures_price_map)
        if not analysis:
            print(f"{symbol} | kline 데이터 부족", flush=True)
            return

        basis_text = (
            f"basis={analysis['basis_pct']:.3f}%"
            if analysis.get("basis_pct") is not None else
            "basis=NA"
        )
        print(
            f"[SIGNAL] {symbol} | trend={analysis['trend_direction']} | "
            f"chg1={analysis['recent_change']:.2f}% | "
            f"chg2={analysis['prev_change']:.2f}% | "
            f"chg_total={analysis['total_change']:.2f}% | "
            f"recent_vol={analysis['recent_vol']:.2f} | "
            f"prev_vol={analysis['prev_vol']:.2f} | avg_vol={analysis['avg_vol']:.2f} | "
            f"body1={analysis['recent_body_ratio']:.2f} | body2={analysis['prev_body_ratio']:.2f} | "
            f"{basis_text}",
            flush=True,
        )
        print(
            f"[DEBUG] {symbol} | long={analysis['is_long']} | short={analysis['is_short']} | "
            f"lead_long={analysis['is_lead_long']} | lead_short={analysis['is_lead_short']}",
            flush=True,
        )

        if not any([
            analysis["is_long"],
            analysis["is_short"],
            analysis["is_lead_long"],
            analysis["is_lead_short"],
        ]):
            return

        send_signal_alert(analysis)

    except Exception as e:
        print(f"{symbol} 오류: {e}", flush=True)
        traceback.print_exc()


def token_to_symbol(token_symbol: str, spot_map: Dict[str, str]) -> Optional[str]:
    token_symbol = (token_symbol or "").strip().upper()
    if not token_symbol:
        return None
    return spot_map.get(token_symbol)


def read_recent_onchain_rows(path: str, top_n: int = 30) -> List[dict]:
    if not os.path.exists(path):
        print(f"[ONCHAIN-CHART] CSV 없음: {path}", flush=True)
        return []

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows[:top_n]
    except Exception as e:
        print(f"[ONCHAIN-CHART] CSV 읽기 실패: {e}", flush=True)
        return []


def should_watch_onchain_row(row: dict) -> bool:
    to_addr = (row.get("to_addr") or "").lower()
    if to_addr == "0x0000000000000000000000000000000000000000":
        return False

    token_symbol = (row.get("token_symbol") or "").upper()
    if not token_symbol or token_symbol.startswith("V"):
        return False

    is_hub = (row.get("is_hub_candidate") or "") == "Y"
    exchange_hits = (row.get("hub_exchange_hits") or "").strip()

    if exchange_hits:
        return True
    if is_hub:
        return True
    return False


def analyze_onchain_chart_candidates() -> None:
    try:
        rows = read_recent_onchain_rows(ONCHAIN_DETAIL_CSV, top_n=50)
        if not rows:
            return

        spot_map = get_spot_symbols()
        futures_price_map = get_futures_price_map()
        watched_symbols: Set[str] = set()

        for row in rows:
            if not should_watch_onchain_row(row):
                continue

            token_symbol = (row.get("token_symbol") or "").upper()
            symbol = token_to_symbol(token_symbol, spot_map)
            if not symbol:
                print(f"[ONCHAIN-CHART] MEXC 현물 심볼 없음: {token_symbol}", flush=True)
                continue

            if symbol in watched_symbols:
                continue
            watched_symbols.add(symbol)

            analysis = analyze_symbol(symbol, futures_price_map=futures_price_map)
            if not analysis:
                print(f"[ONCHAIN-CHART] 차트 분석 실패: {symbol}", flush=True)
                continue

            exchange_hits = (row.get("hub_exchange_hits") or "-").strip() or "-"
            is_hub = (row.get("is_hub_candidate") or "") == "Y"
            shared = row.get("hub_shared_seed_count") or "-"
            amount = row.get("amount") or "-"
            seed = row.get("seed") or "-"
            to_addr = row.get("to_addr") or "-"
            token_name = row.get("token_name") or token_symbol

            onchain_basis_text = (
                f"basis={analysis['basis_pct']:.3f}%"
                if analysis.get("basis_pct") is not None else
                "basis=NA"
            )
            print(
                f"[ONCHAIN-CHART] {symbol} | from_onchain token={token_symbol} | "
                f"hub={is_hub} | exchange={exchange_hits} | "
                f"trend={analysis['trend_direction']} | "
                f"chg_total={analysis['total_change']:.2f}% | "
                f"recent_vol={analysis['recent_vol']:.2f} | avg_vol={analysis['avg_vol']:.2f} | "
                f"{onchain_basis_text}",
                flush=True,
            )

            if not analysis["is_long"] and not analysis["is_short"]:
                continue

            side = "LONG" if analysis["is_long"] else "SHORT"
            key = get_cooldown_key(symbol, side, prefix="onchain_chart")
            now = time.time()
            if key in last_alert_time and (now - last_alert_time[key] < ONCHAIN_CHART_COOLDOWN):
                print(f"[ONCHAIN-CHART] {symbol} {side} 쿨다운 중", flush=True)
                continue
            if is_opposite_direction_locked(symbol, side, prefix="onchain_chart"):
                print(f"[ONCHAIN-CHART] {symbol} 반대 방향 잠금 중", flush=True)
                continue
            last_alert_time[key] = now

            trigger = "거래소 이동" if exchange_hits != "-" else "허브 감지"
            emoji = "🚀" if side == "LONG" else "🔻"
            send_telegram(
                f"[ONCHAIN+CHART] {emoji} {symbol} {side}\n"
                f"트리거: {trigger}\n"
                f"token: {token_symbol} ({token_name})\n"
                f"seed: {seed}\n"
                f"to: {to_addr}\n"
                f"amount: {amount}\n"
                f"hub: {'Y' if is_hub else '-'} / shared: {shared}\n"
                f"exchange: {exchange_hits}\n"
                f"15분 방향: {analysis['trend_direction']}\n"
                f"최근 2개 5분 누적: {analysis['total_change']:.2f}%\n"
                f"최근 거래량: {analysis['recent_vol']:.2f}\n"
                f"평균 거래량: {analysis['avg_vol']:.2f}\n"
                f"최근 몸통비율: {analysis['recent_body_ratio']:.2f} / 이전 몸통비율: {analysis['prev_body_ratio']:.2f}\n"
                f"{format_basis_lines(analysis)}"
            )

    except Exception as e:
        print(f"[ONCHAIN-CHART] 오류: {e}", flush=True)
        traceback.print_exc()


def run_onchain() -> None:
    print("[ONCHAIN] 시작", flush=True)

    try:
        print("[ONCHAIN] ETH 분석 시작", flush=True)
        eth = subprocess.run(
            [
                "python",
                "eth_repeat_wallet_mvp.py",
                "--seeds",
                "seed_addresses.txt",
                "--chainid",
                "1",
                "--days",
                "30",
            ],
            capture_output=True,
            text=True,
        )

        if eth.stdout:
            print(eth.stdout, flush=True)
        if eth.stderr:
            print(eth.stderr, flush=True)

        print(f"[ONCHAIN][ETH] code={eth.returncode}", flush=True)

        if eth.returncode == 0:
            print("[ONCHAIN-CHART] 온체인 토큰 차트 확인 시작", flush=True)
            analyze_onchain_chart_candidates()
            print("[ONCHAIN-CHART] 온체인 토큰 차트 확인 종료", flush=True)

        print("[ONCHAIN] 종료", flush=True)

    except Exception as e:
        print(f"[ONCHAIN] 오류: {e}", flush=True)
        traceback.print_exc()


def signal_loop() -> None:
    while True:
        loop_start = time.time()
        wait_sec = SIGNAL_INTERVAL

        try:
            print("=" * 60, flush=True)
            print(f"[SIGNAL LOOP START] {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

            symbols = update_symbols_if_needed()
            futures_price_map = get_futures_price_map()
            print(f"최종 감시 종목({len(symbols)}개): {symbols}", flush=True)
            print(f"[FAIR PRICE MAP] 수신 종목 수={len(futures_price_map)}", flush=True)

            if not symbols:
                print("감시 종목 없음", flush=True)

            for symbol in symbols:
                check_signal(symbol, futures_price_map=futures_price_map)
                time.sleep(0.2)

            elapsed = time.time() - loop_start
            wait_sec = max(0, SIGNAL_INTERVAL - elapsed)
            print(f"[SIGNAL LOOP END] elapsed={elapsed:.1f}s -> {wait_sec:.1f}초 대기", flush=True)

        except Exception as e:
            print(f"signal_loop 오류: {e}", flush=True)
            traceback.print_exc()

        time.sleep(wait_sec)


def onchain_loop() -> None:
    while True:
        loop_start = time.time()
        wait_sec = ONCHAIN_INTERVAL

        try:
            print("=" * 60, flush=True)
            print(f"[ONCHAIN LOOP START] {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            run_onchain()
            elapsed = time.time() - loop_start
            wait_sec = max(0, ONCHAIN_INTERVAL - elapsed)
            print(f"[ONCHAIN LOOP END] elapsed={elapsed:.1f}s -> {wait_sec:.1f}초 대기", flush=True)

        except Exception as e:
            print(f"onchain_loop 오류: {e}", flush=True)
            traceback.print_exc()

        time.sleep(wait_sec)


@app.route("/")
def home():
    return "bot is running", 200


@app.route("/health")
def health():
    return "ok", 200


def start_background_loops() -> None:
    global spot_loop_started, onchain_loop_started

    try:
        update_symbols_if_needed(force=True)
    except Exception as e:
        print(f"초기 종목 로딩 실패: {e}", flush=True)

    if not spot_loop_started:
        spot_loop_started = True
        thread1 = threading.Thread(target=signal_loop, daemon=True)
        thread1.start()
        print("시세 루프 시작 완료", flush=True)
    else:
        print("시세 루프 이미 시작됨", flush=True)

    if not onchain_loop_started:
        onchain_loop_started = True
        thread2 = threading.Thread(target=onchain_loop, daemon=True)
        thread2.start()
        print("온체인 루프 시작 완료", flush=True)
    else:
        print("온체인 루프 이미 시작됨", flush=True)


start_background_loops()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
