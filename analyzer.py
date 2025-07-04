from utils import fetch_ohlcv_all_timeframes
from strategy import analyze_indicators
from datetime import datetime

def analyze_symbol(symbol: str):
    print(f"🔍 분석 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)

    if not data or '15m' not in data:
        print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
        return None

    score, action, indicators = analyze_indicators(data)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    current_price = data['1m']['close'].iloc[-1]

    message = f"""📊 {symbol.upper()} 기술 분석 (MEXC)
🕒 {now}
💰 현재가: ${current_price:,.2f}

⚖️ RSI: {indicators.get('RSI', 'N/A')}
📊 MACD: {indicators.get('MACD', 'N/A')}
📐 EMA: {indicators.get('EMA', 'N/A')}
📐 EMA 기울기: {indicators.get('EMA_Slope', 'N/A')}
📎 Bollinger: {indicators.get('Bollinger', 'N/A')}
📊 거래량: {indicators.get('Volume', 'N/A')}
🕐 1시간봉 추세: {indicators.get('Trend_1h', 'N/A')}

▶️ 종합 분석 점수: {score}/5

📌 진입 전략 제안
🔴 추천 액션: {action}
"""
    return message
