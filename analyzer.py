import requests
timeout=8
)
r.raise_for_status()
raw = r.json().get("data", [])
if raw:
df = pd.DataFrame(raw, columns=[
"ts","open","high","low","close","volume","turnover"
])
for col in ["open","high","low","close","volume"]:
df[col] = df[col].astype(float)
df["ts"] = pd.to_datetime(df["ts"], unit="ms")
return df.set_index("ts")
last_err = "empty-data"
except Exception as e:
last_err = str(e)
time.sleep(0.2)


raise ValueError(f"{symbol} 선물 K라인 데이터 없음 (interval={kline_interval}, err={last_err})")


def analyze_multi_tf(symbol: str):
print(f"🔍 멀티프레임 전략 분석 시작: {symbol}", flush=True)
t0 = time.perf_counter()
df_30 = fetch_ohlcv(symbol, "30m", 150)
df_15 = fetch_ohlcv(symbol, "15m", 150)
df_5 = fetch_ohlcv(symbol, "5m", 150)
print(f"⏱️ 데이터 수집 {symbol}: {time.perf_counter()-t0:.2f}s", flush=True)


t1 = time.perf_counter()
signal = multi_frame_signal(df_30, df_15, df_5)
print(f"⏱️ 시그널 계산 {symbol}: {time.perf_counter()-t1:.2f}s", flush=True)


if signal == (None, None):
print(f"📭 {symbol} 전략 신호 없음", flush=True)
print(f"✅ {symbol} 전략 분석 완료", flush=True)
return None


direction, detail = signal
price = df_5["close"].iloc[-1]


if direction == "LONG":
sl = price * (1 - SL_PCT)
tp = price * (1 + TP_PCT)
else:
sl = price * (1 + SL_PCT)
tp = price * (1 - TP_PCT)


entry = {
"symbol": symbol, "direction": direction, "entry": float(price),
"tp": float(tp), "sl": float(sl), "score": 0
}
add_virtual_trade(entry)


# detail 안에 p/raw/조건 요약 포함됨
msg = (
f"📊 멀티프레임: {symbol}\n"
f"🧭 방향: {direction} ({detail})\n"
f"💵 진입: ${format_price(price)}\n"
f"🛑 SL: ${format_price(sl)} | 🎯 TP: ${format_price(tp)}"
)
send_telegram(msg)
print(f"✅ {symbol} 전략 분석 완료", flush=True)
return msg