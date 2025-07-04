# analyzer.py

import pandas as pd
from datetime import datetime
from notifier import send_telegram
from utils import fetch_ohlcv_all_timeframes
from config import SYMBOLS

# ====== 지표 계산 ======
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    if val > 70:
        return "과매수구간 ↘ 하락 경고"
    elif val < 30:
        return "과매도구간 ↗ 상승 기대"
    return "중립"

def calculate_macd(df):
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    hist = macd - signal
    if macd.iloc[-1] > signal.iloc[-1] and hist.iloc[-1] > hist.iloc[-2]:
        return "골든크로스 ↗ 상승 전환"
    elif macd.iloc[-1] < signal.iloc[-1] and hist.iloc[-1] < hist.iloc[-2]:
        return "데드크로스 ↘ 하락 경고"
    return "특별한 신호 없음"

def calculate_ema(df):
    ema_short = df['close'].ewm(span=10).mean()
    ema_long = df['close'].ewm(span=50).mean()
    slope = ema_short.diff().iloc[-1]
    direction = "정배열" if ema_short.iloc[-1] > ema_long.iloc[-1] else "역배열"
    slope_text = "우상향 → 상승 강도 강화" if slope > 0 else "우하향 → 추세 약화"
    return f"{direction} ({slope_text})", slope_text

def calculate_bollinger(df):
    ma20 = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    upper = ma20 + 2 * std
    lower = ma20 - 2 * std
    last = df['close'].iloc[-1]
    if last > upper.iloc[-1]:
        return "상단 돌파 ↘ 과열 우려"
    elif last < lower.iloc[-1]:
        return "하단 이탈 ↗ 저평가 가능"
    return "중립"

def calculate_volume(df):
    avg_vol = df['volume'].rolling(window=20).mean()
    if df['volume'].iloc[-1] > avg_vol.iloc[-1] * 1.5:
        return "급등 (매집 또는 투매)"
    elif df['volume'].iloc[-1] < avg_vol.iloc[-1] * 0.5:
        return "급감 (관망 상태)"
    return "뚜렷한 변화 없음"

# ====== 점수 + 전략 ======
def calculate_score(rsi, macd, ema, boll, volume):
    score = 0.0
    if "상승" in macd or "골든" in macd:
        score += 1.5
    if "정배열" in ema:
        score += 1.2
    if "과매도" in rsi or "상승 기대" in rsi:
        score += 1.0
    if "저평가" in boll:
        score += 0.8
    if "급등" in volume:
        score += 0.5
    return round(score, 2)

def recommend_action(score):
    if score >= 3.5:
        return "롱 포지션 진입"
    elif score >= 2.0:
        return "관망 또는 분할 진입"
    else:
        return "숏 포지션 진입"

# ====== 분석 실행 ======
def analyze_symbol(symbol: str):
    print(f"🔍 분석 시작: {symbol}")
    print(f"✅ fetch_ohlcv_all_timeframes 호출 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)
    print(f"✅ data 결과: {type(data)}, keys={list(data.keys()) if data else 'None'}")
    for tf, df in (data or {}).items():
        print(f"🕒 {tf}: {len(df)} rows")

    if not data or len(data['15m']) < 100:
        print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
        return

    df15 = data['15m']
    df1h = data['1h']

    rsi = calculate_rsi(df15)
    macd = calculate_macd(df15)
    ema_text, ema_slope = calculate_ema(df15)
    boll = calculate_bollinger(df15)
    volume = calculate_volume(df15)
    hourly_trend, _ = calculate_ema(df1h)

    score = calculate_score(rsi, macd, ema_text, boll, volume)
    action = recommend_action(score)

    price_now = df15['close'].iloc[-1]
    take_profit = price_now * 1.04
    stop_loss = price_now * 0.97
    entry_range = (price_now * 0.995, price_now * 1.002)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"""📊 {symbol} 기술 분석 (MEXC)
🕒 {now}
💰 현재가: ${price_now:.4f}

⚖️ RSI: {rsi}
📊 MACD: {macd}
📐 EMA: {ema_text}
📐 EMA 기울기: {ema_slope}
📎 Bollinger: {boll}
📊 거래량: {volume}
🕐 1시간봉 추세: {hourly_trend}

▶️ 종합 분석 점수: {score}/5

📌 진입 전략 제안
🔴 추천 액션: {action}
🎯 진입 권장가: ${entry_range[0]:.4f} ~ ${entry_range[1]:.4f}
🛑 손절가: ${stop_loss:.4f}
🟢 익절가: ${take_profit:.4f}
"""
    print(f"📨 전송 메시지:\n{message}")  # 메시지 내용 출력
    print("📤 텔레그램 메시지 전송 시도 중...")  # 전송 시도 확인 로그
    send_telegram(message)
    print(f"✅ 완료 → {symbol}")  # 마무리 로그

