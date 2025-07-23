import requests
import pandas as pd
from strategy import get_trend, entry_signal_ema_only
from config import SYMBOLS
from notifier import send_telegram
import datetime

BASE_URL = 'https://api.mexc.com'

def fetch_ohlcv(symbol: str, interval: str, limit: int = 100):
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

def calc_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def analyze_multi_tf(symbol):
    df_30m = fetch_ohlcv(symbol, interval='30m', limit=100)
    df_15m = fetch_ohlcv(symbol, interval='15m', limit=100)
    df_5m = fetch_ohlcv(symbol, interval='5m', limit=100)
    if df_30m is None or df_15m is None or df_5m is None:
        return None

    direction, entry_type = multi_frame_signal(df_30m, df_15m, df_5m)
    if direction is None:
        return None

    price = df_5m['close'].iloc[-1]
    atr = calc_atr(df_5m)
    # TP/SL 레버리지 반영값으로 안내
    lev = 20
    if direction == 'LONG':
        stop_loss = price - atr * 1.2
        take_profit = price + atr * 2.5
    else:
        stop_loss = price + atr * 1.2
        take_profit = price - atr * 2.5

    msg = f"""📈 [{symbol}]
진입 방향: {direction} (레버리지 {lev}배)
신호 근거: {entry_type}
진입가: ${format_price(price)}
손절가(SL): ${format_price(stop_loss)}
익절가(TP): ${format_price(take_profit)}
(ATR: {format_price(atr)}, {df_5m.index[-1]})
"""
    send_telegram(msg)
    return msg
