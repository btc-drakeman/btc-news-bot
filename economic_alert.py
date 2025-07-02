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

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# Investing.com 크롤링 함수 복붙
def fetch_investing_schedule():
    import requests
    from bs4 import BeautifulSoup
    from datetime import datetime, timedelta

    url = "https://www.investing.com/economic-calendar/"
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://www.investing.com/',
    }
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        table = soup.find("table", {"id": "economicCalendarData"})
        if not table:
            print("❌ 테이블을 찾을 수 없음 (Investing.com 구조 변경 또는 차단 가능성)")
            return []

        rows = table.find_all("tr", {"event_timestamp": True})

        result = []
        now = datetime.utcnow() + timedelta(hours=9)  # 한국시간

        for row in rows:
            try:
                timestamp = int(row["event_timestamp"])
                dt = datetime.utcfromtimestamp(timestamp) + timedelta(hours=9)
                
                if dt.month != now.month:
                    continue  # 이번 달 일정만 추출

                country_el = row.find("td", class_="flagCur")
                country = country_el.text.strip() if country_el else "N/A"

                impact_el = row.find("td", class_="sentiment")
                impact = f"{len(impact_el.find_all('i'))} Level" if impact_el else "N/A"

                title_el = row.find("td", class_="event")
                title = title_el.text.strip() if title_el else "No Title"

                result.append({
                    "datetime": dt,
                    "title": f"[{country}/{impact}] {title}"
                })
            except Exception as e:
                continue

        print(f"✅ Investing 일정 {len(result)}건 가져옴")
        return result

    except Exception as e:
        print(f"❌ Investing 크롤링 실패: {e}")
        return []

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
        all_schedules = fetch_investing_schedule()
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
