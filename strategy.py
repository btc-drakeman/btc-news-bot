import pandas as pd


def analyze_indicators(df: pd.DataFrame) -> tuple:
    close = df['close']
    volume = df['volume']

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    latest_rsi = rsi.iloc[-1]
    rsi_label = (
        f"과매도 ({latest_rsi:.1f})" if latest_rsi < 30 else
        f"과매수 ({latest_rsi:.1f})" if latest_rsi > 70 else
        f"중립 ({latest_rsi:.1f})"
    )

    # MACD
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line
    latest_macd_hist = macd_hist.iloc[-1]
    macd_label = (
        f"상승 전환 (+{latest_macd_hist:.2f})" if latest_macd_hist > 0.05 else
        f"하락 전환 ({latest_macd_hist:.2f})" if latest_macd_hist < -0.05 else
        f"중립 ({latest_macd_hist:.2f})"
    )

    # EMA 기울기
    ema = close.ewm(span=20, adjust=False).mean()
    latest_ema_slope = ema.diff().iloc[-1]
    ema_label = (
        "상승" if latest_ema_slope > 0.1 else
        "하락" if latest_ema_slope < -0.1 else
        "보합"
    )

    # 거래량 평균 이상 여부
    avg_volume = volume.iloc[-21:-1].mean()
    current_volume = volume.iloc[-1]
    volume_score = 0.5 if current_volume > avg_volume * 1.5 else 0.0
    volume_label = "평균 이상" if volume_score > 0 else "평균 이하"

    # 볼린저 중심선 돌파 여부
    middle_band = close.rolling(window=20).mean()
    bb_score = 0.8 if close.iloc[-1] > middle_band.iloc[-1] else 0.0
    bb_label = "돌파" if bb_score > 0 else "미돌파"

    # ADX 계산 (참고용 필터)
    high = df['high']
    low = df['low']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()

    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr14 = tr.rolling(window=14).sum()
    plus_di = 100 * (plus_dm.rolling(window=14).sum() / tr14)
    minus_di = 100 * (minus_dm.rolling(window=14).sum() / tr14)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(window=14).mean()
    latest_adx = adx.iloc[-1]
    latest_atr = atr.iloc[-1]
    adx_label = f"추세 강함 ({latest_adx:.1f})" if latest_adx >= 25 else f"추세 약함 ({latest_adx:.1f})"

    # 점수 계산 (항상 계산)
    long_score = 0.0
    short_score = 0.0

    # RSI
    if latest_rsi < 30:
        long_score += 1.0
    elif latest_rsi > 70:
        short_score += 1.0

    # MACD
    if latest_macd_hist > 0:
        long_score += 1.5
    elif latest_macd_hist < 0:
        short_score += 1.5

    # EMA
    if latest_ema_slope > 0:
        long_score += 1.2
    elif latest_ema_slope < 0:
        short_score += 1.2

    # 거래량
    long_score += volume_score
    short_score += 0.5 - volume_score

    # 볼린저 중심선 돌파 여부
    long_score += bb_score
    short_score += 0.8 - bb_score

    max_score = 5.0
    indicator_summary = {
        'RSI': rsi_label,
        'MACD': macd_label,
        'EMA': ema_label,
        'Volume': volume_label,
        'Bollinger': bb_label,
        'ADX': adx_label
    }

    if long_score >= 4.0:
        return 'LONG', round(long_score, 2), indicator_summary
    elif short_score >= 4.0:
        return 'SHORT', round(short_score, 2), indicator_summary
    else:
        return 'NONE', round(max(long_score, short_score), 2), indicator_summary


def generate_trade_plan(df: pd.DataFrame, direction: str = 'LONG', leverage: int = 10):
    price = df['close'].iloc[-1]

    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean().iloc[-1]

    # ADX 기반 multiplier 조정
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr14 = tr.rolling(window=14).sum()
    plus_di = 100 * (plus_dm.rolling(window=14).sum() / tr14)
    minus_di = 100 * (minus_dm.rolling(window=14).sum() / tr14)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(window=14).mean().iloc[-1]

    base_multiplier = 1.2 * (20 / leverage)
    if adx >= 40:
        atr_multiplier = base_multiplier * 1.6
    elif adx >= 30:
        atr_multiplier = base_multiplier * 1.3
    elif adx >= 25:
        atr_multiplier = base_multiplier * 1.1
    else:
        atr_multiplier = base_multiplier * 0.9

    # 진입 범위 ±0.5%
    entry_low = price * 0.995
    entry_high = price * 1.005

    if direction.upper() == 'SHORT':
        stop_loss = price + (atr * atr_multiplier)
        take_profit = price - (atr * atr_multiplier * 2)
    else:  # LONG
        stop_loss = price - (atr * atr_multiplier)
        take_profit = price + (atr * atr_multiplier * 2)

    return {
        'price': price,
        'entry_range': f"${entry_low:,.4f} ~ ${entry_high:,.4f}",
        'stop_loss': f"${stop_loss:,.4f}",
        'take_profit': f"${take_profit:,.4f}",
        'atr': round(atr, 4)
    }
