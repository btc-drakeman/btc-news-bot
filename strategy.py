import pandas as pd

def analyze_rsi(df: pd.DataFrame):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    latest = rsi.iloc[-1]
    if latest > 70:
        return '과매수', 0.5
    elif latest < 30:
        return '과매도', 1.0
    elif latest > rsi.iloc[-2]:
        return '상승 중', 0.8
    else:
        return '하락 중', 0.2

def analyze_macd(df: pd.DataFrame):
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
        return '상승 강화', 1.5
    elif hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2]:
        return '하락 강화', 0.2
    else:
        return '중립', 0.7

def analyze_ema_slope(df: pd.DataFrame):
    ema20 = df['close'].ewm(span=20).mean()
    slope = ema20.diff()
    diff = ema20 - df['close']
    score = 1.2 if slope.iloc[-1] > 0 and diff.iloc[-1] < 0 else 0.3
    status = '상승 돌파' if score > 1 else '하락 또는 접근 중'
    return status, score

def analyze_bollinger(df: pd.DataFrame):
    mid = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    close = df['close'].iloc[-1]

    if close > upper.iloc[-1]:
        return '상단 돌파', 0.8
    elif close < lower.iloc[-1]:
        return '하단 돌파', 0.9
    elif close > mid.iloc[-1]:
        return '중심 이상', 0.6
    else:
        return '중심 이하', 0.3

def analyze_volume(df: pd.DataFrame):
    avg = df['volume'].rolling(window=20).mean()
    vol = df['volume'].iloc[-1]
    if vol > avg.iloc[-1] * 1.5:
        return '강한 거래량', 0.5
    elif vol > avg.iloc[-1]:
        return '보통 이상', 0.3
    else:
        return '약함', 0.1

def analyze_indicators(data_dict: dict):
    total_score = 0.0
    logs = []
    indicators_result = {}

    for tf, df in data_dict.items():
        rsi_text, rsi_score = analyze_rsi(df)
        macd_text, macd_score = analyze_macd(df)
        ema_text, ema_score = analyze_ema_slope(df)
        boll_text, boll_score = analyze_bollinger(df)
        vol_text, vol_score = analyze_volume(df)

        if tf == '1m':
            indicators_result = {
                'RSI': rsi_text,
                'MACD': macd_text,
                'EMA': ema_text,
                'EMA_Slope': f"{df['close'].ewm(span=20).mean().diff().iloc[-1]:.5f}",
                'Bollinger': boll_text,
                'Volume': vol_text,
                'Trend_1h': '분석 예정'
            }

        score = (
            rsi_score * 1.0 +
            macd_score * 1.5 +
            ema_score * 1.2 +
            boll_score * 0.8 +
            vol_score * 0.5
        )
        logs.append((tf, score))
        total_score += score

    final_score = round(total_score / len(data_dict), 2)

    if final_score >= 3.0:
        action = '롱 진입 시그널'
        direction = 'long'
    else:
        action = '숏 진입 시그널'
        direction = 'short'

    return final_score, action, direction, indicators_result
