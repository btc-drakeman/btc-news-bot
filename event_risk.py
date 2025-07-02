from economic_alert import (
    fetch_investing_schedule,   # ✅ /event 명령에서 실시간 크롤링
    get_this_week_schedule,     # ✅ 자동 알림용 캐시 스케줄
    get_this_month_schedule     # ✅ 여전히 자동 알림엔 사용
)
from datetime import datetime, timedelta

def check_event_risk(symbol, current_time, window_minutes=180):
    """
    주어진 시각 기준으로 3시간 이내 예정된 이벤트가 존재하는지 확인.
    symbol은 참고용이며, 현재는 전체 시장 이벤트만 반영.
    """
    events = get_this_week_schedule()
    risky_events = []
    for e in events:
        event_time = e['datetime'] + timedelta(hours=9)  # UTC → KST
        delta = abs((event_time - current_time).total_seconds())
        if delta <= window_minutes * 60:
            risky_events.append(e['title'])

    return (len(risky_events) > 0), risky_events


def adjust_direction_based_on_event(symbol, direction, now):
    risky, reasons = check_event_risk(symbol, now)
    if risky:
        if direction in ["롱 (Long)", "숏 (Short)"]:
            return "관망", reasons
    return direction, []


def format_monthly_schedule_message():
    """
    /event 명령어에서 사용하는 실시간 크롤링 기반 메시지 생성
    """
    print("📤 /event 명령 처리 시작됨")  # ✅ 확인용 로그

    events = fetch_investing_schedule()  # ✅ 최신 Investing.com 일정 실시간 요청

    if not events:
        print("⚠️ 일정이 0건입니다.")
        return "📅 이번 달 예정된 주요 경제 일정이 없습니다."

    print(f"📥 총 {len(events)}건의 일정 수집됨")  # ✅ 일정 수 표시

    msg = "\n📅 <b>이번 달 주요 경제 일정</b>\n\n"
    for e in events:
        local_time = e['datetime'] + timedelta(hours=9)  # UTC → KST
        msg += f"🗓 {local_time.strftime('%m월 %d일 (%a) %H:%M')} - {e['title']}\n"
    return msg


def handle_event_command():
    """ /event 명령어 요청 시 출력 메시지 반환 """
    return format_monthly_schedule_message()
