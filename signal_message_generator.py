from datetime import datetime

def generate_signal_message(symbol: str, entry_price: float, score: float, direction: str,
                             expected_return: float, tp_ratio: float, sl_ratio: float, avg_bars: float) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    if direction == 'long':
        emoji = "\ud83d\udcc8"
        label = "롱 진입 시그널 감지"
        sl_price = entry_price * 0.985
        tp_price = entry_price * 1.012
        entry_low = entry_price * 0.998
        entry_high = entry_price * 1.002
    else:
        emoji = "\ud83d\udd47"
        label = "숏 진입 시그널 감지"
        sl_price = entry_price * 1.015
        tp_price = entry_price * 0.988
        entry_low = entry_price * 0.998
        entry_high = entry_price * 1.002

    msg = f"""
{emoji} {symbol.upper()} {label}
\ud83d\udd52 {now_str}
\ud83d\udcb0 현재가: ${entry_price:,.2f}
\ud83d\udcca 전략 점수: {score:.2f} / 5.0

\ud83d\udccc 과거 유사 조건 수익 예측
\ud83d\udcc8 평균 수익률: {expected_return:+.2f}%
\u2705 익절 확률: {tp_ratio:.0%}
\u274c 손절 확률: {sl_ratio:.0%}
\ud83d\udd52 평균 보유 시간: {avg_bars:.1f}봉

\ud83c\udf1f 진입가: ${entry_low:.2f} ~ ${entry_high:.2f}
\ud83d\uded1 손절가: ${sl_price:.2f}
\ud83d\udfe2 익절가: ${tp_price:.2f}
"""
    return msg.strip()
