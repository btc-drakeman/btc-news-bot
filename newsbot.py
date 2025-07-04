import requests
import pandas as pd
import time
from flask import Flask, request
from threading import Thread
from datetime import datetime, timedelta
import re

# === 텔레그램 설정 ===
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# === 분석할 코인 ===
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']

# === Flask 앱 생성 ===
app = Flask(__name__)

# === 최대 보유시간 (분) 설정 ===
symbol_max_hold_time = {
    "BTCUSDT": 30,
    "ETHUSDT": 75,
    "XRPUSDT": 120,
    "ETHFIUSDT": 60,
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
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
        except Exception as e:
            print(f"텔레그램 오류: {e}")

def fetch_ohlcv(symbol, interval='1m'):
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}"
    params = {"interval": interval, "limit": 200}
    try:
        for _ in range(3):
            res = requests.get(url, params=params, timeout=15)
            if res.status_code == 200:
                data = res.json().get("data", [])
                if not data:
                    continue
                closes = [float(x[4]) for x in data]
                volumes = [float(x[5]) for x in data]
                df = pd.DataFrame({"close": closes, "volume": volumes})
                return df
            else:
                time.sleep(1)
        raise Exception("재시도 실패")
    except Exception as e:
        print(f"{symbol} ({interval}) MEXC 데이터 요청 실패: {e}")
        return None

# 분석 로직과 지표 계산 함수 등은 newsbot_core.py에 위치한다고 가정
if __name__ == '__main__':
    from economic_alert import start_economic_schedule
    from newsbot_core import analysis_loop, analyze_symbol

    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop, daemon=True).start()
    Thread(target=start_economic_schedule, daemon=True).start()
    Thread(target=position_monitor_loop, daemon=True).start()
    while True:
        time.sleep(60)
