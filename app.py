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

SIGNAL_INTERVAL = 60       # 시세 감지: 1분
ONCHAIN_INTERVAL = 600     # 온체인: 10분
SIGNAL_COOLDOWN = 600      # 일반 시세 알림 재알림 제한
ONCHAIN_CHART_COOLDOWN = 900  # 온체인-차트 결합 알림 재알림 제한
ONCHAIN_DETAIL_CSV = "seed_outflows_hub_candidates.csv"


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
    top = set(get_top_symbols(50))

    final = []
    for base, symbol in spot.items():
        if base in futures and symbol in top:
            final.append(symbol)

    return final[:15]


def get_kline(symbol: str):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit=30"
    return requests.get(url, timeout=10).json()


def check_long_signal(recent_vol: float, prev_vol: float, avg_vol: float, price_change: float) -> bool:
    return (
        avg_vol > 0
        and recent_vol > avg_vol * 1.5
        and recent_vol > prev_vol
        and price_change > 0.4
    )


def check_short_signal(recent_vol: float, prev_vol: float, avg_vol: float, price_change: float) -> bool:
    return (
        avg_vol > 0
        and recent_vol > avg_vol * 1.5
        and recent_vol > prev_vol
        and price_change < -0.4
    )


def get_cooldown_key(symbol: str, side: str, prefix: str = "signal") -> str:
    return f"{prefix}:{symbol}:{side}"


def analyze_symbol(symbol: str) -> Optional[dict]:
    data = get_kline(symbol)
    if not isinstance(data, list) or len(data) < 15:
        return None

    volumes = [float(x[5]) for x in data]
    prices = [float(x[4]) for x in data]

    # 완성된 1분봉 기준
    recent_vol = volumes[-2]
    prev_vol = volumes[-3]
    recent_price = prices[-2]
    prev_price = prices[-3]

    avg_window = volumes[-13:-3]
    if not avg_window or prev_price <= 0:
        return None

    avg_vol = sum(avg_window) / len(avg_window)
    price_change = (recent_price - prev_price) / prev_price * 100

    is_long = check_long_signal(recent_vol, prev_vol, avg_vol, price_change)
    is_short = check_short_signal(recent_vol, prev_vol, avg_vol, price_change)

    return {
        "symbol": symbol,
        "price_change": price_change,
        "recent_vol": recent_vol,
        "prev_vol": prev_vol,
        "avg_vol": avg_vol,
        "is_long": is_long,
        "is_short": is_short,
    }


def send_signal_alert(analysis: dict) -> None:
    now = time.time()
    symbol = analysis["symbol"]

    if analysis["is_long"]:
        key = get_cooldown_key(symbol, "LONG", prefix="signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            print(f"{symbol} | LONG 쿨다운 중", flush=True)
            return

        last_alert_time[key] = now
        send_telegram(
            f"{symbol} 🚀 LONG 신호\n"
            f"확정 1분 변동률: {analysis['price_change']:.2f}%\n"
            f"최근 거래량: {analysis['recent_vol']:.2f}\n"
            f"이전 거래량: {analysis['prev_vol']:.2f}\n"
            f"평균 거래량: {analysis['avg_vol']:.2f}"
        )
        return

    if analysis["is_short"]:
        key = get_cooldown_key(symbol, "SHORT", prefix="signal")
        if key in last_alert_time and (now - last_alert_time[key] < SIGNAL_COOLDOWN):
            print(f"{symbol} | SHORT 쿨다운 중", flush=True)
            return

        last_alert_time[key] = now
        send_telegram(
            f"{symbol} 🔻 SHORT 신호\n"
            f"확정 1분 변동률: {analysis['price_change']:.2f}%\n"
            f"최근 거래량: {analysis['recent_vol']:.2f}\n"
            f"이전 거래량: {analysis['prev_vol']:.2f}\n"
            f"평균 거래량: {analysis['avg_vol']:.2f}"
        )


def check_signal(symbol: str) -> None:
    try:
        analysis = analyze_symbol(symbol)
        if not analysis:
            print(f"{symbol} | kline 데이터 부족", flush=True)
            return

        print(
            f"[SIGNAL] {symbol} | chg={analysis['price_change']:.2f}% | "
            f"recent_vol={analysis['recent_vol']:.2f} | "
            f"prev_vol={analysis['prev_vol']:.2f} | avg_vol={analysis['avg_vol']:.2f}",
            flush=True,
        )
        print(
            f"[DEBUG] {symbol} | long={analysis['is_long']} | short={analysis['is_short']}",
            flush=True,
        )

        if not analysis["is_long"] and not analysis["is_short"]:
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

            analysis = analyze_symbol(symbol)
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

            print(
                f"[ONCHAIN-CHART] {symbol} | from_onchain token={token_symbol} | "
                f"hub={is_hub} | exchange={exchange_hits} | "
                f"chg={analysis['price_change']:.2f}% | "
                f"recent_vol={analysis['recent_vol']:.2f} | avg_vol={analysis['avg_vol']:.2f}",
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
                f"확정 1분 변동률: {analysis['price_change']:.2f}%\n"
                f"최근 거래량: {analysis['recent_vol']:.2f}\n"
                f"평균 거래량: {analysis['avg_vol']:.2f}"
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

            symbols = get_final_symbols()
            print(f"최종 감시 종목: {symbols}", flush=True)

            if not symbols:
                print("감시 종목 없음", flush=True)

            for symbol in symbols:
                check_signal(symbol)
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
