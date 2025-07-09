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
        print(f"❌ {symbol} ({interval}) 데이터 가져오기 실패: {e}")
        return None

def analyze_symbol(symbol: str):
    timeframes = ['1m', '5m', '15m']
    results = []

    for tf in timeframes:
        df = fetch_ohlcv(symbol, interval=tf)
        if df is None or len(df) < 50:
            continue
        direction, score, _ = analyze_indicators(df)
        results.append((direction, score))

    # 다중 타임프레임 분석 종합
    long_scores = [s for d, s in results if d == 'LONG']
    short_scores = [s for d, s in results if d == 'SHORT']

    avg_long = sum(long_scores) / len(long_scores) if long_scores else 0
    avg_short = sum(short_scores) / len(short_scores) if short_scores else 0

    if avg_long >= 4.0 and avg_long > avg_short:
        final_direction = 'LONG'
        final_score = round(avg_long, 2)
    elif avg_short >= 4.0 and avg_short > avg_long:
        final_direction = 'SHORT'
        final_score = round(avg_short, 2)
    else:
        final_direction = 'NONE'
        final_score = round(max(avg_long, avg_short), 2)

    # 최신 가격은 1분봉 기준
    df = fetch_ohlcv(symbol, interval='1m')
    if df is None:
        return None

    messages = []

    spike_msg = detect_spike(symbol, df)
    if spike_msg:
        messages.append(spike_msg)

    crash_msg = detect_crash(symbol, df)
    if crash_msg:
        messages.append(crash_msg)

    price = df['close'].iloc[-1]
    _, _, summary = analyze_indicators(df)
    summary_text = "\\n".join([f"- {k}: {v}" for k, v in summary.items()])

    if final_direction != 'NONE':
        plan = generate_trade_plan(df, direction=final_direction, leverage=10)
        strategy_msg = f"""
📊 {symbol.upper()} 기술 분석 (MEXC)
🕒 최근 가격: ${plan['price']:,.2f}

🔵 추천 방향: {final_direction}
▶️ 종합 분석 점수: {final_score} / 5.0

📌 지표별 상태:
{summary_text}

💰 진입 권장가: {plan['entry_range']}
🛑 손절가: {plan['stop_loss']}
🎯 익절가: {plan['take_profit']}
        """
        messages.append(strategy_msg)
    else:
        fallback_msg = f"""
📊 {symbol.upper()} 분석 결과
🕒 최근 가격: ${price:,.2f}

⚠️ 방향성 판단 애매 (NONE)
▶️ 종합 분석 점수: {final_score} / 5.0

📌 지표별 상태:
{summary_text}

📌 관망 유지 권장
        """
        messages.append(fallback_msg)

    return messages if messages else None
