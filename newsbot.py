import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime
import numpy as np

# 텔레그램 봇 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']  # ✅ 사용자 목록

# 분석할 코인 리스트
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']
TIMEFRAMES = {'10m': '10m', '1h': '1h'}  # 분석 시간대

app = Flask(__name__)

def debug_log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def send_telegram(text):
    for user_id in USER_IDS:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            response = requests.post(url, data=data)
            debug_log(f"메시지 전송 완료 → {user_id}")
        except Exception as e:
            debug_log(f"❌ 텔레그램 전송 실패 (chat_id={user_id}): {e}")

def fetch_ohlcv(symbol, interval):
    url = f"https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 100}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        closes = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        df = pd.DataFrame({"close": closes, "volume": volumes})
        debug_log(f"{symbol} {interval} 데이터 수신 완료")
        return df, closes[-1]
    except Exception as e:
        debug_log(f"❌ {symbol} ({interval}) 데이터 요청 실패: {e}")
        return None, None

def calculate_indicators(df):
    try:
        # RSI (Smoothed)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD (정확한 수식)
        ema_12 = df['close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_12 - ema_26
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # EMA
        df['ema_20'] = df['close'].ewm(span=20).mean()
        df['ema_50'] = df['close'].ewm(span=50).mean()

        # 볼린저 밴드
        df['bollinger_mid'] = df['close'].rolling(window=20).mean()
        df['bollinger_std'] = df['close'].rolling(window=20).std()
        df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
        df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']

        return df
    except Exception as e:
        debug_log(f"❌ 지표 계산 오류: {e}")
        return None

def analyze_symbol(symbol):
    results = []
    debug_log(f"▶️ {symbol} 다중 타임프레임 분석 시작")

    for label, tf in TIMEFRAMES.items():
        df, price_now = fetch_ohlcv(symbol, tf)
        if df is None:
            continue

        df = calculate_indicators(df)
        if df is None:
            continue

        last = df.iloc[-1]
        score = 0
        parts = []

        if last['rsi'] < 30:
            score += 1
            parts.append("RSI 과매도")
        elif last['rsi'] > 70:
            parts.append("RSI 과매수")
        else:
            parts.append("RSI 중립")

        if last['macd'] > last['signal']:
            score += 1
            parts.append("MACD 상승")
        else:
            parts.append("MACD 하락")

        if price_now > last['bollinger_mid']:
            score += 1
            parts.append("볼린저 상단")
        else:
            parts.append("볼린저 하단")

        if last['ema_20'] > last['ema_50']:
            score += 1
            parts.append("EMA 20>50")
        else:
            parts.append("EMA 20<50")

        if df['volume'].iloc[-1] > df['volume'].rolling(window=20).mean().iloc[-1]:
            score += 1
            parts.append("거래량 ↑")
        else:
            parts.append("거래량 ↓")

        # 결정
        if score >= 4:
            status = f"🟢 강매 ({score}/5)"
        elif score <= 2:
            status = f"🔴 매도주의 ({score}/5)"
        else:
            status = f"⚖️ 관망 ({score}/5)"

        result = f"⏱️ {label} → {status}"
        subinfo = f"({', '.join(parts)})"
        results.append((result, subinfo))

    if not results:
        return None

    final_text = f"""
📊 <b>{symbol} 다중 분석</b>
<code>(RSI, MACD, 볼린저밴드, EMA, 거래량 기반)</code>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

""" + "\n".join([f"{r} {s}" for r, s in results])

    return final_text

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            debug_log(f"분석 중: {symbol}")
            msg = analyze_symbol(symbol)
            if msg:
                send_telegram(msg)
            time.sleep(3)
        debug_log("⏳ 10분 대기 후 재분석")
        time.sleep(600)

@app.route('/')
def home():
    return "✅ MEXC 기술분석 봇 작동 중!"

if __name__ == '__main__':
    print("🟢 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
