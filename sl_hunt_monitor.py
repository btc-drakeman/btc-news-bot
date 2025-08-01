# sl_hunt_monitor.py

import pandas as pd
import requests
from notifier import send_telegram
from price_fetcher import get_current_price
from strategy import get_trend

BASE_URL = 'https://api.mexc.com'

# SL 헌팅 감지 함수 (단일 봉 분석)
def detect_sl_hunt(df, threshold=0.2, lookback=20):
    signals = []
    for i in range(lookback, len(df)):
        recent = df.iloc[i - lookback:i]
        high_max = recent['high'].max()
        low_min = recent['low'].min()

        curr = df.iloc[i]
        prev_volume_avg = recent['volume'].mean()

        broke_high = curr['high'] > high_max
        broke_low = curr['low'] < low_min
        high_volume = curr['volume'] > prev_volume_avg * 1.5

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

        # 보조 타임프레임 확인 조건 추가
        def confirm_on_lower(df):
            last = df.iloc[-1]
            wick = abs(last['high'] - last['low'])
            body = abs(last['close'] - last['open'])
            return body / wick < 0.4  # 꼬리가 더 긴 도지형 캔들

        def trend_context(df):
            return get_trend(df)  # UP / DOWN

        if not confirm_on_lower(df_5m):
            continue

        t, direction, hunt_price = signals[-1]
        price = get_current_price(symbol)
        trend = trend_context(df_30m)

        if direction == 'SHORT':
            msg = f"""
🚨 SL 헌팅 감지: {symbol} (SHORT 후보)

세력이 {hunt_price:.4f} 부근에 몰린 손절매를 유도한 뒤
강한 매도 반전을 시도 중입니다.

⚠ 이 구간은 SL이 집중된 '위험 지대'입니다. 
이 부근에서의 무리한 롱 진입은 손실 가능성이 큽니다.

📉 상위 추세: {trend}
💰 현재가: {price:.4f}
🔻 경계 가격대: {hunt_price:.4f}
"""
        else:
            msg = f"""
🚨 SL 헌팅 감지: {symbol} (LONG 후보)

세력이 {hunt_price:.4f} 부근에 몰린 손절매를 유도한 뒤
반등 흐름을 시도 중입니다.

⚠ 이 가격대는 SL이 대량으로 몰린 '저점 지대'입니다.
이 구간에서 숏을 따라갈 경우 낚일 수 있으니 주의하세요.

📈 상위 추세: {trend}
💰 현재가: {price:.4f}
🔺 경계 가격대: {hunt_price:.4f}
"""

        send_telegram(msg.strip())