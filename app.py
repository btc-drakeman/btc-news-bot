import os
import time
import threading
import traceback
import requests
from flask import Flask
import subprocess

app = Flask(__name__)

# Render 환경변수 이름
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

EXCLUDED = {
    "BTC", "ETH", "SOL", "XRP", "DOGE",
    "BNB", "ADA", "TRX", "LINK", "LTC"
}

last_alert_time = {}
loop_started = False
last_onchain_time = 0
ONCHAIN_INTERVAL = 900  # 15분


def send_telegram(msg):
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
    data = requests.get(url, timeout=5).json()

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
    data = requests.get(url, timeout=5).json()

    futures = set()

    for c in data.get("data", []):
        if c.get("quoteCoin") == "USDT" and c.get("settleCoin") == "USDT":
            base = c.get("baseCoin")
            if base and base not in EXCLUDED:
                futures.add(base)

    return futures


def get_top_symbols(n=50):
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    data = requests.get(url, timeout=5).json()

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
    return requests.get(url, timeout=5).json()


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
            f"{symbol} | {price_change:.2f}% | recent_vol={recent_vol:.2f} | avg_vol={avg_vol:.2f}",
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


def detect_loop():
    global last_onchain_time

    while True:
        loop_start = time.time()

        try:
            print("=" * 60, flush=True)
            print(f"[LOOP START] {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

            now = time.time()
            if now - last_onchain_time >= ONCHAIN_INTERVAL:
                print("[ONCHAIN] 주기 실행 조건 충족", flush=True)
                run_onchain()
                last_onchain_time = now

            symbols = get_final_symbols()
            print(f"최종 감시 종목: {symbols}", flush=True)

            if not symbols:
                print("감시 종목 없음", flush=True)

            for symbol in symbols:
                check_signal(symbol)
                time.sleep(0.2)

            elapsed = time.time() - loop_start
            print(f"[LOOP END] elapsed={elapsed:.1f}s -> 60초 대기", flush=True)

        except Exception as e:
            print(f"detect_loop 오류: {e}", flush=True)
            traceback.print_exc()

        time.sleep(60)

def run_onchain():
    print("[ONCHAIN] 시작", flush=True)

    try:
        # 🔵 ETH
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
                "30"
            ],
            capture_output=True,
            text=True
        )
        print(eth.stdout, flush=True)
        print(eth.stderr, flush=True)
        print(f"[ONCHAIN][ETH] code={eth.returncode}", flush=True)

        # 🟡 BSC
        print("[ONCHAIN] BSC 분석 시작", flush=True)
        bsc = subprocess.run(
            [
                "python",
                "eth_repeat_wallet_mvp.py",
                "--seeds",
                "seed_addresses.txt",
                "--chainid",
                "56",
                "--days",
                "30"
            ],
            capture_output=True,
            text=True
        )
        print(bsc.stdout, flush=True)
        print(bsc.stderr, flush=True)
        print(f"[ONCHAIN][BSC] code={bsc.returncode}", flush=True)

        print("[ONCHAIN] 종료", flush=True)

    except Exception as e:
        print(f"[ONCHAIN] 오류: {e}", flush=True)
        traceback.print_exc()

@app.route("/")
def home():
    return "bot is running", 200


@app.route("/health")
def health():
    return "ok", 200


def start_background_loop():
    global loop_started

    if loop_started:
        print("백그라운드 루프 이미 시작됨", flush=True)
        return

    loop_started = True
    thread = threading.Thread(target=detect_loop, daemon=True)
    thread.start()
    print("백그라운드 루프 시작 완료", flush=True)


start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)