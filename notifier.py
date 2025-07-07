# notifier.py

import requests
from config import API_URL, USER_IDS

def send_telegram(message: str, chat_id: str = None):
    targets = [chat_id] if chat_id else USER_IDS
    for uid in targets:
        try:
            response = requests.post(f"{API_URL}/sendMessage", data={
                'chat_id': uid,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True  # 🔕 메시지 깔끔하게 전송
            })
            if response.status_code == 200:
                print(f"✅ 메시지 전송 성공 → {uid}")
            else:
                print(f"❌ 전송 실패 [{uid}] → {response.text}")
        except Exception as e:
            print(f"📛 텔레그램 오류: {e}")
