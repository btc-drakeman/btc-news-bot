def generate_signal_message(symbol, current_price, rsi, macd, ema, ema_slope, bollinger, volume,
                            trend_consistency, timeframe_alignment, breakout_status, candle_pattern,
                            confidence, score, action, entry_low, entry_high, stop_loss, take_profit,
                            hold_bars, avg_return, avg_hold_bars, is_long=True):
    direction_emoji = "📈" if is_long else "📉"
    action_text = f"{direction_emoji} {'롱' if is_long else '숏'} 진입 시그널"
    scenario_text = f"{'롱' if is_long else '숏'} 시나리오"

    return f"""📊 {symbol} 기술 분석 (MEXC)
🕒 2025-07-08 13:00
💰 현재가: ${current_price:,.2f}

⚖️ RSI: {rsi}
📊 MACD: {macd}
📐 EMA: {ema}
📐 EMA 기울기: {ema_slope}
📎 Bollinger: {bollinger}
📊 거래량: {volume}

🧭 추세 일관성(15m): {trend_consistency}
🔗 다중 타임프레임 일치(15m ↔ 1h): {timeframe_alignment}
⛳ 고점 돌파 여부: {breakout_status}
🕯️ 캔들 패턴(15m): {candle_pattern}
🧠 신호 신뢰도: {confidence}
▶️ 종합 분석 점수: {score:.2f}/5

🔴 추천 액션: {action_text}

📌 전략 실행 정보 ({scenario_text})
📈 예상 보유 시간: {hold_bars}봉 (약 {hold_bars * 0.25:.2f}시간)
💵 진입가: ${entry_low:,.2f} ~ ${entry_high:,.2f}
🎯 익절가: ${take_profit:,.2f}
🛑 손절가: ${stop_loss:,.2f}

📊 과거 유사 조건 수익 예측
📈 평균 수익률: {avg_return:+.2f}%
🕒 평균 보유 시간: {avg_hold_bars:.1f}봉"""