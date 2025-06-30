import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime

# 텔레그램 봇 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']

# 분석할 코인 리스트
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']

# 타임프레임 별 MEXC API 인터벌 매핑
timeframes = {
    '10분봉': '5m',
    '1시간봉': '1h'
}

app = Flask(__name__)

def send_telegram(text):
    for user_id in USER_IDS:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            requests.post(url, data=data)
        except Exception as e:
            print(f"텔레그램 전송 오류 (chat_id={user_id}): {e}")

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
        return df, closes[-1]
    except Exception as e:
        print(f"{symbol} ({interval}) 데이터 요청 실패: {e}")
        return None, None

def calculate_indicators(df):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()

    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']
    return df

def analyze_single_tf(df, price_now):
    last = df.iloc[-1]
    score = 0

    if last['rsi'] < 30:
        score += 1
    elif last['rsi'] > 70:
        pass
    else:
        score += 0.5

    if last['macd'] > last['signal']:
        score += 1

    if price_now > last['bollinger_mid']:
        score += 1

    if last['ema_20'] > last['ema_50']:
        score += 1

    if df['volume'].iloc[-1] > df['volume'].rolling(window=20).mean().iloc[-1]:
        score += 1

    if score >= 4.5:
        return "롱 (5/5)"
    elif score >= 3:
        return "롱 (4/5)"
    elif score <= 1.5:
        return "숏 (1~2/5)"
    else:
        return "관망"

def analyze_symbol(symbol):
    summary = {}
    price_now = None
    for tf_name, interval in timeframes.items():
        df, price = fetch_ohlcv(symbol, interval)
        if df is None:
            return None
        price_now = price
        df = calculate_indicators(df)
        summary[tf_name] = analyze_single_tf(df, price_now)

    long_count = list(summary.values()).count("롱 (5/5)") + list(summary.values()).count("롱 (4/5)")
    short_count = list(summary.values()).count("숏 (1~2/5)")
    
    if long_count >= 2:
        decision = "🔥 <i>강한 롱 시그널</i>"
        direction = "롱"
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04
    elif short_count >= 2:
        decision = "⚠️ <i>숏 신호 주의</i>"
        direction = "숏"
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 1.02
        take_profit = price_now * 0.96
    else:
        decision = "🤔 <i>관망 추천</i>"
        direction = None

    msg = f"""
📊 <b>{symbol} 다중 분석</b>  
(i) 분석 기준: RSI, MACD, EMA, 볼린저밴드, 거래량
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: <b>${price_now:,.2f}</b>
"""
    for tf_name, result in summary.items():
        msg += f"\n🔹 <b>{tf_name}</b>: {result}"

    msg += f"\n\n📈 <b>종합 판단</b>: {decision}"

    if direction:
        msg += f"\n\n🎯 <b>진입가</b>: ${entry_low:,.2f} ~ ${entry_high:,.2f}"
        msg += f"\n🛑 <b>손절</b>: ${stop_loss:,.2f} | 🟢 <b>익절</b>: ${take_profit:,.2f}"

    return msg

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"분석 중: {symbol} ({datetime.now().strftime('%H:%M:%S')})")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            time.sleep(2)
        time.sleep(600)

@app.route('/')
def home():
    return "✅ MEXC 다중 기술분석 봇 작동 중"

if __name__ == '__main__':
    print("🟢 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
