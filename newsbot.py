# ✅ newsbot.py (최종 수정 완료 — 순환 import 해결)
import requests
import pandas as pd
import time
from flask import Flask, request
from threading import Thread
from datetime import datetime, timedelta
import re

from config import BOT_TOKEN, USER_IDS, API_URL
from newsbot_utils import send_telegram, fetch_ohlcv, SYMBOLS
from newsbot_core import analysis_loop, analyze_symbol
from economic_alert import start_economic_schedule, handle_event_command

# === Flask 앱 생성 ===
app = Flask(__name__)

# === 최대 보유시간 설정 ===
symbol_max_hold_time = {
    "BTC_USDT": 30,
    "ETH_USDT": 75,
    "XRP_USDT": 120,
    "ETHFI_USDT": 60,
}

# === 포지션 메모리 ===
active_positions = {}

@app.route("/")
def home():
    return "Bot is running"

@app.route(f"/bot{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    print(f"📩 텔레그램 Webhook 데이터 수신됨:\n{data}")
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id", "")

    if text.lower() == "/start":
        send_telegram("✅ 봇이 정상 작동 중입니다!", chat_id)

    elif text.lower().startswith("/buy"):
        parts = text.split()
        if len(parts) == 2:
            symbol = parts[1].upper()
            price = fetch_latest_price(symbol)
            if price:
                store_position(symbol, "LONG", price)
                send_telegram(f"💼 {symbol} 매수 포지션 기록 완료\n진입가: ${price:.2f}", chat_id)
            else:
                send_telegram(f"❌ 가격 데이터를 가져올 수 없습니다: {symbol}", chat_id)
        else:
            send_telegram("사용법: /buy SYMBOL", chat_id)

    elif text.lower() == "/event":
        msg = handle_event_command()
        send_telegram(msg, chat_id)

    return "OK", 200

def store_position(symbol, direction, entry_price):
    active_positions[symbol.upper()] = {
        "entry_time": datetime.utcnow(),
        "direction": direction,
        "entry_price": entry_price
    }
    print(f"✅ 포지션 기록됨: {symbol} / {direction} / {entry_price}")

def position_monitor_loop():
    while True:
        now = datetime.utcnow()
        for symbol, info in list(active_positions.items()):
            max_hold = timedelta(minutes=symbol_max_hold_time.get(symbol, 60))
            if now - info["entry_time"] >= max_hold:
                kst_now = now + timedelta(hours=9)
                entry_kst = info["entry_time"] + timedelta(hours=9)
                message = f"""
⏰ <b>{symbol} 포지션 보유시간 초과</b>
📅 진입 시각 (KST): {entry_kst:%Y-%m-%d %H:%M}
🕒 현재 시각 (KST): {kst_now:%Y-%m-%d %H:%M}
📈 진입 방향: {info['direction']}
💰 진입가: ${info['entry_price']:.2f}
🚪 <b>최대 보유시간 도달 → 수동 청산 고려</b>"""
                send_telegram(message)
                del active_positions[symbol]
        time.sleep(60)

def fetch_latest_price(symbol):
    df = fetch_ohlcv(symbol, '1m')
    if df is not None and not df.empty:
        return df['close'].iloc[-1]
    return None

if __name__ == '__main__':
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop, daemon=True).start()
    Thread(target=start_economic_schedule, daemon=True).start()
    Thread(target=position_monitor_loop, daemon=True).start()
    while True:
        time.sleep(60)