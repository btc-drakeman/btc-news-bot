import csv
import os
import threading
import time
import traceback
import subprocess
from typing import Dict, List, Optional, Set, Tuple

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
LAST_FUTURES_TICKER_TIME = 0.0
FUTURES_TICKER_CACHE: Dict[str, dict] = {}

SIGNAL_INTERVAL = 60
ONCHAIN_INTERVAL = 600
SIGNAL_COOLDOWN = 1800
ONCHAIN_CHART_COOLDOWN = 1800
OPPOSITE_SIDE_LOCK = 900
ONCHAIN_DETAIL_CSV = "seed_outflows_hub_candidates.csv"
SYMBOL_REFRESH_INTERVAL = 900
TOP_SYMBOL_COUNT = 50
FUTURES_TICKER_REFRESH_INTERVAL = 20

SIGNAL_INTERVAL_5M = "5m"
TREND_INTERVAL_15M = "15m"

FIVE_MIN_VOL_MULTIPLIER = 2.5
FIVE_MIN_MIN_CHANGE = 0.35
FIVE_MIN_TOTAL_CHANGE = 0.90

LEAD_VOL_MULTIPLIER = 2.0
LEAD_MIN_CHANGE = 0.55
LEAD_PREV_MAX_OPPOSITE = 0.25

MIN_BODY_RATIO = 0.45
MAX_OPPOSITE_WICK_RATIO = 0.35
MAX_SAME_WICK_RATIO = 0.40
MIN_CLOSE_POSITION = 0.60
MAX_RANGE_PCT = 3.50

# 괴리 필터
MAX_LEAD_POSITIVE_BASIS = 0.25
MAX_SIGNAL_POSITIVE_BASIS = 0.40
MIN_LEAD_NEGATIVE_BASIS = -0.25
MIN_SIGNAL_NEGATIVE_BASIS = -0.40

# 온체인 실전형 필터
ONCHAIN_MIN_SHARED = 3
ONCHAIN_MIN_SCORE = 18
ALLOWED_PROTOCOL_SWAP_ACTIONS = {"BUY", "SELL", "SWAP"}


def send_telegram(msg: str) -> None:
    if not TOKEN or not CHAT_ID:
        print("텔레그램 환경변수 없음", flush=True)
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
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
    sorted_symbols = sorted(usdt_data, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
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


def refresh_futures_ticker_cache_if_needed(force: bool = False) -> Dict[str, dict]:
    global LAST_FUTURES_TICKER_TIME, FUTURES_TICKER_CACHE
    now = time.time()
    if not force and FUTURES_TICKER_CACHE and (now - LAST_FUTURES_TICKER_TIME) < FUTURES_TICKER_REFRESH_INTERVAL:
        return FUTURES_TICKER_CACHE

    url = "https://contract.mexc.com/api/v1/contract/ticker"
    data = requests.get(url, timeout=10).json()
    ticker_map: Dict[str, dict] = {}

    for item in data.get("data", []):
        symbol = str(item.get("symbol") or "").upper()
        if symbol:
            ticker_map[symbol] = item

    FUTURES_TICKER_CACHE = ticker_map
    LAST_FUTURES_TICKER_TIME = now
    return FUTURES_TICKER_CACHE


def get_basis_info(symbol: str, ticker_map: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    if ticker_map is None:
        ticker_map = refresh_futures_ticker_cache_if_needed()

    contract_symbol = symbol.replace("USDT", "_USDT")
    item = ticker_map.get(contract_symbol)
    if not item:
        return None

    try:
        last_price = float(item.get("lastPrice") or item.get("last_price") or 0)
        fair_price = float(item.get("fairPrice") or item.get("fair_price") or 0)
        index_price = float(item.get("indexPrice") or item.get("index_price") or 0)
    except (TypeError, ValueError):
        return None

    ref_price = fair_price if fair_price > 0 else index_price
    if last_price <= 0 or ref_price <= 0:
        return None

    basis_pct = (last_price - ref_price) / ref_price * 100.0
    return {
        "last_price": last_price,
        "fair_price": fair_price,
        "index_price": index_price,
        "ref_price": ref_price,
        "basis_pct": basis_pct,
    }


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
    c1, c2, c3 = closes[-2], closes[-3], closes[-4]
    if c1 > c2 > c3:
        return "LONG"
    if c1 < c2 < c3:
        return "SHORT"
    return "NONE"


def build_candle(row: list) -> Optional[dict]:
    try:
        o = float(row[1]); h = float(row[2]); l = float(row[3]); c = float(row[4]); v = float(row[5])
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
        "open": o, "high": h, "low": l, "close": c, "volume": v,
        "range": candle_range, "body": body,
        "upper_wick": upper_wick, "lower_wick": lower_wick,
        "change_pct": change_pct, "range_pct": range_pct,
        "body_ratio": body_ratio, "close_pos": close_pos,
    }


def is_valid_trend_candle(candle: dict, side: str) -> bool:
    if candle["range_pct"] > MAX_RANGE_PCT:
        return False
    if candle["body_ratio"] < MIN_BODY_RATIO:
        return False

    if side == "LONG":
        return (
            candle["change_pct"] > 0
            and (candle["lower_wick"] / candle["range"]) <= MAX_OPPOSITE_WICK_RATIO
            and (candle["upper_wick"] / candle["range"]) <= MAX_SAME_WICK_RATIO
            and candle["close_pos"] >= MIN_CLOSE_POSITION
        )
    if side == "SHORT":
        return (
            candle["change_pct"] < 0
            and (candle["upper_wick"] / candle["range"]) <= MAX_OPPOSITE_WICK_RATIO
            and (candle["lower_wick"] / candle["range"]) <= MAX_SAME_WICK_RATIO
            and candle["close_pos"] <= (1 - MIN_CLOSE_POSITION)
        )
    return False


def check_long_signal(recent_candle: dict, prev_candle: dict, avg_vol: float, trend_direction: str) -> bool:
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
    )


def check_short_signal(recent_candle: dict, prev_candle: dict, avg_vol: float, trend_direction: str) -> bool:
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
    )


def check_long_lead_signal(recent_candle: dict, prev_candle: dict, avg_vol: float, trend_direction: str) -> bool:
    return (
        avg_vol > 0
        and trend_direction != "SHORT"
        and recent_candle["volume"] > avg_vol * LEAD_VOL_MULTIPLIER
        and recent_candle["change_pct"] > LEAD_MIN_CHANGE
        and is_valid_trend_candle(recent_candle, "LONG")
        and prev_candle["change_pct"] > -LEAD_PREV_MAX_OPPOSITE
        and prev_candle["body_ratio"] >= 0.25
    )


def check_short_lead_signal(recent_candle: dict, prev_candle: dict, avg_vol: float, trend_direction: str) -> bool:
    return (
        avg_vol > 0
        and trend_direction != "LONG"
        and recent_candle["volume"] > avg_vol * LEAD_VOL_MULTIPLIER
        and recent_candle["change_pct"] < -LEAD_MIN_CHANGE
        and is_valid_trend_candle(recent_candle, "SHORT")
        and prev_candle["change_pct"] < LEAD_PREV_MAX_OPPOSITE
        and prev_candle["body_ratio"] >= 0.25
    )


def analyze_symbol(symbol: str, ticker_map: Optional[Dict[str, dict]] = None) -> Optional[dict]:
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

    trend_direction = get_trend_direction_15m(closes_15m)
    is_long = check_long_signal(recent_candle, prev_candle, avg_vol, trend_direction)
    is_short = check_short_signal(recent_candle, prev_candle, avg_vol, trend_direction)
    is_lead_long = False if is_long else check_long_lead_signal(recent_candle, prev_candle, avg_vol, trend_direction)
    is_lead_short = False if is_short else check_short_lead_signal(recent_candle, prev_candle, avg_vol, trend_direction)

    basis_info = get_basis_info(symbol, ticker_map=ticker_map)
    basis_pct = basis_info["basis_pct"] if basis_info else None

    if basis_pct is not None:
        if is_long and basis_pct > MAX_SIGNAL_POSITIVE_BASIS:
            is_long = False
        if is_short and basis_pct < MIN_SIGNAL_NEGATIVE_BASIS:
            is_short = False
        if is_lead_long and basis_pct > MAX_LEAD_POSITIVE_BASIS:
            is_lead_long = False
        if is_lead_short and basis_pct < MIN_LEAD_NEGATIVE_BASIS:
            is_lead_short = False

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
        "is_long": is_long,
        "is_short": is_short,
        "is_lead_long": is_lead_long,
        "is_lead_short": is_lead_short,
        "basis_info": basis_info,
        "basis_pct": basis_pct,
    }


def format_basis_lines(analysis: dict) -> str:
    basis = analysis.get("basis_info")
    if not basis:
        return "선물가/공정가: -\n괴리율: -"
    return (
        f"선물가: {basis['last_price']:.6f}\n"
        f"공정가: {basis['ref_price']:.6f}\n"
        f"괴리율: {basis['basis_pct']:.3f}%"
    )


def send_signal_alert(analysis: dict) -> None:
    now = time.time()
    symbol = analysis["symbol"]

    if analysis["is_long"]:
        key = get_cooldown_key(symbol, "LONG", prefix="signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            return
        if is_opposite_direction_locked(symbol, "LONG", prefix="signal"):
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
            f"{format_basis_lines(analysis)}"
        )
        return

    if analysis["is_short"]:
        key = get_cooldown_key(symbol, "SHORT", prefix="signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            return
        if is_opposite_direction_locked(symbol, "SHORT", prefix="signal"):
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
            f"{format_basis_lines(analysis)}"
        )
        return

    if analysis["is_lead_long"]:
        key = get_cooldown_key(symbol, "LONG", prefix="lead_signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            return
        if is_opposite_direction_locked(symbol, "LONG", prefix="signal") or is_opposite_direction_locked(symbol, "LONG", prefix="lead_signal"):
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
            f"{format_basis_lines(analysis)}"
        )
        return

    if analysis["is_lead_short"]:
        key = get_cooldown_key(symbol, "SHORT", prefix="lead_signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            return
        if is_opposite_direction_locked(symbol, "SHORT", prefix="signal") or is_opposite_direction_locked(symbol, "SHORT", prefix="lead_signal"):
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
            f"{format_basis_lines(analysis)}"
        )


def check_signal(symbol: str, ticker_map: Optional[Dict[str, dict]] = None) -> None:
    try:
        analysis = analyze_symbol(symbol, ticker_map=ticker_map)
        if not analysis:
            print(f"{symbol} | kline 데이터 부족", flush=True)
            return

        basis_text = f" | basis={analysis['basis_pct']:.3f}%" if analysis.get("basis_pct") is not None else ""
        print(
            f"[SIGNAL] {symbol} | trend={analysis['trend_direction']} | "
            f"chg1={analysis['recent_change']:.2f}% | chg2={analysis['prev_change']:.2f}% | "
            f"chg_total={analysis['total_change']:.2f}% | recent_vol={analysis['recent_vol']:.2f} | "
            f"prev_vol={analysis['prev_vol']:.2f} | avg_vol={analysis['avg_vol']:.2f} | "
            f"body1={analysis['recent_body_ratio']:.2f} | body2={analysis['prev_body_ratio']:.2f}{basis_text}",
            flush=True,
        )
        print(
            f"[DEBUG] {symbol} | long={analysis['is_long']} | short={analysis['is_short']} | "
            f"lead_long={analysis['is_lead_long']} | lead_short={analysis['is_lead_short']}",
            flush=True,
        )

        if any([analysis["is_long"], analysis["is_short"], analysis["is_lead_long"], analysis["is_lead_short"]]):
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

    exchange_hits = (row.get("hub_exchange_hits") or "").strip()
    is_hub = (row.get("is_hub_candidate") or "") == "Y"
    shared = int(str(row.get("hub_shared_seed_count") or "0") or 0)
    score = int(str(row.get("hub_score") or "0") or 0)
    target_kind = (row.get("target_kind") or "").strip().lower()
    swap_action = (row.get("swap_action") or "").strip().upper()

    # 1) 거래소 직행은 항상 봄
    if exchange_hits:
        return True
    # 2) protocol/DEX는 BUY/SELL/SWAP 추정이 있고, 허브 강도가 충분할 때만 봄
    if target_kind == "protocol" and swap_action in ALLOWED_PROTOCOL_SWAP_ACTIONS and is_hub and shared >= ONCHAIN_MIN_SHARED and score >= ONCHAIN_MIN_SCORE:
        return True
    # 3) unknown/기타는 매우 강한 허브일 때만
    if is_hub and shared >= ONCHAIN_MIN_SHARED and score >= ONCHAIN_MIN_SCORE:
        return True
    return False


def analyze_onchain_chart_candidates() -> None:
    try:
        rows = read_recent_onchain_rows(ONCHAIN_DETAIL_CSV, top_n=100)
        if not rows:
            return

        spot_map = get_spot_symbols()
        ticker_map = refresh_futures_ticker_cache_if_needed(force=True)
        watched_symbols: Set[str] = set()

        for row in rows:
            if not should_watch_onchain_row(row):
                continue

            token_symbol = (row.get("token_symbol") or "").upper()
            symbol = token_to_symbol(token_symbol, spot_map)
            if not symbol:
                continue
            if symbol in watched_symbols:
                continue
            watched_symbols.add(symbol)

            analysis = analyze_symbol(symbol, ticker_map=ticker_map)
            if not analysis:
                continue
            if not analysis["is_long"] and not analysis["is_short"]:
                # 온체인 잡음 억제를 위해 차트 결합은 확정 신호만 사용
                continue

            exchange_hits = (row.get("hub_exchange_hits") or "-").strip() or "-"
            is_hub = (row.get("is_hub_candidate") or "") == "Y"
            shared = row.get("hub_shared_seed_count") or "-"
            score = row.get("hub_score") or "-"
            amount = row.get("amount") or "-"
            seed = row.get("seed") or "-"
            to_addr = row.get("to_addr") or "-"
            token_name = row.get("token_name") or token_symbol
            target_kind = (row.get("target_kind") or "-").strip() or "-"
            target_label = (row.get("target_label") or "-").strip() or "-"
            swap_action = (row.get("swap_action") or "-").strip() or "-"
            swap_token = (row.get("swap_token") or "-").strip() or "-"

            side = "LONG" if analysis["is_long"] else "SHORT"
            key = get_cooldown_key(symbol, side, prefix="onchain_chart")
            now = time.time()
            if key in last_alert_time and (now - last_alert_time[key] < ONCHAIN_CHART_COOLDOWN):
                continue
            if is_opposite_direction_locked(symbol, side, prefix="onchain_chart"):
                continue
            last_alert_time[key] = now

            if exchange_hits != "-":
                trigger = "거래소 이동"
            elif target_kind == "protocol":
                trigger = "DEX/프로토콜 + 차트"
            else:
                trigger = "강한 허브 + 차트"

            emoji = "🚀" if side == "LONG" else "🔻"
            send_telegram(
                f"[ONCHAIN+CHART] {emoji} {symbol} {side}\n"
                f"트리거: {trigger}\n"
                f"token: {token_symbol} ({token_name})\n"
                f"seed: {seed}\n"
                f"to: {to_addr}\n"
                f"amount: {amount}\n"
                f"kind: {target_kind} / label: {target_label}\n"
                f"swap: {swap_action} {swap_token}\n"
                f"hub: {'Y' if is_hub else '-'} / shared: {shared} / score: {score}\n"
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
        eth = subprocess.run(
            [
                "python",
                "eth_repeat_wallet_mvp.py",
                "--seeds", "seed_addresses.txt",
                "--chainid", "1",
                "--days", "30",
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
            ticker_map = refresh_futures_ticker_cache_if_needed(force=True)
            print(f"최종 감시 종목({len(symbols)}개): {symbols}", flush=True)
            for symbol in symbols:
                check_signal(symbol, ticker_map=ticker_map)
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
        refresh_futures_ticker_cache_if_needed(force=True)
    except Exception as e:
        print(f"초기 로딩 실패: {e}", flush=True)

    if not spot_loop_started:
        spot_loop_started = True
        threading.Thread(target=signal_loop, daemon=True).start()
        print("시세 루프 시작 완료", flush=True)
    if not onchain_loop_started:
        onchain_loop_started = True
        threading.Thread(target=onchain_loop, daemon=True).start()
        print("온체인 루프 시작 완료", flush=True)


start_background_loops()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
