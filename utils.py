# utils.py

import requests
import pandas as pd
from config import MEXC_API_KEY

# MEXC 현물 API 기반 OHLCV 가져오기
def fetch_ohlcv(symbol: str, interval: str, limit: int = 300):
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": symbol.lower(),   # 현물 API는 모두 소문자
        "interval": interval,
        "limit": limit
    }

    try:
        print(f"📡 MEXC 현물 요청 → {symbol} @ {interval}")
        response = requests.get(url, params=params, timeout=10)
        print(f"📡 응답: {response.status_code}, 내용: {response.text[:200]}")
        response.raise_for_status()

        raw = response.json()
        df = pd.DataFrame(raw, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "_close_time", "_quote_volume", "_trades", "_taker_base", "_taker_quote", "_ignore"
        ])

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

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
