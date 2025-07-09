from strategy import analyze_indicators
from spike_detector import detect_spike, detect_crash
import requests
import pandas as pd

BASE_URL = 'https://api.mexc.com/api/v3/klines'

def fetch_ohlcv(symbol: str, interval: str = '1m', limit: int = 100):
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume'
        ])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ {symbol} 데이터 가져오기 실패: {e}")
        return None

def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol)
    if df is None or len(df) < 50:
        return None

    messages = []

    # 급등/급락 전조 시그널
    spike_msg = detect_spike(symbol, df)
    if spike_msg:
        messages.append(spike_msg)

    crash_msg = detect_crash(symbol, df)
    if crash_msg:
        messages.append(crash_msg)

    # 기술적 분석
    direction, score = analyze_indicators(df)
    if direction != 'NONE':
        price = df['close'].iloc[-1]
        entry_low = round(price * 0.995, 2)
        entry_high = round(price * 1.005, 2)
        stop_loss = round(price * 0.985, 2)
        take_profit = round(price * 1.015, 2)

        msg = f"""
📊 {symbol} 기술 분석 (MEXC)
💰 현재가: ${price:.2f}
📈 전략: {direction} / 점수: {score:.2f}

🎯 진입가: ${entry_low} ~ ${entry_high}
🛑 손절: ${stop_loss} | 🟢 익절: ${take_profit}
"""
        messages.append(msg.strip())

    return messages if messages else None
