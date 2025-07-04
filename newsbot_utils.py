# ✅ newsbot_utils.py (현물+선물 분리 구조 반영)
import requests
import pandas as pd
from config import MEXC_API_KEY, BOT_TOKEN, USER_IDS, API_URL

SYMBOLS = ['BTC_USDT', 'ETH_USDT', 'XRP_USDT', 'ETHFI_USDT']

def send_telegram(text, chat_id=None):
    print(f"📤 메시지 전송 시도: {text[:30]}...")
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            response = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"✅ 메시지 전송됨 → {uid}, 상태코드: {response.status_code}")
            if response.status_code != 200:
                print(f"📛 응답 내용: {response.text}")
        except Exception as e:
            print(f"❌ 텔레그램 오류: {e}")

# ✅ 현물 데이터 (안정적인 분석용)
def fetch_spot_ohlcv(symbol, interval='15m'):
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": symbol.replace('_', ''),  # BTC_USDT → BTCUSDT
        "interval": interval,
        "limit": 300
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        raw = response.json()
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume", "_", "_", "_", "_", "_", "_"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"❌ 현물 OHLCV 실패 ({symbol}): {e}")
        return None

# ✅ 선물 가격 조회 (/buy용)
def fetch_futures_price(symbol):
    url = "https://contract.mexc.com/api/v1/kline"
    params = {"symbol": symbol, "interval": "1m", "limit": 1}
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json().get("data", [])
        if not data:
            return None
        close_price = float(data[-1][4])  # 종가
        return close_price
    except Exception as e:
        print(f"❌ 선물 가격 조회 실패 ({symbol}): {e}")
        return None
