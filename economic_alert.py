import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from config import USER_IDS, API_URL
import pytz

# 전역 일정 저장소
all_schedules = []

def send_telegram(text):
    for uid in USER_IDS:
        try:
            requests.post(f"{API_URL}/sendMessage", data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
        except Exception as e:
            print(f"❌ 알림 전송 실패: {e}")

def fetch_forexfactory_schedule():
    from datetime import datetime, timedelta

    now = datetime.utcnow()

    return [
        {
            "datetime": now + timedelta(minutes=70),  # 약 1시간 후
            "title": "🇺🇸 FOMC Meeting Minutes 발표",
            "impact": "High"
        },
        {
            "datetime": now + timedelta(days=1),
            "title": "🇪🇺 유럽중앙은행(ECB) 금리결정",
            "impact": "High"
        },
        {
            "datetime": now + timedelta(days=3),
            "title": "🇨🇳 중국 GDP 발표",
            "impact": "Medium"
        }
    ]

def notify_schedule(event):
    local_dt = event['datetime'] + timedelta(hours=9)  # KST
    msg = f"📢 <b>경제 일정 알림</b>\n⏰ {local_dt.strftime('%m/%d %H:%M')} KST\n📝 {event['title']}"
    send_telegram(msg)

def get_this_week_schedule():
    return all_schedules

def get_this_month_schedule():
    now = datetime.utcnow()
    end = now + timedelta(days=31)
    return [
        e for e in all_schedules
        if now <= e['datetime'] <= end
    ]

def start_economic_schedule():
    global all_schedules
    print("📡 경제 일정 알림 기능 시작")

    def refresh_schedule():
        global all_schedules
        all_schedules = fetch_forexfactory_schedule()
        print(f"🔄 경제 일정 {len(all_schedules)}건 업데이트 완료")

    def check_upcoming():
        now = datetime.utcnow()
        for event in all_schedules:
            delta = (event['datetime'] - now).total_seconds()
            if 3540 <= delta <= 3660:  # 약 1시간 전
                notify_schedule(event)

    # 스케줄러 설정 (thread pool 안정화 포함)
    executors = {'default': ThreadPoolExecutor(5)}
    scheduler = BackgroundScheduler(executors=executors, timezone="UTC")

    refresh_schedule()
    scheduler.add_job(refresh_schedule, 'interval', hours=3)
    scheduler.add_job(check_upcoming, 'interval', minutes=1)
    scheduler.start()
