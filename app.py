import os
import time
import threading
import traceback
import requests
from flask import Flask
import subprocess

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

EXCLUDED = {
    "BTC", "ETH", "SOL", "XRP", "DOGE",
    "BNB", "ADA", "TRX", "LINK", "LTC"
}

last_alert_time = {}
spot_loop_started = False
onchain_loop_started = False

SIGNAL_INTERVAL = 60      # 시세 감지: 1분
ONCHAIN_INTERVAL = 600    # 온체인: 10분


def send_telegram(msg: str) -> None:
    if not TOKEN or not CHAT_ID:
        print("텔레그램 환경변수 없음", flush=True)
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
        print(f"텔레그램 전송: {r.status_code}", flush=True)
    except Exception as e:
        print(f"텔레그램 오류: {e}", flush=True)


def get_spot_symbols():
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    data = requests.get(url, timeout=10).json()

    spot_map = {}

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


def get_futures_bases():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    data = requests.get(url, timeout=10).json()

    futures = set()

    for c in data.get("data", []):
        if c.get("quoteCoin") == "USDT" and c.get("settleCoin") == "USDT":
            base = c.get("baseCoin")
            if base and base not in EXCLUDED:
                futures.add(base)

    return futures


def get_top_symbols(n=50):
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=10).json()

    usdt_data = [x for x in data if x.get("symbol", "").endswith("USDT")]

    sorted_symbols = sorted(
        usdt_data,
        key=lambda x: float(x.get("quoteVolume", 0)),
        reverse=True
    )

    return [x["symbol"] for x in sorted_symbols[:n]]


def get_final_symbols():
    spot = get_spot_symbols()
    futures = get_futures_bases()
    top = set(get_top_symbols(50))

    final = []
    for base, symbol in spot.items():
        if base in futures and symbol in top:
            final.append(symbol)

    return final[:15]


def get_kline(symbol):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit=30"
    return requests.get(url, timeout=10).json()


def check_long_signal(recent_vol, prev_vol, avg_vol, price_change):
    return (
        avg_vol > 0
        and recent_vol > avg_vol * 2
        and recent_vol > prev_vol
        and price_change > 0.7
    )


def check_short_signal(recent_vol, prev_vol, avg_vol, price_change):
    return (
        avg_vol > 0
        and recent_vol > avg_vol * 2
        and recent_vol > prev_vol
        and price_change < -0.7
    )


def get_cooldown_key(symbol, side):
    return f"{symbol}_{side}"


def check_signal(symbol):
    try:
        data = get_kline(symbol)

        if not isinstance(data, list) or len(data) < 5:
            print(f"{symbol} | kline 데이터 부족", flush=True)
            return

        volumes = [float(x[5]) for x in data]
        prices = [float(x[4]) for x in data]

        recent_vol = volumes[-1]
        prev_vol = volumes[-2]
        avg_vol = sum(volumes[:-1]) / len(volumes[:-1])

        prev_price = prices[-2]
        last_price = prices[-1]

        if prev_price <= 0:
            return

        price_change = (last_price - prev_price) / prev_price * 100

        print(
            f"[SIGNAL] {symbol} | {price_change:.2f}% | "
            f"recent_vol={recent_vol:.2f} | prev_vol={prev_vol:.2f} | avg_vol={avg_vol:.2f}",
            flush=True
        )

        is_long = check_long_signal(recent_vol, prev_vol, avg_vol, price_change)
        is_short = check_short_signal(recent_vol, prev_vol, avg_vol, price_change)

        if not is_long and not is_short:
            return

        now = time.time()
        cooldown = 600  # 10분 재알림 제한

        if is_long:
            key = get_cooldown_key(symbol, "LONG")
            if key in last_alert_time and (now - last_alert_time[key] < cooldown):
                print(f"{symbol} | LONG 쿨다운 중", flush=True)
                return

            last_alert_time[key] = now

            send_telegram(
                f"{symbol} 🚀 LONG 신호\n"
                f"1분 변동률: {price_change:.2f}%\n"
                f"최근 거래량: {recent_vol:.2f}\n"
                f"이전 거래량: {prev_vol:.2f}\n"
                f"평균 거래량: {avg_vol:.2f}"
            )
            return

        if is_short:
            key = get_cooldown_key(symbol, "SHORT")
            if key in last_alert_time and (now - last_alert_time[key] < cooldown):
                print(f"{symbol} | SHORT 쿨다운 중", flush=True)
                return

            last_alert_time[key] = now

            send_telegram(
                f"{symbol} 🔻 SHORT 신호\n"
                f"1분 변동률: {price_change:.2f}%\n"
                f"최근 거래량: {recent_vol:.2f}\n"
                f"이전 거래량: {prev_vol:.2f}\n"
                f"평균 거래량: {avg_vol:.2f}"
            )

    except Exception as e:
        print(f"{symbol} 오류: {e}", flush=True)
        traceback.print_exc()


def run_onchain():
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
            text=True
        )

        if eth.stdout:
            print(eth.stdout, flush=True)
        if eth.stderr:
            print(eth.stderr, flush=True)

        print(f"[ONCHAIN][ETH] code={eth.returncode}", flush=True)
        print("[ONCHAIN] 종료", flush=True)

    except Exception as e:
        print(f"[ONCHAIN] 오류: {e}", flush=True)
        traceback.print_exc()


def signal_loop():
    while True:
        loop_start = time.time()

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
            wait_sec = SIGNAL_INTERVAL

        time.sleep(wait_sec)


def onchain_loop():
    while True:
        loop_start = time.time()

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
            wait_sec = ONCHAIN_INTERVAL

        time.sleep(wait_sec)


@app.route("/")
def home():
    return "bot is running", 200


@app.route("/health")
def health():
    return "ok", 200


def start_background_loops():
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