import feedparser
import time
from datetime import datetime, timedelta
from threading import Thread
from apscheduler.schedulers.background import BackgroundScheduler

from config import USER_IDS, API_URL
import requests

# 전역 변수로 일정 저장
all_schedules = []

def fetch_forexfactory_schedule():
    url = "https://n.news.naver.com/rss/economy"
    d = feedparser.parse(url)
    result = []
    for entry in d.entries:
        # 가상의 예시 일정 구조
        result.append({
            'title': entry.title,
            'datetime': datetime(*entry.published_parsed[:6])
        })
    return result

def get_this_week_schedule():
    now = datetime.utcnow()
    end = now + timedelta(days=7)
    return [e for e in all_schedules if now <= e['datetime'] <= end]

def get_this_month_schedule():
    now = datetime.utcnow()
    start = datetime(now.year, now.month, 1)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1)
    else:
        end = datetime(now.year, now.month + 1, 1)
    return [e for e in all_schedules if start <= e['datetime'] < end]

def send_telegram(text):
    for uid in USER_IDS:
        try:
            requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
        except Exception as e:
            print(f"❌ 일정 전송 오류: {e}")

def notify_schedule(event):
    kst_time = event['datetime'] + timedelta(hours=9)
    msg = f"""⏰ <b>1시간 후 예정된 경제 이벤트</b>

📌 {event['title']}
🕒 {kst_time.strftime('%Y-%m-%d %H:%M')} (KST)

⚠️ 시장 변동성 주의"""
    send_telegram(msg)

def handle_event_command():
    msg = "<b>📅 이번 달 경제 일정</b>\n\n"
    schedules = get_this_month_schedule()
    if not schedules:
        return "이번 달 예정된 경제 일정이 없습니다."

    schedules.sort(key=lambda x: x['datetime'])
    for e in schedules:
        kst_time = e['datetime'] + timedelta(hours=9)
        msg += f"📌 {e['title']} - {kst_time.strftime('%m/%d %H:%M')}\n"
    return msg

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

    refresh_schedule()
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_schedule, 'interval', hours=3)
    scheduler.add_job(check_upcoming, 'interval', minutes=1)
    scheduler.start()

# 이 파일이 단독 실행될 일이 없기 때문에 __main__은 생략
