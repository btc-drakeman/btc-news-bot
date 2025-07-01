import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
import os
import re

BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT', 'SEIUSDT']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

app = Flask(__name__)

def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"메시지 전송됨 → {uid}")
        except Exception as e:
            print(f"텔레그램 전송 오류 (chat_id={uid}): {e}")

def fetch_ohlcv(symbol):
    url = f"https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": "1m", "limit": 300}
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

def calculate_entry_range(df, price_now):
    recent_volatility = df['close'].pct_change().abs().rolling(10).mean().iloc[-1]
    if pd.isna(recent_volatility) or recent_volatility == 0:
        return price_now * 0.995, price_now * 1.005
    buffer = max(0.0025, min(recent_volatility * 3, 0.015))
    return price_now * (1 - buffer), price_now * (1 + buffer)

def calculate_weighted_score(last, prev, df, explain):
    score = 0
    total_weight = 0

    if last['rsi'] < 30:
        score += 1.0
        explain.append("📉 RSI: 과매도권 ↗ 반등 가능성")
    elif last['rsi'] > 70:
        explain.append("📈 RSI: 과매수권 ↘ 하락 경고")
    else:
        explain.append("⚖️ RSI: 중립")
    total_weight += 1.0

    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        score += 1.5
        explain.append("📊 MACD: 골든크로스 ↗ 상승 신호")
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        explain.append("📊 MACD: 데드크로스 ↘ 하락 신호")
    else:
        explain.append("📊 MACD: 특별한 신호 없음")
    total_weight += 1.5

    if last['ema_20'] > last['ema_50']:
        score += 1.2
        explain.append("📐 EMA: 단기 이평선이 장기 상단 ↗ 상승 흐름")
    else:
        explain.append("📐 EMA: 단기 이평선이 장기 하단 ↘ 하락 흐름")
    total_weight += 1.2

    if last['close'] < last['lower_band']:
        score += 0.8
        explain.append("📎 Bollinger: 하단 이탈 ↗ 기술적 반등 예상")
    elif last['close'] > last['upper_band']:
        explain.append("📎 Bollinger: 상단 돌파 ↘ 과열 우려")
    else:
        explain.append("📎 Bollinger: 밴드 내 중립")
    total_weight += 0.8

    try:
        if last['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.1:
            score += 0.5
            explain.append("📊 거래량: 평균 대비 증가 ↗ 수급 활발")
        else:
            explain.append("📊 거래량: 뚜렷한 변화 없음")
    except:
        explain.append("📊 거래량: 분석 불가")
    total_weight += 0.5

    return round((score / total_weight) * 5, 2)

def get_safe_stop_rate(direction, leverage, default_stop_rate):
    if leverage is None:
        return default_stop_rate
    safe_margin = 0.8
    if direction == "롱 (Long)":
        max_safe_rate = 1 - 1 / (1 + 1 / leverage)
    elif direction == "숏 (Short)":
        max_safe_rate = (1 / (1 - 1 / leverage)) - 1
    else:
        return default_stop_rate
    return round(min(default_stop_rate, max_safe_rate * safe_margin), 4)

def analyze_symbol(symbol, leverage=None):
    df, price_now = fetch_ohlcv(symbol)
    if df is None:
        return None

    df['rsi'] = calculate_rsi(df)
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df['macd'] = macd_line
    df['signal'] = signal_line
    df['hist'] = df['macd'] - df['signal']
    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()
    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']

    last = df.iloc[-1]
    prev = df.iloc[-2]
    explain = []

    score = calculate_weighted_score(last, prev, df, explain)

    if score >= 3.5:
        decision = f"🟢 ▶️ 종합 분석: 강한 매수 신호 (점수: {score}/5)"
        direction = "롱 (Long)"
    elif score <= 2.0:
        decision = f"🔴 ▶️ 종합 분석: 매도 주의 신호 (점수: {score}/5)"
        direction = "숏 (Short)"
    else:
        decision = f"⚖️ ▶️ 종합 분석: 관망 구간 (점수: {score}/5)"
        direction = "관망"

    entry_low, entry_high = calculate_entry_range(df, price_now)

    if leverage:
        lev = min(max(leverage, 1), 50)
        stop_rate_base = round(1.5 / lev, 4)
        take_rate = round(3.0 / lev, 4)
    else:
        stop_rate_base = 0.02
        take_rate = 0.04

    stop_rate = get_safe_stop_rate(direction, leverage, stop_rate_base)

    stop_loss = take_profit = None
    if direction == "롱 (Long)":
        stop_loss = price_now * (1 - stop_rate)
        take_profit = price_now * (1 + take_rate)
    elif direction == "숏 (Short)":
        stop_loss = price_now * (1 + stop_rate)
        take_profit = price_now * (1 - take_rate)

    now_kst = datetime.utcnow() + timedelta(hours=9)
    msg = f"""
📊 <b>{symbol.upper()} 기술 분석 (MEXC)</b>
🕒 {now_kst.strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.4f}

""" + '\n'.join(explain) + f"\n\n{decision}"

    if direction != "관망":
        msg += f"""\n\n📌 <b>진입 전략 제안</b>
🎯 진입 권장가: ${entry_low:,.2f} ~ ${entry_high:,.2f}
🛑 손절가: ${stop_loss:,.2f}
🟢 익절가: ${take_profit:,.2f}"""
    else:
        msg += f"\n\n📌 참고 가격 범위: ${entry_low:,.2f} ~ ${entry_high:,.2f}"

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
    return "✅ MEXC 기술분석 봇 작동 중!"

@app.route(f"/bot{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'message' in data:
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '')
        match = re.match(r"/go (\w+)(?:\s+(\d+)x)?", text.strip(), re.IGNORECASE)
        if match:
            symbol = match.group(1).upper()
            leverage = int(match.group(2)) if match.group(2) else None
            msg = analyze_symbol(symbol, leverage)
            if msg:
                send_telegram(msg, chat_id=chat_id)
            else:
                send_telegram(f"⚠️ 분석 실패: {symbol} 데이터를 불러올 수 없습니다.", chat_id=chat_id)
    return '', 200

if __name__ == '__main__':
    print("🟢 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()