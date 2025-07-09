import requests
import pandas as pd
from strategy import analyze_indicators, generate_trade_plan
from spike_detector import detect_spike, detect_crash

BASE_URL = 'https://api.mexc.com/api/v3/klines'


def fetch_ohlcv(symbol: str, interval: str = '1m', limit: int = 100):
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume'
        ])
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        return df
    except Exception as e:
        print(f"❌ {symbol} 데이터 가져오기 실패: {e}")
        return None


def analyze_symbol(symbol: str):
    df = fetch_ohlcv(symbol)
    if df is None or len(df) < 50:
        print(f"⚠️ {symbol} 데이터 부족 또는 수집 실패")
        return None

    messages = []

    spike_msg = detect_spike(symbol, df)
    if spike_msg:
        messages.append(spike_msg)

    crash_msg = detect_crash(symbol, df)
    if crash_msg:
        messages.append(crash_msg)

    direction, score, summary = analyze_indicators(df)
    price = df['close'].iloc[-1]

    if direction != 'NONE':
        plan = generate_trade_plan(df, direction=direction, leverage=10)
        summary_text = "\n".join([
            f"- {k}: {v}" for k, v in summary.items()
        ])
        strategy_msg = f"""
📊 {symbol.upper()} 기술 분석 (MEXC)
🕒 최근 가격: ${plan['price']:,.2f}

🔵 추천 방향: {direction}
▶️ 종합 분석 점수: {score} / 5.0

📌 지표별 상태:
{summary_text}

💰 진입 권장가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🎯 익절가: {plan['take_profit']}
        """
        messages.append(strategy_msg)

    else:
        summary_text = "\n".join([
            f"- {k}: {v}" for k, v in summary.items()
        ])
        fallback_msg = f"""
📊 {symbol.upper()} 분석 결과
🕒 최근 가격: ${price:,.2f}

⚠️ 방향성 판단 애매 (NONE)
▶️ 종합 분석 점수: {score} / 5.0

📌 지표별 상태:
{summary_text}

📌 관망 유지 권장
        """
        messages.append(fallback_msg)

    return messages if messages else None
