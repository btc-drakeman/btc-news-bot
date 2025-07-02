import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from config import USER_IDS, API_URL

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

allowed_countries = ["USD"]
important_keywords = [
    "interest", "rate", "fomc", "fed", "inflation", "cpi", "ppi",
    "unemployment", "jobless", "non-farm", "retail", "gdp", "pce", "core"
]

translation_map = {
    "interest": "금리",
    "rate": "금리",
    "fomc": "FOMC 회의",
    "fed": "연준 관련",
    "inflation": "인플레이션",
    "cpi": "소비자물가지수(CPI)",
    "ppi": "생산자물가지수(PPI)",
    "unemployment": "실업률",
    "jobless": "실업률",
    "non-farm": "비농업고용",
    "retail": "소매판매",
    "gdp": "GDP",
    "pce": "개인소비지출(PCE)",
    "core": "근원 지표"
}

def translate_title(title):
    title_lower = title.lower()
    for eng, kor in translation_map.items():
        if eng in title_lower:
            return f"{kor} 관련 발표: {title}"
    return title

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

        rows = soup.select("tr.js-event-item")
        now = datetime.utcnow() + timedelta(hours=9)  # Convert 기준 UTC → KST
        result = []

        for row in rows:
            try:
                timestamp = row.get("data-event-datetime")
                if not timestamp:
                    continue

                dt = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S")

                # ✅ 2~3일 이내 일정만 필터
                if not (now <= dt <= now + timedelta(days=3)):
                    continue

                title_el = row.select_one(".event")
                country_el = row.select_one(".flagCur")
                impact_el = row.select_one(".sentiment")

                if not title_el or not country_el or not impact_el:
                    continue

                title = title_el.text.strip()
                country = country_el.text.strip()
                impact_level = len(impact_el.select("i"))

                if country not in allowed_countries:
                    continue
                if impact_level != 3:
                    continue

                if not any(k in title.lower() for k in important_keywords):
                    continue

                translated = translate_title(title)
                result.append({
                    "datetime": dt,
                    "title": f"[{country}/★★★] {translated}"
                })

            except Exception as e:
                print(f"❌ 이벤트 파싱 오류: {e}")
                continue

        print(f"✅ Investing 일정 {len(result)}건 가져옴 (USD 중심 Level3 필터)")
        return result

    except Exception as e:
        print(f"❌ Investing 크롤링 실패: {e}")
        return []

def notify_schedule(event):
    msg = f"📢 <b>경제 일정 알림</b>\n⏰ {event['datetime'].strftime('%m/%d %H:%M')} KST\n📝 {event['title']}"
    send_telegram(msg)

def get_this_week_schedule():
    return all_schedules

def get_this_month_schedule():
    now = datetime.utcnow() + timedelta(hours=9)
    end = now + timedelta(days=3)
    return [
        e for e in all_schedules
        if now <= e['datetime'] <= end
    ]

def format_monthly_schedule_message():
    print("📤 /event 명령 처리 시작됨")
    events = fetch_investing_schedule()
    if not events:
        return "📅 2~3일 내 예정된 주요 경제 일정이 없습니다."

    msg = "\n📅 <b>2~3일 내 주요 경제 일정</b>\n\n"
    for e in events:
        msg += f"🗓 {e['datetime'].strftime('%m월 %d일 (%a) %H:%M')} - {e['title']}\n"
    return msg

def handle_event_command():
    return format_monthly_schedule_message()

def start_economic_schedule():
    global all_schedules
    print("📡 경제 일정 알림 기능 시작")

    def refresh_schedule():
        global all_schedules
        all_schedules = fetch_investing_schedule()
        print(f"🔄 경제 일정 {len(all_schedules)}건 업데이트 완료")

    def check_upcoming():
        now = datetime.utcnow() + timedelta(hours=9)
        for event in all_schedules:
            delta = (event['datetime'] - now).total_seconds()
            if 3540 <= delta <= 3660:  # 약 1시간 전
                notify_schedule(event)

    executors = {'default': ThreadPoolExecutor(5)}
    scheduler = BackgroundScheduler(executors=executors, timezone="UTC")

    refresh_schedule()
    scheduler.add_job(refresh_schedule, 'interval', hours=3)
    scheduler.add_job(check_upcoming, 'interval', minutes=1)
    scheduler.start()
