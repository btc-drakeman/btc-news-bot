import requests
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

# Investing.com XHR 기반 일정 가져오기 (정적 HTML 아닌 JSON 기반)
def fetch_investing_schedule():
    url = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://www.investing.com/economic-calendar/',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    now = datetime.utcnow()
    payload = {
        'country[]': [],  # 전체 국가
        'importance[]': ['1', '2', '3'],
        'category[]': [],
        'timeZone': '55',  # Asia/Seoul (KST)
        'lang': 'en',
        'dateFrom': now.strftime('%Y-%m-%d'),
        'dateTo': (now + timedelta(days=30)).strftime('%Y-%m-%d'),
        'limit_from': '0'
    }

    try:
        print("📡 Investing 일정 요청 중 (XHR)...")
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()

        data = response.json()
        print(f"📦 응답 타입: {type(data)}")
        print(f"📦 데이터 샘플: {str(data)[:500]}")

        result = []

        if not isinstance(data, dict) or 'data' not in data:
            print("⚠️ JSON 구조가 예상과 다릅니다.")
            return []

        for ev in data['data']:
            try:
                if isinstance(ev, str):
                    print(f"⚠️ 문자열 이벤트 발견 → {ev[:100]}")
                    continue

                dt = datetime.utcfromtimestamp(int(ev['timestamp']))
                title = ev.get('event', 'No Title')
                country = ev.get('country', 'N/A')
                impact = ev.get('impact', 'N/A')

                result.append({
                    'datetime': dt,
                    'title': f"[{country}/{impact}] {title}"
                })
            except Exception as e:
                print(f"❌ 일정 항목 처리 중 오류: {e}")
                continue

        print(f"✅ Investing 일정 {len(result)}건 가져옴 (XHR 방식)")
        return result

    except Exception as e:
        print(f"❌ Investing XHR 크롤링 실패: {e}")
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
