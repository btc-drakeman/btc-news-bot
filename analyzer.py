import time
from utils import fetch_ohlcv_all_timeframes
from strategy import analyze_indicators
from telegram_bot import send_telegram
from config import SYMBOLS
from datetime import datetime

# 분석 결과 메시지 생성

def format_analysis_message(symbol, score, price, details, trend):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry_low = round(price * 0.995, 2)
    entry_high = round(price * 1.005, 2)
    stop_loss = round(price * 0.985, 2)
    take_profit = round(price * 1.015, 2)

    action = '매수 (LONG)' if score >= 3.5 else '관망' if score >= 2.0 else '매도 (SHORT)'

    msg = f"""
📊 {symbol} 기술 분석 (MEXC)
🕒 {now}
💰 현재가: ${price}

{details}
🕐 1시간봉 추세: {trend}

▶️ 종합 분석 점수: {score:.2f}/5

📌 진입 전략 제안
🔴 추천 액션: {action}
🎯 진입 권장가: ${entry_low} ~ ${entry_high}
🛑 손절가: ${stop_loss}
🟢 익절가: ${take_profit}
"""
    return msg

# 전체 심볼 분석 함수
def analyze_symbol(symbol):
    try:
        print(f"🔍 분석 시작: {symbol}")
        print(f"✅ fetch_ohlcv_all_timeframes 호출 시작: {symbol}")
        data = fetch_ohlcv_all_timeframes(symbol)
        print(f"✅ data 결과: {type(data)}, keys={list(data.keys()) if data else None}")

        if not data or '15m' not in data:
            print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
            return None

        score, price, detail_text, trend = analyze_indicators(data)
        message = format_analysis_message(symbol, score, price, detail_text, trend)
        return message

    except Exception as e:
        print(f"❌ 분석 중 오류 발생: {e}")
        return None

# 분석 루프 함수
def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"🌀 루프 진입: {symbol}")
            result = analyze_symbol(symbol)
            if result:
                send_telegram(result)
            time.sleep(3)
        time.sleep(600)
