import requests
from bs4 import BeautifulSoup  # ✅ 누락된 부분
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

def fetch_investing_schedule():
    url = "https://www.investing.com/economic-calendar/"
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://www.investing.com/',
    }

    try:
        print("📡 Investing 일정 요청 중 (BeautifulSoup)...")
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        rows = soup.select("tr[data-event-datetime]")
        now = datetime.utcnow()
        result = []

        for row in rows:
            try:
                timestamp = row.get("data-event-datetime")
                if not timestamp:
                    continue
                dt = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S")

                if dt.month != now.month:
                    continue

                title_el = row.select_one(".event")
                country_el = row.select_one(".flagCur")
                impact_el = row.select_one(".sentiment")

                title = title_el.text.strip() if title_el else "No Title"
                country = country_el.text.strip() if country_el else "N/A"
                impact = f"{len(impact_el.select('i'))} Level" if impact_el else "N/A"

                result.append({
                    "datetime": dt,
                    "title": f"[{country}/{impact}] {title}"
                })
            except Exception as e:
                print(f"❌ 이벤트 파싱 오류: {e}")
                continue

        print(f"✅ Investing 일정 {len(result)}건 가져옴 (BeautifulSoup 방식)")
        return result

    except Exception as e:
        print(f"❌ Investing BeautifulSoup 크롤링 실패: {e}")
        return []

def test_investing_connection():
    try:
        url = "https://www.investing.com/economic-calendar/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        print(f"🔍 Status Code: {res.status_code}")
        print(f"🔍 Content Length: {len(res.text)}")
        if res.status_code == 200:
            print("✅ 연결 성공 (Render에서 investing.com 접속 가능)")
        else:
            print("❌ 비정상 응답 코드")
    except Exception as e:
        print(f"❌ 연결 실패: {e}")


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

test_investing_connection()

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
