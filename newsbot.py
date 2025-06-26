import requests
import feedparser
import time
import pandas as pd
import pandas_ta as ta
from flask import Flask
from threading import Thread
import os

# 텔레그램 봇 토큰과 사용자 채팅 ID
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_ID = '7505401062'

# 키워드 리스트
KEYWORDS = [
    'sec', 'regulation', 'bitcoin regulation', 'fomc', 'interest rate', 'inflation',
    'btc', 'bitcoin', 'institutional investor', 'exchange', 'listing', 'delisting',
    'hack', 'fork', 'upgrade', 'network upgrade', 'elon musk', 'musk',
    'trump', 'fed', 'fed decision', 'central bank', 'government', 'policy'
]

# RSS 피드
RSS_URLS = [
    'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'https://cointelegraph.com/rss',
    'https://www.reuters.com/rssFeed/cryptocurrencyNews',
    'https://www.bloomberg.com/crypto/rss',
]

# 기술지표 설정
TECH_INTERVAL = '1m'
TECH_LIMIT = 100
TECH_SYMBOL = 'BTCUSDT'

# 알림 중복 방지
sent_items = set()
ALERT_TIME_WINDOW = 600

POSITIVE_WORDS = ['gain', 'rise', 'surge', 'bull', 'profit', 'increase', 'positive', 'upgrade', 'growth', 'record']
NEGATIVE_WORDS = ['drop', 'fall', 'decline', 'bear', 'loss', 'decrease', 'negative', 'hack', 'crash', 'sell']

def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': USER_ID, 'text': text, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, data=data)
        print("✅ 텔레그램 응답 코드:", response.status_code)
    except Exception as e:
        print(f"❌ 텔레그램 전송 오류: {e}")

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
        return "📈 상승 예상 (긍정 뉴스)"
    elif neg > pos:
        return "📉 하락 예상 (부정 뉴스)"
    else:
        return "⚖️ 중립"

def check_news():
    print("🔍 뉴스 체크 시작")
    while True:
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
                title_lc = title.lower()
                summary_lc = summary.lower()
                if any(k in title_lc or k in summary_lc for k in KEYWORDS):
                    short_summary = summarize_text(summary) if summary else ''
                    sentiment = analyze_sentiment_simple(title + ". " + short_summary)
                    message = f"\ud83d\udea8 <b>{title}</b>\n\ud83d\udd17 {link}"
                    if short_summary:
                        message += f"\n\n\ud83d\udcdc 요약:\n{short_summary}"
                    message += f"\n\n{sentiment}"
                    send_telegram(message)
                    sent_items.add(item_id)
        time.sleep(60)

def check_technical():
    print("📊 기술지표 체크 시작")
    while True:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={TECH_SYMBOL}&interval={TECH_INTERVAL}&limit={TECH_LIMIT}"
            data = requests.get(url).json()
            df = pd.DataFrame(data, columns=[
                'time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                'quote_asset_volume', 'num_trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'])
            df['close'] = df['close'].astype(float)
            df['rsi'] = ta.rsi(df['close'], length=14)
            macd = ta.macd(df['close'])
            df['macd'] = macd['MACD_12_26_9']
            df['macd_signal'] = macd['MACDs_12_26_9']
            rsi = df['rsi'].iloc[-1]
            macd_cross = df['macd'].iloc[-1] > df['macd_signal'].iloc[-1] and df['macd'].iloc[-2] <= df['macd_signal'].iloc[-2]
            current_price = df['close'].iloc[-1]
            if rsi < 30:
                send_telegram(f"📉 <b>RSI 과매도 신호</b>\n현재 RSI: {rsi:.2f}\nBTC 가격: ${current_price:,.2f}")
            if rsi > 70:
                send_telegram(f"📈 <b>RSI 과매수 신호</b>\n현재 RSI: {rsi:.2f}\nBTC 가격: ${current_price:,.2f}")
            if macd_cross:
                send_telegram(f"⚡ <b>MACD 골든크로스 발생!</b>\nBTC 가격: ${current_price:,.2f}")
        except Exception as e:
            print(f"❌ 기술 분석 오류: {e}")
        time.sleep(300)

app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    print("🟢 Flask + 뉴스 + 기술지표 봇 시작")
    Thread(target=run_flask).start()
    Thread(target=check_news).start()
    Thread(target=check_technical).start()
