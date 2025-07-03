from economic_alert import get_this_week_schedule, format_monthly_schedule_message
from datetime import timedelta

def check_event_risk(symbol, current_time, window_minutes=180):
    """
    주어진 시각 기준으로 N분 이내 예정된 이벤트가 존재하는지 확인.
    symbol은 참고용이며, 현재는 전체 시장 이벤트만 반영.
    """
    events = get_this_week_schedule()
    risky_events = []

    print(f"\n📡 [EVENT RISK CHECK] 기준 시각 (KST): {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 이벤트 개수: {len(events)}개")

    for e in events:
        event_time = e['datetime']  # 이미 KST 기준으로 저장된 시간
        delta = (event_time - current_time).total_seconds()
        print(f"🕒 이벤트: {event_time.strftime('%Y-%m-%d %H:%M:%S')} | Δ: {delta:.1f}초 → 제목: {e['title']}")

        if abs(delta) <= window_minutes * 60:
            risky_events.append(e['title'])

    if risky_events:
        print(f"⚠️ 리스크 감지됨 → {len(risky_events)}건: {risky_events}")
    else:
        print("✅ 리스크 없음")

    return (len(risky_events) > 0), risky_events

def adjust_direction_based_on_event(symbol, direction, now):
    """
    외부 이벤트에 따라 관망으로 변경할지 판단
    """
    risky, reasons = check_event_risk(symbol, now)
    if risky:
        if direction in ["롱 (Long)", "숏 (Short)"]:
            return "관망", reasons
    return direction, []

def handle_event_command():
    return format_monthly_schedule_message()
