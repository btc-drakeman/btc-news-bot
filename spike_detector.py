import pandas_ta as ta
import numpy as np

def detect_spike(symbol: str, df):
    messages = []
    score = 0

    # 볼린저 밴드 폭 분석
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

    # 거래량 급증 감지
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

    # 조건 2개 이상 충족 시 급등 전조 경고
    if score >= 2:
        msg = f"""🚨 급등 전조 감지: {symbol.upper()}
- {'\n- '.join(messages)}

📌 강한 상승 가능성 → 관찰 또는 조기 진입 고려
"""
        return msg

    return None
