# ✅ analyzer.py
import requests
import pandas as pd
from strategy import should_enter_position, is_pre_entry_signal, calculate_tp_sl, compute_rsi, calculate_atr
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
    messages = []

    if direction:
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
        messages.append(msg.strip())
    else:
        pre_signal = is_pre_entry_signal(df)
        if pre_signal:
            rsi_now = df['rsi'].iloc[-1]
            rsi_prev = df['rsi'].iloc[-2]
            volume_now = df['volume'].iloc[-1]
            volume_ma = df['volume'].rolling(21).mean().iloc[-1]

            msg = f"""
⚠️ 예비 진입 시그널 감지: {symbol.upper()} ({pre_signal} 유력)
🔍 RSI: {rsi_now:.2f} (이전봉: {rsi_prev:.2f})
📊 거래량: {volume_now:,.0f} (평균: {volume_ma:,.0f})
📌 다음 캔들에서 진입 조건 충족 가능성 있음
            """
            messages.append(msg.strip())

    return messages if messages else None
