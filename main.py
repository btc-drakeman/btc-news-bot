from flask import Flask
from threading import Thread
from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS, SPIKE_POLL_INTERVAL_SECONDS
from analyzer import analyze_symbol, fetch_market_data
from spike_detector import detect_spike_conditions, detect_crash_conditions
from notifier import send_telegram
import time
import traceback

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"


def strategy_loop():
    """
    매 STRATEGY_INTERVAL_SECONDS마다 SYMBOLS 목록에 대해 전략 분석을 수행하고
    결과가 있을 때마다 텔레그램으로 알림을 전송합니다.
    """
    while True:
        for symbol in SYMBOLS:
            try:
                print(f"\n🔍 전략 분석 시작: {symbol}", flush=True)
                result = analyze_symbol(symbol)

                if result:
                    msgs = result if isinstance(result, list) else [result]
                    print(f"📦 {symbol} 메시지 개수: {len(msgs)}", flush=True)
                    for msg in msgs:
                        print(f"📤 전송할 메시지:\n{msg}\n", flush=True)
                        send_telegram(msg)
                else:
                    print(f"📭 {symbol} 전략 분석 결과 없음", flush=True)

                print(f"✅ {symbol} 전략 분석 완료", flush=True)
            except Exception as e:
                print(f"❌ {symbol} 전략 분석 중 오류 발생: {e}", flush=True)
                traceback.print_exc()

        print(f"⏱️ {STRATEGY_INTERVAL_SECONDS//60}분 대기 중...\n" + "="*50, flush=True)
        time.sleep(STRATEGY_INTERVAL_SECONDS)


def spike_loop():
    """
    실시간으로 SYMBOLS 목록에 대해 급등/급락 조건을 감지하여
    조건 충족 시 텔레그램으로 알림을 전송합니다.
    """
    while True:
        for symbol in SYMBOLS:
            try:
                data = fetch_market_data(symbol)
                if detect_spike_conditions(data):
                    msg = f"🚀 {symbol} 급등 조건 충족"
                    print(f"📢 {msg}", flush=True)
                    send_telegram(msg)
                if detect_crash_conditions(data):
                    msg = f"🔻 {symbol} 급락 조건 충족"
                    print(f"📢 {msg}", flush=True)
                    send_telegram(msg)
            except Exception as e:
                print(f"❌ {symbol} 스파이크 감지 중 오류 발생: {e}", flush=True)
                traceback.print_exc()

        time.sleep(SPIKE_POLL_INTERVAL_SECONDS)


if __name__ == '__main__':
    # 1) 전략 분석 스레드
    t1 = Thread(target=strategy_loop, daemon=True)
    # 2) 스파이크 감지 스레드
    t2 = Thread(target=spike_loop, daemon=True)

    t1.start()
    t2.start()

    # Flask 서버 실행
    app.run(host='0.0.0.0', port=8080)
