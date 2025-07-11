import requests
import pandas as pd
from strategy import (
    analyze_indicators,
    generate_trade_plan,
    compute_rsi,
    calculate_atr,
    is_pre_entry_signal
)
from config import SYMBOLS
from notifier import send_telegram
from spike_detector import detect_spike, detect_crash

BASE_URL = 'https://api.bybit.com'

def fetch_ohlcv(symbol: str, interval: str = '15', limit: int = 100):
    endpoint = '/v5/market/kline'
    params = {
        'category': 'linear',
        'symbol': symbol,
        'interval': interval,
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

    messages = []

    # ✅ 전략 기반 진입 판단 (20x 기반 TP/SL 자동 적용)
    direction, score = analyze_indicators(df)
    if direction != 'NONE':
        plan = generate_trade_plan(current_price, leverage=20)

        msg = f"""
📊 {symbol.upper()} 기술 분석 (Bybit 선물)
🕒 최근 시세 기준
💰 현재가: ${current_price:,.4f}

▶️ 추천 방향: {direction}
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}
        """
        messages.append(msg.strip())

    # ⚠️ 예비 시그널
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

    # 🚨 급등 전조 경고
    spike_msg = detect_spike(symbol, df)
    if spike_msg:
        messages.append(spike_msg)

    # ⚠️ 급락 전조 경고
    crash_msg = detect_crash(symbol, df)
    if crash_msg:
        messages.append(crash_msg)

    return messages if messages else None
