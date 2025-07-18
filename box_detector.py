import pandas as pd


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_adx(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']

    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, min_periods=period).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(span=period, min_periods=period).mean()
    return adx


def detect_box_ranges_v3(df, window=30):
    df = df.copy()

    if 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    else:
        df['timestamp'] = df.index.to_pydatetime()

    df.set_index('timestamp', inplace=True)

    df['rsi'] = compute_rsi(df['close'])
    df['adx'] = compute_adx(df)

    box_ranges = []
    in_box = False
    start_idx = None

    for i in range(window, len(df)):
        score = 0
        window_df = df.iloc[i - window:i]

        window_high = window_df['high'].max()
        window_low = window_df['low'].min()
        range_ratio = (window_high - window_low) / window_low

        rsi_range_ok = window_df['rsi'].max() < 58 and window_df['rsi'].min() > 42
        adx_low = window_df['adx'].mean() < 26
        touches = ((window_df['high'] >= window_high * 0.998).sum() + (window_df['low'] <= window_low * 1.002).sum())

        if range_ratio < 0.012:
            score += 1
        if rsi_range_ok:
            score += 1
        if adx_low:
            score += 1
        if touches >= 4:
            score += 1

        if score >= 3:
            if not in_box:
                in_box = True
                start_idx = df.index[i]
        else:
            if in_box:
                end_idx = df.index[i - 1]
                box_ranges.append({
                    "start": start_idx,
                    "end": end_idx,
                    "high": window_high,
                    "low": window_low
                })
                in_box = False

    return box_ranges


def detect_box_trade_signal(df, symbol):
    df = df.copy()
    df['close'] = df['close'].astype(float)
    df['rsi'] = compute_rsi(df['close'])
    df['adx'] = compute_adx(df)

    box_ranges = detect_box_ranges_v3(df)
    if not box_ranges:
        return None

    latest_box = box_ranges[-1]
    upper = latest_box['high']
    lower = latest_box['low']
    current_price = df['close'].iloc[-1]

    # 브레이크아웃 감지: 상단 돌파
    breakout_thresh = 0.002
    if current_price > upper * (1 + breakout_thresh):
        return (
            f"📦 박스권 브레이크아웃 감지 (/range)\n\n"
            f"🔹 {symbol} 박스권 상단 돌파\n"
            f"▶️ Signal: NONE\n\n"
            f"💵 현재가: ${current_price:.4f}\n"
            f"📈 상단:   ${upper:.4f}\n"
        )
    # 브레이크아웃 감지: 하단 돌파
    if current_price < lower * (1 - breakout_thresh):
        return (
            f"📦 박스권 브레이크아웃 감지 (/range)\n\n"
            f"🔹 {symbol} 박스권 하단 돌파\n"
            f"▶️ Signal: NONE\n\n"
            f"💵 현재가: ${current_price:.4f}\n"
            f"📉 하단:   ${lower:.4f}\n"
        )

    entry_message = None

    # 하단 접근: LONG 신호
    if abs(current_price - lower) / lower < breakout_thresh:
        signal = "LONG"
        tp = current_price + (current_price * 0.012)
        sl = current_price - (current_price * 0.018)
        entry_message = (
            f"📦 박스권 전략 감지 (/range)\n\n"
            f"🔹 {symbol} 박스권 하단 접근\n"
            f"▶️ Signal: {signal}\n\n"
            f"💵 현재가: ${current_price:.4f}\n"
            f"📈 상단:   ${upper:.4f}\n"
            f"📉 하단:   ${lower:.4f}\n\n"
            f"🎯 TP: ${tp:.4f}\n"
            f"🛑 SL: ${sl:.4f}"
        )
    # 상단 접근: SHORT 신호
    elif abs(current_price - upper) / upper < breakout_thresh:
        signal = "SHORT"
        tp = current_price - (current_price * 0.012)
        sl = current_price + (current_price * 0.018)
        entry_message = (
            f"📦 박스권 전략 감지 (/range)\n\n"
            f"🔹 {symbol} 박스권 상단 접근\n"
            f"▶️ Signal: {signal}\n\n"
            f"💵 현재가: ${current_price:.4f}\n"
            f"📈 상단:   ${upper:.4f}\n"
            f"📉 하단:   ${lower:.4f}\n\n"
            f"🎯 TP: ${tp:.4f}\n"
            f"🛑 SL: ${sl:.4f}"
        )

    return entry_message
