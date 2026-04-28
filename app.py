import csv
import os
import threading
import time
import traceback
import subprocess
from typing import Dict, List, Optional, Set, Tuple

import requests
from flask import Flask, abort, send_file

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

SIGNAL_INTERVAL = 120
ONCHAIN_INTERVAL = 300
CANDIDATE_ALERT_COOLDOWN = 7200
ONCHAIN_CHART_COOLDOWN = 1800
ONCHAIN_DETAIL_CSV = "seed_outflows_hub_candidates.csv"
ONCHAIN_FLOW_CSV = "flow_exchange_hub_candidates.csv"
ONCHAIN_FOCUS_TTL = 2 * 60 * 60  # 온체인 거래소 유입 후 2시간 집중 감시
ONCHAIN_FOCUS_MAX_AGE = 12 * 60 * 60  # CSV에서 최근 12시간 이내 flow만 등록
ONCHAIN_FOCUS_SYMBOLS: Dict[str, dict] = {}
SYMBOL_REFRESH_INTERVAL = 900
TOP_SYMBOL_COUNT = 20
VOLUME_POOL_COUNT = 50  # 거래량 상위 50개 중 변동성 높은 20개를 최종 감시
FUTURES_TICKER_REFRESH_INTERVAL = 20

SIGNAL_INTERVAL_5M = "5m"
TREND_INTERVAL_15M = "15m"
ENV_INTERVAL_1H = "60m"

CANDIDATE_MIN_SCORE = 6
CANDIDATE_MAX_PER_ALERT = 2

# 눌림 진입 필터: 돌파 추격이 아니라, 돌파 후 박스 상단/지지선 재확인 구간만 알림
PULLBACK_CONFIRM_ENABLED = True
PULLBACK_LOOKBACK_CANDLES = 12
PULLBACK_BREAKOUT_BUFFER = 0.0015      # 과거 박스 상단을 0.15% 이상 넘긴 흔적 필요
PULLBACK_SUPPORT_BAND = 0.006          # 현재 종가가 박스 상단 ±0.6% 안으로 눌렸는지
PULLBACK_MAX_FROM_BOX_HIGH = 0.012     # 현재가가 박스 상단보다 1.2% 이상 위면 추격이라 제외
PULLBACK_MIN_REBOUND_CLOSE_POS = 0.55  # 눌림 후 캔들 종가 위치가 중간 이상
PULLBACK_MAX_UPPER_WICK_RATIO = 0.45   # 윗꼬리가 길면 털기 가능성으로 제외
PULLBACK_MIN_VOLUME_RATIO = 0.85       # 거래량이 완전히 죽으면 제외
PULLBACK_MAX_RECENT_6C_SURGE = 3.2     # 최근 6봉 과열 제한
PULLBACK_MAX_LAST2_MOVE = 0.90         # 직전 2봉 급등 추격 제한
PULLBACK_REQUIRE_HIGHER_LOW = True

# 하락 추세 필터: ASTER처럼 '하락 중 쉬는 횡보'를 압축 후보로 착각하는 것 방지
DOWNTREND_FILTER_ENABLED = True
DOWNTREND_LOOKBACK_CANDLES = 12
DOWNTREND_HIGH_DROP_MIN = 0.35      # 최근 고점이 과거 고점보다 이 정도 이상 낮아지면 하락 압력으로 봄
DOWNTREND_LOW_DROP_MIN = 0.20       # 최근 저점도 낮아지면 하락 추세 확정성 증가
DOWNTREND_MA_STACK_CHECK = True     # 단기 이평이 중장기 이평 아래면 추가 감점/제외


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

DOWNLOADABLE_ONCHAIN_FILES = {
    "hub_candidates.csv": "전체 허브 후보 랭킹",
    "seed_outflows_hub_candidates.csv": "시드 출금 상세",
    "flow_exchange_hub_candidates.csv": "flow 거래소 도착 결과",
    "active_hubs_hub_candidates.csv": "현재 활성 허브 목록",
    "active_hub_events_hub_candidates.csv": "활성 허브 이벤트",
    "repeat_wallets.db": "SQLite 원본 DB",
    "address_book.json": "수동 거래소 주소록",
    "auto_seeds.json": "자동 임시 시드 목록",
}


def get_file_size_text(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "-"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def build_onchain_files_html() -> str:
    rows = []
    for filename, desc in DOWNLOADABLE_ONCHAIN_FILES.items():
        exists = os.path.exists(filename)
        size = get_file_size_text(filename) if exists else "not created yet"
        updated = "-"
        if exists:
            updated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(filename)))
        if exists:
            action = (
                f'<a href="/download/{filename}">download</a> '
                f'<a href="/view/{filename}">view</a>'
            )
        else:
            action = "-"
        rows.append(
            f"<tr>"
            f"<td>{filename}</td>"
            f"<td>{desc}</td>"
            f"<td>{size}</td>"
            f"<td>{updated}</td>"
            f"<td>{action}</td>"
            f"</tr>"
        )

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Onchain Files</title>
      <style>
        body {{ font-family: Arial, sans-serif; padding: 24px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 14px; }}
        th {{ background: #f3f3f3; }}
      </style>
    </head>
    <body>
      <h2>Onchain generated files</h2>
      <p>CSV 안의 지갑주소 필드는 축약하지 않은 풀주소 기준으로 저장됩니다.</p>
      <table>
        <thead>
          <tr><th>file</th><th>description</th><th>size</th><th>updated</th><th>action</th></tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
      <p>CSV 파일은 Excel 또는 Google Sheets로 열면 주소를 풀주소로 확인할 수 있습니다.</p>
    </body>
    </html>
    """


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


def get_top_symbols(n: int = 20) -> List[str]:
    """
    24h 거래량 상위 50개 풀을 먼저 만들고,
    그 안에서 24h 변동성 높은 순으로 최종 20개를 선별한다.
    """
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=10).json()

    usdt_data = []
    for x in data:
        symbol = str(x.get("symbol", "")).upper()
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if base in EXCLUDED or base in STABLE_EXCLUDED:
            continue
        try:
            quote_volume = float(x.get("quoteVolume", 0) or 0)
            high = float(x.get("highPrice", 0) or 0)
            low = float(x.get("lowPrice", 0) or 0)
            price_change_pct = abs(float(x.get("priceChangePercent", 0) or 0))
        except (TypeError, ValueError):
            continue
        if quote_volume <= 0 or high <= 0 or low <= 0:
            continue
        volatility = (high - low) / low * 100.0
        usdt_data.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "volatility": volatility,
            "price_change_pct": price_change_pct,
        })

    volume_pool = sorted(usdt_data, key=lambda x: x["quote_volume"], reverse=True)[:VOLUME_POOL_COUNT]
    ranked = sorted(
        volume_pool,
        key=lambda x: (x["volatility"], x["price_change_pct"], x["quote_volume"]),
        reverse=True,
    )
    selected = [x["symbol"] for x in ranked[:n]]
    print(
        f"[SYMBOL SELECT] volume_pool={len(volume_pool)} -> volatility_top={len(selected)} | top={selected}",
        flush=True,
    )
    return selected

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

    print("[SYMBOL UPDATE] Top50 거래량 풀 → 변동성 Top20 재선정 시작", flush=True)
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


def detect_candidate(symbol: str, ticker_map: Optional[Dict[str, dict]] = None, relaxed: bool = False) -> Optional[dict]:
    data_5m = get_kline(symbol, interval=SIGNAL_INTERVAL_5M, limit=50)
    data_15m = get_kline(symbol, interval=TREND_INTERVAL_15M, limit=20)
    data_1h = get_kline(symbol, interval=ENV_INTERVAL_1H, limit=10)
    if not isinstance(data_5m, list) or len(data_5m) < 26:
        return None
    if not isinstance(data_15m, list) or len(data_15m) < 6:
        return None
    if not isinstance(data_1h, list) or len(data_1h) < 6:
        print(
            f"[KLINE RAW ERROR] {symbol} | interval={ENV_INTERVAL_1H} | "
            f"type={type(data_1h).__name__} | len={(len(data_1h) if isinstance(data_1h, list) else '-')} | "
            f"data={str(data_1h)[:500]}",
            flush=True,
        )
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
    # relaxed=True는 온체인 거래소 유입이 확인된 코인만 적용한다.
    # 온체인을 AND 조건으로 더하는 게 아니라, 해당 코인의 차트 조건을 약간 완화해 관찰 빈도를 높인다.
    min_range = 0.05 if relaxed else MIN_RANGE_12C
    max_range = 5.5 if relaxed else RANGE_12C_MAX
    max_trend = 6.0 if relaxed else MAX_RECENT12_TREND_ABS
    max_surge = 8.0 if relaxed else MAX_RECENT_6C_SURGE
    max_last2 = 2.4 if relaxed else MAX_LAST2_MOVE
    max_single = 5.5 if relaxed else MAX_SINGLE_CANDLE_RANGE
    min_support = 2 if relaxed else MIN_SUPPORT_TOUCHES
    vol_min = 0.45 if relaxed else VOLUME_ALIVE_MIN
    vol_max = 3.20 if relaxed else VOLUME_ALIVE_MAX
    max_basis = 0.80 if relaxed else MAX_BASIS_ABS
    max_above_support = 5.0 if relaxed else 2.8
    min_score = 4 if relaxed else CANDIDATE_MIN_SCORE

    if recent12_range < min_range:
        return None
    if recent12_range > max_range:
        return None
    if recent12_move > max_trend:
        return None
    if recent6_surge > max_surge:
        return None
    if last2_move > max_last2:
        return None
    if max_single_range > max_single:
        return None
    if support_touches < min_support:
        return None
    if volume_ratio < vol_min or volume_ratio > vol_max:
        return None
    if basis_pct is not None and abs(basis_pct) > max_basis:
        return None
    if price_above_support > max_above_support:
        return None
    if not relaxed and not env_ok:
        return None
    if score < min_score:
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
        "recent12_high": max(c["high"] for c in recent12),
        "box_position": ((recent12[-1]["close"] - support_low) / max((max(c["high"] for c in recent12) - support_low), 1e-12)),
        "higher_low_structure": has_higher_low_structure(recent4),
        "clear_downtrend": is_clear_downtrend(recent12)[0],
        "downtrend_reasons": is_clear_downtrend(recent12)[1],
        **is_clear_downtrend(recent12)[2],
        "candidate_candle_ts": recent12[-1]["ts"],
        "candles_5m": candles_5m,
        "relaxed": relaxed,
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

    shown_count = min(len(candidates), CANDIDATE_MAX_PER_ALERT)
    lines = [f"[변동성TOP20 눌림 진입 후보] 상위 {shown_count}개 / 통과 {len(candidates)}개"]
    for idx, c in enumerate(candidates[:CANDIDATE_MAX_PER_ALERT], 1):
        reason_text = ", ".join(c["reasons"][:5])
        focus = c.get("onchain_focus") or {}
        prefix = "[온체인집중] " if focus else ""
        focus_line = ""
        if focus:
            focus_line = f"\n   온체인: {focus.get('token', '-')} → {focus.get('exchange', '-')} / {focus.get('end_time_utc', '-')}"
        lines.append(
            f"{idx}. {prefix}{c['symbol']} | select={c.get('select_score', '-')} | score={c['score']} | 1h={c['env_direction_1h']} | 15분={c['trend_direction']} | "
            f"12봉범위={c['recent12_range']:.2f}% | 박스위치={c.get('box_position', 0):.2f} | "
            f"6봉합={c['recent6_surge']:.2f}% | 직전2봉={c['last2_move']:.2f}% | "
            f"압축={c['compression_ratio']:.2f} | 거래량={c['volume_ratio']:.2f}x | 지지={c['support_touches']}회\n"
            f"   눌림확인: {', '.join(c.get('pullback_reasons', [])[:5])}\n"
            f"   이유: {reason_text}{focus_line}"
        )

    lines.append("※ 이 알림은 '압축 후보 + 돌파 후 눌림 확인'이 같이 나온 선별 결과")
    lines.append(f"마감 캔들 ts: {candle_ts}")
    send_telegram("\n".join(lines))



def parse_utc_ts(text: str) -> int:
    try:
        return int(time.mktime(time.strptime(text.strip(), "%Y-%m-%d %H:%M:%S")))
    except Exception:
        return 0


def cleanup_onchain_focus_symbols() -> None:
    now = time.time()
    expired = [sym for sym, info in ONCHAIN_FOCUS_SYMBOLS.items() if float(info.get("expires_at", 0)) <= now]
    for sym in expired:
        ONCHAIN_FOCUS_SYMBOLS.pop(sym, None)


def register_onchain_focus_symbol(symbol: str, source: dict) -> None:
    symbol = (symbol or "").strip().upper()
    if not symbol.endswith("USDT"):
        return
    now = time.time()
    prev = ONCHAIN_FOCUS_SYMBOLS.get(symbol, {})
    ONCHAIN_FOCUS_SYMBOLS[symbol] = {
        "expires_at": max(float(prev.get("expires_at", 0)), now + ONCHAIN_FOCUS_TTL),
        "token": source.get("token_symbol", symbol.replace("USDT", "")),
        "exchange": source.get("exchange", "-"),
        "end_time_utc": source.get("end_time_utc", "-"),
        "path": source.get("path_addresses") or source.get("path") or "-",
    }
    print(f"[ONCHAIN-FOCUS] 등록/연장: {symbol} until={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ONCHAIN_FOCUS_SYMBOLS[symbol]['expires_at']))}", flush=True)


def update_onchain_focus_from_flow_csv(path: str = ONCHAIN_FLOW_CSV) -> None:
    cleanup_onchain_focus_symbols()
    if not os.path.exists(path):
        print(f"[ONCHAIN-FOCUS] flow CSV 없음: {path}", flush=True)
        return
    try:
        spot_map = get_spot_symbols()
        now = time.time()
        added = 0
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                token = (row.get("token_symbol") or "").strip().upper()
                if not token or token in STABLE_EXCLUDED or token.startswith("V"):
                    continue
                end_ts = parse_utc_ts(row.get("end_time_utc") or row.get("start_time_utc") or "")
                if end_ts and now - end_ts > ONCHAIN_FOCUS_MAX_AGE:
                    continue
                symbol = token_to_symbol(token, spot_map)
                if not symbol:
                    continue
                register_onchain_focus_symbol(symbol, row)
                added += 1
        print(f"[ONCHAIN-FOCUS] flow CSV 반영 완료: {added}건 / 현재 {len(ONCHAIN_FOCUS_SYMBOLS)}개", flush=True)
    except Exception as e:
        print(f"[ONCHAIN-FOCUS] CSV 반영 오류: {e}", flush=True)
        traceback.print_exc()


def get_scan_symbols_with_focus(symbols: List[str]) -> List[str]:
    """
    일반 Top 감시 종목 + 온체인 거래소 유입 감지 종목을 합친다.
    ONCHAIN_FOCUS_SYMBOLS에 있는 코인은 Top 거래량 리스트에 없어도 무조건 분석 대상에 포함한다.
    """
    cleanup_onchain_focus_symbols()

    base_symbols = [str(sym).strip().upper() for sym in symbols if str(sym).strip()]
    focus_symbols = [str(sym).strip().upper() for sym in ONCHAIN_FOCUS_SYMBOLS.keys() if str(sym).strip()]

    merged = list(dict.fromkeys(base_symbols + focus_symbols))

    if focus_symbols:
        missing = sorted(set(focus_symbols) - set(base_symbols))
        print(f"[ONCHAIN-FOCUS] 집중 감시 종목: {sorted(focus_symbols)}", flush=True)
        if missing:
            print(f"[ONCHAIN-FOCUS] Top 목록 밖 강제 추가: {missing}", flush=True)
        print(f"[ONCHAIN-FOCUS] 병합 후 감시 종목 수: {len(base_symbols)} -> {len(merged)}", flush=True)

    return merged





def get_box_position(candidate: dict) -> float:
    """
    최근 12봉 박스 안에서 현재가가 어느 위치인지 계산.
    0에 가까우면 박스 하단, 1에 가까우면 박스 상단.
    """
    last_close = float(candidate.get("last_close") or 0)
    support_low = float(candidate.get("support_low") or 0)
    recent12_range = float(candidate.get("recent12_range") or 0)
    if last_close <= 0 or support_low <= 0 or recent12_range <= 0:
        return 0.0

    # recent12_range = (high - low) / low * 100 이므로 high를 역산
    estimated_high = support_low * (1 + recent12_range / 100.0)
    box_height = estimated_high - support_low
    if box_height <= 0:
        return 0.0
    return max(0.0, min(1.0, (last_close - support_low) / box_height))


def has_higher_low_structure(candles: List[dict]) -> bool:
    """
    최근 저점이 미세하게 올라오는지 확인.
    너무 엄격하게 연속 상승을 요구하지 않고,
    최근 저점이 3~4봉 전 저점보다 위에 있으면 통과.
    """
    if len(candles) < 4:
        return False
    lows = [c["low"] for c in candles[-4:]]
    return lows[-1] > min(lows[:2]) and lows[-2] >= min(lows[:2]) * 0.998




def is_clear_downtrend(candles: List[dict]) -> Tuple[bool, List[str], dict]:
    """
    최근 구간이 '압축'이 아니라 '하락 추세 속 잠깐 횡보'인지 판별.
    ASTER 같은 구조:
    - 앞 구간 고점보다 최근 고점이 낮음
    - 앞 구간 저점보다 최근 저점도 낮음
    - 최근 종가가 단기 평균 아래쪽에 머무름
    """
    reasons: List[str] = []
    stats = {
        "downtrend_high_drop": 0.0,
        "downtrend_low_drop": 0.0,
        "downtrend_close_vs_mid": 0.0,
    }

    if len(candles) < max(8, DOWNTREND_LOOKBACK_CANDLES):
        return False, reasons, stats

    recent = candles[-DOWNTREND_LOOKBACK_CANDLES:]
    first_half = recent[:len(recent)//2]
    second_half = recent[len(recent)//2:]

    prev_high = max(c["high"] for c in first_half)
    recent_high = max(c["high"] for c in second_half)
    prev_low = min(c["low"] for c in first_half)
    recent_low = min(c["low"] for c in second_half)
    last_close = recent[-1]["close"]

    high_drop = (prev_high - recent_high) / prev_high * 100.0 if prev_high > 0 else 0.0
    low_drop = (prev_low - recent_low) / prev_low * 100.0 if prev_low > 0 else 0.0
    mid_price = (prev_high + prev_low) / 2.0 if prev_high > 0 and prev_low > 0 else last_close
    close_vs_mid = (last_close - mid_price) / mid_price * 100.0 if mid_price > 0 else 0.0

    stats.update({
        "downtrend_high_drop": high_drop,
        "downtrend_low_drop": low_drop,
        "downtrend_close_vs_mid": close_vs_mid,
    })

    lower_high = high_drop >= DOWNTREND_HIGH_DROP_MIN
    lower_low = low_drop >= DOWNTREND_LOW_DROP_MIN
    weak_close = close_vs_mid < -0.10

    # 최근 4봉의 고점도 계속 약한지 확인
    last4 = recent[-4:]
    last4_high_weak = max(c["high"] for c in last4) < prev_high * (1 - DOWNTREND_HIGH_DROP_MIN / 200.0)

    is_down = lower_high and (lower_low or weak_close) and last4_high_weak

    if lower_high:
        reasons.append(f"고점 하락({high_drop:.2f}%)")
    if lower_low:
        reasons.append(f"저점 하락({low_drop:.2f}%)")
    if weak_close:
        reasons.append(f"종가 약세({close_vs_mid:.2f}%)")
    if last4_high_weak:
        reasons.append("최근4봉 고점 회복 실패")

    return is_down, reasons, stats


def get_upper_wick_ratio(candle: dict) -> float:
    candle_range = float(candle.get("range") or 0)
    if candle_range <= 0:
        return 0.0
    return float(candle.get("upper_wick") or 0) / candle_range


def is_pullback_confirmed(candidate: dict) -> Tuple[bool, List[str]]:
    """
    돌파 순간 추격 금지.
    최근 12봉 박스 상단을 한 번 넘긴 뒤, 다시 박스 상단 근처로 눌리고,
    그 자리에서 무너지지 않고 반등 캔들/거래량/저점 상승이 확인될 때만 알림.
    """
    reasons: List[str] = []
    candles = candidate.get("candles_5m") or []
    if len(candles) < PULLBACK_LOOKBACK_CANDLES + 2:
        return False, ["5분봉 데이터 부족"]

    recent = candles[-(PULLBACK_LOOKBACK_CANDLES + 1):]
    box_base = recent[:-3] if len(recent) >= 6 else recent[:-1]
    last = recent[-1]
    prev = recent[-2]

    if len(box_base) < 6:
        return False, ["박스 기준봉 부족"]

    box_high = max(c["high"] for c in box_base)
    box_low = min(c["low"] for c in box_base)
    last_close = float(last["close"])
    last_low = float(last["low"])
    prev_close = float(prev["close"])

    if box_high <= 0 or box_low <= 0 or last_close <= 0:
        return False, ["가격 데이터 오류"]

    breakout_seen = max(c["high"] for c in recent[-4:-1]) > box_high * (1 + PULLBACK_BREAKOUT_BUFFER)
    pullback_to_support = last_low <= box_high * (1 + PULLBACK_SUPPORT_BAND) and last_close >= box_high * (1 - PULLBACK_SUPPORT_BAND)
    not_chasing = last_close <= box_high * (1 + PULLBACK_MAX_FROM_BOX_HIGH)
    reclaimed = last_close > box_high or (last_close > prev_close and last_close > last["open"])
    rebound_close_pos = float(last.get("close_pos") or 0)
    upper_wick_ratio = get_upper_wick_ratio(last)

    volume_ratio = float(candidate.get("volume_ratio") or 0)
    recent6_surge = float(candidate.get("recent6_surge") or 0)
    last2_move = float(candidate.get("last2_move") or 0)
    trend = candidate.get("trend_direction") or "NONE"
    higher_low = bool(candidate.get("higher_low_structure"))

    ok = True

    if breakout_seen:
        reasons.append("돌파 흔적 있음")
    else:
        ok = False
        reasons.append("돌파 흔적 없음")

    if pullback_to_support:
        distance = (last_close - box_high) / box_high * 100.0
        reasons.append(f"박스상단 눌림({distance:.2f}%)")
    else:
        ok = False
        reasons.append("박스상단 눌림 아님")

    if not_chasing:
        reasons.append("추격 아님")
    else:
        ok = False
        reasons.append("박스상단 대비 과열")

    if reclaimed and rebound_close_pos >= PULLBACK_MIN_REBOUND_CLOSE_POS:
        reasons.append(f"재상승 확인(close_pos={rebound_close_pos:.2f})")
    else:
        ok = False
        reasons.append(f"재상승 약함(close_pos={rebound_close_pos:.2f})")

    if upper_wick_ratio <= PULLBACK_MAX_UPPER_WICK_RATIO:
        reasons.append(f"윗꼬리 양호({upper_wick_ratio:.2f})")
    else:
        ok = False
        reasons.append(f"윗꼬리 과다({upper_wick_ratio:.2f})")

    if volume_ratio >= PULLBACK_MIN_VOLUME_RATIO:
        reasons.append(f"거래량 유지({volume_ratio:.2f}x)")
    else:
        ok = False
        reasons.append(f"거래량 부족({volume_ratio:.2f}x)")

    if recent6_surge <= PULLBACK_MAX_RECENT_6C_SURGE and last2_move <= PULLBACK_MAX_LAST2_MOVE:
        reasons.append(f"과열 제한(6봉={recent6_surge:.2f}%, 2봉={last2_move:.2f}%)")
    else:
        ok = False
        reasons.append(f"과열/추격 위험(6봉={recent6_surge:.2f}%, 2봉={last2_move:.2f}%)")

    if PULLBACK_REQUIRE_HIGHER_LOW and not higher_low:
        ok = False
        reasons.append("저점 상승 구조 없음")
    elif PULLBACK_REQUIRE_HIGHER_LOW:
        reasons.append("저점 상승 구조")

    if trend == "SHORT":
        ok = False
        reasons.append("15분 SHORT 제외")
    else:
        reasons.append(f"15분 {trend}")

    if DOWNTREND_FILTER_ENABLED and candidate.get("clear_downtrend"):
        ok = False
        down_reasons = candidate.get("downtrend_reasons") or []
        reasons.append("하락추세 제외" + (f"({', '.join(down_reasons[:3])})" if down_reasons else ""))

    candidate["pullback_box_high"] = box_high
    candidate["pullback_box_low"] = box_low
    candidate["pullback_upper_wick_ratio"] = upper_wick_ratio
    return ok, reasons

def calculate_selection_score(candidate: dict) -> float:
    """
    후보 통과 후, 실제 알림 우선순위를 다시 매기는 선별 점수.
    목적:
    - 단순 score 높은 후보가 아니라
    - 거래량이 살아나고, 압축이 좋고, 직전 2봉이 살짝 움직이며,
      15분 방향이 나쁘지 않은 후보를 우선 알림.
    """
    s = float(candidate.get("score") or 0)

    volume_ratio = float(candidate.get("volume_ratio") or 0)
    compression_ratio = float(candidate.get("compression_ratio") or 99)
    last2_move = float(candidate.get("last2_move") or 0)
    recent12_range = float(candidate.get("recent12_range") or 0)
    recent6_surge = float(candidate.get("recent6_surge") or 0)
    support_touches = int(candidate.get("support_touches") or 0)
    trend = candidate.get("trend_direction") or "NONE"
    env = candidate.get("env_direction_1h") or "NONE"
    basis_pct = candidate.get("basis_pct")

    # 거래량: 너무 죽은 것보다 0.9~1.5x를 우선. 1.8x 이상은 추격 위험으로 감점.
    if 0.90 <= volume_ratio <= 1.50:
        s += 2.0
    elif 0.75 <= volume_ratio < 0.90:
        s += 0.8
    elif 1.50 < volume_ratio <= 1.80:
        s += 0.5
    elif volume_ratio > 1.80:
        s -= 1.5

    # 압축: 낮을수록 우선. 단, 너무 죽은 차트만 고르지 않도록 다른 조건과 같이 봄.
    if compression_ratio <= 0.75:
        s += 2.0
    elif compression_ratio <= 1.00:
        s += 1.2
    elif compression_ratio <= 1.25:
        s += 0.3
    elif compression_ratio > 1.50:
        s -= 1.0

    # 직전 2봉: 완전 무반응보다 살짝 살아난 후보 우선. 너무 크면 추격 위험.
    if 0.15 <= last2_move <= 0.80:
        s += 1.6
    elif 0.05 <= last2_move < 0.15:
        s += 0.5
    elif last2_move > 1.00:
        s -= 1.2

    # 최근 12봉 범위: 너무 좁아도 무반응, 너무 넓어도 이미 흔들림.
    if 0.50 <= recent12_range <= 2.20:
        s += 1.0
    elif recent12_range < 0.25:
        s -= 0.6
    elif recent12_range > 2.80:
        s -= 0.8

    # 최근 6봉 과열도: 낮되 완전 죽은 것보다는 적당한 움직임 선호.
    if 0.50 <= recent6_surge <= 2.50:
        s += 0.8
    elif recent6_surge < 0.25:
        s -= 0.4
    elif recent6_surge > 3.50:
        s -= 0.8

    # 지지 터치: 많을수록 좋지만 12회처럼 전부 붙어 있으면 너무 죽은 박스일 수도 있어 과가산 방지.
    if 4 <= support_touches <= 8:
        s += 1.0
    elif support_touches > 8:
        s += 0.4

    # 방향성: 롱 후보 기준. 15분 SHORT는 강하게 감점.
    if trend == "LONG":
        s += 1.5
    elif trend == "SHORT":
        s -= 2.0

    # 1시간 환경: LONG 우선, SHORT는 감점, NONE은 중립.
    if env == "LONG":
        s += 1.0
    elif env == "SHORT":
        s -= 1.0

    # 괴리율: 공정가와 너무 벌어진 후보는 우선순위 낮춤.
    if basis_pct is not None:
        try:
            basis_abs = abs(float(basis_pct))
            if basis_abs <= 0.15:
                s += 0.6
            elif basis_abs > 0.30:
                s -= 0.6
        except Exception:
            pass

    # 하락 추세 속 횡보는 강하게 감점.
    if candidate.get("clear_downtrend"):
        s -= 4.0

    # 온체인 집중 종목은 같은 차트 조건이면 우선순위 소폭 가산.
    if candidate.get("onchain_focus"):
        s += 1.5

    return round(s, 2)


def scan_candidates(symbols: List[str], ticker_map: Optional[Dict[str, dict]] = None) -> List[dict]:
    candidates: List[dict] = []
    for symbol in symbols:
        try:
            is_focus = symbol in ONCHAIN_FOCUS_SYMBOLS
            candidate = detect_candidate(symbol, ticker_map=ticker_map, relaxed=is_focus)
            if not candidate:
                label = "온체인집중 제외" if is_focus else "제외"
                print(f"[CANDIDATE] {symbol} | {label}", flush=True)
                continue
            if is_focus:
                candidate["onchain_focus"] = ONCHAIN_FOCUS_SYMBOLS.get(symbol, {})

            candidate["select_score"] = calculate_selection_score(candidate)
            pullback_ok, pullback_reasons = is_pullback_confirmed(candidate)
            candidate["pullback_ok"] = pullback_ok
            candidate["pullback_reasons"] = pullback_reasons

            if PULLBACK_CONFIRM_ENABLED and not pullback_ok:
                print(
                    f"[PULLBACK WAIT] {symbol} | select={candidate['select_score']} | score={candidate['score']} | "
                    f"box={candidate.get('box_position', 0):.2f} | 2봉={candidate['last2_move']:.2f}% | "
                    f"거래량={candidate['volume_ratio']:.2f}x | higher_low={candidate.get('higher_low_structure')} | "
                    f"downtrend={candidate.get('clear_downtrend')} | 이유: {', '.join(pullback_reasons[:5])}",
                    flush=True,
                )
                continue

            key = get_cooldown_key(symbol, prefix="onchain_focus" if is_focus else "candidate")
            last_time = last_alert_time.get(key, 0.0)
            if time.time() - last_time < CANDIDATE_ALERT_COOLDOWN:
                print(f"[CANDIDATE] {symbol} | 쿨다운", flush=True)
                continue

            focus_tag = "[ONCHAIN-FOCUS] " if symbol in ONCHAIN_FOCUS_SYMBOLS else ""
            print(
                f"[CANDIDATE] {focus_tag}{symbol} | select={candidate['select_score']} | score={candidate['score']} | 1h={candidate['env_direction_1h']} | trend={candidate['trend_direction']} | "
                f"12봉범위={candidate['recent12_range']:.2f}% | box={candidate.get('box_position', 0):.2f} | "
                f"6봉합={candidate['recent6_surge']:.2f}% | 2봉합={candidate['last2_move']:.2f}% | "
                f"압축={candidate['compression_ratio']:.2f} | 거래량={candidate['volume_ratio']:.2f}x | "
                f"지지={candidate['support_touches']}회 | 눌림확인=Y | 하락추세=N",
                flush=True,
            )
            candidates.append(candidate)
        except Exception as e:
            print(f"[CANDIDATE] {symbol} 오류: {e}", flush=True)
            traceback.print_exc()

    candidates.sort(
        key=lambda x: (
            x.get("select_score", 0),
            x["score"],
            -x["recent12_range"],
            -x["support_touches"],
            -x["compression_ratio"],
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
            pullback_ok, pullback_reasons = is_pullback_confirmed(candidate)
            if PULLBACK_CONFIRM_ENABLED and not pullback_ok:
                print(f"[ONCHAIN-CHART] {symbol} 눌림 대기: {', '.join(pullback_reasons[:5])}", flush=True)
                continue
            candidate["pullback_reasons"] = pullback_reasons

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
                f"[ONCHAIN+눌림 후보] {symbol}\n"
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
                f"눌림확인: {', '.join(candidate.get('pullback_reasons', [])[:5])}\n"
                f"{format_basis_lines(candidate)}"
            )

    except Exception as e:
        print(f"[ONCHAIN-CHART] 오류: {e}", flush=True)
        traceback.print_exc()


def run_onchain() -> None:
    print("[ONCHAIN] 시작", flush=True)
    try:
        cmd = [
            "python",
            "-u",
            "eth_repeat_wallet_mvp.py",
            "--seeds", "seed_addresses.txt",
            "--chainid", "1",
            # 실시간 알림용 경량 세팅: 30일 재분석 대신 최근 1일만 확인
            "--days", "1",
            "--max-pages", "1",
            "--offset", "50",
            "--sleep-sec", "0.2",
            "--address-book", "address_book.json",
            # flow는 유지하되, 확장 추적 대상/깊이를 제한
            "--enable-flow",
            "--flow-expand-max-pages", "1",
            "--flow-max-track-addrs", "5",
            "--flow-alert-max-age-hours", "3",
            "--flow-max-alerts-per-run", "3",
            # 활성 허브도 핵심 5개만 얕게 감시
            "--enable-active-hubs",
            "--active-hub-max-track", "5",
            "--active-hub-scan-max-pages", "1",
        ]

        print(f"[ONCHAIN] 실행 명령: {' '.join(cmd)}", flush=True)
        print("[ONCHAIN] 자동 거래소 주소 확장 OFF: address_book.json 수동 주소만 사용", flush=True)

        eth = subprocess.run(
            cmd,
            timeout=240,
        )

        print(f"[ONCHAIN][ETH] code={eth.returncode}", flush=True)

        if eth.returncode == 0:
            update_onchain_focus_from_flow_csv(ONCHAIN_FLOW_CSV)
            print("[ONCHAIN-FOCUS] 온체인 거래소 유입 코인은 signal_loop에서 완화 조건으로 집중 감시", flush=True)
        else:
            print("[ONCHAIN] eth_repeat_wallet_mvp.py 비정상 종료", flush=True)

        print("[ONCHAIN] 종료", flush=True)

    except subprocess.TimeoutExpired:
        print("[ONCHAIN] TIMEOUT: 240초 초과로 강제 종료", flush=True)
        traceback.print_exc()
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
            symbols = get_scan_symbols_with_focus(symbols)
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
                    prefix = "onchain_focus" if c.get("onchain_focus") else "candidate"
                    last_alert_time[get_cooldown_key(c["symbol"], prefix=prefix)] = now
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
    return (
        "bot is running<br>"
        "onchain files: <a href='/files'>/files</a><br>"
        "health: <a href='/health'>/health</a>"
    ), 200


@app.route("/files")
def files_page():
    return build_onchain_files_html(), 200


@app.route("/download/<path:filename>")
def download_onchain_file(filename: str):
    if filename not in DOWNLOADABLE_ONCHAIN_FILES:
        abort(404)
    if not os.path.exists(filename):
        abort(404)
    return send_file(os.path.abspath(filename), as_attachment=True, download_name=filename)


@app.route("/view/<path:filename>")
def view_onchain_file(filename: str):
    if filename not in DOWNLOADABLE_ONCHAIN_FILES:
        abort(404)
    if not os.path.exists(filename):
        abort(404)
    if filename.endswith(".db"):
        abort(400)
    return send_file(os.path.abspath(filename), mimetype="text/plain; charset=utf-8")


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
