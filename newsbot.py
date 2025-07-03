import requests
import pandas as pd
import time
from flask import Flask, request
from threading import Thread
from datetime import datetime, timedelta
import re

# === 텔레그램 설정 ===
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# === Binance 선물 심볼 설정 ===
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']

# === Flask 앱 생성 ===
app = Flask(__name__)

# === 1. 코인별 최대 보유시간 (분 단위)
symbol_max_hold_time = {
    "BTCUSDT": 30,
    "ETHUSDT": 75,
    "XRPUSDT": 120,
    "ETHFIUSDT": 60,
}

# === 2. 진입 포지션 추적용 메모리 ===
active_positions = {}

# === 3. 진입 후 저장 함수 (명령어 /buy 입력 시 호출) ===
def store_position(symbol, direction, entry_price):
    active_positions[symbol.upper()] = {
        "entry_time": datetime.utcnow(),
        "direction": direction,
        "entry_price": entry_price
    }
    print(f"✅ 포지션 기록됨: {symbol} / {direction} / {entry_price}")

# === 4. 보유시간 초과 감시 루프 ===
def position_monitor_loop():
    while True:
        now = datetime.utcnow()
        for symbol, info in list(active_positions.items()):
            max_hold = timedelta(minutes=symbol_max_hold_time.get(symbol, 60))
            if now - info["entry_time"] >= max_hold:
                kst_now = now + timedelta(hours=9)
                entry_kst = info["entry_time"] + timedelta(hours=9)
                message = f"""
⏰ <b>{symbol} 포지션 보유시간 초과</b>
📅 진입 시각 (KST): {entry_kst:%Y-%m-%d %H:%M}
🕒 현재 시각 (KST): {kst_now:%Y-%m-%d %H:%M}
📈 진입 방향: {info['direction']}
💰 진입가: ${info['entry_price']:.2f}

🚪 <b>최대 보유시간 도달 → 수동 청산 고려</b>
                """
                send_telegram(message)
                del active_positions[symbol]
        time.sleep(60)

# === 텔레그램 전송 ===
def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"메시지 전송됨 → {uid}")
        except Exception as e:
            print(f"텔레그램 전송 오류 (chat_id={uid}): {e}")

# === Binance 선물 데이터 가져오기 ===
def fetch_ohlcv(symbol, interval='1m'):
    url = f"https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": 300}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        closes = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        df = pd.DataFrame({"close": closes, "volume": volumes})
        return df
    except Exception as e:
        print(f"{symbol} ({interval}) 데이터 요청 실패: {e}")
        return None

# === 기술지표 계산 ===
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_indicators(df):
    df['rsi'] = calculate_rsi(df)
    ema_12 = df['close'].ewm(span=12).mean()
    ema_26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema_12 - ema_26
    df['signal'] = df['macd'].ewm(span=9).mean()
    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()
    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']
    return df

# === 점수 계산 ===
def calculate_weighted_score(last, prev, df, explain):
    score = 0
    total_weight = 0
    ...
    # 생략된 나머지 분석/포맷 함수들은 동일하게 유지

# === Flask webhook ===
@app.route('/')
def home():
    return "✅ Binance Futures 기반 기술분석 봇 작동 중!"

@app.route(f"/bot{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'message' in data:
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '').strip().lower()
        if text == "/event":
            from event_risk import handle_event_command
            send_telegram(handle_event_command(), chat_id=chat_id)
        elif text.startswith("/buy"):
            match = re.match(r"/buy (\w+)", text)
            if match:
                symbol = match.group(1).upper()
                df = fetch_ohlcv(symbol)
                if df is not None and not df.empty:
                    price = df['close'].iloc[-1]
                    store_position(symbol, "롱 (Long)", price)
                    send_telegram(f"✅ <b>{symbol}</b> 포지션 기록됨\n📈 진입가: ${price:.2f}", chat_id=chat_id)
                else:
                    send_telegram(f"⚠️ {symbol} 데이터 조회 실패", chat_id=chat_id)
        else:
            match = re.match(r"/go (\w+)(?:\s+(\d+)x)?", text)
            if match:
                symbol = match.group(1).upper()
                leverage = int(match.group(2)) if match.group(2) else None
                from event_risk import adjust_direction_based_on_event
                msg = analyze_symbol(symbol, leverage)
                send_telegram(msg or f"⚠️ 분석 실패: {symbol} 데이터를 불러올 수 없습니다.", chat_id=chat_id)
    return '', 200

# === 백그라운드 루프 실행 ===
if __name__ == '__main__':
    from economic_alert import start_economic_schedule
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop, daemon=True).start()
    Thread(target=start_economic_schedule, daemon=True).start()
    Thread(target=position_monitor_loop, daemon=True).start()
    while True:
        time.sleep(60)
