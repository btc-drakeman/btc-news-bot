import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
import os

BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT', 'XRPUSDT']

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
    params = {"symbol": symbol, "interval": "1m", "limit": 300}
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

    # RSI
    rsi_score = 0
    if last['rsi'] < 30:
        rsi_score = 1.0
        explain.append(f"📉 RSI: 과매도권 ↗ 반등 가능성")
    elif last['rsi'] > 70:
        explain.append(f"📈 RSI: 과매수권 ↘ 하락 경고")
    else:
        explain.append(f"⚖️ RSI: 중립")
    score += rsi_score
    total_weight += 1.0

    # MACD
    macd_score = 0
    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        macd_score = 1.5
        explain.append(f"📊 MACD: 골든크로스 ↗ 상승 신호")
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        explain.append(f"📊 MACD: 데드크로스 ↘ 하락 신호")
    else:
        explain.append(f"📊 MACD: 특별한 신호 없음")
    score += macd_score
    total_weight += 1.5

    # EMA
    ema_score = 0
    if last['ema_20'] > last['ema_50']:
        ema_score = 1.2
        explain.append(f"📐 EMA: 단기 이평선이 장기 상단 ↗ 상승 흐름")
    else:
        explain.append(f"📐 EMA: 단기 이평선이 장기 하단 ↘ 하락 흐름")
    score += ema_score
    total_weight += 1.2

    # Bollinger
    boll_score = 0
    if last['close'] < last['lower_band']:
        boll_score = 0.8
        explain.append(f"📎 Bollinger: 하단 이탈 ↗ 기술적 반등 예상")
    elif last['close'] > last['upper_band']:
        explain.append(f"📎 Bollinger: 상단 돌파 ↘ 과열 우려")
    else:
        explain.append(f"📎 Bollinger: 밴드 내 중립")
    score += boll_score
    total_weight += 0.8

    # Volume
    vol_score = 0
    try:
        vol_now = last['volume']
        vol_avg = df['volume'].rolling(window=20).mean().iloc[-1]
        if vol_now > vol_avg * 1.1:
            vol_score = 0.5
            explain.append(f"📊 거래량: 평균 대비 증가 ↗ 수급 활발")
        else:
            explain.append(f"📊 거래량: 뚜렷한 변화 없음")
    except:
        explain.append(f"📊 거래량: 분석 불가")
    score += vol_score
    total_weight += 0.5

    normalized_score = round((score / total_weight) * 5, 2)
    return normalized_score

def analyze_symbol(symbol):
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
        direction = "롱 (Long)"
    elif score <= 2.0:
        direction = "숏 (Short)"
    else:
        direction = "관망"

    entry_low, entry_high = calcu
