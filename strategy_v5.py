import pandas as pd

def analyze_rsi(df: pd.DataFrame):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_macd(df: pd.DataFrame):
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return hist

def run_strategy_v5(df: pd.DataFrame):
    rsi = analyze_rsi(df)
    macd_hist = analyze_macd(df)

    score = 0
    entry_signal = False

    # 최근 지표 기반 판단
    if rsi.iloc[-1] > 50:
        score += 1
    if macd_hist.iloc[-1] > 0:
        score += 1
    if rsi.iloc[-1] > rsi.iloc[-2]:
        score += 0.5

    if score >= 2.5:
        entry_signal = True

    return entry_signal, rsi.iloc[-1], macd_hist.iloc[-1]

def simulate_exit(df: pd.DataFrame, entry_price: float, entry_index: int, max_hold: int = 12):
    rsi = analyze_rsi(df)
    exit_reason = '보유만료'
    tp_pct = 0.02
    sl_pct = 0.018
    peak_ret = -999

    for j in range(1, max_hold + 1):
        if entry_index + j >= len(df):
            break
        cur = df.iloc[entry_index + j]
        ret = (cur['close'] - entry_price) / entry_price
        peak_ret = max(peak_ret, ret)

        # RSI 따라 목표가 조정
        if rsi.iloc[entry_index + j] > 55 and rsi.iloc[entry_index + j] > rsi.iloc[entry_index + j - 1]:
            tp_pct += 0.002
        if rsi.iloc[entry_index + j] < rsi.iloc[entry_index + j - 1] and ret >= 0.005:
            exit_reason = f"RSI하락 트레일링익절 ({ret*100:.2f}%)"
            return cur['close'], ret * 20, exit_reason, j
        if ret >= tp_pct:
            exit_reason = f"익절 +{tp_pct*100:.2f}%"
            return cur['close'], ret * 20, exit_reason, j
        if ret <= -sl_pct:
            exit_reason = f"손절 -{sl_pct*100:.2f}%"
            return cur['close'], ret * 20, exit_reason, j

    # 보유만료 시
    final_close = df.iloc[min(entry_index + max_hold, len(df)-1)]['close']
    ret = (final_close - entry_price) / entry_price
    return final_close, ret * 20, exit_reason, max_hold
