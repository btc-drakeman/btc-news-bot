import pandas as pd
import numpy as np

def should_enter_v6(i: int, df: pd.DataFrame) -> tuple[bool, float]:
    window = df.iloc[i - 50:i + 1].copy()
    close = window["close"]
    volume = window["volume"]

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_score = 1.0 if rsi.iloc[-1] < 30 else (0.8 if rsi.iloc[-1] < rsi.iloc[-2] else 0.2)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    macd_score = 1.5 if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2] else (0.8 if hist.iloc[-1] > 0 else 0.2)

    # EMA
    ema_short = close.ewm(span=12).mean()
    ema_long = close.ewm(span=26).mean()
    ema_slope = ema_short.diff()
    ema_score = 1.2 if ema_short.iloc[-1] > ema_long.iloc[-1] and ema_slope.iloc[-1] > 0 else 0.3

    # Bollinger
    mid = close.rolling(window=20).mean()
    std = close.rolling(window=20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    boll_score = 1.0 if close.iloc[-1] < lower.iloc[-1] else (0.5 if close.iloc[-1] < mid.iloc[-1] else 0.2)

    # Volume
    avg_vol = volume.rolling(window=20).mean()
    vol_score = 0.5 if volume.iloc[-1] > avg_vol.iloc[-1] * 1.5 else (0.3 if volume.iloc[-1] > avg_vol.iloc[-1] else 0.1)

    score = round(
        rsi_score * 1.0 +
        macd_score * 1.5 +
        ema_score * 1.2 +
        boll_score * 0.8 +
        vol_score * 0.5, 2
    )

    return score >= 2.1, score

def run_backtest(df: pd.DataFrame, symbol: str = "BTCUSDT"):
    leverage = 20
    results = []

    for i in range(50, len(df) - 12):
        should_enter, score = should_enter_v6(i, df)
        if not should_enter:
            continue

        entry = df["close"].iloc[i]
        sl = entry * 0.982
        tp = entry * 1.02

        exit_price = entry
        exit_type = "보유종료"

        for j in range(1, 13):
            price = df["close"].iloc[i + j]
            # RSI 트레일링 감지
            window = df.iloc[i + j - 14:i + j + 1]
            delta = window['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            if rsi.dropna().shape[0] >= 2 and rsi.iloc[-1] < rsi.iloc[-2]:
                exit_price = price
                exit_type = "반전종료"
                break
            if price >= tp:
                exit_price = price
                exit_type = "익절"
                break
            if price <= sl:
                exit_price = price
                exit_type = "손절"
                break
        hold_bars = j
        profit = (exit_price - entry) / entry * 100 * leverage

        results.append({
            "symbol": symbol,
            "time": df.index[i],
            "score": score,
            "entry": entry,
            "exit": exit_price,
            "exit_type": exit_type,
            "hold_bars": hold_bars,
            "profit_%": profit
        })

    return pd.DataFrame(results)

def predict_from_condition(results_df: pd.DataFrame, score_threshold: float = 2.1):
    matched = results_df[results_df['score'] >= score_threshold]
    if matched.empty:
        return 0.0, 0.0, 0.0, 0.0

    avg_return = matched['profit_%'].mean()
    tp_ratio = len(matched[matched['exit_type'] == '익절']) / len(matched)
    sl_ratio = len(matched[matched['exit_type'] == '손절']) / len(matched)
    avg_bars = matched['hold_bars'].mean()
    return avg_return, tp_ratio, sl_ratio, avg_bars
