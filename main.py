# main.py - /buy SYMBOL 명령 처리 포함 + 급등 전조 감지 추가

from flask import Flask, request
from threading import Thread
from datetime import datetime
from config import SYMBOLS
from analyzer import analyze_symbol
from notifier import send_telegram
from tracker import set_entry_price
from utils import get_current_price, fetch_ohlcv_all_timeframes  # ✅ fetch 추가
from spike_detector import detect_spike  # ✅ 급등 감지 로직 추가

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

            # ✅ 기존 기술 분석 수행
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            else:
                print(f"⚠️ {symbol} 분석 실패 (데이터 부족)")

            # ✅ 급등 전조 감지 (15분봉 기준)
            data = fetch_ohlcv_all_timeframes(symbol)
            if data and '15m' in data:
                spike_msg = detect_spike(symbol, data['15m'])
                if spike_msg:
                    send_telegram(spike_msg)

        time.sleep(900)  # 15분마다 반복

if __name__ == '__main__':
    print("🔍 분석 시작")
    thread = Thread(target=analysis_loop)
    thread.start()
    app.run(host='0.0.0.0', port=8080)
