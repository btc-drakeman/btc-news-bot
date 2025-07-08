def generate_signal_message(
    symbol: str,
    current_price: float,
    indicators: dict,
    action: str,
    score: float,
    direction: str,
    entry_price: tuple,
    stop_loss: float,
    take_profit: float,
    expected_return: float,
    expected_hold: float,
    consistency: bool,
    alignment: bool,
    breakout: bool,
    candle_signal: str,
    reliability: str,
    tp_ratio: float = None,  # ✅ 익절 비율 추가
    sl_ratio: float = None   # ✅ 손절 비율 추가
):
    entry_low, entry_high = entry_price

    icon_consistency = "🧭"
    icon_alignment = "📐"
    icon_breakout = "📌"
    icon_candle = "🕯️"
    icon_reliability = "🔎"

    lines = [
        f"📊 <b>{symbol}</b> 기술 분석 (MEXC)",
        f"🕒 {indicators['timestamp']}",
        f"💰 현재가: ${current_price:,.2f}\n",
        f"⚖️ RSI: {indicators['RSI']}",
        f"📊 MACD: {indicators['MACD']}",
        f"📐 EMA: {indicators['EMA']}",
        f"📐 EMA 기울기: {indicators['EMA Slope']}",
        f"📎 Bollinger: {indicators['Bollinger']}",
        f"📊 거래량: {indicators['Volume']}\n",
        f"{icon_consistency} 추세 일관성(15m): {'✅' if consistency else '❌'}",
        f"{icon_alignment} 다중 타임프레임 일치(15m ↔ 1h): {'✅' if alignment else '❌'}",
        f"{icon_breakout} 고점 돌파 여부: {'✅' if breakout else '❌'}",
        f"{icon_candle} 캔들 패턴(15m): {candle_signal}",
        f"{icon_reliability} 신호 신뢰도: {reliability}",
        f"▶️ 종합 분석 점수: {score:.2f}/5\n",
        f"{'🟢 롱 진입 시그널' if direction == 'long' else '🔴 숏 진입 시그널'}",
        "",
        f"📌 전략 실행 정보 ({'롱' if direction == 'long' else '숏'} 시나리오)",
        f"⏱️ 예상 보유 시간: {expected_hold:.1f}봉",
        f"💵 진입가: ${entry_low:,.2f} ~ ${entry_high:,.2f}",
        f"🎯 익절가: ${take_profit:,.2f}",
        f"🛑 손절가: ${stop_loss:,.2f}",
        f"📈 예상 수익률(20x): {expected_return:+.2f}%"
    ]

    return "\n".join(lines)
