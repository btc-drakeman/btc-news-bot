from flask import Flask
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_multi_tf
import time
import traceback
import datetime

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"

def strategy_loop():
    """
    5분, 15분, 30분, 1시간 모두 정각(봉 마감) 타이밍에 분석.
    신호가 일치할 때만 알림 발송.
    """
    print("🚦 멀티프레임 전략 분석 루프 시작")
    already_ran = set()
    while True:
        now = datetime.datetime.now()
        check = False

        # 5, 15, 30, 60분 프레임 모두 '정각 마감' 타이밍(5의 배수, 10초 이내)일 때만 실행
        if now.minute % 5 == 0 and now.second < 10:
            time_key = now.strftime('%Y%m%d%H%M')
            if time_key not in already_ran:
                check = True
                already_ran.add(time_key)

        if check:
            for symbol in SYMBOLS:
                try:
                    print(f"\n🔍 [{now.strftime('%Y-%m-%d %H:%M:%S')}] {symbol} 멀티프레임 전략 분석 시작", flush=True)
                    multi_msg = analyze_multi_tf(symbol)
                    if multi_msg:
                        print(f"📤 전략 전송:\n{multi_msg}\n", flush=True)
                    else:
                        print(f"📭 {symbol} 전략 신호 없음", flush=True)
                    print(f"✅ {symbol} 전략 분석 완료", flush=True)
                except Exception as e:
                    print(f"❌ {symbol} 전략 분석 중 오류 발생: {e}", flush=True)
                    traceback.print_exc()
            # 오래된 타임키는 메모리 보호용으로 정리(옵션)
            if len(already_ran) > 2000:
                already_ran = set(list(already_ran)[-1000:])
        time.sleep(5)

if __name__ == '__main__':
    t1 = Thread(target=strategy_loop, daemon=True)
    t1.start()
    app.run(host='0.0.0.0', port=8080)
