from flask import Flask
from threading import Thread
from config import SYMBOLS, STRATEGY_INTERVAL_SECONDS, SPIKE_POLL_INTERVAL_SECONDS
from analyzer import analyze_symbol, fetch_market_data
from spike_detector import detect_spike_conditions, detect_crash_conditions
from notifier import send_telegram
import time
import traceback

app = Flask(__name__)

@app.route('/')
def home():
    return "🟢 봇 실행 중"

def strategy_loop():
    """
    매 STRATEGY_INTERVAL_SECONDS마다 SYMBOLS 목록에 대해 전략 분석을 수행하고
    결과가 있을 때마다 텔레그램으로 알림을 전송합니다.
    """
    while True:
        for symbol in SYMBOLS:
            try:
                print(f"\n🔍 전략 분석 시작: {symbol}", flush=True)
                result = analyze_symbol(symbol)

                if result:
                    msgs = result if isinstance(result, list) else [result]
                    print(f"📦 {symbol} 메시지 개수: {len(msgs)}", flush=True)
                    for msg in msgs:
                        print(f"📤 전송할 메시지:\n{msg}\n", flush=True)
                        send_telegram(msg)
                else:
                    print(f"📭 {symbol} 전략 분석 결과 없음", flush=True)

                print(f"✅ {symbol} 전략 분석 완료", flush=True)
            except Exception as e:
                print(f"❌ {symbol} 전략 분석 중 오류 발생: {e}", flush=True)
                traceback.print_exc()

        print(f"⏱️ {STRATEGY_INTERVAL_SECONDS//60}분 대기 중...\n" + "="*50, flush=True)
        time.sleep(STRATEGY_INTERVAL_SECONDS)

# ✅ 아래 두 줄을 spike_loop 함수 위에 추가!
last_spike_status = {}
last_crash_status = {}

def spike_loop():
    global last_spike_status, last_crash_status  # ✅ 전역변수 사용 선언
    while True:
        for symbol in SYMBOLS:
            try:
                data = fetch_market_data(symbol)
                
                # 급등(스파이크) 감지
                spike_msgs = detect_spike_conditions(data)
                if spike_msgs:
                    if not last_spike_status.get(symbol):
                        # ✅ 코인명 포함, 중복 방지
                        msg = [f"🚨 [{symbol}] 급등 신호"]
                        msg.extend([f"[{symbol}] {m}" for m in spike_msgs])
                        msg.append('━━━━━━━━━━━━━━━━━━━')
                        
                        analysis_msgs = analyze_symbol(symbol)
                        if analysis_msgs:
                            msg.append("📊 [기술 분석]")
                            if isinstance(analysis_msgs, list):
                                msg.extend(analysis_msgs)
                            else:
                                msg.append(analysis_msgs)
                        
                        send_telegram('\n'.join(msg))
                        last_spike_status[symbol] = True
                else:
                    last_spike_status[symbol] = False

                # 급락(크래시) 감지
                crash_msgs = detect_crash_conditions(data)
                if crash_msgs:
                    if not last_crash_status.get(symbol):
                        msg = [f"⚠️ [{symbol}] 급락 신호"]
                        msg.extend([f"[{symbol}] {m}" for m in crash_msgs])
                        msg.append('━━━━━━━━━━━━━━━━━━━')
                        
                        analysis_msgs = analyze_symbol(symbol)
                        if analysis_msgs:
                            msg.append("📊 [기술 분석]")
                            if isinstance(analysis_msgs, list):
                                msg.extend(analysis_msgs)
                            else:
                                msg.append(analysis_msgs)
                        
                        send_telegram('\n'.join(msg))
                        last_crash_status[symbol] = True
                else:
                    last_crash_status[symbol] = False

            except Exception as e:
                print(f"❌ {symbol} 스파이크 감지 중 오류 발생: {e}")
                traceback.print_exc()

        time.sleep(SPIKE_POLL_INTERVAL_SECONDS)

if __name__ == '__main__':
    # 1) 전략 분석 스레드
    t1 = Thread(target=strategy_loop, daemon=True)
    # 2) 스파이크 감지 스레드
    t2 = Thread(target=spike_loop, daemon=True)

    t1.start()
    t2.start()

    # Flask 서버 실행
    app.run(host='0.0.0.0', port=8080)
