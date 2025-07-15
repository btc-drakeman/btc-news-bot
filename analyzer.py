import requests
import pandas as pd
from strategy import analyze_indicators, generate_trade_plan
from config import SYMBOLS
from notifier import send_telegram
from spike_detector import detect_spike, detect_crash

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

    # 📌 급등/급락 시그널 감지
    spike_msg = detect_spike(symbol, df)
    if spike_msg:
        messages.append(spike_msg)

    crash_msg = detect_crash(symbol, df)
    if crash_msg:
        messages.append(crash_msg)

    # 📌 전략 분석 (롱/숏)
    direction, score = analyze_indicators(df)
    if direction != 'NONE':
        current_price = fetch_current_price(symbol)
        if current_price is None:
            return None

        # ✅ ATR 계산
        df['tr'] = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        df['atr'] = df['tr'].rolling(14).mean()
        atr = df['atr'].iloc[-1]

        if pd.isna(atr) or atr == 0:
            print(f"⚠️ {symbol} ATR 계산 실패")
            return None

        plan = generate_trade_plan(current_price, atr, direction)

        # ✅ 방향별 메시지 이모지 구분
        emoji = "📈" if direction == 'LONG' else "📉"

        msg = f"""
{emoji} {symbol.upper()} 기술 분석 (MEXC)
🕒 최근 시세 기준
💰 현재가: ${current_price:,.4f}

▶️ 추천 방향: {direction}
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}
        """
        messages.append(msg.strip())

    return messages if messages else None
