import pandas_ta as ta
import numpy as np
from strategy import generate_trade_plan  # ✅ 최신 전략 함수 사용

def detect_spike(symbol: str, df):
    messages = []
    score = 0

    # 볼린저 밴드 확장
    bb = ta.bbands(df['close'], length=20)
    if bb is not None and 'BBU_20_2.0' in bb:
        bb_width = bb['BBU_20_2.0'] - bb['BBL_20_2.0']
        if len(bb_width) >= 21:
            prev_std = bb_width.iloc[-21:-1].mean()
            current_std = bb_width.iloc[-1]
            expansion = current_std / prev_std if prev_std > 0 else 0
            if expansion > 1.8:
                score += 1
                messages.append(f"📎 볼린저 밴드 확장 감지 (폭 ↑ {expansion:.2f}배)")

    # 거래량 급증
    vol = df['volume']
    if len(vol) >= 21:
        avg_vol = vol.iloc[-21:-1].mean()
        current_vol = vol.iloc[-1]
        if current_vol > avg_vol * 2:
            score += 1
            messages.append(f"📊 거래량 급증 (+{(current_vol / avg_vol):.2f}배)")

    # MACD 히스토그램 반전
    macd = ta.macd(df['close'])
    if macd is not None and len(macd['MACDh_12_26_9'].dropna()) >= 2:
        hist = macd['MACDh_12_26_9'].dropna()
        if hist.iloc[-2] < 0 and hist.iloc[-1] > 0:
            score += 1
            messages.append("📉 MACD 히스토그램 반전 (음 → 양)")

    # RSI 급반등
    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None and len(rsi.dropna()) >= 2:
        prev_rsi = rsi.iloc[-2]
        current_rsi = rsi.iloc[-1]
        if 45 <= prev_rsi <= 55 and current_rsi > 60:
            score += 1
            messages.append(f"⚡ RSI 급반등 ({prev_rsi:.1f} → {current_rsi:.1f})")

    if score >= 2:
        plan = generate_trade_plan(df, direction='LONG', leverage=10)
        details = '\n- '.join(messages)
        msg = f"""🚨 급등 전조 감지: {symbol.upper()}
- {details}

📌 강한 상승 가능성 → 관찰 또는 조기 진입 고려

📌 진입 전략 제안 (레버리지 10x 기준)
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}
"""
        return msg

    return None

def detect_crash(symbol: str, df):
    messages = []
    score = 0

    # 볼린저 밴드 하단 이탈 + 확장
    bb = ta.bbands(df['close'], length=20)
    if bb is not None and 'BBL_20_2.0' in bb:
        bb_width = bb['BBU_20_2.0'] - bb['BBL_20_2.0']
        if len(bb_width) >= 21:
            prev_std = bb_width.iloc[-21:-1].mean()
            current_std = bb_width.iloc[-1]
            last_close = df['close'].iloc[-1]
            lower_band = bb['BBL_20_2.0'].iloc[-1]
            if current_std / prev_std > 1.8 and last_close < lower_band:
                score += 1
                messages.append(f"📎 볼린저 밴드 하단 이탈 + 확장 (↓ {current_std / prev_std:.2f}배)")

    # 거래량 급증
    vol = df['volume']
    if len(vol) >= 21:
        avg_vol = vol.iloc[-21:-1].mean()
        current_vol = vol.iloc[-1]
        if current_vol > avg_vol * 2:
            score += 1
            messages.append(f"📊 거래량 급증 (+{(current_vol / avg_vol):.2f}배)")

    # MACD 양 → 음 반전
    macd = ta.macd(df['close'])
    if macd is not None and len(macd['MACDh_12_26_9'].dropna()) >= 2:
        hist = macd['MACDh_12_26_9'].dropna()
        if hist.iloc[-2] > 0 and hist.iloc[-1] < 0:
            score += 1
            messages.append("📉 MACD 히스토그램 반전 (양 → 음)")

    # RSI 급하락
    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None and len(rsi.dropna()) >= 2:
        prev_rsi = rsi.iloc[-2]
        current_rsi = rsi.iloc[-1]
        if 45 <= prev_rsi <= 55 and current_rsi < 40:
            score += 1
            messages.append(f"⚡ RSI 급하락 ({prev_rsi:.1f} → {current_rsi:.1f})")

    if score >= 2:
        plan = generate_trade_plan(df, direction='SHORT', leverage=10)
        details = '\n- '.join(messages)
        msg = f"""⚠️ 급락 전조 감지: {symbol.upper()}
- {details}

📌 강한 하락 가능성 → 포지션 주의

📌 진입 전략 제안 (레버리지 10x 기준)
🎯 진입가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🟢 익절가: {plan['take_profit']}
"""
        return msg

    return None
