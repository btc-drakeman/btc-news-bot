import time
from datetime import datetime
import pandas as pd
from newsbot import fetch_ohlcv, send_telegram


# === 기술 지표 계산 함수 ===
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    last_rsi = rsi.iloc[-1]
    if last_rsi > 70:
        return "과매수 (하락 가능성)"
    elif last_rsi < 30:
        return "과매도 (상승 가능성)"
    else:
        return "중립"

def calculate_macd(df):
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    if macd.iloc[-1] > signal.iloc[-1] and hist.iloc[-1] > hist.iloc[-2]:
        return "골든크로스 ↗️ 상승 전환 가능성"
    elif macd.iloc[-1] < signal.iloc[-1] and hist.iloc[-1] < hist.iloc[-2]:
        return "데드크로스 ↘️ 하락 경고"
    else:
        return "중립"

def calculate_ema(df):
    ema_short = df['close'].ewm(span=10, adjust=False).mean()
    ema_long = df['close'].ewm(span=50, adjust=False).mean()
    if ema_short.iloc[-1] > ema_long.iloc[-1]:
        return "정배열 (상승 흐름)"
    elif ema_short.iloc[-1] < ema_long.iloc[-1]:
        return "역배열 (하락 흐름)"
    else:
        return "중립"

def calculate_bollinger(df):
    ma20 = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    upper = ma20 + 2 * std
    lower = ma20 - 2 * std
    last = df['close'].iloc[-1]
    if last > upper.iloc[-1]:
        return "상단 돌파 (과열 가능성)"
    elif last < lower.iloc[-1]:
        return "하단 이탈 (저평가 가능성)"
    else:
        return "중립"

def calculate_volume(df):
    vol = df['volume']
    avg = vol.rolling(window=20).mean()
    if vol.iloc[-1] > avg.iloc[-1] * 1.5:
        return "급등 (매집 또는 투매)"
    elif vol.iloc[-1] < avg.iloc[-1] * 0.5:
        return "급감 (관망 상태)"
    else:
        return "중립"

# === 점수 계산 ===
def calculate_score(rsi, macd, ema, boll, volume):
    score = 0.0
    if "상승" in macd or "골든" in macd:
        score += 1.5
    if "정배열" in ema or "상승" in ema:
        score += 1.2
    if "과매도" in rsi or "상승" in rsi:
        score += 1.0
    if "상단 돌파" in boll or "저평가" in boll:
        score += 0.8
    if "급등" in volume:
        score += 0.5
    return round(score, 2)

def action_recommendation(score):
    if score >= 4.0:
        return "강한 매수 시그널 (진입 고려)"
    elif score >= 2.5:
        return "관망 또는 분할 진입"
    elif score >= 1.5:
        return "진입 자제 (약한 신호)"
    else:
        return "매도 또는 숏 포지션 고려"

# === 심볼 분석 ===
def analyze_symbol(symbol):
    print(f"분석 중: {symbol} ({datetime.now().strftime('%H:%M:%S')})")
    df = fetch_ohlcv(symbol, '15m')
    if df is None or len(df) < 50:
        print(f"❌ 데이터 부족: {symbol}")
        return None

    rsi = calculate_rsi(df)
    macd = calculate_macd(df)
    ema = calculate_ema(df)
    boll = calculate_bollinger(df)
    volume = calculate_volume(df)

    score = calculate_score(rsi, macd, ema, boll, volume)
    recommendation = action_recommendation(score)

    price_now = df['close'].iloc[-1]
    upper = df['close'].rolling(20).mean().iloc[-1] + 2 * df['close'].rolling(20).std().iloc[-1]
    lower = df['close'].rolling(20).mean().iloc[-1] - 2 * df['close'].rolling(20).std().iloc[-1]
    take_profit = price_now * 1.02
    stop_loss = price_now * 0.985

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = f"""
📊 {symbol} 기술분석 (MEXC)
🕒 {now}
💰 현재가: ${price_now:.4f}

📌 RSI: {rsi}
📌 MACD: {macd}
📌 EMA: {ema}
📌 Bollinger: {boll}
📌 거래량: {volume}

▶️ 종합 분석 점수: {score} / 5.0
📌 포지션: {recommendation}
📈 참고 가격 범위: ${lower:.2f} ~ ${upper:.2f}
🎯 익절가: ${take_profit:.2f}
🛑 손절가: ${stop_loss:.2f} 
"""
    send_telegram(result)
    return result

# === 분석 루프 ===
def analysis_loop():
    while True:
        for symbol in ['BTC_USDT', 'ETH_USDT', 'XRP_USDT', 'ETHFI_USDT']:
            analyze_symbol(symbol)
            time.sleep(3)
        time.sleep(600)
