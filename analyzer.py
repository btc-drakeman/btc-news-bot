from utils import fetch_ohlcv_all_timeframes
from strategy_short import analyze_indicators_short
from strategy_long import predict_from_condition, should_enter_v6, run_backtest
from signal_message_generator import generate_signal_message
from datetime import datetime
import pandas as pd

def analyze_symbol(symbol: str):
    print(f"🔍 분석 시작: {symbol}")
    data = fetch_ohlcv_all_timeframes(symbol)

    if not data or '15m' not in data:
        print(f"❌ 데이터 부족: {symbol}")
        return None

    df = data['15m']
    df['timestamp'] = pd.to_datetime(df.index, unit='ms')
    df = df.set_index('timestamp')

    try:
        # 롱 전략 점수 계산
        latest_i = len(df) - 2
        should_enter, score = should_enter_v6(latest_i, df)
        print(f"📊 {symbol} 진입 점수: {score:.2f}, 진입 조건 통과 여부: {should_enter}")

        if should_enter:
            entry_price = df['close'].iloc[latest_i]
            result_df = run_backtest(df)
            print(f"📁 {symbol} 백테스트 결과 수: {len(result_df)}")

            if result_df.empty:
                print(f"⚠️ {symbol} 백테스트 결과 없음")
                return None

            expected_return, tp_ratio, sl_ratio, avg_bars = predict_from_condition(result_df)

            indicators = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'RSI': '상승 중',
                'MACD': '중립',
                'EMA': '접근 중',
                'EMA Slope': '-0.01',
                'Bollinger': '중심선 근처',
                'Volume': '보통'
            }

            message = generate_signal_message(
                symbol=symbol,
                current_price=entry_price,
                indicators=indicators,
                action='진입',
                score=score,
                direction="long",
                entry_price=(entry_price * 0.995, entry_price * 1.005),
                stop_loss=entry_price * (1 - abs(sl_ratio)),
                take_profit=entry_price * (1 + abs(tp_ratio)),
                expected_return=expected_return,
                expected_hold=avg_bars,
                consistency=True,
                alignment=True,
                breakout=False,
                candle_signal='상승 반전형',
                reliability='높음'
            )
            return message

        # 숏 전략 점수 계산
        score, action, direction, indicators = analyze_indicators_short(data)
        print(f"📉 {symbol} 숏 전략 점수: {score:.2f}, 조건: RSI={indicators['RSI']}, MACD={indicators['MACD']}")

        if score >= 2.1 and indicators['RSI'] in ['과매수', '하락 중'] and indicators['MACD'] in ['하락 강화', '약한 하락']:
            entry_price = df['close'].iloc[-1]
            expected_return = -2.1
            tp_ratio = 0.56
            sl_ratio = 0.18
            avg_bars = 6

            message = generate_signal_message(
                symbol=symbol,
                current_price=entry_price,
                indicators=indicators,
                action='진입',
                score=score,
                direction="short",
                entry_price=(entry_price * 0.995, entry_price * 1.005),
                stop_loss=entry_price * (1 + abs(sl_ratio)),
                take_profit=entry_price * (1 - abs(tp_ratio)),
                expected_return=expected_return,
                expected_hold=avg_bars,
                consistency=True,
                alignment=False,
                breakout=False,
                candle_signal='하락 반전형',
                reliability='중간'
            )
            return message

    except Exception as e:
        print(f"❌ 분석 오류: {e}")
        return None
