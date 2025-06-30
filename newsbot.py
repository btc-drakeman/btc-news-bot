import requests
import feedparser
import time
from flask import Flask
from threading import Thread
import os
import pandas as pd
from datetime import datetime
import html

# 텔레그램 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'  # 실제 토큰
USER_ID = '7505401062'  # 실제 사용자 ID

KEYWORDS = [
    'sec', 'regulation', 'bitcoin regulation', 'fomc', 'interest rate', 'inflation',
    'btc', 'bitcoin', 'institutional investor', 'exchange', 'listing', 'delisting',
    'hack', 'fork', 'upgrade', 'network upgrade', 'elon musk', 'musk',
    'trump', 'fed', 'fed decision', 'central bank', 'government', 'policy'
]

RSS_URLS = [
    'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'https://cointelegraph.com/rss',
    'https://www.cnn.com/services/rss/',
    'http://feeds.reuters.com/reuters/technologyNews'
]

POSITIVE_WORDS = ['gain', 'rise', 'surge', 'bull', 'profit', 'increase', 'positive', 'upgrade', 'growth', 'record']
NEGATIVE_WORDS = ['drop', 'fall', 'decline', 'bear', 'loss', 'decrease', 'negative', 'hack', 'crash', 'sell']

sent_items = set()
ALERT_TIME_WINDOW = 600

def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': USER_ID, 'text': html.escape(text), 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, data=data)
        print(f"✅ 텔레그램 응답 코드: {response.status_code}")
        return response
    except Exception as e:
        print(f"❌ 텔레그램 전송 오류: {e}")
        return None

def summarize_text(text, max_sentences=3):
    sentences = text.split('. ')
    summary = '. '.join(sentences[:max_sentences])
    return summary if summary.endswith('.') else summary + '.'

def analyze_sentiment_simple(text):
    text_lc = text.lower()
    pos = sum(word in text_lc for word in POSITIVE_WORDS)
    neg = sum(word in text_lc for word in NEGATIVE_WORDS)
    return "📈 긍정적 뉴스로 판단됨" if pos > neg else "📉 부정적 뉴스로 판단됨" if neg > pos else "⚖️ 중립적 뉴스로 판단됨"

def get_btc_technical_summary():
    try:
        print("📥 CoinGecko에서 가격 데이터 요청 중...")
        url = 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart'
        params = {'vs_currency': 'usd', 'days': '1', 'interval': 'minute'}
        res = requests.get(url, params=params)
        res.raise_for_status()
        data = res.json()
        prices = data.get('prices', [])
        print(f"🔢 수신한 가격 데이터 개수: {len(prices)}")
        if len(prices) < 50:
            raise Exception("가격 데이터 부족")

        df = pd.DataFrame(prices, columns=['timestamp', 'price'])
        df['price'] = df['price'].astype(float)

        delta = df['price'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_now = rsi.iloc[-1]
        rsi_status = "과매도" if rsi_now < 30 else "과매수" if rsi_now > 70 else "중립"

        ema12 = df['price'].ewm(span=12, adjust=False).mean()
        ema26 = df['price'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        macd_now = df['macd'].iloc[-1]
        signal_now = df['signal'].iloc[-1]
        macd_status = "골든크로스" if macd_now > signal_now else "데드크로스"

        advice = (
            "🟢 매수 신호로 판단됩니다" if rsi_now < 30 and macd_now > signal_now else
            "🔴 매도 주의 구간입니다" if rsi_now > 70 and macd_now < signal_now else
            "⚖️ 중립 구간입니다"
        )

        print("📈 기술 분석 계산 완료")
        return (
            f"📊 <b>BTC 기술 분석</b>\n"
            f"💰 현재가: ${df['price'].iloc[-1]:,.2f}\n"
            f"📈 RSI: {rsi_now:.1f} ({rsi_status})\n"
            f"📉 MACD: {macd_status}\n\n"
            f"{advice}"
        )

    except Exception as e:
        print(f"❌ 기술 분석 함수 내부 예외: {e}")
        return None

def check_news():
    print("🚀 뉴스 체크 시작")
    while True:
        try:
            now = time.time()
            for rss_url in RSS_URLS:
                feed = feedparser.parse(rss_url)
                if not feed.entries:
                    continue

                for entry in feed.entries:
                    if not hasattr(entry, 'published_parsed'):
                        continue

                    pub_time = time.mktime(entry.published_parsed)
                    if now - pub_time > ALERT_TIME_WINDOW:
                        continue

                    title = entry.title.strip()
                    summary = getattr(entry, 'summary', '')
                    link = entry.link
                    item_id = f"{title}-{getattr(entry, 'published', str(pub_time))}"

                    if item_id in sent_items:
                        continue

                    if any(k in title.lower() or k in summary.lower() for k in KEYWORDS):
                        short_summary = summarize_text(summary)
                        sentiment = analyze_sentiment_simple(title + ". " + short_summary)
                        tech_summary = get_btc_technical_summary()
                        message = f"🚨 <b>{title}</b>\n🔗 {link}\n\n📝 {short_summary}\n\n{sentiment}"
                        if tech_summary:
                            message += f"\n\n{tech_summary}"
                        resp = send_telegram(message)
                        if resp and resp.status_code == 200:
                            sent_items.add(item_id)

        except Exception as e:
            print(f"❌ 뉴스 오류: {e}")
        time.sleep(60)

def check_tech_loop():
    print("📉 기술 분석 루프 시작")
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"⏰ 기술 분석 시작 시각: {now}")
            msg = get_btc_technical_summary()
            if msg:
                print("✅ 기술 분석 메시지 생성 성공")
                response = send_telegram(msg)
                print(f"📨 텔레그램 응답 코드: {response.status_code if response else '전송 실패'}")
            else:
                print("⚠️ 기술 분석 메시지가 생성되지 않음")
        except Exception as e:
            print(f"❌ 기술 분석 루프 예외 발생: {e}")
        time.sleep(900)

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ BTC 뉴스 + RSI + MACD 텔레그램 봇 작동 중!"

@app.route('/test')
def test():
    print("🧪 /test 요청 수신 → 메시지 전송 시도")
    send_telegram("✅ [테스트] 텔레그램 봇 연결 확인!")
    return "✅ 테스트 메시지 전송됨"

if __name__ == '__main__':
    print("🟢 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)).start()
    Thread(target=check_news).start()
    Thread(target=check_tech_loop).start()
