import requests
import pandas as pd

# MEXC 현물 API 기반 OHLCV 가져오기
def fetch_ohlcv(symbol: str, interval: str, limit: int = 300):
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }

    try:
        print(f"📡 MEXC 현물 요청 → {symbol} @ {interval}")
        response = requests.get(url, params=params, timeout=10)
        print(f"📡 응답: {response.status_code}, 내용: {response.text[:200]}")
        response.raise_for_status()

        raw = response.json()

        # 현물 데이터는 8개 컬럼만 존재함
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
