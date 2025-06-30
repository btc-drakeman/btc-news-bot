import requests
import pandas as pd
import time
from flask import Flask, request
from threading import Thread
from datetime import datetime
import os

# 텔레그램 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
ADMIN_ID = '7505401062'  # 최초 관리자
USER_ID_FILE = 'user_ids.txt'

# 분석할 코인 리스트
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']

app = Flask(__name__)

# 사용자 목록 불러오기
def load_user_ids():
    if not os.path.exists(USER_ID_FILE):
        return set([ADMIN_ID])
    with open(USER_ID_FILE, 'r') as f:
        return set(line.strip() for line in f if line.strip())

# 사용자 목록 저장
def save_user_id(chat_id):
    user_ids = load_user_ids()
    if chat_id not in user_ids:
        with open(USER_ID_FILE, 'a') as f:
            f.write(str(chat_id) + '\n')
        print(f"✅ 새로운 사용자 등록됨: {chat_id}")

# 텔레그램 메시지 전송
def send_telegram(text):
    for uid in load_user_ids():
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': uid, 'text': text, 'parse_mode': 'HTML'}
        try:
            response = requests.post(url, data=data)
            print(f"📨 전송 대상 {uid} 응답 코드: {response.status_code}")
        except Exception as e:
            print(f"❌ 텔레그램 전송 오류 ({uid}): {e}")

# OHLCV 가져오기 (MEXC)
def fetch_ohlcv(symbol):
    url = f"https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1m", "limit": 100}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        closes = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        df = pd.DataFrame({"close": closes, "volume": volumes})
        return df, closes[-1]
    except Exception as e:
        print(f"{symbol} 데이터 요청 실패: {e}")
        return None, None

# 분석 함수
def analyze_symbol(symbol):
    df, price_now = fetch_ohlcv(symbol)
    if df is None:
        return None

    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()
    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']

    last = df.iloc[-1]
    score = 0
    explain = []

    if last['rsi'] < 30:
        score += 1
        explain.append("✅ RSI: {:.1f} (과매도)".format(last['rsi']))
    elif last['rsi'] > 70:
        explain.append("❌ RSI: {:.1f}".format(last['rsi']))
    else:
        explain.append("⚖️ RSI: {:.1f}".format(last['rsi']))

    if last['macd'] > last['signal']:
        score += 1
        explain.append("✅ MACD: 골든크로스")
    else:
        explain.append("❌ MACD: 데드크로스")

    if price_now > last['bollinger_mid']:
        score += 1
        explain.append("✅ 볼린저: 중심선 이상")
    else:
        explain.append("❌ 볼린저: 중심선 이하")

    if last['ema_20'] > last['ema_50']:
        score += 1
        explain.append("✅ EMA: 20/50 상단")
    else:
        explain.append("❌ EMA: 20/50 하단")

    if df['volume'].iloc[-1] > df['volume'].rolling(window=20).mean().iloc[-1]:
        score += 1
        explain.append("✅ 거래량: 증가")
    else:
        explain.append("❌ 거래량: 증가 없음")

    if score >= 4:
        decision = f"🟢 ▶️ 종합 분석: 강한 매수 신호 (점수: {score}/5)"
        direction = "롱 (Long)"
    elif score <= 2:
        decision = f"🔴 ▶️ 종합 분석: 매도 주의 신호 (점수: {score}/5)"
        direction = "숏 (Short)"
    else:
        decision = f"⚖️ ▶️ 종합 분석: 관망 구간 (점수: {score}/5)"
        direction = "관망"

    if direction == "롱 (Long)":
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04
    elif direction == "숏 (Short)":
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 1.02
        take_profit = price_now * 0.96
    else:
        entry_low = entry_high = stop_loss = take_profit = None

    msg = f"""
📊 <b>{symbol} 기술 분석 (MEXC)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.4f}

"""
    msg += '\n'.join(explain)
    msg += f"\n\n{decision}"

    if direction != "관망":
        msg += f"\n\n📌 <b>전략 제안</b>"
        msg += f"\n- 🔁 <b>유리한 포지션</b>: {direction}"
        msg += f"\n- 🎯 <b>진입 권장가</b>: ${entry_low:,.2f} ~ ${entry_high:,.2f}"
        msg += f"\n- 🛑 <b>손절 제안</b>: ${stop_loss:,.2f}"
        msg += f"\n- 🟢 <b>익절 목표</b>: ${take_profit:,.2f}"

    return msg

# 분석 루프
def analysis_loop():
    while True:
        try:
            for symbol in SYMBOLS:
                print(f"분석 중: {symbol} ({datetime.now().strftime('%H:%M:%S')})")
                result = analyze_symbol(symbol)
                if result:
                    send_telegram(result)
                time.sleep(3)
            time.sleep(600)
        except Exception as e:
            print(f"❌ 루프 오류: {e}")

# 텔레그램 웹훅
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'message' in data:
        chat_id = str(data['message']['chat']['id'])
        text = data['message'].get('text', '')
        if text.strip() == "/start":
            save_user_id(chat_id)
            send_telegram("✅ 알림이 등록되었습니다!")
    return '', 200

# 상태 확인용
@app.route('/')
def home():
    return "✅ MEXC 기술분석 통합 봇 작동 중!"

# 실행
if __name__ == '__main__':
    print("🟢 전체 통합 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
