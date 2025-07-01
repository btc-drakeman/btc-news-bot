import requests
import pandas as pd
import time
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT', 'SEIUSDT']
TIMEFRAMES = {"1m": 1, "5m": 2, "15m": 3}

app = Flask(__name__)

def send_telegram(text):
    for user_id in USER_IDS:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            requests.post(url, data=data)
            print(f"[텔레그램] 메시지 전송 완료 → {user_id}")
        except Exception as e:
            print(f"[텔레그램 오류] {e}")

def fetch_ohlcv_safe(symbol, interval, limit=150):
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        closes = [float(x[4]) for x in data]
        highs = [float(x[2]) for x in data]
        lows = [float(x[3]) for x in data]
        volumes = [float(x[5]) for x in data]
        df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": volumes})
        return df, closes[-1]
    except Exception as e:
        print(f"[{symbol}-{interval}] 요청 실패: {e}")
        return None, None

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def weighted_average(values, weights):
    total_weight = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / total_weight

def summarize_direction(signals):
    score = sum(signals)
    if score >= 2:
        return "상승 우세"
    elif score <= -2:
        return "하락 우세"
    else:
        return "중립"

def analyze_symbol(symbol):
    rsi_values = []
    macd_signals, ema_signals, boll_signals, vol_signals = [], [], [], []
    weights = []
    price_now = None

    for tf, weight in TIMEFRAMES.items():
        df, price = fetch_ohlcv_safe(symbol, tf)
        if df is None or len(df) < 30:
            continue
        if price_now is None:
            price_now = price

        df['rsi'] = calculate_rsi(df)

        try:
            ema_12 = df['close'].ewm(span=12, adjust=False).mean()
            ema_26 = df['close'].ewm(span=26, adjust=False).mean()
            macd_line = ema_12 - ema_26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            hist = macd_line - signal_line

            df['macd'] = macd_line
            df['signal'] = signal_line
            df['hist'] = hist
        except:
            continue

        ema_20 = df['close'].ewm(span=20).mean()
        ema_50 = df['close'].ewm(span=50).mean()

        boll_mid = df['close'].rolling(window=20).mean()
        boll_std = df['close'].rolling(window=20).std()
        upper = boll_mid + 2 * boll_std
        lower = boll_mid - 2 * boll_std

        vol_now = df['volume'].iloc[-1]
        vol_avg = df['volume'].rolling(window=20).mean().iloc[-1]

        last = df.iloc[-1]
        prev = df.iloc[-2]

        if not pd.isna(last['rsi']):
            rsi_values.append(last['rsi'])
            weights.append(weight)

        # MACD 신호 판단
        if 'hist' in df.columns and 'macd' in df.columns:
            if df['hist'].iloc[-1] > df['hist'].iloc[-2]:
                if df['macd'].iloc[-1] > 0:
                    macd_signals.append(1)
                else:
                    macd_signals.append(0)
            else:
                if df['macd'].iloc[-1] < 0:
                    macd_signals.append(-1)
                else:
                    macd_signals.append(0)

        # EMA
        ema_cross = 1 if ema_20.iloc[-1] > ema_50.iloc[-1] else -1
        price_pos = 1 if price > ema_20.iloc[-1] else -1
        ema_signals.append(1 if ema_cross + price_pos >= 1 else -1)

        # Bollinger Band
        band_width = upper.iloc[-1] - lower.iloc[-1]
        prev_band_width = upper.iloc[-2] - lower.iloc[-2]
        band_change = band_width - prev_band_width
        if band_change < -0.05 * prev_band_width:
            boll_signals.append(0)
        elif price < lower.iloc[-1]:
            boll_signals.append(-1)
        elif price > upper.iloc[-1]:
            boll_signals.append(1)
        else:
            boll_signals.append(0)

        if vol_now > vol_avg * 1.2:
            vol_signals.append(1)
        elif vol_now < vol_avg * 0.8:
            vol_signals.append(-1)
        else:
            vol_signals.append(0)

    if price_now is None or not rsi_values:
        return None

    rsi_avg = weighted_average(rsi_values, weights)
    now_kst = datetime.utcnow() + timedelta(hours=9)
    now_str = now_kst.strftime('%Y-%m-%d %H:%M (KST)')

    msg = f"""
📊 <b>{symbol} 기술 분석 (MEXC)</b>
🕒 {now_str}
💰 현재가: ${price_now:,.2f}

📌 <b>다중프레임 요약 (1분·5분·15분)</b>
RSI 평균: {rsi_avg:.1f}
MACD: {summarize_direction(macd_signals)}
EMA: {summarize_direction(ema_signals)}
Bollinger: {summarize_direction(boll_signals)}
Volume: {summarize_direction(vol_signals)}
"""

    score = macd_signals.count(1) + ema_signals.count(1) + boll_signals.count(-1)
    if score >= 4:
        decision = "🟢 매수 (Long)"
        direction = "롱"
    elif score <= 1:
        decision = "🔴 매도 (Short)"
        direction = "숏"
    else:
        decision = "⚖️ 관망"
        direction = "관망"

    msg += f"\n\n📌 <b>종합 판단</b>\n{decision}"

    entry_low = price_now * 0.995
    entry_high = price_now * 1.005

    if direction == "롱":
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04
    elif direction == "숏":
        stop_loss = price_now * 1.02
        take_profit = price_now * 0.96
    else:
        stop_loss = take_profit = None

    msg += f"\n\n📌 <b>진입 전략 제안</b>"
    msg += f"\n🎯 진입 범위: ${entry_low:,.2f} ~ ${entry_high:,.2f}"
    if stop_loss and take_profit:
        msg += f"\n🛑 손절가: ${stop_loss:,.2f}"
        msg += f"\n💰 익절가: ${take_profit:,.2f}"

    return msg

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"분석 중: {symbol} ({datetime.now().strftime('%H:%M:%S')})")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            time.sleep(3)
        time.sleep(600)

@app.route('/')
def home():
    return "✅ MEXC 기술분석 봇 작동 중!"

if __name__ == '__main__':
    print("🟢 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
