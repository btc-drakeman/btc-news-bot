import pandas_ta as ta


def detect_spike_conditions(df):
    """
    가격 급등 관련 기술적 지표를 분석하여
    2개 이상의 신호가 감지되면 메시지 목록을 반환합니다.
    """
    messages = []
    score = 0

    # 볼린저 밴드 폭 확장
    bb = ta.bbands(df['close'], length=20)
    if bb is not None and 'BBU_20_2.0' in bb:
        bb_width = bb['BBU_20_2.0'] - bb['BBL_20_2.0']
        if len(bb_width) >= 21:
            prev_std = bb_width.iloc[-21:-1].mean()
            current_std = bb_width.iloc[-1]
            if prev_std > 0 and current_std / prev_std > 1.8:
                score += 1
                messages.append(
                    f"📌 볼린저밴드 폭 확장 (전 {prev_std:.4f} ➔ 현 {current_std:.4f}, {current_std/prev_std:.2f}배)"
                )

    # 거래량 급증 확인
    vol = df['volume']
    if len(vol) >= 21:
        avg_vol = vol.iloc[-21:-1].mean()
        current_vol = vol.iloc[-1]
        if current_vol > avg_vol * 2:
            score += 1
            messages.append(
                f"📈 거래량 급증 (+{(current_vol/avg_vol):.2f}배)"
            )

    # MACD 히스토그램 전환 (음 ➔ 양)
    macd = ta.macd(df['close'])
    if macd is not None:
        hist = macd['MACDh_12_26_9'].dropna()
        if len(hist) >= 2 and hist.iloc[-2] < 0 < hist.iloc[-1]:
            score += 1
            messages.append("🔄 MACD 히스토그램 반전 (음 ➔ 양)")

    # RSI 급반등 체크
    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None:
        rsi_clean = rsi.dropna()
        if len(rsi_clean) >= 2:
            prev_rsi = rsi_clean.iloc[-2]
            curr_rsi = rsi_clean.iloc[-1]
            if 45 <= prev_rsi <= 55 and curr_rsi > 60:
                score += 1
                messages.append(
                    f"⚡ RSI 급반등 ({prev_rsi:.1f} ➔ {curr_rsi:.1f})"
                )

    return messages if score >= 2 else None



def detect_crash_conditions(df):
    """
    가격 급락 관련 기술적 지표를 분석하여
    2개 이상의 신호가 감지되면 메시지 목록을 반환합니다.
    """
    messages = []
    score = 0

    # 볼린저 밴드 하단 이탈 및 확장
    bb = ta.bbands(df['close'], length=20)
    if bb is not None and 'BBL_20_2.0' in bb:
        bb_width = bb['BBU_20_2.0'] - bb['BBL_20_2.0']
        if len(bb_width) >= 21:
            prev_std = bb_width.iloc[-21:-1].mean()
            current_std = bb_width.iloc[-1]
            last_close = df['close'].iloc[-1]
            lower_band = bb['BBL_20_2.0'].iloc[-1]
            if prev_std > 0 and current_std / prev_std > 1.8 and last_close < lower_band:
                score += 1
                messages.append(
                    f"📌 볼린저밴드 하단 이탈 & 폭 확장 ({current_std/prev_std:.2f}배)"
                )

    # 거래량 급증 확인
    vol = df['volume']
    if len(vol) >= 21:
        avg_vol = vol.iloc[-21:-1].mean()
        current_vol = vol.iloc[-1]
        if current_vol > avg_vol * 2:
            score += 1
            messages.append(
                f"📈 거래량 급증 (+{(current_vol/avg_vol):.2f}배)"
            )

    # MACD 히스토그램 전환 (양 ➔ 음)
    macd = ta.macd(df['close'])
    if macd is not None:
        hist = macd['MACDh_12_26_9'].dropna()
        if len(hist) >= 2 and hist.iloc[-2] > 0 > hist.iloc[-1]:
            score += 1
            messages.append("🔄 MACD 히스토그램 반전 (양 ➔ 음)")

    # RSI 급하락 체크
    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None:
        rsi_clean = rsi.dropna()
        if len(rsi_clean) >= 2:
            prev_rsi = rsi_clean.iloc[-2]
            curr_rsi = rsi_clean.iloc[-1]
            if 45 <= prev_rsi <= 55 and curr_rsi < 40:
                score += 1
                messages.append(
                    f"⚡ RSI 급하락 ({prev_rsi:.1f} ➔ {curr_rsi:.1f})"
                )

    return messages if score >= 2 else None
