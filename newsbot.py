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
            reasons.append(f"❌ RSI: {rsi_now:.1f}")

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
        upper = ma20 + 2 * std
        lower = ma20 - 2 * std
        if price_now > ma20.iloc[-1] and price_now < upper.iloc[-1]:
            score += 1
            reasons.append("✅ 볼린저: 중심선 이상")
        else:
            reasons.append("❌ 볼린저: 중심선 이하")

        # EMA
        ema20 = df['close'].ewm(span=20).mean()
        ema50 = df['close'].ewm(span=50).mean()
        if price_now > ema20.iloc[-1] and price_now > ema50.iloc[-1]:
            score += 1
            reasons.append("✅ EMA: 20/50 상단")
        else:
            reasons.append("❌ EMA: 하단 위치")

        # 거래량
        vol_now = df['volume'].iloc[-1]
        vol_avg = df['volume'].rolling(window=10).mean().iloc[-1]
        if vol_now > vol_avg * 1.2:
            score += 1
            reasons.append(f"✅ 거래량: 평균보다 ↑")
        else:
            reasons.append("❌ 거래량: 증가 없음")

        # 종합 판단
        if score >= 4:
            trend_msg = "🟢 ▶️ 종합 분석: 강한 매수 신호 감지"
        elif score >= 2:
            trend_msg = "⚖️ ▶️ 종합 분석: 관망 구간"
        else:
            trend_msg = "🔴 ▶️ 종합 분석: 매도 주의 신호"

        # 전략 제안
        position = "롱 (Long)" if rsi_now < 50 and macd_now > signal_now else "숏 (Short)"
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04

        strategy_msg = (
            f"\n📌 <b>전략 제안</b>\n"
            f"- 🔁 <b>유리한 포지션</b>: {position}\n"
            f"- 🎯 <b>진입 권장가</b>: ${entry_low:,.2f} ~ ${entry_high:,.2f}\n"
            f"- 🛑 <b>손절 제안</b>: ${stop_loss:,.2f}\n"
            f"- 🟢 <b>익절 목표</b>: ${take_profit:,.2f}"
        )

        msg = (
            f"📊 <b>{symbol} 기술 분석 (MEXC)</b>\n"
            f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"💰 현재가: ${price_now:,.4f}\n\n" +
            "\n".join(reasons) +
            f"\n\n{trend_msg} (점수: {score}/5)" +
            strategy_msg
        )
        return msg

    except Exception as e:
        print(f"❌ {symbol} 분석 오류: {e}")
        return None

def check_tech_loop():
    print("📉 기술 분석 루프 시작")
    while True:
        try:
            print(f"⏰ 분석 tick: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            for symbol in SYMBOLS:
                msg = analyze_symbol(symbol)
                if msg:
                    send_telegram(msg)
                time.sleep(2)  # 과도한 요청 방지
        except Exception as e:
            print(f"❌ 루프 오류: {e}")
        time.sleep(600)  # 10분마다

# Flask 서버
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ 전략 기반 종합 기술분석 봇 작동 중!"

@app.route('/test')
def test():
    send_telegram("✅ [테스트] 전략 분석 봇 정상 작동 중입니다.")
    return "✅ 테스트 메시지 전송됨"

if __name__ == '__main__':
    print("🟢 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)).start()
    Thread(target=check_tech_loop).start()
