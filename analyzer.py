from utils import fetch_ohlcv_all_timeframes, get_rsi_trend, get_macd_trend, get_ema_trend
from strategy import analyze_indicators
from datetime import datetime

def analyze_symbol(symbol: str):
    print(f"🔍 분석 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)

    if not data or '15m' not in data:
        print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
        return None

    # 지표별 점수 계산
    score, action, indicators = analyze_indicators(data)

    # 추세 필터 (15분봉 기준)
    df_15m = data['15m']
    rsi_trend = get_rsi_trend(df_15m)
    macd_trend = get_macd_trend(df_15m)
    ema_trend = get_ema_trend(df_15m)

    # 기본은 관망
    final_action = "관망 (불확실한 추세)"

    if all([rsi_trend, macd_trend, ema_trend]) and \
       len(set(rsi_trend)) == 1 and \
       len(set(macd_trend)) == 1 and \
       len(set(ema_trend)) == 1 and \
       rsi_trend[0] == macd_trend[0] == ema_trend[0]:

        if score >= 3.5:
            if rsi_trend[0] == 'bull':
                final_action = "📈 롱 진입 추천"
            elif rsi_trend[0] == 'bear':
                final_action = "📉 숏 진입 추천"
            else:
                final_action = "관망 (중립 추세)"
        else:
            final_action = "관망 (점수 부족)"
    else:
        final_action = "관망 (추세 불일치)"

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
🔴 추천 액션: {final_action}
"""
    return message
