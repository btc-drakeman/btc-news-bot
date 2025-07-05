from utils import (
    fetch_ohlcv_all_timeframes,
    get_rsi_trend,
    get_macd_trend,
    get_ema_trend,
    check_trend_consistency,
    check_multi_timeframe_alignment,
    check_resistance_breakout,
    detect_candle_pattern
)


from strategy import analyze_indicators
from datetime import datetime
import pytz

def analyze_symbol(symbol: str):
    print(f"🔍 분석 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)

    if not data or '15m' not in data or '30m' not in data:
        print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
        return None

    # 지표별 점수 계산
    score, action, indicators = analyze_indicators(data)

    # 추세 필터 (15분봉 + 30분봉 기준)
    df_15m = data['15m']
    df_1h = data['30m']  # 30m * 2 = 1시간 대응

    # 고점 돌파 여부 판단 (15분봉 기준)
    breakout_ok, recent_high = check_resistance_breakout(df_15m)
    breakout_str = f"{'✅' if breakout_ok else '❌'} 최근 고점 (${recent_high:,.2f}) {'돌파' if breakout_ok else '미돌파'}"

    # ✅ 최근 캔들 패턴 판별 (15분봉)
    candle_pattern = detect_candle_pattern(df_15m)

    rsi_15m = get_rsi_trend(df_15m)
    macd_15m = get_macd_trend(df_15m)
    ema_15m = get_ema_trend(df_15m)

    rsi_1h = get_rsi_trend(df_1h)
    macd_1h = get_macd_trend(df_1h)
    ema_1h = get_ema_trend(df_1h)

    consistency_ok = all([
        check_trend_consistency(rsi_15m),
        check_trend_consistency(macd_15m),
        check_trend_consistency(ema_15m)
    ])

    alignment_ok = all([
        check_multi_timeframe_alignment(rsi_15m, rsi_1h),
        check_multi_timeframe_alignment(macd_15m, macd_1h),
        check_multi_timeframe_alignment(ema_15m, ema_1h)
    ])

        # 신뢰도 등급
    confidence = "❕ 약함"
    if consistency_ok and alignment_ok:
        confidence = "✅ 높음"
    elif consistency_ok or alignment_ok:
        confidence = "⚠️ 중간"

    # ✅ 여기부터 교체
    # 최종 전략 판단
    final_action = "관망 (조건 미충족)"

    if score >= 4.5:
        final_action = "🟢 진입 강력 추천 (고점 돌파 대기 가능)"
    elif score >= 3.5 and consistency_ok and alignment_ok:
        if rsi_15m and rsi_15m[0] == 'bull':
            final_action = "📈 롱 진입 추천"
        elif rsi_15m and rsi_15m[0] == 'bear':
            final_action = "📉 숏 진입 추천"
        else:
            final_action = "관망 (중립 추세)"
    elif score >= 3.5:
        final_action = "관망 (추세 불확실)"


    KST = pytz.timezone('Asia/Seoul')
    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')

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

📌 추세 일관성(15m): {"✅" if consistency_ok else "❌"}
📌 다중 타임프레임 일치(15m ↔ 1h): {"✅" if alignment_ok else "❌"}
📌 고점 돌파 여부: {breakout_str}
📌 캔들 패턴(15m): {candle_pattern}

📌 신호 신뢰도: {confidence}
▶️ 종합 분석 점수: {score}/5

📌 진입 전략 제안
🔴 추천 액션: {final_action}
"""
    return message
