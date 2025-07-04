# ✅ newsbot_utils.py (현물 기준 분석 + 레버리지별 손익폭 안내)
import requests
from datetime import datetime

from newsbot_core import analyze_multi_timeframe, get_now_price

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']

BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            res = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"📤 메시지 전송됨 → {uid}, 상태코드: {res.status_code}")
        except Exception as e:
            print(f"❌ 텔레그램 전송 오류 ({uid}): {e}")

def analyze_symbol(symbol: str):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    try:
        score, explain, price_now = analyze_multi_timeframe(symbol)
        print(f"📡 현재가: {price_now:.2f}, 점수: {score:.2f}")

        take_profit_10x = price_now * 1.02
        stop_loss_10x = price_now * 0.98
        take_profit_20x = price_now * 1.04
        stop_loss_20x = price_now * 0.96
        take_profit_30x = price_now * 1.06
        stop_loss_30x = price_now * 0.94
        take_profit_50x = price_now * 1.10
        stop_loss_50x = price_now * 0.90

        msg = f"""
📊 <b>{symbol} 기술분석 (현물 기준)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:.2f}

{explain}

🎯 <b>레버리지별 손익폭 참고</b>
🔹 10x: 익절가 ${take_profit_10x:.2f} / 손절가 ${stop_loss_10x:.2f}
🔸 20x: 익절가 ${take_profit_20x:.2f} / 손절가 ${stop_loss_20x:.2f}
🔺 30x: 익절가 ${take_profit_30x:.2f} / 손절가 ${stop_loss_30x:.2f}
🔻 50x: 익절가 ${take_profit_50x:.2f} / 손절가 ${stop_loss_50x:.2f}
"""
        return msg.strip()
    except Exception as e:
        print(f"❌ analyze_symbol() 오류: {e}")
        return None
