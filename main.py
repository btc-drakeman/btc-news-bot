# main.py - /buy SYMBOL 명령 처리 포함 + 급등/급락 전조 감지 추가

from flask import Flask, request
from threading import Thread
from datetime import datetime
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram
from tracker import set_entry_price
from utils import get_current_price, fetch_ohlcv_all_timeframes
from spike_detector import detect_spike, detect_crash  # ✅ 급락 감지도 추가

import time

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 MEXC 기술 분석 봇 가동중"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    message = data.get('message', {}).get('text', '')
    chat_id = data.get('message', {}).get('chat', {}).get('id')

    if message.startswith("/buy"):
        parts = message.strip().split()
        if len(parts) == 2:
            symbol = parts[1].upper()
            price = get_current_price(symbol)
            if price:
                set_entry_price(symbol, price)
                send_telegram(f"✅ {symbol} 진입가 ${price} 기록 완료", chat_id)
            else:
                send_telegram(f"❌ {symbol} 가격 모음 실패", chat_id)
        else:
            send_telegram("/♥️ 사용방식: /buy SYMBOL", chat_id)

    return "ok"

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"🔀 루프 진입: {symbol}")

            try:
                # ✅ 기술 분석 수행
                result = analyze_symbol(symbol)
                if result:
                    try:
                        send_telegram(result)
                    except Exception as e:
                        print(f"❌ Telegram 전송 실패: {e}")
                else:
                    print(f"⚠️ {symbol} 분석 실패 (데이터 부족)")
            except Exception as e:
                print(f"❌ 분석 중 오류 발생 ({symbol}): {e}")

            try:
                # ✅ 급등/급락 전조 감지
                data = fetch_ohlcv_all_timeframes(symbol)
                if data and '15m' in data:
                    try:
                        spike_msg = detect_spike(symbol, data['15m'])
                        if spike_msg:
                            send_telegram(spike_msg)
                    except Exception as e:
                        print(f"❌ 급등 감지 실패: {e}")

                    try:
                        crash_msg = detect_crash(symbol, data['15m'])
                        if crash_msg:
                            send_telegram(crash_msg)
                    except Exception as e:
                        print(f"❌ 급락 감지 실패: {e}")
                else:
                    print(f"⚠️ {symbol} 15분봉 데이터 부족으로 감지 생략")
            except Exception as e:
                print(f"❌ 감지 루틴 실패 ({symbol}): {e}")

        time.sleep(900)  # 15분마다 반복


if __name__ == '__main__':
    print("🔍 분석 시작")
    thread = Thread(target=analysis_loop)
    thread.start()
    app.run(host='0.0.0.0', port=8080)
