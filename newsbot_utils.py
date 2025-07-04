# ✅ newsbot_utils.py (최신 버전 — 현물 분석 + 레버리지별 손익폭 안내)
import requests
import pandas as pd
from datetime import datetime

from config import API_URL, USER_IDS

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ETHFIUSDT"]

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            resp = requests.post(f"{API_URL}/sendMessage", data={
                "chat_id": uid,
                "text": text,
                "parse_mode": "HTML"
            })
            print(f"✅ 메시지 전송됨 → {uid}, 상태코드: {resp.status_code}")
        except Exception as e:
            print(f"❌ 텔레그램 전송 오류: {e}")

def fetch_ohlcv_spot(symbol, interval="15m", limit=100):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    print(f"📡 요청 URL: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_base_volume", "taker_quote_volume", "ignore"])
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df.set_index("time", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        print(f"❌ OHLCV 가져오기 실패: {e}")
        return None

def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    df = fetch_ohlcv_spot(symbol)
    if df is None or len(df) < 50:
        print("⚠️ 분석 결과 없음 (데이터 부족)")
        return None

    close = df["close"]
    volume = df["volume"]

    rsi = compute_rsi(close)
    macd_val, macd_signal = compute_macd(close)
    ema_fast = df["close"].ewm(span=12).mean()
    ema_slow = df["close"].ewm(span=26).mean()

    score = 0
    explanation = []

    if rsi[-1] > 70:
        explanation.append("📉 RSI: 과매수 (하락 우세)")
    elif rsi[-1] < 30:
        explanation.append("📈 RSI: 과매도 (상승 가능)")
        score += 1
    else:
        explanation.append("📊 RSI: 중립")

    if macd_val[-1] > macd_signal[-1]:
        explanation.append("📈 MACD: 골든크로스 (상승 신호)")
        score += 1
    else:
        explanation.append("📉 MACD: 데드크로스 (하락 신호)")

    if ema_fast[-1] > ema_slow[-1]:
        explanation.append("📐 EMA: 단기 상승 흐름")
        score += 1
    else:
        explanation.append("📐 EMA: 단기 하락 흐름")

    price_now = close.iloc[-1]

    tp_list = [round(price_now * (1 + 0.01 * lev), 2) for lev in [10, 20, 30, 50]]
    sl_list = [round(price_now * (1 - 0.005 * lev), 2) for lev in [10, 20, 30, 50]]

    price_block = "💸 <b>현물 기준 참고 손익폭</b>\n"
    price_block += "\n".join([
        f"🔹 {lev}x → 익절: ${tp:,} / 손절: ${sl:,}" for lev, tp, sl in zip([10, 20, 30, 50], tp_list, sl_list)
    ])

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    result = f"""
📊 <b>{symbol} 기술분석 (현물 기준)</b>
🕒 {now} UTC

{chr(10).join(explanation)}

{price_block}
"""
    print("📨 텔레그램 전송 메시지:", result)
    return result

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def compute_macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal
