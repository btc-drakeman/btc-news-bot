from flask import Flask
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram
import time
import traceback  # ⬅️ 추가

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"

def loop():
    while True:
        for symbol in SYMBOLS:
            try:
                print(f"\n🔍 분석 시작: {symbol}", flush=True)
                result = analyze_symbol(symbol)

                if result:
                    print(f"📦 {symbol} 메시지 개수: {len(result)}", flush=True)
                    if isinstance(result, list):
                        for msg in result:
                            print(f"📤 전송할 메시지:\n{msg}\n", flush=True)
                            send_telegram(msg)
                    else:
                        print(f"📤 전송할 메시지:\n{result}\n", flush=True)
                        send_telegram(result)
                else:
                    print(f"📭 {symbol} 분석 결과 없음", flush=True)

                print(f"✅ {symbol} 분석 완료", flush=True)
            except Exception as e:
                print(f"❌ {symbol} 분석 중 오류 발생: {e}", flush=True)
                traceback.print_exc()  # ⬅️ 오류 상세 출력

        print("⏱️ 10분 대기 중...\n" + "="*50, flush=True)
        time.sleep(600)  # 10분 간격

if __name__ == '__main__':
    Thread(target=loop, daemon=True).start()  # 백그라운드 스레드 실행
    app.run(host='0.0.0.0', port=8080)
