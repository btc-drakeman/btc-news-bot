# analyzer.py (Bybit 선물 기반)

import requests
import pandas as pd
from strategy import should_enter_position, is_pre_entry_signal, calculate_tp_sl, compute_rsi, calculate_atr
from config import SYMBOLS
from notifier import send_telegram

BASE_URL = 'https://api.bybit.com'

def fetch_ohlcv(symbol: str, interval: str = '15', limit: int = 100):
    endpoint = '/v5/market/kline'
    params = {
        'category': 'linear',     # 선물 마켓
        'symbol': symbol,
        'interval': interval,     # ex: '1', '3', '15', '60'
        'limit': limit
    }

    try:
        res = requests.get(BASE_URL + endpoint, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()

        if raw['retCode'] != 0:
            print(f"❌ {symbol} 캔들 요청 실패: {raw['retMsg']}")
            return None

        df = pd.DataFrame(raw['result']['list'], columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover', 'confirm'
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
    endpoint = '/v5/market/tickers'
    params = {
        'category': 'linear',
        'symbol': symbol
    }
    try:
        res = requests.get(BASE_URL + endpoint, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()

        if raw['retCode'] != 0:
            print(f"❌ {symbol} 현재가 요청 실패: {raw['retMsg']}")
            return None

        return float(raw['result']['list'][0]['lastPrice'])

    except Exception as e:
        print(f"❌ {symbol} 현재가 가져오기 실패: {e}")
        return None

def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol, interval='15', limit=100)
    if df is None or len(df) < 50:
        return None

    df['rsi'] = compute_rsi(df['close'])
    df['atr'] = calculate_atr(df)

    current_price = fetch_current_price(symbol)
    if current_price is None:
        return None

    direction = should_enter_position(df)
    messages = []

    if direction:
        entry_price = current_price
        tp, sl = calculate_tp_sl(entry_price, df['atr'].iloc[-1], direction)

        msg = f"""
📊 {symbol.upper()} 기술 분석 (Bybit 선물)
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
