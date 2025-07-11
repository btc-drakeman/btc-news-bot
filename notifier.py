import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

def send_telegram(text):
    chat_ids = TELEGRAM_CHAT_ID if isinstance(TELEGRAM_CHAT_ID, list) else [TELEGRAM_CHAT_ID]
    for uid in chat_ids:
        try:
            res = requests.post(API_URL, data={
                'chat_id': uid,
                'text': text
            })
            print(f"✅ 메시지 전송 성공 → {uid}")
        except Exception as e:
            print(f"❌ 메시지 전송 실패: {e}")
