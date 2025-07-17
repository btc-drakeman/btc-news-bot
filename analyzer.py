import requests
import pandas as pd
from strategy import analyze_indicators, generate_trade_plan
from config import SYMBOLS
from notifier import send_telegram
from spike_detector import detect_spike_conditions, detect_crash_conditions

BASE_URL = 'https://api.mexc.com'

def fetch_ohlcv(symbol: str, interval: str = '15m', limit: int = 100):
    endpoint = '/api/v3/klines'
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }

    try:
        res = requests.get(BASE_URL + endpoint, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()

        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume'
        ])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    except Exception as e:
        print(f"❌ {symbol} 데이터 불러오기 실패: {e}")
        return None

def fetch_current_price(symbol: str):
    endpoint = '/api/v3/ticker/price'
    params = {'symbol': symbol}
    try:
        res = requests.get(BASE_URL + endpoint, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        return float(data['price'])
    except Exception as e:
        print(f"❌ {symbol} 현재가 가져오기 실패: {e}")
        return None

def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol)
    if df is None or len(df) < 50:
        return None

    messages = []

    # 📌 ATR 계산
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    atr = df['atr'].iloc[-1]

    current_price = fetch_current_price(symbol)
    if current_price is None:
        return None

    # ✅ 전략 판단 메시지 (기본 루프 기반)
    direction, score = analyze_indicators(df)
    if direction != 'NONE':
        if direction == 'LONG':
            entry_low = round(current_price * 0.995, 2)
            entry_high = round(current_price * 1.005, 2)
            stop_loss = round(current_price * 0.985, 2)
            take_profit = round(current_price * 1.015, 2)
        elif direction == 'SHORT':
            entry_low = round(current_price * 1.005, 2)
            entry_high = round(current_price * 0.995, 2)
            stop_loss = round(current_price * 1.015, 2)
            take_profit = round(current_price * 0.985, 2)

        msg = f"""
📊 {symbol} 기술 분석 결과
🕒 최근 가격: ${current_price:.2f}

🔵 추천 방향: {direction}
💰 진입 권장가: ${entry_low} ~ ${entry_high}
🛑 손절가: ${stop_loss}
🎯 익절가: ${take_profit}
"""
        messages.append(msg)

    # 🔍 급등/급락 시그널 감지 및 메시지 생성
    spike_msgs = detect_spike_conditions(df)
    if spike_msgs:
        messages.extend(spike_msgs)

    crash_msgs = detect_crash_conditions(df)
    if crash_msgs:
        messages.extend(crash_msgs)

    return messages if messages else None