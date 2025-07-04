# utils.py

import requests
import pandas as pd
from config import MEXC_API_KEY

# MEXC 선물 OHLCV 가져오기 (interval: 1m, 5m, 15m, 1h)
def fetch_ohlcv(symbol: str, interval: str, limit: int = 300):
    url = "https://contract.mexc.com/api/v1/kline"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    if MEXC_API_KEY:
        headers["ApiKey"] = MEXC_API_KEY

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            return None

        df = pd.DataFrame(data)
        df.columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        print(f"❌ OHLCV 요청 실패 [{symbol} {interval}]: {e}")
        return None

# 4개 타임프레임 모두 가져오기
def fetch_ohlcv_all_timeframes(symbol: str):
    intervals = ['1m', '5m', '15m', '1h']
    result = {}
    for interval in intervals:
        df = fetch_ohlcv(symbol, interval)
        if df is not None and not df.empty:
            result[interval] = df
    return result
