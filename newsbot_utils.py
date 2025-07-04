import requests
import pandas as pd
from datetime import datetime
from config import API_URL, BOT_TOKEN

def send_telegram(text, chat_id):
    try:
        requests.post(f'{API_URL}/sendMessage', data={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        })
        print(f"📤 메시지 전송 시도: {text[:30]}...")
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

def analyze_symbol(symbol):
    try:
        interval = '15m'
        url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}"
        print(f"📡 요청 URL: {url}")
        response = requests.get(url, timeout=10)
        df = pd.DataFrame(response.json(), columns=[
            'timestamp','open','high','low','close','volume','close_time',
            'quote_asset_volume','number_of_trades',
            'taker_buy_base','taker_buy_quote','ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        price_now = df['close'].iloc[-1]

        # 기술 분석 지표들 계산 (RSI, MACD, EMA, Bollinger Bands 등)
        rsi = compute_rsi(df['close'])
        macd_signal = compute_macd(df['close'])
        ema_trend = compute_ema(df['close'])
        boll_position = compute_bollinger(df['close'])
        vol_status = compute_volume(df['volume'])

        # 종합 점수 및 액션
        score = rsi[1] + macd_signal[1] + ema_trend[1] + boll_position[1] + vol_status[1]
        action = '관망' if score < 1.5 else '진입 고려'

        stop_loss = round(price_now * 0.97, 2)
        liquid_price = round(price_now * 0.95, 2)

        msg = f'''
📊 <b>{symbol} 기술분석 (현물 기준)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.2f}

⚖️ RSI: {rsi[0]}
📊 MACD: {macd_signal[0]}
📐 EMA: {ema_trend[0]}
📎 Bollinger: {boll_position[0]}
📊 거래량: {vol_status[0]}

▶️ 종합 분석 점수: {score:.2f}/5
🎯 추천 액션: {action}

📌 진입 참고가: ${price_now:,.2f}
🛑 손절가: ${stop_loss}
💣 청산 위험선: ${liquid_price}
'''.strip()
        return msg

    except Exception as e:
        print(f"❌ 분석 실패 ({symbol}): {e}")
        return None

def compute_rsi(series):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1]
    if value > 70: return ("과매수", 0)
    elif value < 30: return ("과매도", 1)
    else: return ("중립", 0.5)

def compute_macd(series):
    ema12 = series.ewm(span=12).mean()
    ema26 = series.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    hist = macd - signal
    if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
        return ("골든크로스 ↗️", 1)
    elif hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2]:
        return ("데드크로스 ↘️", 0)
    else:
        return ("중립", 0.5)

def compute_ema(series):
    ema_short = series.ewm(span=7).mean()
    ema_long = series.ewm(span=25).mean()
    if ema_short.iloc[-1] > ema_long.iloc[-1]:
        return ("상승 흐름", 1)
    elif ema_short.iloc[-1] < ema_long.iloc[-1]:
        return ("하락 흐름", 0)
    else:
        return ("중립", 0.5)

def compute_bollinger(series):
    mid = series.rolling(20).mean()
    std = series.rolling(20).std()
    upper = mid + (2 * std)
    lower = mid - (2 * std)
    price = series.iloc[-1]
    if price > upper.iloc[-1]:
        return ("밴드 상단 ↗️", 0.8)
    elif price < lower.iloc[-1]:
        return ("밴드 하단 ↘️", 0.8)
    else:
        return ("중립", 0.4)

def compute_volume(vol_series):
    avg = vol_series.rolling(20).mean()
    current = vol_series.iloc[-1]
    if current > avg.iloc[-1] * 1.2:
        return ("거래량 증가", 0.7)
    elif current < avg.iloc[-1] * 0.8:
        return ("거래량 감소", 0.3)
    else:
        return ("보통", 0.5)