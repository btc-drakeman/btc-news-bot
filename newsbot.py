import requests
import pandas as pd
import time
from datetime import datetime
from flask import Flask
from threading import Thread
import html
import os

# 텔레그램 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_ID = '7505401062'

# 분석 대상 심볼
SYMBOLS = ['BTCUSDT', 'SEIUSDT', 'VIRTUALUSDT', 'ETHUSDT', 'ETHFIUSDT', 'XRPUSDT']

# 텔레그램 메시지 전송
def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': USER_ID, 'text': html.escape(text), 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, data=data)
        print(f"✅ 텔레그램 응답 코드: {response.status_code}")
        return response
    except Exception as e:
        print(f"❌ 텔레그램 전송 오류: {e}")
        return None

# RSI + MACD 기술 분석
def analyze_symbol(symbol):
    try:
        print(f"📥 {symbol} 데이터 요청 중...")
        url = "https://api.mexc.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": "1m",
            "limit": 100
        }
        res = requests.get(url, params=params)
        res.raise_for_status()
        data = res.json()
        if len(data) < 50:
            raise ValueError("시세 데이터 부족")

        closes = [float(candle[4]) for candle in data]
        df = pd.DataFrame(closes, columns=['close'])

        # RSI 계산
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_now = rsi.iloc[-1]
        rsi_status = "과매도" if rsi_now < 30 else ("과매수" if rsi_now > 70 else "중립")

        # MACD 계산
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        macd_now = df['macd'].iloc[-1]
        signal_now = df['signal'].iloc[-1]
        macd_status = "골든크로스" if macd_now > signal_now else "데드크로스"

        # 종합 판단
        if rsi_now < 30 and macd_now > signal_now:
            advice = "🟢 매수 타이밍으로 판단됩니다"
        elif rsi_now > 70 and macd_now < signal_now:
            advice = "🔴 매도 주의 타이밍입니다"
        else:
            advice = "⚖️ 중립 구간입니다"

        price_now = df['close'].iloc[-1]
        print(f"📊 {symbol} 분석 완료")

        return (
            f"📊 <b>{symbol} 기술 분석 (MEXC)</b>\n"
            f"💰 현재가: ${price_now:,.4f}\n"
            f"📈 RSI: {rsi_now:.1f} ({rsi_status})\n"
            f"📉 MACD: {macd_status}\n\n"
            f"{advice}"
        )

    except Exception as e:
        print(f"❌ {symbol} 분석 오류: {e}")
        return None

# 루프 실행: 모든 코인 분석
def check_tech_loop():
    print("📉 멀티코인 기술 분석 루프 시작")
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"⏰ 분석 시작: {now}")
            for symbol in SYMBOLS:
                msg = analyze_symbol(symbol)
                if msg:
                    print(f"📨 {symbol} 메시지 전송 중...")
                    response = send_telegram(msg)
                    print(f"✅ {symbol} 전송 응답: {response.status_code if response else '실패'}")
                else:
                    print(f"⚠️ {symbol} 메시지 없음")
        except Exception as e:
            print(f"❌ 기술 분석 루프 오류: {e}")
        time.sleep(900)  # 15분

# Flask 서버 설정
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 멀티코인 RSI+MACD 봇 작동 중!"

@app.route('/test')
def test():
    print("🧪 /test 요청 수신")
    send_telegram("✅ [테스트] 멀티코인 기술 분석 봇 정상 작동 중입니다.")
    return "✅ 테스트 메시지 전송됨"

# 실행 시작
if __name__ == '__main__':
    print("🟢 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)).start()
    Thread(target=check_tech_loop).start()
