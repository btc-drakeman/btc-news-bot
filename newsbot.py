# newsbot.py

import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
import os
import re

# 기본 설정
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

    # RSI
    if last['rsi'] < 30:
        score += 1.0
        explain.append(f"📉 RSI: 과매도권 ↗ 반등 가능성")
    elif last['rsi'] > 70:
        explain.append(f"📈 RSI: 과매수권 ↘ 하락 경고")
    else:
        explain.append(f"⚖️ RSI: 중립")
    total_weight += 1.0

    # MACD
    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        score += 1.5
        explain.append(f"📊 MACD: 골든크로스 ↗ 상승 신호")
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        explain.append(f"📊 MACD: 데드크로스 ↘ 하락 신호")
    else:
        explain.append(f"📊 MACD: 특별한 신호 없음")
    total_weight += 1.5

    # EMA
    if last['ema_20'] > last['ema_50']:
        score += 1.2
        explain.append(f"📐 EMA: 단기 이평선이 장기 상단 ↗ 상승 흐름")
    else:
        explain.append(f"📐 EMA: 단기 이평선이 장기 하단 ↘ 하락 흐름")
    total_weight += 1.2

    # Bollinger Band
    if last['close'] < last['lower_band']:
        score += 0.8
        explain.append(f"📎 Bollinger: 하단 이탈 ↗ 기술적 반등 예상")
    elif last['close'] > last['upper_band']:
        explain.append(f"📎 Bollinger: 상단 돌파 ↘ 과열 우려")
    else:
        explain.append(f"📎 Bollinger: 밴드 내 중립")
    total_weight += 0.8

    # Volume
    try:
        if last['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.1:
            score += 0.5
            explain.append(f"📊 거래량: 평균 대비 증가 ↗ 수급 활발")
        else:
            explain.append(f"📊 거래량: 뚜렷한 변화 없음")
    except:
        explain.append(f"📊 거래량: 분석 불가")
    total_weight += 0.5

    return round((score / total_weight) * 5, 2)

def analyze_symbol(symbol, leverage=None):
    df, price_now = fetch_ohlcv(symbol)
    if df is None:
        return None

    df['rsi'] = calculate_rsi(df)
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

    last = df.iloc[-1]
    prev = df.iloc[-2]
    explain = []

    score = calculate_weighted_score(last, prev, df, explain)

    direction = "관망"
    if score >= 3.5:
        direction = "롱 (Long)"
    elif score <= 2.0:
        direction = "숏 (Short)"

    entry_low, entry_high = calculate_entry_range(df, price_now)

    # 레버리지 반영 손절/익절 비율 설정
    if leverage:
        lev = min(max(leverage, 1), 50)
        stop_rate = round(1.5 / lev, 4)
        take_rate = round(3.0 / lev, 4)
    else:
        stop_rate = 0.02
        take_rate = 0.04

    stop_loss = take_profit = None
    if direction == "롱 (Long)":
        stop_loss = price_now * (1 - stop_rate)
        take_profit = price_now * (1 + take_rate)
        action_msg = f"🟢 <b>추천 액션: 롱 포지션 진입</b>"
    elif direction == "숏 (Short)":
        stop_loss = price_now * (1*
