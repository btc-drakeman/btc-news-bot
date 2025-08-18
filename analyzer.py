import requests
import pandas as pd
from strategy import multi_frame_signal
from config import SYMBOLS, SL_PCT, TP_PCT, format_price
from notifier import send_telegram
from simulator import add_virtual_trade
from sl_hunt_monitor import check_sl_hunt_alert

FUTURES_BASE = "https://contract.mexc.com"

def _map_interval(iv: str) -> str:
    m = {"1m":"Min1", "5m":"Min5", "15m":"Min15", "30m":"Min30", "1h":"Min60"}
    return m.get(iv, "Min5")

def fetch_ohlcv(symbol: str, interval: str, limit: int = 150) -> pd.DataFrame:
    fsym = symbol.replace("USDT", "_USDT")
    kline_type = _map_interval(interval)
    r = requests.get(f"{FUTURES_BASE}/api/v1/contract/kline/{fsym}",
                     params={"type": kline_type, "limit": limit}, timeout=8)
    r.raise_for_status()
    raw = r.json()["data"]
    df = pd.DataFrame(raw, columns=[
        "ts","open","high","low","close","volume","turnover"
    ])
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("ts")
    return df

def analyze_multi_tf(symbol: str):
    df_30 = fetch_ohlcv(symbol, "30m", 150)
    df_15 = fetch_ohlcv(symbol, "15m", 150)
    df_5  = fetch_ohlcv(symbol, "5m",  150)

    signal = multi_frame_signal(df_30, df_15, df_5)
    if signal == (None, None):
        return None

    direction, detail = signal
    price = df_5["close"].iloc[-1]

    # 퍼센트 기반 TP/SL
    if direction == "LONG":
        sl = price * (1 - SL_PCT)
        tp = price * (1 + TP_PCT)
    else:
        sl = price * (1 + SL_PCT)
        tp = price * (1 - TP_PCT)

    # 시뮬 기록
    entry = {
        "symbol": symbol,
        "direction": direction,
        "entry": float(price),
        "tp": float(tp),
        "sl": float(sl),
        "score": 0
    }
    add_virtual_trade(entry)

    msg = (
        f"📊 멀티프레임: {symbol}\n"
        f"🧭 방향: {direction} ({detail})\n"
        f"💵 진입: ${format_price(price)}\n"
        f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
    )

    sl_alert = check_sl_hunt_alert(symbol)
    if sl_alert:
        msg += f"\n\n{sl_alert}"

    send_telegram(msg)
    return msg
