import requests
import pandas as pd
from strategy import analyze_indicators

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
        return df
    except Exception as e:
        print(f"❌ {symbol} 데이터 가져오기 실패: {e}")
        return None


def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol)
    if df is None or len(df) < 50:
        return None

    direction, score = analyze_indicators(df)
    if direction == 'NONE':
        return None

    price = df['close'].iloc[-1]
    entry_low = round(price * 0.995, 2)
    entry_high = round(price * 1.005, 2)
    stop_loss = round(price * 0.985, 2)
    take_profit = round(price * 1.015, 2)

    return f"""
📊 {symbol} 기술 분석 결과
🕒 최근 가격: ${price:.2f}

🔵 추천 방향: {direction}
💰 진입 권장가: ${entry_low} ~ ${entry_high}
🛑 손절가: ${stop_loss}
🎯 익절가: ${take_profit}
    """