# ✅ newsbot_utils.py (현물 기준 분석 + 레버리지별 손익폭 안내 포함)
import requests
import pandas as pd
from datetime import datetime
from config import API_URL, BOT_TOKEN, USER_IDS

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ETHFIUSDT"]

HEADERS = {
    'User-Agent': 'Mozilla/5.0'
}

# 이모지 세트
EMOJI = {
    "up": "📈",
    "down": "📉",
    "neutral": "➖",
    "check": "✅",
    "warn": "⚠️",
    "info": "ℹ️",
    "bot": "🤖",
    "money": "💰",
    "time": "⏰"
}

def send_telegram(text):
    for uid in USER_IDS:
        try:
            response = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"📤 메시지 전송 시도: {text[:30]}...\n✅ 메시지 전송됨 → {uid}, 상태코드: {response.status_code}")
        except Exception as e:
            print(f"❌ 텔레그램 전송 실패 ({uid}): {e}")

def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=15m"
    print(f"📡 요청 URL: {url}")
    
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"❌ 데이터 요청 실패: {e}")
        return None

    if not data or isinstance(data, dict):
        print("❌ 받은 데이터가 비정상적입니다")
        return None

    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])

    df['close'] = df['close'].astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    close = df['close']
    current_price = close.iloc[-1]
    prev_price = close.iloc[-2]
    change_pct = ((current_price - prev_price) / prev_price) * 100

    direction = EMOJI['up'] if change_pct > 0 else EMOJI['down'] if change_pct < 0 else EMOJI['neutral']
    
    kst_now = datetime.utcnow() + pd.Timedelta(hours=9)
    
    # 레버리지별 참고 손익폭 계산
    ref_rows = []
    for lev in [10, 20, 30, 50]:
        tp = current_price * (1 + (0.02 / lev))
        sl = current_price * (1 - (0.01 / lev))
        ref_rows.append(f"<b>{lev}x</b> ➤ 익절: ${tp:.2f} / 손절: ${sl:.2f}")

    reference_price_info = '\n'.join(ref_rows)

    message = f"""
{EMOJI['bot']} <b>{symbol} 기술분석</b>
{EMOJI['time']} 기준 시각 (KST): {kst_now:%Y-%m-%d %H:%M:%S}

{EMOJI['money']} 현재가: ${current_price:.2f} {direction} ({change_pct:.2f}%)

📌 <b>레버리지별 참고 손익폭</b>
{reference_price_info}
"""
    return message.strip()
