# ✅ analyzer.py
import requests
import pandas as pd
from strategy import is_strong_entry_signal, generate_trade_plan
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

    messages = []

    if is_strong_entry_signal(df):
        plan = generate_trade_plan(df, direction='LONG', leverage=10)
        msg = f"""
🧠 강력 진입 조건 포착: {symbol.upper()}
📉 RSI < 35, MACD 반전, ADX > 20 충족

💰 현재가: ${plan['price']:,.2f}
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}
        """
        messages.append(msg.strip())

    return messages if messages else None
