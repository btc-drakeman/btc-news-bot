# main.py - v5 전략 통합 버전

from flask import Flask, request
from threading import Thread
from datetime import datetime
from config import SYMBOLS
from strategy_v5 import run_strategy_v5, simulate_exit  # ✅ 전략 v5
from tracker import set_entry_price
from utils import get_current_price, fetch_ohlcv_all_timeframes
from notifier import send_telegram
from spike_detector import detect_spike, detect_crash

import time

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 MEXC 기술 분석 봇 v5 가동중"

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
            send_telegram("/🛒 사용방식: /buy SYMBOL", chat_id)

    return "ok"

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"🔍 {symbol} 분석 시작")
            try:
                data = fetch_ohlcv_all_timeframes(symbol)
                if not data or '15m' not in data:
                    print(f"⚠️ {symbol} 데이터 부족")
                    continue

                df = data['15m']
                if len(df) < 50:
                    print(f"⚠️ {symbol} 캔들 수 부족")
                    continue

                entry_ok, rsi, macd = run_strategy_v5(df)

                if entry_ok:
                    entry_price = df.iloc[-1]['close']
                    entry_time = df.index[-1]

                    exit_price, return_pct, reason, hold = simulate_exit(df, entry_price, len(df)-1)

                    msg = f"""
📊 {symbol} 기술 분석 (v5)
🕒 {entry_time.strftime('%Y-%m-%d %H:%M')}
💰 진입가: ${entry_price:.2f}

📎 RSI: {rsi:.2f}
📊 MACD 히스토그램: {macd:.4f}
⏳ 보유기간: {hold}봉

📌 청산가: ${exit_price:.2f}
💸 수익률: {return_pct:.2f}%
🚪 종료 사유: {reason}
                    """.strip()

                    send_telegram(msg)
                else:
                    print(f"⛔ {symbol} 진입 조건 불충족")

            except Exception as e:
                print(f"❌ {symbol} 분석 오류: {e}")

            # 급등/급락 감지
            try:
                if data and '15m' in data:
                    spike_msg = detect_spike(symbol, data['15m'])
                    if spike_msg:
                        send_telegram(spike_msg)

                    crash_msg = detect_crash(symbol, data['15m'])
                    if crash_msg:
                        send_telegram(crash_msg)
            except Exception as e:
                print(f"❌ {symbol} 급등락 감지 오류: {e}")

        time.sleep(900)  # 15분 주기 반복

if __name__ == '__main__':
    print("🔄 v5 전략 기반 분석 시작")
    thread = Thread(target=analysis_loop)
    thread.start()
    app.run(host='0.0.0.0', port=8080)
