# sl_hunt_monitor.py

import pandas as pd
import requests
from notifier import send_telegram
from price_fetcher import get_current_price
from strategy import get_trend

BASE_URL = 'https://api.mexc.com'

# 가격 포맷 함수
def format_price(price: float) -> str:
    if price >= 1000:
        return f"{price:.2f}"
    elif price >= 1:
        return f"{price:.3f}"
    elif price >= 0.1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.5f}"
    elif price >= 0.001:
        return f"{price:.6f}"
    elif price >= 0.0001:
        return f"{price:.7f}"
    elif price >= 0.00001:
        return f"{price:.8f}"
    else:
        return f"{price:.9f}"

# SL 헌팅 감지 함수 (단일 봉 분석)
def detect_sl_hunt(df, threshold=0.35, lookback=20):
    signals = []
    for i in range(lookback, len(df)):
        recent = df.iloc[i - lookback:i]
        high_max = recent['high'].max()
        low_min = recent['low'].min()

        curr = df.iloc[i]
        prev_volume_avg = recent['volume'].mean()

        broke_high = curr['high'] > high_max
        broke_low = curr['low'] < low_min
        high_volume = curr['volume'] > prev_volume_avg * 2.0

        upper_wick = curr['high'] - max(curr['close'], curr['open'])
        lower_wick = min(curr['close'], curr['open']) - curr['low']
        body = abs(curr['close'] - curr['open'])

        upper_wick_ratio = upper_wick / body if body > 0 else 0
        lower_wick_ratio = lower_wick / body if body > 0 else 0

        if broke_high and high_volume and upper_wick_ratio > threshold:
            signals.append((df.index[i], 'SHORT', curr['high']))
        elif broke_low and high_volume and lower_wick_ratio > threshold:
            signals.append((df.index[i], 'LONG', curr['low']))
    return signals

# 데이터 불러오기
def fetch_ohlcv(symbol: str, interval: str = '15m', limit: int = 100):
    endpoint = '/api/v3/klines'
    params = {'symbol': symbol, 'interval': interval, 'limit': limit}
    try:
        res = requests.get(BASE_URL + endpoint, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume'
        ])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df.set_index('timestamp')
    except Exception as e:
        print(f"❌ {symbol} OHLCV 로딩 실패: {e}")
        return None

def fetch_multi_ohlcv(symbol):
    df_15m = fetch_ohlcv(symbol, interval='15m')
    df_5m = fetch_ohlcv(symbol, interval='5m')
    df_30m = fetch_ohlcv(symbol, interval='30m')
    return df_15m, df_5m, df_30m

# SL 헌팅 탐지 후 텔레그램 알림

def run_sl_hunt_monitor(symbols):
    print("🚨 SL 헌팅 모니터링 시작")
    for symbol in symbols:
        df_15m, df_5m, df_30m = fetch_multi_ohlcv(symbol)
        if df_15m is None or df_5m is None or df_30m is None:
            continue

        signals = detect_sl_hunt(df_15m)
        if not signals:
            continue

        def confirm_on_lower(df):
            last = df.iloc[-1]
            wick = abs(last['high'] - last['low'])
            body = abs(last['close'] - last['open'])
            return body / wick < 0.25

        def trend_context(df):
            return get_trend(df)

        if not confirm_on_lower(df_5m):
            continue

        t, direction, hunt_price = signals[-1]
        price = get_current_price(symbol)
        trend = trend_context(df_30m)

        if direction == 'SHORT':
            msg = f"""
🚨 {symbol} - SL 헌팅 감지 (숏 진입 가능성)

📍 최근 {format_price(hunt_price)} 부근에서 매수세 과열 후 급락이 포착되었습니다.
📈 현재 추세는 {trend}이지만, 단기적으로는 매도 압력이 커질 수 있는 지점입니다.

⚠️ 지금 롱 진입은 낚일 가능성이 있습니다.

💰 현재가: {format_price(price)}
🔻 주요 반락 지점: {format_price(hunt_price)}
"""
        else:
            msg = f"""
🚨 {symbol} - SL 헌팅 감지 (롱 진입 가능성)

📍 최근 {format_price(hunt_price)} 부근에서 투매 발생 후 반등 시도가 포착되었습니다.
📉 현재 추세는 {trend}이지만, 단기적으로는 매수세가 살아날 수 있는 지점입니다.

⚠️ 지금 숏 진입은 낚일 가능성이 있습니다.

💰 현재가: {format_price(price)}
🔹 주요 반등 지점: {format_price(hunt_price)}
"""

        send_telegram(msg.strip())