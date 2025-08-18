from analyzer import fetch_ohlcv, format_price  # format_price는 config로 옮겼다면 거기서 import 해도 됨
import pandas as pd

def check_sl_hunt_alert(symbol: str) -> str | None:
    try:
        df = fetch_ohlcv(symbol, "5m", 60)
        curr = df.iloc[-1]
        prev20 = df.iloc[-21:-1]

        high_max = prev20["high"].max()
        low_min  = prev20["low"].min()

        broke_high = curr["high"] > high_max
        broke_low  = curr["low"]  < low_min

        body_top = max(curr["close"], curr["open"])
        body_bot = min(curr["close"], curr["open"])
        upper_wick = curr["high"] - body_top
        lower_wick = body_bot - curr["low"]

        if broke_high and upper_wick > (curr["high"] - curr["low"]) * 0.4:
            ratio = upper_wick / max(curr["high"]-curr["low"], 1e-9)
            return f"⚠️ SL 헌팅 의심(상단 꼬리)\n고점 갱신 후 급반전, 상단 꼬리 비율: {ratio:.2f}"
        if broke_low and lower_wick > (curr["high"] - curr["low"]) * 0.4:
            ratio = lower_wick / max(curr["high"]-curr["low"], 1e-9)
            return f"⚠️ SL 헌팅 의심(하단 꼬리)\n저점 갱신 후 급반등, 하단 꼬리 비율: {ratio:.2f}"
        return None
    except Exception:
        return None
