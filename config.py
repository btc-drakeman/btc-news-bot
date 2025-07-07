# config.py

# ✅ 텔레그램 봇 설정
BOT_TOKEN = '7213273799:AAEi6KtkzHqwKkrsQgaxSgKSnRWbXM70gUA'
USER_IDS = ['7505401062', '7576776181']
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# ✅ 분석 대상 심볼 (MEXC 선물 표기 기준)
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT']

# ✅ MEXC API Key (선택사항: 없으면 인증 헤더 생략 가능)
MEXC_API_KEY = ''

# ✅ 각 심볼별 최대 보유 시간 (분) – 추후 포지션 추적 기능용
MAX_HOLD_MINUTES = {
    'BTCUSDT': 30,
    'ETHUSDT': 60,
    'XRPUSDT': 90,
    'SOLUSDT': 45,
}
