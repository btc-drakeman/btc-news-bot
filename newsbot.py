import requests
import feedparser
import time
from flask import Flask
from threading import Thread
import os
import pandas as pd
from datetime import datetime

# 텔레그램 설정
BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_ID = '7505401062'

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
    'http://rss.cnn.com/rss/edition.rss',
    'http://feeds.reuters.com/reuters/topNews',
]

sent_items = set()
ALERT_TIME_WINDOW = 600  # 뉴스 유효시간: 10분

# 텔레그램 메시지 전송 함수
def send_telegram(text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': USER_ID, 'text': text, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, data=data)
        print(f"✅ 텔레그램 응답 코드: {response.status_code}")
    except Exception as e:
        print(f"❌ 텔레그램 전송 오류: {e}")

# 뉴스 요약
def summarize_text(text, max_sentences=3):
    sentences = text.split('. ')
    summary = '. '.join(sentences[:max_sentences])
    if not summary.endswith('.'):
        summary += '.'
    return summary

# 뉴스 체크 루프
def check_news():
    print("🚀 뉴스 체크 쓰레드 시작")
    while True:
        print("✅ check_news 루프 진입")
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

                    title_lc = title.lower()
                    summary_lc = summary.lower()

                    if any(keyword in title_lc or keyword in summary_lc for keyword in KEYWORDS):
                        short_summary = summarize_text(summary)
                        message = f"🚨 <b>{title}</b>\n🔗 {link}\n\n📝 {short_summary}"
                        send_telegram(message)
                        sent_items.add(item_id)
        except Exception as e:
            print(f"❌ 뉴스 확인 중 오류: {e}")
        time.sleep(60)

# 기술 분석 함수
def get_btc_technical_summary():
    try:
        url = 'https://api.binance.com/api/v3/klines'
        params = {'symbol': 'BTCUSDT', 'interval': '1m', 'limit': 100}
        res = requests.get(url, params=params).json()

        print(f"🟠 Binance 응답: {res}")  # Binance 응답을 그대로 로그 출력

        if not isinstance(res, list) or len(res) == 0:
            raise ValueError("Binance API가 유효한 데이터를 반환하지 않았습니다.")

        closes = [float(candle[4]) for candle in res]
        df = pd.DataFrame(closes, columns=['close'])

        if len(df) < 14:
            raise ValueError("데이터가 부족하여 RSI 계산 불가")

        df['rsi'] = df['close'].rolling(window=14).apply(lambda x: (
            100 - (100 / (1 + (sum([max(0, x[i] - x[i-1]) for i in range(1, len(x))]) /
                               sum([abs(min(0, x[i] - x[i-1])) for i in range(1, len(x))]))))
        ) if len(x) == 14 else None, raw=False)

        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        rsi_now = df['rsi'].iloc[-1]
        macd_now = df['macd'].iloc[-1]
        signal_now = df['signal'].iloc[-1]
        price_now = df['close'].iloc[-1]

        macd_trend = "골든크로스" if macd_now > signal_now else "데드크로스"
        rsi_status = "과매도" if rsi_now < 30 else ("과매수" if rsi_now > 70 else "중립")

        if rsi_now < 30 and macd_now > signal_now:
            advice = "🟢 매수 타이밍으로 판단됩니다"
        elif rsi_now > 70 and macd_now < signal_now:
            advice = "🔴 매도 주의 타이밍입니다"
        else:
            advice = "⚖️ 중립 구간으로 판단됩니다"

        msg = (
            f"📊 <b>BTC 기술 분석 (Binance)</b>\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"💰 현재가: ${price_now:,.2f}\n"
            f"📈 RSI: {rsi_now:.1f} ({rsi_status})\n"
            f"📉 MACD: {macd_trend}\n\n"
            f"{advice}"
        )
        return msg

    except Exception as e:
        error_msg = f"❌ 기술 분석 오류 발생: {e}"
        print(error_msg)
        send_telegram(error_msg)  # 오류를 텔레그램으로 전송
        return None

# 기술 분석 루프
def check_tech_loop():
    print("🚀 기술분석 체크 쓰레드 시작")
    while True:
        print(f"⏰ check_tech_loop tick: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            msg = get_btc_technical_summary()
            if msg:
                send_telegram(msg)
        except Exception as e:
            print(f"❌ 기술 분석 루프 오류: {e}")
        time.sleep(900)  # 15분

# Flask 서버 (Render용)
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ BTC 뉴스 + 기술분석 봇 작동 중!"

if __name__ == '__main__':
    print("🟢 Flask + 뉴스 + 기술지표 봇 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))).start()
    Thread(target=check_news).start()
    Thread(target=check_tech_loop).start()
