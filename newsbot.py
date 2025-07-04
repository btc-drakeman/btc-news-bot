import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime
from config import BOT_TOKEN, USER_IDS
from newsbot_core import analysis_loop

API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'
app = Flask(__name__)

def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"✅ 메시지 전송됨 → {uid}")
        except Exception as e:
            print(f"❌ 메시지 전송 실패 ({uid}): {e}")

@app.route('/')
def index():
    return "Bot is running."

if __name__ == '__main__':
    print("📡 기술분석 봇 실행 시작")
    t = Thread(target=analysis_loop)
    t.start()
    app.run(host='0.0.0.0', port=8080)