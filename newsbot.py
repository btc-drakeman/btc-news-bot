
import requests
import pandas as pd
import time
from flask import Flask, request
from threading import Thread
from datetime import datetime, timedelta
import re
from config import BOT_TOKEN, USER_IDS, API_URL
from economic_alert import start_economic_schedule
from event_risk import adjust_direction_based_on_event, handle_event_command

# 텔레그램 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']

app = Flask(__name__)

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

def fetch_ohlcv(symbol, interval='1m', limit=300):
    url = f"https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
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
    df['ema_200'] = df['close'].ewm(span=200).mean()
    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']

    # ✅ EMA 기울기 계산 추가 (최근 5분 변화량 기반)
    if len(df) >= 6:
        df['ema_slope'] = (df['ema_20'] - df['ema_20'].shift(5)) / 5
    else:
        df['ema_slope'] = 0

    return df

def calculate_weighted_score(last, prev, df, explain):
    score = 0
    total_weight = 0

    if last['rsi'] < 30:
        score += 1.0
        explain.append("⚖️ RSI: 과매도구간 ↗ 반등 가능성")
    elif last['rsi'] > 70:
        explain.append("⚖️ RSI: 과매수구간 ↘ 하락 경고")
    else:
        explain.append("⚖️ RSI: 중립")
    total_weight += 1.0

    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        score += 1.5
        explain.append("📊 MACD: 골든크로스 ↗ 상승 신호")
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        explain.append("📊 MACD: 데드크로스 ↘ 하락 신호")
    else:
        explain.append("📊 MACD: 특별한 신호 없음")
    total_weight += 1.5

    if last['ema_20'] > last['ema_50']:
        score += 1.2
        explain.append("📐 EMA: 단기 이평선이 장기 상단 ↗ 상승 흐름")
    else:
        explain.append("📐 EMA: 단기 이평선이 장기 하단 ↘ 하락 흐름")
    total_weight += 1.2

    # ✅ EMA 기울기 반영
    if 'ema_slope' in last and not pd.isna(last['ema_slope']):
        if last['ema_slope'] > 0:
            score += 0.4
            explain.append("📐 EMA 기울기: 우상향 → 상승 강도 강화")
        elif last['ema_slope'] < 0:
            explain.append("📐 EMA 기울기: 우하향 → 하락 압력")
        else:
            explain.append("📐 EMA 기울기: 거의 평탄 → 방향성 약함")
    total_weight += 0.4

    if last['close'] < last['lower_band']:
        score += 0.8
        explain.append("📎 Bollinger: 하단 이탈 ↗ 기술적 반등 예상")
    elif last['close'] > last['upper_band']:
        explain.append("📎 Bollinger: 상단 돌파 ↘ 과열 우려")
    else:
        explain.append("📎 Bollinger: 밴드 내 중립")
    total_weight += 0.8

    try:
        if last['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.1:
            score += 0.5
            explain.append("📊 거래량: 평균 대비 증가 ↗ 수급 활발")
        else:
            explain.append("📊 거래량: 뚜렷한 변화 없음")
    except:
        explain.append("📊 거래량: 분석 불가")
    total_weight += 0.5

    return round((score / total_weight) * 5, 2)

def analyze_multi_timeframe(symbol):
    timeframes = [('1m', 0.5), ('5m', 1.0), ('15m', 1.5)]
    total_score = 0
    total_weight = 0
    final_explain = []
    price_now = None

    for interval, weight in timeframes:
        df = fetch_ohlcv(symbol, interval)
        if df is None or len(df) < 30:
            continue
        df = calculate_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        explain = []
        score = calculate_weighted_score(last, prev, df, explain)
        total_score += score * weight
        total_weight += weight
        if interval == '15m':
            final_explain = explain
            price_now = last['close']

    # 1시간봉 추세 필터 추가 (1m 데이터 720개 사용)
def analyze_multi_timeframe(symbol):
    timeframes = [('1m', 0.5), ('5m', 1.0), ('15m', 1.5)]
    total_score = 0
    total_weight = 0
    final_explain = []
    price_now = None

    for interval, weight in timeframes:
        df = fetch_ohlcv(symbol, interval)
        if df is None or len(df) < 30:
            continue
        df = calculate_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        explain = []
        score = calculate_weighted_score(last, prev, df, explain)
        total_score += score * weight
        total_weight += weight
        if interval == '15m':
            final_explain = explain
            price_now = last['close']

    # 1시간봉 추세 필터 추가
    df_1m_long = fetch_ohlcv(symbol, '1m', limit=720)
    if df_1m_long is not None and len(df_1m_long) >= 60:
        df_1m_long.index = pd.date_range(end=pd.Timestamp.now(), periods=len(df_1m_long), freq='1min')
        df_1h = df_1m_long.resample('1H').agg({
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        if len(df_1h) >= 5:
            df_1h = calculate_indicators(df_1h)
            last = df_1h.iloc[-1]
            if all(col in last and not pd.isna(last[col]) for col in ['ema_20', 'ema_50', 'ema_200']):
                if last['ema_20'] > last['ema_50'] > last['ema_200']:
                    total_score += 1.0 * 2.0
                    total_weight += 2.0
                    final_explain.append('🕐 1시간봉 추세: EMA 정배열 → 상승 추세 강화')

    if total_weight == 0 or price_now is None:
        return None, None, None

    final_score = round(total_score / total_weight, 2)
    return final_score, final_explain, price_now


def calculate_entry_range(df, price_now):
    recent_volatility = df['close'].pct_change().abs().rolling(10).mean().iloc[-1]
    if pd.isna(recent_volatility) or recent_volatility == 0:
        return price_now * 0.995, price_now * 1.005
    buffer = max(0.0025, min(recent_volatility * 3, 0.015))
    return price_now * (1 - buffer), price_now * (1 + buffer)

def get_safe_stop_rate(direction, leverage, default_stop_rate):
    if leverage is None:
        return default_stop_rate
    safe_margin = 0.8
    if direction == "롱 (Long)":
        max_safe_rate = 1 - 1 / (1 + 1 / leverage)
    elif direction == "숏 (Short)":
        max_safe_rate = (1 / (1 - 1 / leverage)) - 1
    else:
        return default_stop_rate
    return round(min(default_stop_rate, max_safe_rate * safe_margin), 4)

def format_message(symbol, price_now, score, explain, direction, entry_low, entry_high, stop_loss, take_profit):
    now_kst = datetime.utcnow() + timedelta(hours=9)
    action_line = {
        "롱 (Long)": "🟢 추천 액션: 롱 포지션 진입",
        "숏 (Short)": "🔴 추천 액션: 숏 포지션 진입",
        "관망": "⚪ 추천 액션: 관망 (진입 자제)"
    }[direction]

    # 지표 설명 분리
    indicators = "\n".join([line for line in explain if not line.startswith("▶️")])
    score_line = f"▶️ 종합 분석 점수: {score}/5"

    msg = f"""
📊 {symbol.upper()} 기술 분석 (MEXC)
🕒 {now_kst.strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.4f}

{indicators}

{score_line}
"""

    if direction != "관망":
        msg += f"""\n📌 진입 전략 제안
{action_line}
🎯 진입 권장가: ${entry_low:,.4f} ~ ${entry_high:,.4f}
🛑 손절가: ${stop_loss:,.4f}
🟢 익절가: ${take_profit:,.4f}"""
    else:
        msg += f"""\n📌 참고 가격 범위
{action_line}
🎯 참고 가격: ${entry_low:,.4f} ~ ${entry_high:,.4f}"""

    return msg


def analyze_symbol(symbol, leverage=None):
    score, explain, price_now = analyze_multi_timeframe(symbol)
    if score is None:
        return None

    if score >= 3.5:
        direction = "롱 (Long)"
    elif score <= 2.0:
        direction = "숏 (Short)"
    else:
        direction = "관망"
    now_kst = datetime.utcnow() + timedelta(hours=9)
    direction, reasons = adjust_direction_based_on_event(symbol, direction, now_kst)
    for r in reasons:
        explain.append(f"⚠️ 외부 이벤트 반영: {r}")

    df = fetch_ohlcv(symbol)  # 1분봉으로 entry range 계산용
    if df is None:
        return None
    df = calculate_indicators(df)
    entry_low, entry_high = calculate_entry_range(df, price_now)

    if direction == "롱 (Long)":
        stop_rate = get_safe_stop_rate(direction, leverage, 0.02)
        stop_loss = price_now * (1 - stop_rate)
        take_profit = price_now * 1.04
    elif direction == "숏 (Short)":
        stop_rate = get_safe_stop_rate(direction, leverage, 0.02)
        stop_loss = price_now * (1 + stop_rate)
        take_profit = price_now * 0.96
    else:
        stop_loss = take_profit = None

    return format_message(symbol, price_now, score, explain, direction, entry_low, entry_high, stop_loss, take_profit)

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

@app.route(f"/bot{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    print("🟢 텔레그램 요청 수신됨")
    data = request.get_json()
    print(f"📦 RAW 전체 데이터:\n{data}")  # 전체 구조 로그 출력

    if 'message' in data:
        print("✅ 'message' 키 있음 → 본 로직 진입")
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '')
        print(f"💬 입력된 텍스트(raw): {repr(text)}")  # ← 공백/줄바꿈 포함 확인용

        text_stripped = text.strip().lower()
        print(f"📏 정제된 텍스트: {repr(text_stripped)}")

        if text_stripped == "/event":
            print("🧭 /event 명령어 분기 진입")
            event_msg = handle_event_command()
            send_telegram(event_msg, chat_id=chat_id)

        else:
            print("❌ /event 아님 → 다른 명령 시도")
            match = re.match(r"/go (\w+)(?:\s+(\d+)x)?", text_stripped, re.IGNORECASE)
            if match:
                symbol = match.group(1).upper()
                leverage = int(match.group(2)) if match.group(2) else None
                print(f"⚙️ 분석 시작: {symbol}, 레버리지={leverage}")
                msg = analyze_symbol(symbol, leverage)
                if msg:
                    send_telegram(msg, chat_id=chat_id)
                else:
                    send_telegram(f"⚠️ 분석 실패: {symbol} 데이터를 불러올 수 없습니다.", chat_id=chat_id)

    else:
        print("❌ 'message' 키가 없음")

    return '', 200


if __name__ == '__main__':
    # Flask 서버 실행 (데몬 스레드 아님, blocking 되지 않도록 lambda)
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

    # 기술 분석 루프 실행 (데몬)
    Thread(target=analysis_loop, daemon=True).start()

    # 경제 일정 스케줄러 실행 (데몬)
    Thread(target=start_economic_schedule, daemon=True).start()

    # 메인 스레드는 대기 (영원히)
    while True:
        time.sleep(60)


