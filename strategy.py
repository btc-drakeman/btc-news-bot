import pandas as pd

# 지표별 가중치
WEIGHTS = {
    'RSI': 1.0,
    'MACD': 1.5,
    'EMA': 1.2,
    'BOLL': 0.8,
    'VOLUME': 0.5
}

def analyze_indicators(df: pd.DataFrame) -> tuple:
    close = df['close']
    volume = df['volume']
    result_messages = []
    long_score = 0.0
    short_score = 0.0

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # RSI 롱
    if rsi.iloc[-1] > rsi.iloc[-2]:
        long_score += 0.3 * WEIGHTS['RSI']
        result_messages.append("📈 RSI 상승 흐름 (+0.3)")
    if rsi.iloc[-2] < 50 <= rsi.iloc[-1]:
        long_score += 0.4 * WEIGHTS['RSI']
        result_messages.append("📈 RSI 50 상향 돌파 (+0.4)")
    if rsi.iloc[-2] < 30 and rsi.iloc[-1] > 35:
        long_score += 0.6 * WEIGHTS['RSI']
        result_messages.append("📈 RSI 과매도 반등 (+0.6)")

    # RSI 숏
    if rsi.iloc[-1] < rsi.iloc[-2]:
        short_score += 0.3 * WEIGHTS['RSI']
        result_messages.append("📉 RSI 하락 흐름 (+0.3)")
    if rsi.iloc[-2] > 50 >= rsi.iloc[-1]:
        short_score += 0.4 * WEIGHTS['RSI']
        result_messages.append("📉 RSI 50 하향 이탈 (+0.4)")
    if rsi.iloc[-2] > 70 and rsi.iloc[-1] < 65:
        short_score += 0.6 * WEIGHTS['RSI']
        result_messages.append("📉 RSI 과매수 후 하락 (+0.6)")

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    if macd_hist.iloc[-1] > macd_hist.iloc[-2]:
        long_score += 0.5 * WEIGHTS['MACD']
        result_messages.append("📈 MACD 히스토그램 확대 (+0.5)")
    if macd_hist.iloc[-2] < 0 < macd_hist.iloc[-1]:
        long_score += 0.8 * WEIGHTS['MACD']
        result_messages.append("📈 MACD 음→양 전환 (+0.8)")

    if macd_hist.iloc[-1] < macd_hist.iloc[-2]:
        short_score += 0.5 * WEIGHTS['MACD']
        result_messages.append("📉 MACD 히스토그램 축소 (+0.5)")
    if macd_hist.iloc[-2] > 0 > macd_hist.iloc[-1]:
        short_score += 0.8 * WEIGHTS['MACD']
        result_messages.append("📉 MACD 양→음 전환 (+0.8)")

    # EMA
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema_slope = ema20.diff()

    if ema_slope.iloc[-1] > 0:
        long_score += 0.4 * WEIGHTS['EMA']
        result_messages.append("📈 EMA 양의 기울기 (+0.4)")
    if ema20.iloc[-1] > ema20.iloc[-2] > ema20.iloc[-3]:
        long_score += 0.6 * WEIGHTS['EMA']
        result_messages.append("📈 EMA 3봉 연속 상승 (+0.6)")

    if ema_slope.iloc[-1] < 0:
        short_score += 0.4 * WEIGHTS['EMA']
        result_messages.append("📉 EMA 음의 기울기 (+0.4)")
    if ema20.iloc[-1] < ema20.iloc[-2] < ema20.iloc[-3]:
        short_score += 0.6 * WEIGHTS['EMA']
        result_messages.append("📉 EMA 3봉 연속 하락 (+0.6)")

    # Bollinger Bands
    std = close.rolling(window=20).std()
    mid = close.rolling(window=20).mean()
    upper = mid + (2 * std)
    lower = mid - (2 * std)

    if close.iloc[-2] < mid.iloc[-2] and close.iloc[-1] > mid.iloc[-1]:
        long_score += 0.4 * WEIGHTS['BOLL']
        result_messages.append("📈 볼린저 중심선 상향 돌파 (+0.4)")
    if std.iloc[-1] > std.iloc[-2]:
        long_score += 0.3 * WEIGHTS['BOLL']
        result_messages.append("📈 볼린저 밴드 확장 중 (+0.3)")

    if close.iloc[-2] > mid.iloc[-2] and close.iloc[-1] < mid.iloc[-1]:
        short_score += 0.4 * WEIGHTS['BOLL']
        result_messages.append("📉 볼린저 중심선 하향 이탈 (+0.4)")
    if std.iloc[-1] > std.iloc[-2]:
        short_score += 0.3 * WEIGHTS['BOLL']
        result_messages.append("📉 볼린저 밴드 확장 중 (+0.3)")

    # 거래량
    avg_vol = volume.rolling(window=20).mean()

    if volume.iloc[-1] > avg_vol.iloc[-1] * 1.5:
        long_score += 0.4 * WEIGHTS['VOLUME']
        result_messages.append("📊 거래량 평균 대비 1.5배 ↑ (+0.4)")
    if volume.iloc[-1] > avg_vol.iloc[-1] * 2:
        long_score += 0.6 * WEIGHTS['VOLUME']
        result_messages.append("📊 거래량 평균 대비 2배 ↑ (+0.6)")

    if volume.iloc[-1] > avg_vol.iloc[-1] * 1.5:
        short_score += 0.4 * WEIGHTS['VOLUME']
        result_messages.append("📊 거래량 급증 (하락 시 경계) (+0.4)")
    if volume.iloc[-1] > avg_vol.iloc[-1] * 2:
        short_score += 0.6 * WEIGHTS['VOLUME']
        result_messages.append("📊 거래량 폭증 (하락 시 경계) (+0.6)")

    # 최종 판단
    if long_score >= 3.5 and long_score > short_score:
        result_messages.append(f"▶️ 종합 점수: {long_score:.2f} → LONG")
        return 'LONG', round(long_score, 2)
    elif short_score >= 3.5 and short_score > long_score:
        result_messages.append(f"▶️ 종합 점수: {short_score:.2f} → SHORT")
        return 'SHORT', round(short_score, 2)
    else:
        result_messages.append(f"▶️ 종합 점수: {max(long_score, short_score):.2f} → NONE")
        return 'NONE', round(max(long_score, short_score), 2)
