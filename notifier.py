import requests
from config import BOT_TOKEN, USER_IDS

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def send_telegram(text):
    for uid in USER_IDS:
        try:
            res = requests.post(API_URL, data={
                'chat_id': uid,
                'text': text
            })
            print(f"✅ 메시지 전송 성공 → {uid}")
        except Exception as e:
            print(f"❌ 메시지 전송 실패: {e}")
