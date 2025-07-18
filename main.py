import os
import sys
# 프로젝트 루트(이 파일이 있는 디렉토리)를 모듈 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_symbol, fetch_ohlcv  # fetch_ohlcv 사용
from notifier import send_telegram
from box_detector import detect_box_trade_signal  # 박스권 전략
from multi_factor_trend_strategy import run_multi_factor_live  # 멀티-팩터 전략
import time
import traceback

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 박스권 포함 봇 실행 중"


def loop():
    while True:
        for symbol in SYMBOLS:
            try:
                print(f"\n🔍 분석 시작: {symbol}", flush=True)

                # OHLCV 데이터 직접 추출 (박스권용)
                df = fetch_ohlcv(symbol)

                # 일반 분석
                result = analyze_symbol(symbol)
                if result:
                    print(f"📦 {symbol} 메시지 개수: {len(result)}", flush=True)
                    for msg in result:
                        print(f"📤 전송할 메시지:\n{msg}\n", flush=True)
                        send_telegram(msg)
                else:
                    print(f"📭 {symbol} 분석 결과 없음", flush=True)

                # 박스권 전략 메시지
                if df is not None:
                    box_msg = detect_box_trade_signal(df=df, symbol=symbol)
                    if box_msg:
                        print(f"📤 [박스권] 전송할 메시지:\n{box_msg}\n", flush=True)
                        send_telegram(box_msg)

                # 멀티-팩터 트렌드 전략 실시간 알림
                try:
                    df15 = fetch_ohlcv(symbol, timeframe='15m')
                    if df15 is not None:
                        run_multi_factor_live(symbol, df15)
                except Exception as e:
                    print(f"❌ 멀티-팩터 전략 오류 for {symbol}: {e}", flush=True)
                    traceback.print_exc()

                print(f"✅ {symbol} 분석 완료", flush=True)

            except Exception as e:
                print(f"❌ {symbol} 분석 중 오류 발생: {e}", flush=True)
                traceback.print_exc()

        print("⏱️ 10분 대기 중...\n" + "="*50, flush=True)
        time.sleep(600)


if __name__ == '__main__':
    Thread(target=loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)
