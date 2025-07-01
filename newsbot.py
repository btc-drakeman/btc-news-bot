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
TIMEFRAMES = {"1분": "1m", "10분": "10m", "1시간": "1h"}

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

# ✅ 안전한 OHLCV 데이터 요청
def fetch_ohlcv_safe(symbol, interval, limit=150, retries=3):
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for _ in range(retries):
        try:
            res = requests.get(url, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
            closes = [float(x[4]) for x in data]
            volumes = [float(x[5]) for x in data]
            df = pd.DataFrame({"close": closes, "volume": volumes})
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
    return df

# ✅ MACD 상태 분석
def get_macd_signal(df):
    if len(df) < 2:
        return "불충분"
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        return "상승 전환"
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        return "하락 전환"
    elif last['hist'] > prev['hist'] and last['hist'] > 0:
        return "상승 지속"
    elif last['hist'] < prev['hist'] and last['hist'] < 0:
        return "하락 지속"
    else:
        return "중립"

# ✅ 타임프레임 분석 결과 생성
def analyze_all_timeframes(symbol):
    msg = f"<b>📊 {symbol} 다중 타임프레임 분석 (MEXC)</b>\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    for label, interval in TIMEFRAMES.items():
        df, price_now = fetch_ohlcv_safe(symbol, interval)
        if df is None or price_now is None:
            msg += f"\n❌ <b>{label}봉</b>: 데이터 수신 실패"
            continue
        df = calculate_indicators(df)
        last = df.iloc[-1]
        rsi = last['rsi']
        macd_status = get_macd_signal(df)
        msg += f"\n\n⏱ <b>{label}봉</b>"
        msg += f"\n- 💰 현재가: ${price_now:,.2f}"
        msg += f"\n- 📈 RSI: {rsi:.2f}"
        msg += f"\n- 📊 MACD: {macd_status}"
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
        time.sleep(600)  # 10분 간격 반복

# ✅ Flask 서버 및 봇 실행
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 다중 타임프레임 분석 봇 작동 중입니다!"

if __name__ == '__main__':
    print("🟢 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
