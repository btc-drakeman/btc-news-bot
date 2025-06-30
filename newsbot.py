import requests
import pandas as pd
import time
from flask import Flask
from threading import Thread
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io

BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_IDS = ['7505401062', '7576776181']
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'ETHFIUSDT']

app = Flask(__name__)

def send_telegram(text, image_path=None):
    for user_id in USER_IDS:
        if image_path:
            url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto'
            with open(image_path, 'rb') as img:
                files = {'photo': img}
                data = {'chat_id': user_id, 'caption': text, 'parse_mode': 'HTML'}
                try:
                    response = requests.post(url, data=data, files=files)
                    print(f"이미지+메시지 전송됨 → {user_id}")
                except Exception as e:
                    print(f"텔레그램 전송 오류 (chat_id={user_id}): {e}")
        else:
            url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
            data = {'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'}
            try:
                response = requests.post(url, data=data)
                print(f"메시지 전송됨 → {user_id}")
            except Exception as e:
                print(f"텔레그램 전송 오류 (chat_id={user_id}): {e}")

def fetch_ohlcv(symbol):
    url = f"https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1m", "limit": 300}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        timestamps = [datetime.fromtimestamp(x[0]/1000) for x in data]
        closes = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        df = pd.DataFrame({"timestamp": timestamps, "close": closes, "volume": volumes})
        return df, closes[-1]
    except Exception as e:
        print(f"{symbol} 데이터 요청 실패: {e}")
        return None, None

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def generate_chart(df, symbol, take_profit=None, stop_loss=None):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1.5, 1]})
    fig.suptitle(f"{symbol} 기술 분석 차트", fontsize=14)

    # 가격 및 이동평균, 볼린저밴드
    ax1.plot(df['timestamp'], df['close'], label='Price', color='black')
    ax1.plot(df['timestamp'], df['ema_20'], label='EMA 20', color='blue', linestyle='--')
    ax1.plot(df['timestamp'], df['ema_50'], label='EMA 50', color='orange', linestyle='--')
    ax1.plot(df['timestamp'], df['bollinger_mid'], label='Bollinger Mid', color='green')
    ax1.fill_between(df['timestamp'], df['lower_band'], df['upper_band'], color='gray', alpha=0.2, label='Bollinger Band')
    if take_profit:
        ax1.axhline(take_profit, color='green', linestyle=':', label='Take Profit')
    if stop_loss:
        ax1.axhline(stop_loss, color='red', linestyle=':', label='Stop Loss')
    ax1.legend()
    ax1.set_ylabel("Price")

    # MACD
    ax2.plot(df['timestamp'], df['macd'], label='MACD', color='purple')
    ax2.plot(df['timestamp'], df['signal'], label='Signal', color='red')
    ax2.bar(df['timestamp'], df['hist'], label='Histogram', color='gray')
    ax2.legend()
    ax2.set_ylabel("MACD")

    # RSI
    ax3.plot(df['timestamp'], df['rsi'], label='RSI', color='darkgreen')
    ax3.axhline(70, color='red', linestyle='--')
    ax3.axhline(30, color='blue', linestyle='--')
    ax3.set_ylabel("RSI")
    ax3.set_xlabel("Time")
    ax3.legend()

    plt.xticks(rotation=45)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    img_path = f"chart_{symbol}.png"
    plt.savefig(img_path)
    plt.close()
    return img_path

def analyze_symbol(symbol):
    df, price_now = fetch_ohlcv(symbol)
    if df is None:
        return None

    df['rsi'] = calculate_rsi(df)
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df['macd'] = macd_line
    df['signal'] = signal_line
    df['hist'] = df['macd'] - df['signal']
    df['ema_20'] = df['close'].ewm(span=20).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()
    df['bollinger_mid'] = df['close'].rolling(window=20).mean()
    df['bollinger_std'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['bollinger_mid'] + 2 * df['bollinger_std']
    df['lower_band'] = df['bollinger_mid'] - 2 * df['bollinger_std']

    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    explain = []

    rsi_score = last['rsi']
    rsi_prev = prev['rsi']
    if rsi_score < 20:
        score += 1
        explain.append(f"✅ RSI: {rsi_score:.1f} (강한 과매도)")
    elif rsi_score < 30:
        score += 1
        explain.append(f"⚠️ RSI: {rsi_score:.1f} (과매도)")
    elif rsi_score > 80:
        explain.append(f"❌ RSI: {rsi_score:.1f} (강한 과매수)")
    elif rsi_score > 70:
        explain.append(f"⚠️ RSI: {rsi_score:.1f} (과매수)")
    else:
        explain.append(f"⚖️ RSI: {rsi_score:.1f}")

    if rsi_score < 30 and rsi_score > rsi_prev:
        explain.append("↗️ RSI: 반등 조짐")
    elif rsi_score > 70 and rsi_score < rsi_prev:
        explain.append("↘️ RSI: 고점 이후 꺾임")

    if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
        score += 1
        explain.append("✅ MACD: 골든크로스")
    elif prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
        explain.append("❌ MACD: 데드크로스")
    elif last['hist'] > prev['hist'] and last['hist'] > 0:
        score += 1
        explain.append("✅ MACD: 상승 모멘텀 강화")
    else:
        explain.append("⚖️ MACD: 특별한 신호 없음")

    if price_now < last['lower_band']:
        score += 1
        explain.append("✅ 볼린저: 하단 밴드 이탈 → 과매도")
    elif price_now > last['upper_band']:
        explain.append("❌ 볼린저: 상단 밴드 돌파 → 과열")
    elif price_now > last['bollinger_mid']:
        score += 1
        explain.append("✅ 볼린저: 중심선 상단 유지")
    else:
        explain.append("❌ 볼린저: 중심선 하단")

    if rsi_score < 30 and price_now < last['lower_band']:
        score += 1
        explain.append("🔍 과매도 중복 시그널 → 반등 강도 ↑")

    if last['ema_20'] > last['ema_50']:
        score += 1
        explain.append("✅ EMA: 20/50 상단")
    else:
        explain.append("❌ EMA: 20/50 하단")

    vol_now = df['volume'].iloc[-1]
    vol_avg = df['volume'].rolling(window=20).mean().iloc[-1]
    if vol_now > vol_avg * 1.1:
        score += 1
        explain.append("✅ 거래량: 평균 대비 뚜렷한 증가")
    else:
        explain.append("❌ 거래량: 뚜렷한 증가 없음")

    if score >= 4:
        decision = f"🟢 ▶️ 종합 분석: 강한 매수 신호 (점수: {score}/5)"
        direction = "롱 (Long)"
    elif score <= 2:
        decision = f"🔴 ▶️ 종합 분석: 매도 주의 신호 (점수: {score}/5)"
        direction = "숏 (Short)"
    else:
        decision = f"⚖️ ▶️ 종합 분석: 관망 구간 (점수: {score}/5)"
        direction = "관망"

    if direction == "롱 (Long)":
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 0.98
        take_profit = price_now * 1.04
    elif direction == "숏 (Short)":
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = price_now * 1.02
        take_profit = price_now * 0.96
    else:
        entry_low = price_now * 0.995
        entry_high = price_now * 1.005
        stop_loss = take_profit = None

    msg = f"""
📊 <b>{symbol} 기술 분석 (MEXC)</b>
🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
💰 현재가: ${price_now:,.4f}

"""
    msg += '\n'.join(explain)
    msg += f"\n\n{decision}"

    if direction != "관망":
        msg += f"\n\n📌 <b>전력 제안</b>"
        msg += f"\n- 🔁 <b>유리한 포지션</b>: {direction}"
        msg += f"\n- 🎯 <b>진입 권장가</b>: ${entry_low:,.2f} ~ ${entry_high:,.2f}"
        msg += f"\n- 🛑 <b>손절 제안</b>: ${stop_loss:,.2f}"
        msg += f"\n- 🟢 <b>익절 목표</b>: ${take_profit:,.2f}"
        try:
            avg_delta = df['close'].pct_change().abs().rolling(5).mean().iloc[-1]
            target_pct = abs(take_profit - price_now) / price_now
            estimated_minutes = int(target_pct / avg_delta) if avg_delta > 0 else None
            if estimated_minutes:
                msg += f"\n⏱ <b>예상 익절 시간</b>: 약 {estimated_minutes}분 후 (최근 변동성 기준)"
        except:
            pass
    else:
        msg += f"\n\n📌 <b>참고 가격 범위</b> (관망 중)"
        msg += f"\n- 💡 진입 예상 범위: ${entry_low:,.2f} ~ ${entry_high:,.2f}"

    chart_path = generate_chart(df, symbol, take_profit, stop_loss)
    return msg, chart_path

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"분석 중: {symbol} ({datetime.now().strftime('%H:%M:%S')})")
            result = analyze_symbol(symbol)
            if result:
                text, chart_path = result
                send_telegram(text, image_path=chart_path)
            time.sleep(3)
        time.sleep(600)

@app.route('/')
def home():
    return "✅ MEXC 기술분석 보스 작동 중!"

if __name__ == '__main__':
    print("🟢 기술분석 봇 실행 시작")
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    Thread(target=analysis_loop).start()
