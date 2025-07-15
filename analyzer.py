import requests
import pandas as pd
from strategy import analyze_indicators, generate_trade_plan
from config import SYMBOLS
from notifier import send_telegram

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
    from spike_detector import detect_spike_conditions, detect_crash_conditions

    df = fetch_ohlcv(symbol)
    if df is None or len(df) < 50:
        return None

    messages = []

    # 📌 전략 판단 및 ATR 계산
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

    direction, score = analyze_indicators(df)

    # 🔍 스파이크 조건 확인
    spike_signals = detect_spike_conditions(df)
    crash_signals = detect_crash_conditions(df)

    if spike_signals:
        signal_details = '\n- '.join(spike_signals)
        msg = f"""🚨 {symbol.upper()} 급등 전조 감지
- {signal_details}"""
        if direction == 'LONG':
            plan = generate_trade_plan(current_price, atr, direction)
            msg += f"""

📌 전략 진입 조건: ✅ LONG 진입 고려 가능
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}"""
        else:
            msg += "\n\n📌 전략 진입 조건: ❌ 미충족 (관망 권장)"
        messages.append(msg)

    if crash_signals:
        signal_details = '\n- '.join(crash_signals)
        msg = f"""⚠️ {symbol.upper()} 급락 전조 감지
- {signal_details}"""
        if direction == 'SHORT':
            plan = generate_trade_plan(current_price, atr, direction)
            msg += f"""

📌 전략 진입 조건: ✅ SHORT 진입 고려 가능
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}"""
        else:
            msg += "\n\n📌 전략 진입 조건: ❌ 미충족 (관망 권장)"
        messages.append(msg)

    return messages if messages else None
