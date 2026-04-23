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
STABLE_EXCLUDED = {"USDC", "EUR", "FDUSD", "USDT", "TUSD", "USDE", "DAI", "PYUSD", "USDD"}

last_alert_time: Dict[str, float] = {}
spot_loop_started = False
onchain_loop_started = False

CURRENT_SYMBOLS: List[str] = []
LAST_SYMBOL_UPDATE_TIME = 0.0
LAST_FUTURES_TICKER_TIME = 0.0
FUTURES_TICKER_CACHE: Dict[str, dict] = {}
LAST_CANDIDATE_CANDLE_TS = 0

SIGNAL_INTERVAL = 60
ONCHAIN_INTERVAL = 600
CANDIDATE_ALERT_COOLDOWN = 7200
ONCHAIN_CHART_COOLDOWN = 1800
ONCHAIN_DETAIL_CSV = "seed_outflows_hub_candidates.csv"
SYMBOL_REFRESH_INTERVAL = 900
TOP_SYMBOL_COUNT = 50
FUTURES_TICKER_REFRESH_INTERVAL = 20

SIGNAL_INTERVAL_5M = "5m"
TREND_INTERVAL_15M = "15m"
ENV_INTERVAL_1H = "1h"

CANDIDATE_MIN_SCORE = 6
CANDIDATE_MAX_PER_ALERT = 5
MAX_RECENT_6C_SURGE = 4.5
MAX_LAST2_MOVE = 1.2
MAX_BASIS_ABS = 0.35
MIN_SUPPORT_TOUCHES = 4
SUPPORT_BAND_PCT = 1.2
COMPRESSION_RATIO_MAX = 0.85
VOLUME_ALIVE_MIN = 0.75
VOLUME_ALIVE_MAX = 1.80
WICK_TEST_MIN_RATIO = 0.45
WICK_TEST_MAX_BODY = 0.45
MAX_SINGLE_CANDLE_RANGE = 3.2
RANGE_12C_MAX = 3.0
RANGE_12C_BEST = 2.0
MIN_RANGE_12C = 0.20
MAX_RECENT12_TREND_ABS = 3.5
ENV_1H_RANGE_MAX = 9.0
ENV_1H_LAST3_MOVE_MAX = 6.0
ENV_1H_COMPRESSION_MAX = 1.25

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
        if base in EXCLUDED or base in STABLE_EXCLUDED:
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
            if base and base not in EXCLUDED and base not in STABLE_EXCLUDED:
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


def get_cooldown_key(symbol: str, prefix: str = "candidate") -> str:
    return f"{prefix}:{symbol}"


def get_trend_direction_15m(closes: List[float]) -> str:
    if len(closes) < 4:
        return "NONE"
    c1, c2, c3 = closes[-2], closes[-3], closes[-4]
    if c1 > c2 > c3:
        return "LONG"
    if c1 < c2 < c3:
        return "SHORT"
    return "NONE"


def get_trend_direction_1h(closes: List[float]) -> str:
    if len(closes) < 5:
        return "NONE"
    recent5 = closes[-5:]
    up = sum(1 for i in range(1, len(recent5)) if recent5[i] > recent5[i - 1])
    down = sum(1 for i in range(1, len(recent5)) if recent5[i] < recent5[i - 1])
    total_move = abs((recent5[-1] - recent5[0]) / recent5[0] * 100.0) if recent5[0] > 0 else 0.0
    if up >= 3 and total_move >= 1.5:
        return "LONG"
    if down >= 3 and total_move >= 1.5:
        return "SHORT"
    return "NONE"


def build_candle(row: list) -> Optional[dict]:
    try:
        ts = int(row[0])
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
        "ts": ts,
        "open": o, "high": h, "low": l, "close": c, "volume": v,
        "range": candle_range, "body": body,
        "upper_wick": upper_wick, "lower_wick": lower_wick,
        "change_pct": change_pct, "range_pct": range_pct,
        "body_ratio": body_ratio, "close_pos": close_pos,
    }


def avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def get_range_pct(candles: List[dict]) -> float:
    if not candles:
        return 0.0
    low = min(c["low"] for c in candles)
    high = max(c["high"] for c in candles)
    return (high - low) / low * 100.0 if low > 0 else 0.0


def get_net_change_pct(candles: List[dict]) -> float:
    if not candles:
        return 0.0
    first_open = candles[0]["open"]
    last_close = candles[-1]["close"]
    return (last_close - first_open) / first_open * 100.0 if first_open > 0 else 0.0


def support_touch_count(candles: List[dict], band_pct: float = SUPPORT_BAND_PCT) -> int:
    if not candles:
        return 0
    anchor_low = min(c["low"] for c in candles)
    threshold = anchor_low * (1 + band_pct / 100.0)
    return sum(1 for c in candles if c["low"] <= threshold)


def has_liquidity_test(candles: List[dict]) -> bool:
    for c in candles:
        upper_ratio = c["upper_wick"] / c["range"] if c["range"] else 0.0
        lower_ratio = c["lower_wick"] / c["range"] if c["range"] else 0.0
        if c["body_ratio"] <= WICK_TEST_MAX_BODY and max(upper_ratio, lower_ratio) >= WICK_TEST_MIN_RATIO:
            return True
    return False


def is_1h_environment_ok(candles_1h: List[dict]) -> Tuple[bool, str, dict]:
    if len(candles_1h) < 5:
        return False, "1시간봉 부족", {}

    recent5 = candles_1h[-5:]
    recent3 = candles_1h[-3:]
    prev2 = candles_1h[-5:-3]
    env_range = get_range_pct(recent5)
    env_last3_move = abs(get_net_change_pct(recent3))
    recent3_avg_range = avg([c["range_pct"] for c in recent3])
    prev2_avg_range = avg([c["range_pct"] for c in prev2])
    env_compression = (recent3_avg_range / prev2_avg_range) if prev2_avg_range > 0 else 99.0

    ok = (
        env_range <= ENV_1H_RANGE_MAX
        and env_last3_move <= ENV_1H_LAST3_MOVE_MAX
        and env_compression <= ENV_1H_COMPRESSION_MAX
    )
    reason = f"1h범위={env_range:.2f}% / 1h최근3이동={env_last3_move:.2f}% / 1h압축={env_compression:.2f}"
    return ok, reason, {
        "env_range_1h": env_range,
        "env_last3_move_1h": env_last3_move,
        "env_compression_1h": env_compression,
    }


def detect_candidate(symbol: str, ticker_map: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    data_5m = get_kline(symbol, interval=SIGNAL_INTERVAL_5M, limit=50)
    data_15m = get_kline(symbol, interval=TREND_INTERVAL_15M, limit=20)
    data_1h = get_kline(symbol, interval=ENV_INTERVAL_1H, limit=10)
    if not isinstance(data_5m, list) or len(data_5m) < 26:
        return None
    if not isinstance(data_15m, list) or len(data_15m) < 6:
        return None
    if not isinstance(data_1h, list) or len(data_1h) < 6:
        return None

    candles_5m = [c for c in (build_candle(x) for x in data_5m[:-1]) if c]
    candles_1h = [c for c in (build_candle(x) for x in data_1h[:-1]) if c]
    if len(candles_5m) < 18 or len(candles_1h) < 5:
        return None

    recent12 = candles_5m[-12:]
    recent6 = candles_5m[-6:]
    recent3 = candles_5m[-3:]
    prev6 = candles_5m[-12:-6]
    recent4 = candles_5m[-4:]

    closes_15m = [float(x[4]) for x in data_15m]
    closes_1h = [float(x[4]) for x in data_1h[:-1]]
    trend_direction = get_trend_direction_15m(closes_15m)
    env_direction_1h = get_trend_direction_1h(closes_1h)

    recent12_range = get_range_pct(recent12)
    recent12_move = abs(get_net_change_pct(recent12))
    recent6_surge = sum(abs(c["change_pct"]) for c in recent6)
    last2_move = abs(recent6[-1]["change_pct"] + recent6[-2]["change_pct"])
    recent3_range_avg = avg([c["range_pct"] for c in recent3])
    prev6_range_avg = avg([c["range_pct"] for c in prev6])
    compression_ratio = (recent3_range_avg / prev6_range_avg) if prev6_range_avg > 0 else 99.0
    recent3_vol = avg([c["volume"] for c in recent3])
    prev6_vol = avg([c["volume"] for c in prev6])
    volume_ratio = (recent3_vol / prev6_vol) if prev6_vol > 0 else 0.0
    support_touches = support_touch_count(recent12)
    liquidity_test = has_liquidity_test(recent4)
    max_single_range = max(c["range_pct"] for c in recent6)
    support_low = min(c["low"] for c in recent12)
    price_above_support = ((recent12[-1]["close"] - support_low) / support_low * 100.0) if support_low > 0 else 99.0

    basis_info = get_basis_info(symbol, ticker_map=ticker_map)
    basis_pct = basis_info["basis_pct"] if basis_info else None

    env_ok, env_reason, env_stats = is_1h_environment_ok(candles_1h)

    score = 0
    reasons: List[str] = []

    if recent12_range <= RANGE_12C_MAX:
        score += 1
        reasons.append(f"12봉 횡보({recent12_range:.2f}%)")
    if recent12_range <= RANGE_12C_BEST:
        score += 1
        reasons.append(f"12봉 강한 횡보({recent12_range:.2f}%)")
    if recent12_move <= MAX_RECENT12_TREND_ABS:
        score += 1
        reasons.append(f"12봉 방향 과함 아님({recent12_move:.2f}%)")
    if recent6_surge <= MAX_RECENT_6C_SURGE:
        score += 1
        reasons.append(f"최근 6봉 과열 아님({recent6_surge:.2f}%)")
    if last2_move <= MAX_LAST2_MOVE:
        score += 1
        reasons.append(f"직전 2봉 급등 추격 아님({last2_move:.2f}%)")
    if compression_ratio <= COMPRESSION_RATIO_MAX:
        score += 1
        reasons.append(f"변동성 압축({compression_ratio:.2f})")
    if VOLUME_ALIVE_MIN <= volume_ratio <= VOLUME_ALIVE_MAX:
        score += 1
        reasons.append(f"거래량 생존({volume_ratio:.2f}x)")
    if support_touches >= MIN_SUPPORT_TOUCHES:
        score += 1
        reasons.append(f"지지 재확인 {support_touches}회")
    if liquidity_test:
        score += 1
        reasons.append("유동성 테스트 흔적")
    if basis_pct is None or abs(basis_pct) <= MAX_BASIS_ABS:
        score += 1
        reasons.append(f"괴리 안정({basis_pct:.3f}%)" if basis_pct is not None else "괴리 정보 없음")
    if env_ok:
        score += 1
        reasons.append(env_reason)

    # 제거 조건
    if recent12_range < MIN_RANGE_12C:
        return None
    if recent12_range > RANGE_12C_MAX:
        return None
    if recent12_move > MAX_RECENT12_TREND_ABS:
        return None
    if recent6_surge > MAX_RECENT_6C_SURGE:
        return None
    if last2_move > MAX_LAST2_MOVE:
        return None
    if max_single_range > MAX_SINGLE_CANDLE_RANGE:
        return None
    if support_touches < MIN_SUPPORT_TOUCHES:
        return None
    if volume_ratio < VOLUME_ALIVE_MIN or volume_ratio > VOLUME_ALIVE_MAX:
        return None
    if basis_pct is not None and abs(basis_pct) > MAX_BASIS_ABS:
        return None
    if price_above_support > 2.8:
        return None
    if not env_ok:
        return None
    if score < CANDIDATE_MIN_SCORE:
        return None

    return {
        "symbol": symbol,
        "score": score,
        "reasons": reasons,
        "trend_direction": trend_direction,
        "env_direction_1h": env_direction_1h,
        "recent12_range": recent12_range,
        "recent12_move": recent12_move,
        "recent6_surge": recent6_surge,
        "last2_move": last2_move,
        "compression_ratio": compression_ratio,
        "volume_ratio": volume_ratio,
        "support_touches": support_touches,
        "liquidity_test": liquidity_test,
        "basis_info": basis_info,
        "basis_pct": basis_pct,
        "last_close": recent12[-1]["close"],
        "support_low": support_low,
        "candidate_candle_ts": recent12[-1]["ts"],
        **env_stats,
    }


def format_basis_lines(candidate: dict) -> str:
    basis = candidate.get("basis_info")
    if not basis:
        return "선물가/공정가: -\n괴리율: -"
    return (
        f"선물가: {basis['last_price']:.6f}\n"
        f"공정가: {basis['ref_price']:.6f}\n"
        f"괴리율: {basis['basis_pct']:.3f}%"
    )


def send_candidate_alert(candidates: List[dict], candle_ts: int) -> None:
    if not candidates:
        return

    lines = [f"[TOP50 매집 후보] {len(candidates)}개"]
    for idx, c in enumerate(candidates[:CANDIDATE_MAX_PER_ALERT], 1):
        reason_text = ", ".join(c["reasons"][:5])
        lines.append(
            f"{idx}. {c['symbol']} | score={c['score']} | 1h={c['env_direction_1h']} | 15분={c['trend_direction']} | "
            f"12봉범위={c['recent12_range']:.2f}% | 6봉합={c['recent6_surge']:.2f}% | 직전2봉={c['last2_move']:.2f}% | "
            f"압축={c['compression_ratio']:.2f} | 거래량={c['volume_ratio']:.2f}x | 지지={c['support_touches']}회\n"
            f"   이유: {reason_text}"
        )

    lines.append("※ 이 알림은 진입 신호가 아니라 '아직 안 터진 후보' 스캔 결과")
    lines.append(f"마감 캔들 ts: {candle_ts}")
    send_telegram("\n".join(lines))


def scan_candidates(symbols: List[str], ticker_map: Optional[Dict[str, dict]] = None) -> List[dict]:
    candidates: List[dict] = []
    for symbol in symbols:
        try:
            candidate = detect_candidate(symbol, ticker_map=ticker_map)
            if not candidate:
                print(f"[CANDIDATE] {symbol} | 제외", flush=True)
                continue

            key = get_cooldown_key(symbol, prefix="candidate")
            last_time = last_alert_time.get(key, 0.0)
            if time.time() - last_time < CANDIDATE_ALERT_COOLDOWN:
                print(f"[CANDIDATE] {symbol} | 쿨다운", flush=True)
                continue

            print(
                f"[CANDIDATE] {symbol} | score={candidate['score']} | 1h={candidate['env_direction_1h']} | trend={candidate['trend_direction']} | "
                f"12봉범위={candidate['recent12_range']:.2f}% | 6봉합={candidate['recent6_surge']:.2f}% | 2봉합={candidate['last2_move']:.2f}% | "
                f"압축={candidate['compression_ratio']:.2f} | 거래량={candidate['volume_ratio']:.2f}x | 지지={candidate['support_touches']}회",
                flush=True,
            )
            candidates.append(candidate)
        except Exception as e:
            print(f"[CANDIDATE] {symbol} 오류: {e}", flush=True)
            traceback.print_exc()

    candidates.sort(
        key=lambda x: (
            x["score"],
            -x["recent12_range"],
            -x["support_touches"],
            x["compression_ratio"],
            -(abs(x["basis_pct"]) if x["basis_pct"] is not None else 0.0),
        ),
        reverse=True,
    )
    return candidates


def get_latest_closed_5m_candle_ts(symbol: str) -> int:
    data = get_kline(symbol, interval=SIGNAL_INTERVAL_5M, limit=3)
    if not isinstance(data, list) or len(data) < 2:
        return 0
    try:
        return int(data[-2][0])
    except Exception:
        return 0


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
    if not token_symbol or token_symbol.startswith("V") or token_symbol in STABLE_EXCLUDED:
        return False

    exchange_hits = (row.get("hub_exchange_hits") or "").strip()
    is_hub = (row.get("is_hub_candidate") or "") == "Y"
    shared = int(str(row.get("hub_shared_seed_count") or "0") or 0)
    score = int(str(row.get("hub_score") or "0") or 0)
    target_kind = (row.get("target_kind") or "").strip().lower()
    swap_action = (row.get("swap_action") or "").strip().upper()

    if exchange_hits:
        return True
    if target_kind == "protocol" and swap_action in ALLOWED_PROTOCOL_SWAP_ACTIONS and is_hub and shared >= ONCHAIN_MIN_SHARED and score >= ONCHAIN_MIN_SCORE:
        return True
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
            if not symbol or symbol in watched_symbols:
                continue
            watched_symbols.add(symbol)

            candidate = detect_candidate(symbol, ticker_map=ticker_map)
            if not candidate:
                continue

            key = get_cooldown_key(symbol, prefix="onchain_candidate")
            now = time.time()
            if key in last_alert_time and (now - last_alert_time[key] < ONCHAIN_CHART_COOLDOWN):
                continue
            last_alert_time[key] = now

            exchange_hits = (row.get("hub_exchange_hits") or "-").strip() or "-"
            is_hub = (row.get("is_hub_candidate") or "") == "Y"
            shared = row.get("hub_shared_seed_count") or "-"
            hub_score = row.get("hub_score") or "-"
            amount = row.get("amount") or "-"
            seed = row.get("seed") or "-"
            to_addr = row.get("to_addr") or "-"
            token_name = row.get("token_name") or token_symbol
            target_kind = (row.get("target_kind") or "-").strip() or "-"
            target_label = (row.get("target_label") or "-").strip() or "-"
            swap_action = (row.get("swap_action") or "-").strip() or "-"
            swap_token = (row.get("swap_token") or "-").strip() or "-"

            if exchange_hits != "-":
                trigger = "거래소 이동 + 후보"
            elif target_kind == "protocol":
                trigger = "DEX/프로토콜 + 후보"
            else:
                trigger = "강한 허브 + 후보"

            send_telegram(
                f"[ONCHAIN+TOP50 후보] {symbol}\n"
                f"트리거: {trigger}\n"
                f"token: {token_symbol} ({token_name})\n"
                f"seed: {seed}\n"
                f"to: {to_addr}\n"
                f"amount: {amount}\n"
                f"kind: {target_kind} / label: {target_label}\n"
                f"swap: {swap_action} {swap_token}\n"
                f"hub: {'Y' if is_hub else '-'} / shared: {shared} / score: {hub_score}\n"
                f"exchange: {exchange_hits}\n"
                f"후보 score: {candidate['score']} / 1h: {candidate['env_direction_1h']} / 15분: {candidate['trend_direction']}\n"
                f"12봉 범위: {candidate['recent12_range']:.2f}% / 최근 6봉 과열도: {candidate['recent6_surge']:.2f}%\n"
                f"직전 2봉 변화: {candidate['last2_move']:.2f}% / 변동성 압축: {candidate['compression_ratio']:.2f}\n"
                f"거래량 생존: {candidate['volume_ratio']:.2f}x / 지지 재확인: {candidate['support_touches']}회\n"
                f"이유: {', '.join(candidate['reasons'][:5])}\n"
                f"{format_basis_lines(candidate)}"
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
                "--address-book", "address_book.json",
                "--enable-flow",
                "--enable-active-hubs",
                "--auto-exchange-enrich",
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
            # 차트 후보 알림([TOP50 매집 후보])은 signal_loop에서 독립적으로 전송한다.
            # 온체인 결합 후보([ONCHAIN+TOP50 후보])는 중복 방지를 위해 비활성화한다.
            print("[ONCHAIN-CHART] 비활성화: 차트 후보 알림은 signal_loop에서만 전송", flush=True)

        print("[ONCHAIN] 종료", flush=True)
    except Exception as e:
        print(f"[ONCHAIN] 오류: {e}", flush=True)
        traceback.print_exc()


def signal_loop() -> None:
    global LAST_CANDIDATE_CANDLE_TS
    while True:
        loop_start = time.time()
        wait_sec = SIGNAL_INTERVAL
        try:
            print("=" * 60, flush=True)
            print(f"[SIGNAL LOOP START] {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            symbols = update_symbols_if_needed()
            ticker_map = refresh_futures_ticker_cache_if_needed(force=True)
            print(f"최종 감시 종목({len(symbols)}개): {symbols}", flush=True)

            if not symbols:
                elapsed = time.time() - loop_start
                wait_sec = max(0, SIGNAL_INTERVAL - elapsed)
                print(f"[SIGNAL LOOP END] 종목 없음 -> {wait_sec:.1f}초 대기", flush=True)
                time.sleep(wait_sec)
                continue

            latest_candle_ts = get_latest_closed_5m_candle_ts(symbols[0])
            if latest_candle_ts == 0 or latest_candle_ts == LAST_CANDIDATE_CANDLE_TS:
                elapsed = time.time() - loop_start
                wait_sec = max(0, SIGNAL_INTERVAL - elapsed)
                print(f"[SIGNAL LOOP END] 새 5분 마감봉 없음 -> {wait_sec:.1f}초 대기", flush=True)
                time.sleep(wait_sec)
                continue

            LAST_CANDIDATE_CANDLE_TS = latest_candle_ts
            candidates = scan_candidates(symbols, ticker_map=ticker_map)
            picked = candidates[:CANDIDATE_MAX_PER_ALERT]
            if picked:
                send_candidate_alert(picked, latest_candle_ts)
                now = time.time()
                for c in picked:
                    last_alert_time[get_cooldown_key(c["symbol"], prefix="candidate")] = now
            else:
                print("[CANDIDATE] 이번 5분봉 후보 없음", flush=True)

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
