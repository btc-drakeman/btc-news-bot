# utils.py

import requests
import pandas as pd
from config import MEXC_API_KEY

# MEXC 선물 OHLCV 가져오기
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
        print(f"📡 MEXC 요청 → {symbol} @ {interval}")
        print(f"📡 요청 URL: {url}, params: {params}")
        response = requests.get(url, params=params, headers=headers, timeout=10)
        print(f"📡 응답: {response.status_code}, 내용: {response.text[:200]}")  # 응답 앞부분만 출력

        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            print(f"⚠️ 받은 데이터 없음: {symbol} ({interval})")
            return None

        df = pd.DataFrame(data)
        df.columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
          import traceback
          print(f"❌ OHLCV 요청 실패 [{symbol} {interval}]: {e}")
          traceback.print_exc()  # ✅ 전체 에러 스택 출력
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
