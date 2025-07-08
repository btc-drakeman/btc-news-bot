import requests
import pandas as pd
import pandas_ta as ta
from tracker import entry_price_dict, peak_price_dict

# ✅ MEXC 현물 API 기반 OHLCV 가져오기 (기존 분석용)
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
        if not raw:
            print(f"⚠️ 응답 데이터 없음: {symbol} @ {interval}")
            return None

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

# ✅ 실시간 분석용 (1m, 5m, 15m, 30m)
def fetch_ohlcv_all_timeframes(symbol: str):
    intervals = ['1m', '5m', '15m', '30m']
    result = {}
    for interval in intervals:
        try:
            df = fetch_ohlcv(symbol, interval)
            if df is not None and not df.empty:
                result[interval] = df
        except Exception as e:
            print(f"❌ [fetch_ohlcv_all_timeframes] {symbol}-{interval} 실패: {e}")
    return result

# ✅ 백테스트 전용 15분봉 최근 7일치 (672개)
def fetch_recent_ohlcv(symbol: str, interval: str = '15m', limit: int = 672):
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    try:
        print(f"📊 백테스트용 OHLCV 요청 → {symbol} @ {interval} ({limit}개)")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        raw = response.json()
        if not raw:
            print(f"⚠️ 백테스트용 응답 없음: {symbol} {interval}")
            return None

        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "_1", "_2"
        ])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    except Exception as e:
        print(f"❌ [fetch_recent_ohlcv] 실패: {e}")
        return None

# ✅ 실시간 가격 획득 (1m 보조)
def get_current_price(symbol: str):
    try:
        url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if not data or len(data[0]) < 5:
            print(f"⚠️ [get_current_price] 응답 이상: {data}")
            return None
        close_price = float(data[0][4])
        return close_price
    except Exception as e:
        print(f"❌ [get_current_price] 오류: {e}")
        return None

# --- 아래는 기존 추세 분석 함수들 (생략 없이 유지됨) ---

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

# ✅ 3봉 추세 일관성 체크 (모두 같은 방향인지)
def check_trend_consistency(trend_list: list):
    if not trend_list or len(trend_list) < 3:
        return False
    return len(set(trend_list)) == 1 and trend_list[0] in ["bull", "bear"]

# ✅ 다중 타임프레임 추세 일치 확인
def check_multi_timeframe_alignment(trend_15m: list, trend_1h: list):
    if not trend_15m or not trend_1h:
        return False
    return (
        len(set(trend_15m)) == 1 and
        len(set(trend_1h)) == 1 and
        trend_15m[0] == trend_1h[0] and
        trend_15m[0] in ["bull", "bear"]
    )

# ✅ 고점(저항선) 돌파 여부 판단
def check_resistance_breakout(df: pd.DataFrame, lookback: int = 20):
    if len(df) < lookback + 1:
        return False, None
    recent_high = df['high'].iloc[-(lookback+1):-1].max()
    current_price = df['close'].iloc[-1]
    breakout = current_price > recent_high
    return breakout, recent_high

# ✅ 캔들 패턴 분석 함수
def detect_candle_pattern(df: pd.DataFrame):
    if len(df) < 2:
        return "N/A"
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    range_total = last['high'] - last['low']
    if range_total == 0:
        return "N/A"
    body_ratio = body / range_total
    if body_ratio > 0.75:
        return "📈 장대 양봉" if last['close'] > last['open'] else "📉 장대 음봉"
    elif body_ratio < 0.2:
        return "🕯️ 도지형"
    else:
        return "보통 캔들"
