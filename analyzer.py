import requests
import pandas as pd
from strategy import get_trend, entry_signal
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

def analyze_multi_tf(symbol: str):
    """
    30분 상위 프레임 방향 필터 + 15분, 5분 하위프레임 진입 신호
    ATR 기반 TP/SL 자동 산정, 진입방향/ATR 명확히 표기
    """
    df_30m = fetch_ohlcv(symbol, interval='30m', limit=50)
    df_15m = fetch_ohlcv(symbol, interval='15m', limit=50)
    df_5m = fetch_ohlcv(symbol, interval='5m', limit=50)

    if None in (df_30m, df_15m, df_5m):
        return None

    trend_30m = get_trend(df_30m)
    direction = 'LONG' if trend_30m == 'UP' else 'SHORT'
    if entry_signal(df_15m, direction) and entry_signal(df_5m, direction):
        price = df_5m["close"].iloc[-1]
        atr = calc_atr(df_5m)  # 5분봉 ATR 기준
        if direction == 'LONG':
            entry_low = price * 0.998
            entry_high = price * 1.002
            stop_loss = price - atr * 1.2
            take_profit = price + atr * 2.5
        else:
            entry_low = price * 1.002
            entry_high = price * 0.998
            stop_loss = price + atr * 1.2
            take_profit = price - atr * 2.5

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = (
            f"📈 [{now}] {symbol}\n\n"
            f"진입 방향: {direction}  (상위프레임 {trend_30m}, 중하위프레임 {direction} 신호)\n\n"
            f"[진입 제안]\n"
            f"- 진입가: ${format_price(entry_low)} ~ ${format_price(entry_high)}\n"
            f"- 손절가(SL, ATR기반): ${format_price(stop_loss)}\n"
            f"- 익절가(TP, ATR기반): ${format_price(take_profit)}\n\n"
            f"(ATR: ${format_price(atr)})"
        )
        send_telegram(msg)
        return msg
    return None
