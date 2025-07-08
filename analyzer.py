import requests
import pandas as pd
from strategy import analyze_indicators
from spike_detector import detect_spike, detect_crash  # 🔥 추가

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
        df['volume'] = df['volume'].astype(float)  # 🔥 볼륨 사용 위해 추가
        return df
    except Exception as e:
        print(f"❌ {symbol} 데이터 가져오기 실패: {e}")
        return None


def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol)
    if df is None or len(df) < 50:
        return None

    messages = []

    # 🔥 급등/급락 별도 감지
    spike_msg = detect_spike(symbol, df)
    if spike_msg:
        messages.append(spike_msg)

    crash_msg = detect_crash(symbol, df)
    if crash_msg:
        messages.append(crash_msg)

    # 📊 기술적 분석은 별도 수행
    direction, score = analyze_indicators(df)
    if direction != 'NONE':
        price = df['close'].iloc[-1]
        entry_low = round(price * 0.995, 2)
        entry_high = round(price * 1.005, 2)
        stop_loss = round(price * 0.985, 2)
        take_profit = round(price * 1.015, 2)

        strategy_msg = f"""
📊 {symbol} 기술 분석 결과
🕒 최근 가격: ${price:.2f}

🔵 추천 방향: {direction}
💰 진입 권장가: ${entry_low} ~ ${entry_high}
🛑 손절가: ${stop_loss}
🎯 익절가: ${take_profit}
        """
        messages.append(strategy_msg)

    return messages if messages else None

