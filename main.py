from flask import Flask, send_from_directory
from threading import Thread
from config import SYMBOLS
from analyzer import analyze_multi_tf
from price_fetcher import get_all_prices
from simulator import check_positions
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
    """
    5분, 15분, 30분, 1시간 모두 정각(봉 마감) 타이밍에 분석.
    신호가 일치할 때만 알림 발송.
    """
    print("🚦 멀티프레임 전략 분석 루프 시작")
    already_ran = set()
    while True:
        now = datetime.datetime.now()
        check = False

        # 5, 15, 30, 60분 프레임 모두 '정각 마감' 타이밍(5의 배수, 10초 이내)일 때만 실행
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
            # 오래된 타임키는 메모리 보호용으로 정리(옵션)
            if len(already_ran) > 2000:
                already_ran = set(list(already_ran)[-1000:])
        time.sleep(5)

def monitor_price_loop():
    """
    실시간 가격을 주기적으로 확인하여 TP/SL 조건 충족 여부 판단
    """
    print("📡 실시간 가격 감시 루프 시작")
    while True:
        try:
            prices = get_all_prices(SYMBOLS)
            check_positions(prices)
        except Exception as e:
            print(f"⚠️ 가격 감시 오류: {e}")
        time.sleep(30)  # 30초마다 확인

if __name__ == '__main__':
    t1 = Thread(target=strategy_loop, daemon=True)
    t2 = Thread(target=monitor_price_loop, daemon=True)
    t1.start()
    t2.start()
    app.run(host='0.0.0.0', port=8080)
