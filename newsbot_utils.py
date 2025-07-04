# ✅ newsbot_utils.py (최신 버전 — 현물 기준 분석 + 레버리지 손익폭 안내 포함)
import requests
import pandas as pd
from config import API_URL, BOT_TOKEN, USER_IDS
from analysis import analyze_multi_timeframe, get_now_price

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']


def send_telegram(text, chat_id=None):
    targets = USER_IDS if chat_id is None else [chat_id]
    for uid in targets:
        try:
            response = requests.post(f'{API_URL}/sendMessage', data={
                'chat_id': uid,
                'text': text,
                'parse_mode': 'HTML'
            })
            print(f"📤 메시지 전송됨 → {uid}, 상태코드: {response.status_code}")
        except Exception as e:
            print(f"❌ 메시지 전송 실패 ({uid}): {e}")


def analyze_symbol(symbol):
    print(f"📊 analyze_symbol() 호출됨: {symbol}")

    price_now = get_now_price(symbol)
    if price_now is None:
        print(f"❌ 현재가 조회 실패: {symbol}")
        return None

    score, explain = analyze_multi_timeframe(symbol)
    if score is None:
        print(f"❌ 분석 점수 없음: {symbol}")
        return None

    leverage_levels = [10, 20, 30, 50]
    risk_range = price_now * 0.003
    reward_range = price_now * 0.005

    leverage_text = "\n".join([
        f"<b>💼 {lev}x 기준 참고 손익폭</b>\n<b>익절가</b>: ${round(price_now + reward_range / lev, 4)} / <b>손절가</b>: ${round(price_now - risk_range / lev, 4)}"
        for lev in leverage_levels
    ])

    result = (
        f"📊 <b>{symbol} 기술분석 (현물 기준)</b>\n"
        f"🕒 <b>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</b>\n"
        f"💰 <b>현재가</b>: ${price_now:.4f}\n\n"
        f"{explain}\n\n"
        f"{leverage_text}"
    )

    return result
