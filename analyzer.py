import requests
import pandas as pd
from strategy import get_trend, entry_signal
from config import SYMBOLS
from notifier import send_telegram
import datetime

BASE_URL = 'https://api.mexc.com'

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

# Alias for market data fetching in main.py and spike detector
fetch_market_data = fetch_ohlcv

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

def format_price(price: float) -> str:
    if price >= 1000:
        return f"{price:.2f}"
    elif price >= 1:
        return f"{price:.3f}"
    elif price >= 0.1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.5f}"
    else:
        return f"{price:.6f}"

def analyze_multi_tf(symbol: str):
    """
    30분봉 방향에 따라 5분봉 LONG/SHORT 진입 신호를 판별해 텔레그램 알림 발송
    """
    # 30분봉 데이터
    df_30m = fetch_ohlcv(symbol, interval='30m', limit=50)
    if df_30m is None or len(df_30m) < 25:
        return None

    # 5분봉 데이터
    df_5m = fetch_ohlcv(symbol, interval='5m', limit=50)
    if df_5m is None or len(df_5m) < 25:
        return None

    trend = get_trend(df_30m)  # 'UP' 또는 'DOWN'

    direction = None
    if trend == 'UP':
        direction = 'LONG'
    elif trend == 'DOWN':
        direction = 'SHORT'

    if direction and entry_signal(df_5m, direction):
        price = df_5m["close"].iloc[-1]
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = (
            f"📈 [{now}] {symbol}\n"
            f"30분봉 EMA20 {('상승장' if direction=='LONG' else '하락장')} + 5분봉 {direction} 진입 신호!\n"
            f"최근가: ${format_price(price)}"
        )
        send_telegram(msg)
        return msg
    return None
