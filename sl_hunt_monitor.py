# sl_hunt_monitor.py

import pandas as pd
import requests
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

# 보조 타임프레임 조건 확인 (도지형 캔들)
def confirm_on_lower(df):
    last = df.iloc[-1]
    wick = abs(last['high'] - last['low'])
    body = abs(last['close'] - last['open'])
    return body / wick < 0.25

# SL 헌팅 통합 검사 함수 (진입 전략 후 호출용)
def check_sl_hunt_alert(symbol):
    try:
        from analyzer import fetch_ohlcv
        df_15m = fetch_ohlcv(symbol, interval='15m')
        df_5m = fetch_ohlcv(symbol, interval='5m')
        df_30m = fetch_ohlcv(symbol, interval='30m')
        if df_15m is None or df_5m is None or df_30m is None:
            return None

        signals = detect_sl_hunt(df_15m)
        if not signals:
            return None
        if not confirm_on_lower(df_5m):
            return None

        t, direction, hunt_price = signals[-1]
        price = get_current_price(symbol)
        trend = get_trend(df_30m)

        if direction == 'SHORT':
            msg = f"""
⚠️ 참고: 이 타이밍에서 SL 헌팅 반전 패턴이 감지되었습니다.
📍 최근 고점 돌파 후 급락 발생 → 단기 숏 시그널 주의 필요
🔻 헌팅 지점: {format_price(hunt_price)}
            """
        else:
            msg = f"""
⚠️ 참고: 이 타이밍에서 SL 헌팅 반전 패턴이 감지되었습니다.
📍 최근 투매 후 반등 발생 → 단기 롱 시그널 주의 필요
🔹 헌팅 지점: {format_price(hunt_price)}
            """

        return msg.strip()
    except Exception as e:
        print(f"❌ SL 헌팅 체크 오류 ({symbol}): {e}")
        return None

# 기존 SL 루프는 비활성화함 (통합됨)
# def run_sl_hunt_monitor(symbols):
#     ... 제거됨 ...
