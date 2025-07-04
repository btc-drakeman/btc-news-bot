from utils import fetch_ohlcv_all_timeframes
from strategy import analyze_indicators
from datetime import datetime

def analyze_symbol(symbol: str):
    print(f"🔍 분석 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)

    if not data or '15m' not in data:
        print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
        return None

    score, action = analyze_indicators(data)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    current_price = data['1m']['close'].iloc[-1]

    message = f"""📊 {symbol.upper()} 기술 분석 (MEXC)
🕒 {now}
💰 현재가: ${current_price:,.2f}

▶️ 종합 분석 점수: {score}/5
📌 진입 전략 제안
🔴 추천 액션: {action}
"""
    return message
