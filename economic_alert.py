import time
import investpy
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from config import USER_IDS, API_URL

def send_telegram(text):
    import requests
    for uid in USER_IDS:
        requests.post(f'{API_URL}/sendMessage', data={
            'chat_id': uid,
            'text': text,
            'parse_mode': 'HTML'
        })

def get_this_week_schedule():
    today = datetime.now()
    start = today.strftime('%d/%m/%Y')
    end = (today + timedelta(days=7)).strftime('%d/%m/%Y')
    try:
        df = investpy.economic_calendar(from_date=start, to_date=end, countries=None, importances=['high'])
        df = df[df['importance'] == 'high']
        events = []
        for _, r in df.iterrows():
            dt = datetime.strptime(f"{r['date']} {r['time']}", '%d/%m/%Y %H:%M')
            events.append({'title': r['event'], 'datetime': dt})
        return events
    except Exception as e:
        print("경제 일정 수집 실패:", e)
        return []

def send_weekly_schedule():
    evs = get_this_week_schedule()
    if not evs:
        return
    text = "📆 <b>[이번 주 주요 일정]</b>\n"
    for ev in evs:
        dt_k = ev['datetime'] + timedelta(hours=9)
        text += f"• 🕒 {dt_k.strftime('%m월 %d일 (%a) %H:%M')} — {ev['title']}\n"
    send_telegram(text)

def schedule_alerts(scheduler):
    evs = get_this_week_schedule()
    for ev in evs:
        alert = ev['datetime'] - timedelta(hours=1) + timedelta(hours=9)
        def job(title=ev['title']):
            send_telegram(f"⏰ <b>1시간 후 {title} 예정입니다.</b>\n포지션 주의하세요!")
        scheduler.add_job(job, 'date', run_date=alert)

def start_economic_schedule():
    scheduler = BackgroundScheduler(timezone='Asia/Seoul')
    scheduler.add_job(send_weekly_schedule, 'cron', day_of_week='mon', hour=9, minute=0)
    schedule_alerts(scheduler)
    scheduler.start()
    print("📡 경제 일정 알림 기능 시작")
    while True:
        time.sleep(60)
