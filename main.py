from flask import Flask
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram
from box_detector import detect_box_trade_signal  # ✅ 박스권 전략 추가
import time
import traceback

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

                # ✅ 박스권 전략 메시지도 병렬 전송
                box_msg = detect_box_trade_signal(df=analyze_symbol.df_cache[symbol], symbol=symbol)
                if box_msg:
                    print(f"📤 [박스권] 전송할 메시지:\n{box_msg}\n", flush=True)
                    send_telegram(box_msg)

                print(f"✅ {symbol} 분석 완료", flush=True)
            except Exception as e:
                print(f"❌ {symbol} 분석 중 오류 발생: {e}", flush=True)
                traceback.print_exc()

        print(⏱️ 10분 대기 중...\n" + "="*50, flush=True)
        time.sleep(600)

if __name__ == '__main__':
    Thread(target=loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)
