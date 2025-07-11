# ✅ analyzer.py
import requests
import pandas as pd
from strategy import should_enter_position, calculate_tp_sl
from config import SYMBOLS
from notifier import send_telegram

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
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"❌ {symbol} 데이터 불러오기 실패: {e}")
        return None

def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol, interval='15m', limit=100)
    if df is None or len(df) < 50:
        return None

    df['rsi'] = compute_rsi(df['close'])
    df['atr'] = calculate_atr(df)

    direction = should_enter_position(df, symbol)
    if not direction:
        return None

    entry_price = df['close'].iloc[-1]
    tp, sl = calculate_tp_sl(entry_price, df['atr'].iloc[-1], direction)

    msg = f"""
📊 {symbol.upper()} 기술 분석 (MEXC)
🕒 최근 시세 기준
💰 현재가: ${entry_price:,.4f}

⚖️ RSI: {df['rsi'].iloc[-1]:.2f}
📐 ATR: {df['atr'].iloc[-1]:.4f}

▶️ 추천 방향: {direction}
🎯 진입가: ${entry_price:,.4f}
🛑 손절가: ${sl:,.4f}
🟢 익절가: ${tp:,.4f}
    """

    return [msg.strip()]

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()
