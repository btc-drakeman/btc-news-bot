import requests
import pandas as pd
from strategy import get_trend, entry_signal_ema_only, multi_frame_signal
from config import SYMBOLS
from notifier import send_telegram
from simulator import add_virtual_trade
from sl_hunt_monitor import check_sl_hunt_alert  # ✅ SL 헌팅 통합
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
    elif price >= 0.001:
        return f"{price:.6f}"
    elif price >= 0.0001:
        return f"{price:.7f}"
    elif price >= 0.00001:
        return f"{price:.8f}"
    else:
        return f"{price:.9f}"

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

def extract_score(entry_type: str) -> int:
    try:
        return int(entry_type.split('score=')[1].split('/')[0])
    except:
        return 0

def map_score_to_stars(score: int) -> str:
    if score == 5:
        return "★★★★★ (5점 - 강력 추천)"
    elif score == 4:
        return "★★★★☆ (4점 - 전략 조건 우수)"
    elif score == 3:
        return "★★★☆☆ (3점 - 전략 기준 충족)"
    elif score == 2:
        return "★★☆☆☆ (2점 - 약한 진입 신호)"
    else:
        return "(조건 미달)"

def get_sl_tp_multipliers(score: int):
    if score >= 5:
        return 1.0, 3.0
    elif score == 4:
        return 1.1, 2.8
    elif score == 3:
        return 1.2, 2.5
    elif score == 2:
        return 1.3, 2.0
    else:
        return 1.5, 1.2

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
    lev = 20

    score = extract_score(entry_type)
    stars = map_score_to_stars(score)
    sl_mult, tp_mult = get_sl_tp_multipliers(score)

    if direction == 'LONG':
        stop_loss = price - atr * sl_mult
        take_profit = price + atr * tp_mult
        symbol_prefix = "📈"
    else:
        stop_loss = price + atr * sl_mult
        take_profit = price - atr * tp_mult
        symbol_prefix = "📉"

    reward = abs(take_profit - price)
    risk = abs(price - stop_loss)
    rr_ratio = reward / risk if risk != 0 else 0
    rr_label = f"⚠ 수익/손실 비율: {rr_ratio:.2f}" if rr_ratio < 1.2 else f"📐 수익/손실 비율: {rr_ratio:.2f}"

    entry = {
        "symbol": symbol,
        "direction": direction,
        "entry": price,
        "tp": take_profit,
        "sl": stop_loss,
        "score": score
    }
    add_virtual_trade(entry)

    msg = f"""{symbol_prefix} [{symbol}]
🎯 진입 방향: {direction} (레버리지 {lev}배)
💡 추천 진입 강도: {stars}

📊 신호 근거: {entry_type}
💵 진입가: ${format_price(price)}
🛑 손절가(SL): ${format_price(stop_loss)}
🎯 익절가(TP): ${format_price(take_profit)}
{rr_label}
⏱️ (ATR: {format_price(atr)}, {df_5m.index[-1]})"""

    sl_alert_msg = check_sl_hunt_alert(symbol)
    if sl_alert_msg:
        msg += f"\n\n{sl_alert_msg}"

    send_telegram(msg)
    return msg
