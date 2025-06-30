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

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']

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

def analyze_symbol(symbol):
    try:
        print(f"📥 {symbol} 데이터 요청 중...")
        url = "https://api.mexc.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 100}
        res = requests.get(url, params=params)
        res.raise_for_status()
        data = res.json()

        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]

        df = pd.DataFrame({
            'close': closes,
            'high': highs,
            'low': lows,
            'volume': volumes
        })

        score = 0
        reasons = []

        price_now = df['close'].iloc[-1]

        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_now = rsi.iloc[-1]
        if 35 <= rsi_now <= 45:
            score += 1
            reasons.append(f"✅ RSI: {rsi_now:.1f} (과매도 회복)")
        else:
            reasons.append(f"❌ RSI: {rsi_now:.1f} (비추세 구간)")

        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['signal'] = df['macd'].ewm(span=9).mean()
        macd_now = df['macd'].iloc[-1]
        signal_now = df['signal'].iloc[-1]
        if macd_now > signal_now:
            score += 1
            reasons.append("✅ MACD: 골든크로스")
        else:
            reasons.append("❌ MACD: 데드크로스")

        # 볼린저밴드
        ma20 = df['close'].rolling(window=20).mean()
        std = df['close'].rolling(window=20).std()
        upper = ma20 + (2 * std)
        lower = ma20 - (2 * std)
        if price_now > ma20.iloc[-1] and price_now < upper.iloc[-1]:
            score += 1
            reasons.append("✅ 볼린저: 중심선 이상 & 상단 여유")
        else:
            reasons.append("❌ 볼린저: 중심선 미만 or 상단 돌파")

        # EMA
        ema20 = df['close'].ewm(span=20).mean()
        ema50 = df['close'].ewm(span=50).mean()
        if price_now > ema20.iloc[-1] and price_now > ema50.iloc[-1]:
            score += 1
            reasons.append("✅ EMA: 20/50 상단에 위치")
        else:
            reasons.append("❌ EMA: 추세선 하단에 위치")

        # 거래량
        vol_now = df['volume'].iloc[-1]
        vol_avg = df['volume'].rolling(window=10).mean().iloc[-1]
        if vol_now > vol_avg * 1.2:
            score += 1
            reasons.append(f"✅ 거래량: 평균 대비 +{(vol_now/vol_avg - 1)*100:.1f}% 증가")
        else:
            reasons.append("❌ 거래량: 뚜렷한 증가 없음")

        # 종합 판단
        if score >= 4:
            final_msg = "🟢 ▶️ 종합 분석: 강한 매수 신호 감지"
        elif score >= 2:
            final_msg = "⚖️ ▶️ 종합 분석: 관망 구간"
        else:
            final_msg = "🔴 ▶️ 종합 분석: 매도 주의 신호"

        msg = (
            f"📊 <b>{symbol} 기술 분석 (MEXC)</b>\n"
            f"💰 현재가: ${price_now:,.4f}\n\n" +
            "\n".join(reasons) +
            f"\n\n{final_msg} (점수: {score}/5)"
        )

        return msg

    except Exception as e:
        print(f"❌ {symbol} 분석 오류: {e}")
        return None

def check_tech_loop():
    print("📉 기술 분석 루프 시작")
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"⏰ 분석 시작: {now}")
            for symbol in SYMBOLS:
                msg = analyze_symbol(symbol)
                if msg:
                    send_telegram(msg)
                else:
                    print(f"⚠️ {symbol} 메시지 없음")
        except Exception as e:
            print(f"❌ 루프 오류: {e}")
        time.sleep(900)

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 종합 기술 분석 봇 작동 중!"

@app.route('/test')
def test():
    send_telegram("✅ [테스트] 종합 분석 봇 작동 확인!")
    return "✅ 테스트 메시지 전송됨"

if __name__ == '__main__':
    print("🟢 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)).start()
    Thread(target=check_tech_loop).start()
