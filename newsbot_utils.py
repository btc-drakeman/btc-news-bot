# ✅ newsbot_utils.py (현물 분석 + 레버리지별 손익폭 안내)
import requests
import pandas as pd
from datetime import datetime
from config import API_URL, USER_IDS
from newsbot_core import analyze_multi_timeframe, get_now_price

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']

def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            requests.post(f"{API_URL}/sendMessage", data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"✅ 메시지 전송됨 → {uid}")
        except Exception as e:
            print(f"❌ 메시지 전송 실패 ({uid}): {e}")

def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    try:
        score, explain, price_now = analyze_multi_timeframe(symbol)
    except Exception as e:
        print(f"❌ 분석 실패: {e}")
        return None

    try:
        price_now = float(price_now)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        reference = f"""
📊 <b>{symbol} 기술분석 요약</b>
📅 분석 시각: <b>{now_str}</b>
💰 현재가: <b>${price_now:,.4f}</b>

{explain}

📉 <b>레버리지별 참고 손익폭</b>
🔹 10x: ±<b>{(price_now * 0.01):.2f}</b> USD
🔸 20x: ±<b>{(price_now * 0.005):.2f}</b> USD
🔺 30x: ±<b>{(price_now * 0.0033):.2f}</b> USD
🟥 50x: ±<b>{(price_now * 0.002):.2f}</b> USD
        """.strip()
        return reference
    except Exception as e:
        print(f"❌ 메시지 구성 실패: {e}")
        return None
