import pandas as pd

def analyze_indicators_short(data_dict: dict):
    total_score = 0.0
    for tf, df in data_dict.items():
        close = df['close']
        volume = df['volume']

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi_score = 1.0 if rsi.iloc[-1] > 70 else (0.8 if rsi.iloc[-1] < rsi.iloc[-2] else 0.2)
        rsi_text = '과매수' if rsi.iloc[-1] > 70 else ('하락 중' if rsi.iloc[-1] < rsi.iloc[-2] else '상승 중')

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        macd_score = 1.5 if hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2] else (0.8 if hist.iloc[-1] < 0 else 0.4)
        macd_text = '하락 강화' if macd_score == 1.5 else ('약한 하락' if macd_score == 0.8 else '중립')

        # EMA
        ema_short = close.ewm(span=12).mean()
        ema_long = close.ewm(span=26).mean()
        slope = ema_short.diff()
        ema_score = 1.2 if ema_short.iloc[-1] < ema_long.iloc[-1] and slope.iloc[-1] < 0 else 0.3
        ema_text = '하락 추세' if ema_score > 1 else '중립 또는 상승'

        # Bollinger
        mid = close.rolling(window=20).mean()
        std = close.rolling(window=20).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        boll_score = 1.0 if close.iloc[-1] > upper.iloc[-1] else (0.5 if close.iloc[-1] < mid.iloc[-1] else 0.2)
        boll_text = '상단 돌파 후 되밀림' if boll_score == 1.0 else ('중심 이하' if boll_score == 0.5 else '중심 이상')

        # Volume
        avg = volume.rolling(window=20).mean()
        vol_score = 0.5 if volume.iloc[-1] < avg.iloc[-1] * 0.8 else (0.1 if volume.iloc[-1] > avg.iloc[-1] * 1.5 else 0.3)
        vol_text = '거래량 감소' if vol_score == 0.5 else ('거래량 급증' if vol_score == 0.1 else '보통')

        score = (
            rsi_score * 1.0 +
            macd_score * 1.5 +
            ema_score * 1.2 +
            boll_score * 0.8 +
            vol_score * 0.5
        )
        total_score += score

    final_score = round(total_score / len(data_dict), 2)
    action = '숏 진입 시그널' if final_score >= 2.1 else '보류'
    direction = 'short'

    return final_score, action, direction, {
        'RSI': rsi_text,
        'MACD': macd_text,
        'EMA': ema_text,
        'EMA_Slope': f"{slope.iloc[-1]:.5f}",
        'Bollinger': boll_text,
        'Volume': vol_text,
        'Trend_1h': 'N/A'
    }
