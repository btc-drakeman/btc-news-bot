import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime

# 텔레그램 봇 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']  # 사용자 목록

# 분석할 코인 리스트
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']

app = Flask(__name__)

def send_telegram(text):
    for user_id in USER_IDS:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            response = requests.post(url, data=data)
            print(f"메시지 전송됨 → {user_id}")
        except Exception as e:
            print(f"텔레그램 전송 오류 (chat_id={user_id}): {e}")

def fetch_ohlcv(symbol):
    url = f"https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1m", "limit": 100}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        closes = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        df = pd.DataFrame({"close": closes, "volume": volumes})
        return df, closes[-1]
    except Exception as e:
        print(f"{symbol} 데이터 요청 실패: {e}")
        return None, None

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_symbol(symbol):
    df, price_now = fetch_ohlcv(symbol)
    if df is None:
        return None

    # 지표 계산
    df['rsi'] = calculate_rsi(df)
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df['macd'] = macd_line
    df['signal'] = signal_line
    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()
    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']

    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    explain = []

    # RSI
    rsi_score = last['rsi']
    if rsi_score < 30:
        score += 1
        explain.append(f"✅ RSI: {rsi_score:.1f} (과매도)")
    elif rsi_score > 70:
        explain.append(f"❌ RSI: {rsi_score:.1f}")
    else:
        explain.append(f"⚖️ RSI: {rsi_score:.1f}")

    # MACD
    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        score += 1
        explain.append("✅ MACD: 골든크로스 발생")
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        explain.append("❌ MACD: 데드크로스 발생")
    else:
        explain.append("⚖️ MACD: 교차 없음")

    # Bollinger Band
    if price_now > last['bollinger_mid']:
        score += 1
        explain.append("✅ 볼린저: 중심선 이상")
    else:
        explain.append("❌ 볼린저: 중심선 이하")

    # EMA
    if last['ema_20'] > last['ema_50']:
        score += 1
        explain.append("✅ EMA: 20/50 상단")
    else:
        explain.append("❌ EMA: 20/50 하단")

    # 거래량
    vol_now = df['volume'].iloc[-1]
    vol_avg = df['volume'].rolling(window=20).mean().iloc[-1]
    if vol_now > vol_avg * 1.1:
        score += 1
        explain.append("✅ 거래량: 평균 대비 뚜렷한 증가")
    else:
        explain.append("❌ 거래량: 뚜렷한 증가 없음")

    # 종합 판단
    if score >= 4:
        decision = f"🟢 ▶️ 종합 분석: 강한 매수 신호 (점수: {score}/5)"
        direction = "롱 (Long)"
    elif score <= 2:
        decision = f"🔴 ▶️ 종합 분석: 매도 주의 신호 (점수: {score}/5)"
        direction = "숏 (Short)"
    else:
        decision = f"⚖️ ▶️ 종합 분석: 관망 구간 (점수: {score}/5)"
        direction = "관망"

    if direction == "롱 (Long)":
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04
    elif direction == "숏 (Short)":
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 1.02
        take_profit = price_now * 0.96
    else:
        entry_low = entry_high = stop_loss = take_profit = None

    msg = f"""
📊 <b>{symbol} 기술 분석 (MEXC)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.4f}

"""
    msg += '\n'.join(explain)
    msg += f"\n\n{decision}"

    if direction != "관망":
        msg += f"\n\n📌 <b>전력 제안</b>"
        msg += f"\n- 🔁 <b>유리한 포지션</b>: {direction}"
        msg += f"\n- 🎯 <b>진입 권장가</b>: ${entry_low:,.2f} ~ ${entry_high:,.2f}"
        msg += f"\n- 🛑 <b>손절 제안</b>: ${stop_loss:,.2f}"
        msg += f"\n- 🟢 <b>익절 목표</b>: ${take_profit:,.2f}"

    return msg

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"분석 중: {symbol} ({datetime.now().strftime('%H:%M:%S')})")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            time.sleep(3)
        time.sleep(600)

@app.route('/')
def home():
    return "✅ MEXC 기술분석 보스 작동 중!"

if __name__ == '__main__':
    print("🟢 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
