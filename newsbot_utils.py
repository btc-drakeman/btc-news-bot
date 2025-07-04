# ✅ newsbot_utils.py (최신 버전 — 텔레그램 메시지 전송 + 기술 분석)
import requests
from config import API_URL, USER_IDS
from analysis import analyze_multi_timeframe, get_now_price

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ETHFIUSDT"]

# 텔레그램 전송 함수
def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            print(f"📤 메시지 전송 시도 → {uid}")
            res = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"✅ 메시지 전송됨 → {uid}, 상태코드: {res.status_code}")
        except Exception as e:
            print(f"❌ 텔레그램 전송 실패 → {uid}: {e}")

# 기술분석 수행 함수
def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")
    now_price = get_now_price(symbol)
    if now_price is None:
        return f"⚠️ 현재가 조회 실패: {symbol}"

    score, explain, _ = analyze_multi_timeframe(symbol)
    explain = explain.strip()

    try:
        now_price = float(now_price)
        leverage_levels = [10, 20, 30, 50]
        leverage_text = "\n".join([
            f"📈 <b>{lev}x 기준 손익폭</b>\n⤴️ 익절가: ${now_price * (1 + 0.01 * lev):,.2f} | ⤵️ 손절가: ${now_price * (1 - 0.01 * lev):,.2f}"
            for lev in leverage_levels
        ])
    except Exception as e:
        leverage_text = "⚠️ 손익폭 계산 실패"
        print(f"❌ 손익폭 계산 오류: {e}")

    return f"📊 <b>{symbol} 기술분석</b> (현물 기준)\n🕒 <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n💰 <b>현재가</b>: ${now_price:,.2f}\n\n{explain}\n\n{leverage_text}"
