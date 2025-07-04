import requests
import pandas as pd
import time
from config import MEXC_API_KEY
from flask import Flask, request
from threading import Thread
from datetime import datetime, timedelta
import re

# === 텔레그램 설정 ===
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# === 분석할 코인 ===
SYMBOLS = ['BTC_USDT', 'ETH_USDT', 'XRP_USDT', 'ETHFI_USDT']

# === Flask 앱 생성 ===
app = Flask(__name__)

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

    return "OK", 200

# === 최대 보유시간 (분) 설정 ===
symbol_max_hold_time = {
    "BTC_USDT": 30,
    "ETH_USDT": 75,
    "XRP_USDT": 120,
    "ETHFI_USDT": 60,
}

# === 포지션 메모리 ===
active_positions = {}

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

def send_telegram(text, chat_id=None):
    print(f"📤 메시지 전송 시도: {text[:30]}...")  # 앞부분만 찍기
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            response = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"✅ 메시지 전송됨 → {uid}, 상태코드: {response.status_code}")
            if response.status_code != 200:
                print(f"📛 응답 내용: {response.text}")
        except Exception as e:
            print(f"❌ 텔레그램 오류: {e}")

import requests
import pandas as pd
from config import MEXC_API_KEY

def fetch_ohlcv(symbol, interval):
    url = "https://contract.mexc.com/api/v1/kline"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": 300
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "ApiKey": MEXC_API_KEY  # 인증 헤더 (공식문서에 명시되어있지는 않지만 일부 시스템에서는 인식함)
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        print(f"📡 요청 URL: {response.url}")
        print(f"📨 응답 예시: {response.text[:200]}...")
        response.raise_for_status()
        raw = response.json().get("data", [])

        df = pd.DataFrame(raw)
        if df.empty:
            return None

        df.columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        print(f"{symbol} ({interval}) MEXC 선물 데이터 요청 실패: {e}")
        return None

def fetch_latest_price(symbol):
    df = fetch_ohlcv(symbol, '1m')
    if df is not None and not df.empty:
        return df['close'].iloc[-1]
    return None

if __name__ == '__main__':
    from economic_alert import start_economic_schedule
    from newsbot_core import analysis_loop, analyze_symbol

    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop, daemon=True).start()
    Thread(target=start_economic_schedule, daemon=True).start()
    Thread(target=position_monitor_loop, daemon=True).start()
    while True:
        time.sleep(60)
