from utils import (
    fetch_ohlcv_all_timeframes,
    fetch_recent_ohlcv,
    get_rsi_trend,
    get_macd_trend,
    get_ema_trend,
    check_trend_consistency,
    check_multi_timeframe_alignment,
    check_resistance_breakout,
    detect_candle_pattern
)

from strategy import analyze_indicators
from strategy_backtest import get_optimal_hold_period
from datetime import datetime
import pytz

def analyze_symbol(symbol: str):
    print(f"\U0001f50d 분석 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)

    if not data or '15m' not in data or '30m' not in data:
        print(f"❌ 데이터 부족 또는 15m 봉 부족: {symbol}")
        return None

    score, action, direction, indicators = analyze_indicators(data)

    df_15m = data['15m']
    df_1h = data['30m']

    breakout_ok, recent_high = check_resistance_breakout(df_15m)
    breakout_str = f"{'✅' if breakout_ok else '❌'} 최근 고점 (${recent_high:,.2f}) {'돌파' if breakout_ok else '미돌파'}"

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

    confidence = "❕ 약함"
    if consistency_ok and alignment_ok:
        confidence = "✅ 높음"
    elif consistency_ok or alignment_ok:
        confidence = "⚠️ 중간"

    KST = pytz.timezone('Asia/Seoul')
    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    current_price = data['1m']['close'].iloc[-1]

    # ✅ 실시간 최적 보유시간 계산
    try:
        backtest_df = fetch_recent_ohlcv(symbol, interval='15m', limit=672)
        hold_bars = get_optimal_hold_period(backtest_df, direction)
    except Exception as e:
        print(f"❌ 최적 보유시간 계산 실패: {e}")
        hold_bars = 13  # fallback 기본값

    entry = current_price
    tp = round(entry * (1.04 if direction == 'long' else 0.96), 2)
    sl = round(entry * (0.98 if direction == 'long' else 1.02), 2)
    ret = round(abs(tp - entry) / entry * 20 * 100, 2)

    strategy_block = f"""
📌 전략 실행 정보 ({'롱' if direction == 'long' else '숏'} 시나리오)
📈 예상 보유 시간: {hold_bars}봉 (약 {round(hold_bars * 15 / 60, 2)}시간)
💵 진입가: ${entry:,.2f}
🎯 익절가: ${tp:,.2f} (+4%)
🛑 손절가: ${sl:,.2f} (-2%)
📊 예상 수익률(20x): +{ret}%"""

    final_action = "📈 롱 진입 시그널" if direction == 'long' else "📉 숏 진입 시그널"

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

📌 추세 일관성(15m): {'✅' if consistency_ok else '❌'}
📌 다중 타임프레임 일치(15m ↔ 1h): {'✅' if alignment_ok else '❌'}
📌 고점 돌파 여부: {breakout_str}
📌 캔들 패턴(15m): {candle_pattern}

📌 신호 신뢰도: {confidence}
▶️ 종합 분석 점수: {score}/5

🔴 추천 액션: {final_action}

{strategy_block}
"""

    print(f"📊 [디버그] {symbol} 최종 점수: {score}, 액션: {action} → 방향: {direction}")
    return message
