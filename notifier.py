import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

def send_telegram(text):
    chat_ids = TELEGRAM_CHAT_ID if isinstance(TELEGRAM_CHAT_ID, list) else [TELEGRAM_CHAT_ID]
    for uid in chat_ids:
        try:
            print(f"📤 텔레그램 메시지 전송 시도 → {uid}")
            print(f"📨 메시지 내용:\n{text}\n")  # ✅ 메시지 본문 출력

            res = requests.post(API_URL, data={
                'chat_id': uid,
                'text': text
            })

            if res.status_code == 200:
                print(f"✅ 메시지 전송 성공 → {uid}")
            else:
                print(f"⚠️ 전송 실패 → {uid}, 상태코드: {res.status_code}, 응답: {res.text}")

        except Exception as e:
            print(f"❌ 메시지 전송 실패: {e}")
