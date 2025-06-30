import requests
import feedparser
import time
from flask import Flask, request
from threading import Thread
import os
import pandas as pd
from datetime import datetime

# 텔레그램 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS_FILE = 'user_ids.txt'

# 유저 ID 저장소
def load_user_ids():
    if os.path.exists(USER_IDS_FILE):
        with open(USER_IDS_FILE, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_user_ids(user_ids):
    with open(USER_IDS_FILE, 'w') as f:
        for uid in user_ids:
            f.write(uid + '\n')

USER_IDS = load_user_ids()

# 주요 키워드
KEYWORDS = [
    'sec', 'regulation', 'bitcoin regulation', 'fomc', 'interest rate', 'inflation',
    'btc', 'bitcoin', 'institutional investor', 'exchange', 'listing', 'delisting',
    'hack', 'fork', 'upgrade', 'network upgrade', 'elon musk', 'musk',
    'trump', 'fed', 'fed decision', 'central bank', 'government', 'policy'
]

# RSS 주소
RSS_URLS = [
    'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'https://cointelegraph.com/rss',
    'https://www.cnn.com/services/rss/',
    'http://feeds.reuters.com/reuters/technologyNews'
]

sent_items = set()
ALERT_TIME_WINDOW = 600  # 10분

POSITIVE_WORDS = ['gain', 'rise', 'surge', 'bull', 'profit', 'increase', 'positive', 'upgrade', 'growth', 'record']
NEGATIVE_WORDS = ['drop', 'fall', 'decline', 'bear', 'loss', 'decrease', 'negative', 'hack', 'crash', 'sell']

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']
TECH_INTERVAL = 600  # 10분

# MEXC 데이터 요청
def fetch_mexc_ohlcv(symbol, interval='1m', limit=100):
    url = f'https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    res = requests.get(url)
    res.raise_for_status()
    data = res.json()
    df = pd.DataFrame(data, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

# 지표 분석 및 전략

def analyze_indicators(symbol):
    try:
        df = fetch_mexc_ohlcv(symbol)
        price_now = df['close'].iloc[-1]

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_now = rsi.iloc[-1]

        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        macd_now = macd.iloc[-1]
        signal_now = signal.iloc[-1]

        # 볼린저 밴드
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        bb_status = '상단' if price_now > upper.iloc[-1] else ('하단' if price_now < lower.iloc[-1] else '중심선')

        # EMA
        ema20 = df['close'].ewm(span=20).mean().iloc[-1]
        ema50 = df['close'].ewm(span=50).mean().iloc[-1]
        ema_status = '20/50 상단' if price_now > ema20 and price_now > ema50 else '하단'

        # 거래량
        vol_now = df['volume'].iloc[-1]
        vol_avg = df['volume'].rolling(window=20).mean().iloc[-1]
        vol_status = '증가' if vol_now > vol_avg else '감소'

        # 점수 및 포지션
        score = sum([
            rsi_now < 70,
            macd_now > signal_now,
            bb_status == '중심선',
            ema_status == '20/50 상단',
            vol_status == '증가']
        )

        position = '롱 (Long)' if score >= 3 else '숏 (Short)'

        # 전략 제안
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        sl = price_now * (0.985 if position == '롱 (Long)' else 1.015)
        tp = price_now * (1.04 if position == '롱 (Long)' else 0.96)

        msg = (
            f"\n📊 <b>{symbol} 기술 분석 (MEXC)</b>"
            f"\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            f"\n💰 현재가: ${price_now:,.4f}"
            f"\n\n{'✅' if rsi_now < 70 else '❌'} RSI: {rsi_now:.1f}"
            f"\n{'✅' if macd_now > signal_now else '❌'} MACD: {'골든크로스' if macd_now > signal_now else '데드크로스'}"
            f"\n{'✅' if bb_status == '중심선' else '❌'} 볼린저: {bb_status}"
            f"\n{'✅' if ema_status == '20/50 상단' else '❌'} EMA: {ema_status}"
            f"\n{'✅' if vol_status == '증가' else '❌'} 거래량: {vol_status}"
            f"\n\n⚖️ ▶️ 종합 분석: {'매수 유망' if score >= 4 else ('관망 구간' if score == 3 else '매도 주의')} (점수: {score}/5)"
            f"\n📌 <b>전략 제안</b>"
            f"\n- 🔁 <b>유리한 포지션</b>: {position}"
            f"\n- 🎯 <b>진입 권장가</b>: ${entry_low:,.2f} ~ ${entry_high:,.2f}"
            f"\n- 🛑 <b>손절 제안</b>: ${sl:,.2f}"
            f"\n- 🟢 <b>익절 목표</b>: ${tp:,.2f}"
        )
        return msg

    except Exception as e:
        return f"❌ {symbol} 분석 실패: {e}"

# 전송 함수

def send_telegram(text):
    for uid in USER_IDS:
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {'chat_id': uid, 'text': text, 'parse_mode': 'HTML'}
        try:
            requests.post(url, data=data)
        except Exception as e:
            print(f"❌ {uid} 전송 오류: {e}")

# 뉴스 관련

def summarize_text(text, max_sentences=3):
    sentences = text.split('. ')
    summary = '. '.join(sentences[:max_sentences])
    if not summary.endswith('.'):
        summary += '.'
    return summary

def analyze_sentiment_simple(text):
    text_lc = text.lower()
    pos = sum(word in text_lc for word in POSITIVE_WORDS)
    neg = sum(word in text_lc for word in NEGATIVE_WORDS)
    if pos > neg:
        return "📈 긍정적 뉴스로 판단됨"
    elif neg > pos:
        return "📉 부정적 뉴스로 판단됨"
    else:
        return "⚖️ 중립적 뉴스로 판단됨"

def check_news():
    while True:
        try:
            now = time.time()
            for rss_url in RSS_URLS:
                feed = feedparser.parse(rss_url)
                for entry in feed.entries:
                    if not hasattr(entry, 'published_parsed'):
                        continue
                    published_time = time.mktime(entry.published_parsed)
                    if now - published_time > ALERT_TIME_WINDOW:
                        continue
                    title = entry.title.strip()
                    summary = entry.summary.strip() if hasattr(entry, 'summary') else ''
                    link = entry.link
                    item_id = f"{title}-{entry.published}"
                    if item_id in sent_items:
                        continue
                    if any(k in title.lower() or k in summary.lower() for k in KEYWORDS):
                        short = summarize_text(summary)
                        sentiment = analyze_sentiment_simple(title + '. ' + short)
                        message = f"🚨 <b>{title}</b>\n🔗 {link}\n\n📝 {short}\n\n{sentiment}"
                        send_telegram(message)
                        sent_items.add(item_id)
        except Exception as e:
            print(f"❌ 뉴스 오류: {e}")
        time.sleep(60)

def check_tech_loop():
    while True:
        for symbol in SYMBOLS:
            msg = analyze_indicators(symbol)
            send_telegram(msg)
        time.sleep(TECH_INTERVAL)

# Flask 앱 및 봇 Webhook 수신

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ BTC 봇 작동 중"

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    message = data.get('message', {})
    text = message.get('text', '')
    chat = message.get('chat', {})
    chat_id = str(chat.get('id'))

    if chat_id:
        if text.strip().lower() == '/stop':
            if chat_id in USER_IDS:
                USER_IDS.remove(chat_id)
                save_user_ids(USER_IDS)
                msg = "🚫 알림 수신이 중단되었습니다. 다시 시작하려면 /start 를 입력하세요."
            else:
                msg = "ℹ️ 이미 수신 대상이 아닙니다."
        else:
            if chat_id not in USER_IDS:
                USER_IDS.add(chat_id)
                save_user_ids(USER_IDS)
                msg = "👋 알림 수신이 등록되었습니다!"
            else:
                msg = "✅ 이미 등록되어 있습니다."
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        requests.post(url, data={'chat_id': chat_id, 'text': msg})

    return "ok"

if __name__ == '__main__':
    print("🟢 전체 통합 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))).start()
    Thread(target=check_news).start()
    Thread(target=check_tech_loop).start()
