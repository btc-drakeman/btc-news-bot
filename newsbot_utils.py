# ✅ newsbot_utils.py (현물 기준 분석 + 레버리지별 손익폭 안내)
import requests
import pandas as pd
from datetime import datetime

from config import API_URL, USER_IDS

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']

def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            res = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"✅ 메시지 전송됨 → {uid}, 상태코드: {res.status_code}")
        except Exception as e:
            print(f"❌ 텔레그램 전송 실패: {e}")

def get_now_price(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    res = requests.get(url)
    return float(res.json()['price'])

def analyze_multi_timeframe(symbol):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=15m&limit=100"
    res = requests.get(url)
    df = pd.DataFrame(res.json(), columns=[
        'timestamp','open','high','low','close','volume','close_time','qav','num_trades','taker_base_vol','taker_quote_vol','ignore'
    ])
    df['close'] = df['close'].astype(float)

    now_price = df['close'].iloc[-1]
    ma = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    upper = ma + 2 * std
    lower = ma - 2 * std

    band_status = "🔵 밴드 수렴 중" if (upper.iloc[-1] - lower.iloc[-1]) / now_price < 0.05 else "⚫️ 중립"
    score = 2.0 if band_status.startswith("🔵") else 1.0
    return score, band_status, now_price

def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    price_now = get_now_price(symbol)
    score, band_explain, price_now = analyze_multi_timeframe(symbol)

    tp_sl_text = ""
    for lev in [10, 20, 30, 50]:
        tp = price_now * (1 + 0.01 / lev)
        sl = price_now * (1 - 0.01 / lev)
        tp_sl_text += f"📈 <b>{lev}x 기준</b> 익절: ${tp:.2f} | 손절: ${sl:.2f}\n"

    message = f"""
📊 <b>{symbol} 기술분석 (현물 기준)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.2f}

{band_explain}

{tp_sl_text}📌 참고: 손익폭은 레버리지 비율에 따라 자동 계산됨.
    """
    return message.strip()
