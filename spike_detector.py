import pandas_ta as ta
import numpy as np
from strategy import analyze_indicators


def detect_spike_conditions(df):
    messages = []
    score = 0

    bb = ta.bbands(df['close'], length=20)
    if bb is not None and 'BBU_20_2.0' in bb:
        bb_width = bb['BBU_20_2.0'] - bb['BBL_20_2.0']
        if len(bb_width) >= 21:
            prev_std = bb_width.iloc[-21:-1].mean()
            current_std = bb_width.iloc[-1]
            expansion = current_std / prev_std if prev_std > 0 else 0
            if expansion > 1.8:
                score += 1
                messages.append(f"\ud83d\udcce \ubcfc\ub9b0\uc800 \ubc94\ub4dc \ud655\uc7a5 \uac10\uc9c0 (\ud3ed \u2191 {expansion:.2f}\ubc30)")

    vol = df['volume']
    if len(vol) >= 21:
        avg_vol = vol.iloc[-21:-1].mean()
        current_vol = vol.iloc[-1]
        if current_vol > avg_vol * 2:
            score += 1
            messages.append(f"\ud83d\udcca \uac70\ub798\ub7c9 \uae09\uc99d (+{(current_vol / avg_vol):.2f}\ubc30)")

    macd = ta.macd(df['close'])
    if macd is not None and len(macd['MACDh_12_26_9'].dropna()) >= 2:
        hist = macd['MACDh_12_26_9'].dropna()
        if hist.iloc[-2] < 0 and hist.iloc[-1] > 0:
            score += 1
            messages.append("\ud83d\udcc9 MACD \ud788\uc2a4\ud1a0\uadf8\ub7a8 \ubc18\uc804 (\uc74c \u2192 \uc591)")

    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None and len(rsi.dropna()) >= 2:
        prev_rsi = rsi.iloc[-2]
        current_rsi = rsi.iloc[-1]
        if 45 <= prev_rsi <= 55 and current_rsi > 60:
            score += 1
            messages.append(f"\u26a1 RSI \uae09\ubc18\ub4dc ({prev_rsi:.1f} \u2192 {current_rsi:.1f})")

    if score >= 2:
        direction, strategy_score = analyze_indicators(df)
        current_price = df['close'].iloc[-1]

        if direction != 'NONE':
            entry_low = round(current_price * 0.995, 2)
            entry_high = round(current_price * 1.005, 2)
            stop_loss = round(current_price * 0.985, 2)
            take_profit = round(current_price * 1.015, 2)

            messages.append(f"\n\ud83d\udcca \uc804\ub825 \ubd84\uc11d \uacb0\uacfc\n\ud83d\udd35 \ubc29\ud5a5: {direction}\n\ud83d\udcb0 \uc9c4\uc785\uac00: ${entry_low} ~ ${entry_high}\n\ud83d\udea9 \uc190\uc808\uac00: ${stop_loss}\n\ud83c\udf1f \uc775\uc808\uac00: ${take_profit}")
        else:
            messages.append("\n\ud83d\udccc \uc804\ub825 \uc870\uac74: \u274c \ubb34\ucd95\ucda9 (\uad00\ub9dd \uad8c\uc7a5)")

        return messages

    return None


def detect_crash_conditions(df):
    messages = []
    score = 0

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
                messages.append(f"\ud83d\udccf \ubcfc\ub9b0\uc800 \ubc94\ub4dc \ud558\ub2e8 \uc774\ud0c8 + \ud655\uc7a5 (\u2193 {current_std / prev_std:.2f}\ubc30)")

    vol = df['volume']
    if len(vol) >= 21:
        avg_vol = vol.iloc[-21:-1].mean()
        current_vol = vol.iloc[-1]
        if current_vol > avg_vol * 2:
            score += 1
            messages.append(f"\ud83d\udcca \uac70\ub798\ub7c9 \uae09\uc99d (+{(current_vol / avg_vol):.2f}\ubc30)")

    macd = ta.macd(df['close'])
    if macd is not None and len(macd['MACDh_12_26_9'].dropna()) >= 2:
        hist = macd['MACDh_12_26_9'].dropna()
        if hist.iloc[-2] > 0 and hist.iloc[-1] < 0:
            score += 1
            messages.append("\ud83d\udcc9 MACD \ud788\uc2a4\ud1a0\uadf8\ub7a8 \ubc18\uc804 (\uc591 \u2192 \uc74c)")

    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None and len(rsi.dropna()) >= 2:
        prev_rsi = rsi.iloc[-2]
        current_rsi = rsi.iloc[-1]
        if 45 <= prev_rsi <= 55 and current_rsi < 40:
            score += 1
            messages.append(f"\u26a1 RSI \uae09\ud558\ub77d ({prev_rsi:.1f} \u2192 {current_rsi:.1f})")

    if score >= 2:
        direction, strategy_score = analyze_indicators(df)
        current_price = df['close'].iloc[-1]

        if direction != 'NONE':
            entry_low = round(current_price * 0.995, 2)
            entry_high = round(current_price * 1.005, 2)
            stop_loss = round(current_price * 0.985, 2)
            take_profit = round(current_price * 1.015, 2)

            messages.append(f"\n\ud83d\udcca \uc804\ub825 \ubd84\uc11d \uacb0\uacfc\n\ud83d\udd34 \ubc29\ud5a5: {direction}\n\ud83d\udcb0 \uc9c4\uc785\uac00: ${entry_low} ~ ${entry_high}\n\ud83d\udea9 \uc190\uc808\uac00: ${stop_loss}\n\ud83c\udf1f \uc775\uc808\uac00: ${take_profit}")
        else:
            messages.append("\n\ud83d\udccc \uc804\ub825 \uc870\uac74: \u274c \ubb34\ucd95\ucda9 (\uad00\ub9dd \uad8c\uc7a5)")

        return messages

    return None