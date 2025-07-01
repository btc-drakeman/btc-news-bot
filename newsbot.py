import requests
import pandas as pd
import time
from datetime import datetime
from flask import Flask
from threading import Thread

# ✅ 기본 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT', 'SEIUSDT']
TIMEFRAMES = {"1분": "1m", "5분": "5m", "1시간": "1h"}  # 안정성 고려

# ✅ 텔레그램 메시지 전송
def send_telegram(text):
    for user_id in USER_IDS:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            requests.post(url, data=data)
            print(f"[텔레그램] 메시지 전송 완료 → {user_id}")
        except Exception as e:
            print(f"[텔레그램 오류] {e}")

# ✅ OHLCV 안전 요청
def fetch_ohlcv_safe(symbol, interval, limit=150, retries=3):
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for _ in range(retries):
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
            time.sleep(1)
    return None, None

# ✅ RSI 계산
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ✅ 기술 지표 계산
def calculate_indicators(df):
    df['rsi'] = calculate_rsi(df)
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['boll_mid'] = df['close'].rolling(window=20).mean()
    df['boll_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['boll_mid'] + 2 * df['boll_std']
    df['lower_band'] = df['boll_mid'] - 2 * df['boll_std']
    df['vol_avg'] = df['volume'].rolling(window=20).mean()
    return df

# ✅ MACD 해석
def get_macd_signal(df):
    if len(df) < 2:
        return "중립"
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        return "상승"
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        return "하락"
    elif last['hist'] > prev['hist'] and last['hist'] > 0:
        return "상승"
    elif last['hist'] < prev['hist'] and last['hist'] < 0:
        return "하락"
    else:
        return "중립"

# ✅ 종합 분석
def analyze_all_timeframes(symbol):
    indicators = {"rsi": [], "macd": [], "ema": [], "boll": [], "vol": []}
    direction_votes = {"로우": 0, "슈스": 0}
    price_now = None

    for label, interval in TIMEFRAMES.items():
        df, last_price = fetch_ohlcv_safe(symbol, interval)
        if df is None or last_price is None:
            continue
        price_now = last_price
        df = calculate_indicators(df)
        last = df.iloc[-1]

        # RSI
        rsi = last['rsi']
        indicators["rsi"].append(rsi)
        if rsi < 30:
            direction_votes["로우"] += 1
        elif rsi > 70:
            direction_votes["슈스"] += 1

        # MACD
        macd_signal = get_macd_signal(df)
        indicators["macd"].append(macd_signal)
        if macd_signal == "상승":
            direction_votes["로우"] += 1
        elif macd_signal == "하락":
            direction_votes["슈스"] += 1

        # EMA
        ema_cross = "상향" if last['ema20'] > last['ema50'] else "하향"
        indicators["ema"].append(ema_cross)
        direction_votes["로우"] += ema_cross == "상향"
        direction_votes["슈스"] += ema_cross == "하향"

        # Bollinger
        boll_pos = "상단" if price_now > last['boll_mid'] else "하단"
        indicators["boll"].append(boll_pos)
        direction_votes["로우"] += boll_pos == "상단"
        direction_votes["슈스"] += boll_pos == "하단"

        # Volume
        volume_trend = "증가" if last['volume'] > last['vol_avg'] else "감소"
        indicators["vol"].append(volume_trend)

    if not indicators["rsi"] or price_now is None:
        return f"❌ {symbol} 데이터 부족으로 분석 실패"

    # 종합 판단
    if direction_votes["로우"] > direction_votes["슈스"]:
        signal = "🟢 매수 (Long)"
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04
    elif direction_votes["슈스"] > direction_votes["로우"]:
        signal = "🔴 매도 (Short)"
        stop_loss = price_now * 1.02
        take_profit = price_now * 0.96
    else:
        signal = "⚖️ 관망"
        stop_loss = take_profit = None

    entry_low = price_now * 0.995
    entry_high = price_now * 1.005
    avg_rsi = sum(indicators["rsi"]) / len(indicators["rsi"])

    # 메시지 생성
    msg = f"""\
📊 <b>{symbol} 기술 분석 (MEXC)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.2f}

📌 <b>다중프레임 분석 결과</b>
- RSI 평균: {avg_rsi:.2f}
- MACD: {', '.join(indicators['macd'])}
- EMA 방향: {', '.join(indicators['ema'])}
- 볼린저 위치: {', '.join(indicators['boll'])}
- 거래량: {', '.join(indicators['vol'])}

📌 <b>종합 판단</b>
{signal}
"""

    if signal != "⚖️ 관망":
        msg += f"""
📌 <b>진입 전략 제안</b>
- 진입 범위: ${entry_low:,.2f} ~ ${entry_high:,.2f}
- 손절가: ${stop_loss:,.2f}
- 익절가: ${take_profit:,.2f}
"""

    return msg

# ✅ 분석 루프
def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"[분석 중] {symbol} - {datetime.now().strftime('%H:%M:%S')}")
            try:
                msg = analyze_all_timeframes(symbol)
                send_telegram(msg)
            except Exception as e:
                print(f"[오류] {symbol} 분석 실패: {e}")
            time.sleep(3)
        time.sleep(600)

# ✅ Flask 서버
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 다중 타임프레임 분석 보스 작동 중입니다!"

if __name__ == '__main__':
    print("🟢 보스 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
