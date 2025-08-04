from flask import Flask, send_from_directory
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_multi_tf
from price_fetcher import get_all_prices
from simulator import check_positions
from strategy_spring import analyze_spring_signal
import time
import traceback
import datetime

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"

@app.route('/logs/full')
def download_full_csv():
    return send_from_directory("simulation_logs", "results_export.csv", as_attachment=True)

@app.route('/logs/<symbol>.csv')
def download_coin_csv(symbol):
    return send_from_directory("simulation_logs/export_by_coin", f"{symbol}.csv", as_attachment=True)

def strategy_loop():
    print("🚦 멀티프레임 전략 분석 루프 시작")
    already_ran = set()
    while True:
        now = datetime.datetime.now()
        check = False

        if now.minute % 5 == 0 and now.second < 10:
            time_key = now.strftime('%Y%m%d%H%M')
            if time_key not in already_ran:
                check = True
                already_ran.add(time_key)

        if check:
            for symbol in SYMBOLS:
                try:
                    print(f"\n🔍 [{now.strftime('%Y-%m-%d %H:%M:%S')}] {symbol} 멀티프레임 전략 분석 시작", flush=True)
                    multi_msg = analyze_multi_tf(symbol)
                    if multi_msg:
                        print(f"📤 전략 전송:\n{multi_msg}\n", flush=True)
                    else:
                        print(f"📭 {symbol} 전략 신호 없음", flush=True)
                    print(f"✅ {symbol} 전략 분석 완료", flush=True)
                except Exception as e:
                    print(f"❌ {symbol} 전략 분석 중 오류 발생: {e}", flush=True)
                    traceback.print_exc()
            if len(already_ran) > 2000:
                already_ran = set(list(already_ran)[-1000:])
        time.sleep(5)

# 실시간 급등/급락 감지용 변수
recent_alerts = {}
alert_cooldown = 300  # 중복 알림 방지 기간 (초)
previous_prices = {}

def monitor_price_loop():
    print("📡 실시간 가격 감시 및 급등/급락 감지 루프 시작")
    while True:
        try:
            prices = get_all_prices(SYMBOLS)
            check_positions(prices)

            for symbol, current_price in prices.items():
                if current_price is None:
                    continue

                prev_price = previous_prices.get(symbol)
                if prev_price is not None:
                    delta = abs(current_price - prev_price) / prev_price
                    if delta > 0.015:  # 1.5% 이상 변동 시
                        last_time = recent_alerts.get(symbol, 0)
                        if time.time() - last_time > alert_cooldown:
                            print(f"⚡ 급등/급락 감지: {symbol} ({prev_price:.6f} → {current_price:.6f}) → 즉시 분석")
                            msg = analyze_multi_tf(symbol)
                            if msg:
                                print(f"📤 즉시 분석 알림 전송:\n{msg}")
                                recent_alerts[symbol] = time.time()

                previous_prices[symbol] = current_price

        except Exception as e:
            print(f"⚠️ 급등/급락 감지 루프 오류: {e}")
        time.sleep(30)

def spring_strategy_loop():
    print("🌀 스프링 전략 루프 시작")
    already_sent = set()
    while True:
        now = datetime.datetime.now()
        key = now.strftime('%Y%m%d%H%M')
        if now.minute % 30 == 0 and now.second < 10:
            if key not in already_sent:
                for symbol in SYMBOLS:
                    try:
                        msg = analyze_spring_signal(symbol)
                        if msg:
                            print(f"[SPRING] {symbol} 조건 만족")
                    except Exception as e:
                        print(f"[SPRING ERROR] {symbol}: {e}")
                already_sent.add(key)
        time.sleep(5)

if __name__ == '__main__':
    t1 = Thread(target=strategy_loop, daemon=True)
    t2 = Thread(target=monitor_price_loop, daemon=True)
    t3 = Thread(target=spring_strategy_loop, daemon=True)  # ← 스프링 전략 추가
    
    t1.start()
    t2.start()
    t3.start()  # ← 반드시 start() 해줘야 작동해
    
    app.run(host='0.0.0.0', port=8080)

