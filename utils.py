import requests
import pandas as pd
import pandas_ta as ta

# MEXC 현물 API 기반 OHLCV 가져오기
def fetch_ohlcv(symbol: str, interval: str, limit: int = 300):
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    try:
        print(f"📱 MEXC 현무 요청 → {symbol} @ {interval}")
        response = requests.get(url, params=params, timeout=10)
        print(f"📱 응답: {response.status_code}, 내용: {response.text[:200]}")
        response.raise_for_status()

        raw = response.json()

        # 현무 데이터는 8개 컬럼만 존재함
        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "_1", "_2"
        ])

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    except Exception as e:
        print(f"❌ OHLCV 요청 실패 [{symbol} {interval}]: {e}")
        return None


# 4개 타임프레임 모두 가져오기 (1h → 30m 변경)
def fetch_ohlcv_all_timeframes(symbol: str):
    intervals = ['1m', '5m', '15m', '30m']  # 1h 제거, 30m 사용
    result = {}
    for interval in intervals:
        df = fetch_ohlcv(symbol, interval)
        if df is not None and not df.empty:
            result[interval] = df
    return result


# 실시간 가격 획득 (1m 보조)
def get_current_price(symbol: str):
    try:
        url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        close_price = float(data[0][4])  # 종가
        return close_price
    except Exception as e:
        print(f"[get_current_price] 오류: {e}")
        return None


# ✅ RSI 추세 판별 함수
def get_rsi_trend(df: pd.DataFrame, period: int = 14, length: int = 3):
    rsi = ta.rsi(df['close'], length=period)
    if rsi is None or len(rsi.dropna()) < length:
        return None

    trend = []
    for val in rsi.dropna()[-length:]:
        if val > 55:
            trend.append("bull")
        elif val < 45:
            trend.append("bear")
        else:
            trend.append("neutral")
    return trend


# ✅ MACD 추세 판별 함수
def get_macd_trend(df: pd.DataFrame, length: int = 3):
    macd = ta.macd(df['close'])
    if macd is None or macd.shape[0] < length:
        return None

    hist = macd['MACDh_12_26_9'].dropna()
    if len(hist) < length:
        return None

    trend = []
    for val in hist[-length:]:
        if val > 0:
            trend.append("bull")
        elif val < 0:
            trend.append("bear")
        else:
            trend.append("neutral")
    return trend


# ✅ EMA 추세 판별 함수
def get_ema_trend(df: pd.DataFrame, short=12, long=26, length: int = 3):
    ema_short = ta.ema(df['close'], length=short)
    ema_long = ta.ema(df['close'], length=long)

    if ema_short is None or ema_long is None:
        return None

    trend = []
    for s, l in zip(ema_short[-length:], ema_long[-length:]):
        if s > l:
            trend.append("bull")
        elif s < l:
            trend.append("bear")
        else:
            trend.append("neutral")
    return trend
