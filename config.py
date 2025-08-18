# =========================
# 기본 설정
# =========================

# 분석 대상 심볼 (MEXC 선물/현물 공통 표기)
SYMBOLS = [
    'BTCUSDT','ETHUSDT','ETHFIUSDT','SUIUSDT','XRPUSDT',
    'FLOKIUSDT','ANIUSDT','SPKUSDT','OMNIUSDT','MOCAUSDT',
    'MYXUSDT', 'PUFFERUSDT', 'PROVEUSDT', 'DOGEUSDT'
]

TELEGRAM_TOKEN = '7213273799:AAEcuDAiureO1jY32JMtELcWsoJjHub5Pv0'
TELEGRAM_CHAT_ID = ['7505401062', '7576776181']

# 전략 루프(멀티프레임) 체크 주기(초)
STRATEGY_INTERVAL_SECONDS = 300  # 5분

# 가격 모니터링(포지션 TP/SL 체결 감시) 주기(초)
SPIKE_POLL_INTERVAL_SECONDS = 1

# =========================
# 리스크/청산 설정 (ATR 제거 버전)
# =========================
# 퍼센트 기반(비율) TP/SL (예: 0.010 = 1.0%)
SL_PCT = 0.010   # 1.0% 손절
TP_PCT = 0.016   # 1.6% 익절 (R:R ~ 1:1.6)

# 포맷팅 자릿수
def format_price(x: float) -> str:
    if x >= 1000: return f"{x:.2f}"
    if x >= 1:    return f"{x:.3f}"
    if x >= 0.1:  return f"{x:.4f}"
    if x >= 0.01: return f"{x:.5f}"
    return f"{x:.8f}"
