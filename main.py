from flask import Flask
from threading import Thread
from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS
from analyzer import analyze_multi_tf
import time
import traceback

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"

def strategy_loop():
    """
    매 STRATEGY_INTERVAL_SECONDS마다 SYMBOLS 목록에 대해
    다중프레임 전략 분석을 수행하고,
    결과가 있을 때마다 텔레그램으로 알림을 전송합니다.
    """
    while True:
        for symbol in SYMBOLS:
            try:
                print(f"\n🔍 {symbol} 다중프레임 전략 분석 시작", flush=True)
                multi_msg = analyze_multi_tf(symbol)
                if multi_msg:
                    print(f"📤 다중프레임 전략 전송:\n{multi_msg}\n", flush=True)
                else:
                    print(f"📭 {symbol} 다중프레임 전략 신호 없음", flush=True)
                print(f"✅ {symbol} 전략 분석 완료", flush=True)
            except Exception as e:
                print(f"❌ {symbol} 전략 분석 중 오류 발생: {e}", flush=True)
                traceback.print_exc()

        print(f"⏱️ {STRATEGY_INTERVAL_SECONDS//60}분 대기 중...\n" + "="*50, flush=True)
        time.sleep(STRATEGY_INTERVAL_SECONDS)

if __name__ == '__main__':
    t1 = Thread(target=strategy_loop, daemon=True)
    t1.start()
    app.run(host='0.0.0.0', port=8080)
