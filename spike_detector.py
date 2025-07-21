import time
import pandas_ta as ta
from analyzer import fetch_market_data
from notifier import send_telegram
from config import SYMBOLS


def detect_spike_conditions(df):
    """
    가격 급등/급락 관련 기술적 지표를 분석하여
    2개 이상의 신호가 감지되면 메시지 목록을 반환합니다.
    """
    messages = []
    score = 0

    # 볼린저 밴드 폭 확장
    bb = ta.bbands(df['close'], length=20)
    if bb is not None and 'BBU_20_2.0' in bb:
        width = bb['BBU_20_2.0'] - bb['BBL_20_2.0']
        if len(width) >= 21:
            prev = width.iloc[-21:-1].mean()
            curr = width.iloc[-1]
            if prev > 0 and curr > prev * 1.8:
                score += 1
                messages.append(f"🌀 볼린저 밴드 폭 확장 ({prev:.2f}→{curr:.2f})")

    # 거래량 급증
    vol = df['volume']
    if len(vol) >= 21:
        prev_vol = vol.iloc[-21:-1].mean()
        curr_vol = vol.iloc[-1]
        if prev_vol > 0 and curr_vol > prev_vol * 2:
            score += 1
            messages.append(f"📈 거래량 급증 ({prev_vol:.2f}→{curr_vol:.2f})")

    # MACD 히스토그램 전환
    macd = ta.macd(df['close'])
    if macd is not None and 'MACDh_12_26_9' in macd:
        hist = macd['MACDh_12_26_9'].dropna()
        if len(hist) >= 2:
            if hist.iloc[-2] < 0 and hist.iloc[-1] > 0:
                score += 1
                messages.append(f"📊 MACD 히스토그램 반전 ({hist.iloc[-2]:.2f}→{hist.iloc[-1]:.2f})")

    # RSI 급반등/급하락
    rsi = ta.rsi(df['close'], length=14)
    if rsi is not None:
        rsi_clean = rsi.dropna()
        if len(rsi_clean) >= 2:
            prev_rsi, curr_rsi = rsi_clean.iloc[-2], rsi_clean.iloc[-1]
            # 급등
            if 45 <= prev_rsi <= 55 and curr_rsi > 60:
                score += 1
                messages.append(f"⚡ RSI 급반등 ({prev_rsi:.1f}→{curr_rsi:.1f})")
            # 급락
            if 45 <= prev_rsi <= 55 and curr_rsi < 40:
                score += 1
                messages.append(f"⚡ RSI 급하락 ({prev_rsi:.1f}→{curr_rsi:.1f})")

    return messages if score >= 2 else None


def spike_loop():
    """
    지속적으로 스파이크 조건을 체크하고,
    조건 충족 시 ATR 기반 TP/SL을 포함한 알림 전송
    """
    while True:
        for symbol in SYMBOLS:
            df = fetch_market_data(symbol)
            if df is None or df.empty:
                continue
            spike_msgs = detect_spike_conditions(df)
            if spike_msgs:
                entry = df['close'].iloc[-1]
                atr   = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
                tp    = entry + atr * 1.5
                sl    = entry - atr * 1.0

                # 메시지 조합
                alert = [f"🚀 {symbol} 스파이크 신호 감지"]
                alert.append(f"💡 진입가: {entry:.4f}")
                alert.append(f"🎯 TP: {tp:.4f} (+1.5×ATR)")
                alert.append(f"🛑 SL: {sl:.4f} (−1.0×ATR)")
                alert.extend(spike_msgs)

                send_telegram("\n".join(alert))
        time.sleep(1)
