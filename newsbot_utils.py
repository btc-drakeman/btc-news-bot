# ✅ newsbot_utils.py (공통 함수 분리)
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

def fetch_ohlcv(symbol, interval):
    url = "https://contract.mexc.com/api/v1/kline"
    params = {"symbol": symbol, "interval": interval, "limit": 300}
    headers = {"ApiKey": MEXC_API_KEY, "User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        raw = response.json().get("data", [])
        df = pd.DataFrame(raw)
        if df.empty:
            return None
        df.columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"❌ {symbol} ({interval}) MEXC 선물 데이터 요청 실패: {e}")
        return None
