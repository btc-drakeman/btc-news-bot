import requests
import feedparser
import time
from flask import Flask
from threading import Thread
import os

# 텔레그램 봇 토큰과 사용자 채팅 ID (본인 것으로 변경하세요)
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_ID = '7505401062'

KEYWORDS = [
    'sec', 'regulation', 'bitcoin regulation', 'fomc', 'interest rate', 'inflation',
    'btc', 'bitcoin', 'institutional investor', 'exchange', 'listing', 'delisting',
    'hack', 'fork', 'upgrade', 'network upgrade', 'elon musk', 'musk',
    'trump', 'fed', 'fed decision', 'central bank', 'government', 'policy'
]

RSS_URLS = [
    'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'https://cointelegraph.com/rss',
]

sent_items = set()
ALERT_TIME_WINDOW = 1200  # 20분 이내 뉴스만 알림

POSITIVE_WORDS = [
    'gain', 'rise', 'surge', 'bull', 'profit', 'increase', 'positive', 'upgrade', 'growth', 'record'
]
NEGATIVE_WORDS = [
    'drop', 'fall', 'decline', 'bear', 'loss', 'decrease', 'negative', 'hack', 'crash', 'sell'
]

def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': USER_ID, 'text': text, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=data)
        print(f"텔레그램 메시지 전송 성공: {text[:30]}...")  # 전송 로그
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")

def summarize_text(text, max_sentences=3):
    sentences = text.split('. ')
    summary = '. '.join(sentences[:max_sentences])
    if not summary.endswith('.'):
        summary += '.'
    return summary

def analyze_sentiment_simple(text):
    text_lc = text.lower()
    positive_count = sum(word in text_lc for word in POSITIVE_WORDS)
    negative_count = sum(word in text_lc for word in NEGATIVE_WORDS)

    if positive_count > negative_count:
        return "📈 Price Up Expected (Positive News)"
    elif negative_count > positive_count:
        return "📉 Price Down Expected (Negative News)"
    else:
        return "⚖️ Neutral Impact Expected"

def check_news():
    while True:
        try:
            now = time.time()
            for rss_url in RSS_URLS:
                feed = feedparser.parse(rss_url)
                for entry in feed.entries:
                    print(f"뉴스 제목: {entry.title}")  # 뉴스 제목 로그 출력

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

                    title_lc = title.lower()
                    summary_lc = summary.lower()

                    if any(keyword in title_lc or keyword in summary_lc for keyword in KEYWORDS):
                        short_summary = summarize_text(summary) if summary else ''

                        sentiment_text = title + ". " + short_summary
                        sentiment = analyze_sentiment_simple(sentiment_text)

                        message = f"🚨 <b>{title}</b>\n🔗 {link}"
                        if short_summary:
                            message += f"\n\n📝 Summary:\n{short_summary}"
                        message += f"\n\n{sentiment}"

                        send_telegram(message)
                        print(f"텔레그램 메시지 전송 시도: {title}")  # 전송 시도 로그

                        sent_items.add(item_id)
        except Exception as e:
            print(f"뉴스 체크 중 오류 발생: {e}")

        time.sleep(60)

app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    print("🟢 뉴스 봇 및 Flask 서버 시작 중...")
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    news_thread = Thread(target=check_news)
    news_thread.start()

    news_thread.join()
    flask_thread.join()
