import requests
import pandas as pd
from datetime import datetime
from config import API_URL, USER_IDS

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

def get_now_price(symbol):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=15m&limit=1"
    response = requests.get(url, timeout=10)
    data = response.json()
    return float(data[-1][4])  # 종가

def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    try:
        now_price = get_now_price(symbol)
    except Exception as e:
        print(f"❌ 가격 조회 실패: {e}")
        return None

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    explain = "⚙️ (샘플 설명) 기술적 분석 결과를 기반으로 한 판단 내용입니다."  # 추후 수정 가능

    try:
        reference = f"""
📊 <b>{symbol} 기술분석 (현물 기준)</b>
🕒 <b>{now}</b>
💰 현재가: <b>${now_price:,.4f}</b>

{explain}

🎯 <b>레버리지별 참고 손익폭</b>
🔹 10x: ±{(now_price * 0.01):.2f} USD
🔸 20x: ±{(now_price * 0.005):.2f} USD
🔺 30x: ±{(now_price * 0.0033):.2f} USD
🟥 50x: ±{(now_price * 0.002):.2f} USD
        """.strip()
        return reference
    except Exception as e:
        print(f"❌ 메시지 구성 실패: {e}")
        return None
