# multi_factor_trend_strategy.py

import pandas as pd
import numpy as np
from notifier import send_telegram

# 전략 파라미터
REGIME_ADX_8H = 25      # 8시간 ADX 임계
BB_WIDTH_8H  = 0.02     # 8시간 볼린저 밴드 폭 임계
EMA_SHORT    = 20       # EMA 단기 기간
EMA_LONG     = 50       # EMA 장기 기간
ADX_1H_TH    = 20       # 2시간봉 ADX 임계
VOL_MUL      = 1.2      # 체결량 배수 임계
RSI_TH_LONG  = 70       # RSI 과매수 임계
RSI_TH_SHORT = 30       # RSI 과매도 임계
ATR_SL       = 1.5      # ATR 기반 손절 배수
ATR_TP1      = 1.0      # ATR 기반 1차 익절 배수
ATR_TP2      = 2.0      # ATR 기반 2차 익절 배수
ATR_TRAIL    = 1.0      # ATR 기반 트레일링 스탑 배수


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_s = pd.Series(plus_dm, index=high.index).rolling(period).mean()
    minus_s = pd.Series(minus_dm, index=high.index).rolling(period).mean()
    plus_di = 100 * plus_s / atr
    minus_di = 100 * minus_s / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(period).mean()


def compute_regime_8h(df8h: pd.DataFrame) -> pd.Series:
    adx8 = compute_adx(df8h['high'], df8h['low'], df8h['close'], period=14)
    ma = df8h['close'].rolling(20).mean()
    std = df8h['close'].rolling(20).std()
    bbw = std * 2 / ma
    return (adx8 > REGIME_ADX_8H) & (bbw > BB_WIDTH_8H)


def compute_1h_indicators(df2h: pd.DataFrame) -> pd.DataFrame:
    df = df2h.copy()
    df['ema_s']  = df['close'].ewm(span=EMA_SHORT, adjust=False).mean()
    df['ema_l']  = df['close'].ewm(span=EMA_LONG, adjust=False).mean()
    df['adx1h']  = compute_adx(df['high'], df['low'], df['close'], period=14)
    delta       = df['close'].diff()
    gain        = delta.clip(lower=0)
    loss        = -delta.clip(upper=0)
    avg_gain    = gain.rolling(14).mean()
    avg_loss    = loss.rolling(14).mean()
    df['rsi1h'] = 100 - (100 / (1 + avg_gain / avg_loss))
    ma20        = df['close'].rolling(20).mean()
    sd20        = df['close'].rolling(20).std()
    df['bb_u']  = ma20 + sd20 * 2
    df['bb_l']  = ma20 - sd20 * 2
    df['vol_ma'] = df['volume'].rolling(20).mean()
    prev        = df['close'].shift(1)
    tr          = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev).abs(),
        (df['low'] - prev).abs()
    ], axis=1).max(axis=1)
    df['ATR']   = tr.rolling(14).mean()
    return df.dropna()


def run_multi_factor_live(symbol: str, df15: pd.DataFrame):
    """
    실시간 15분봉 데이터(df15)로 2H/8H 레짐 필터 적용 후, 직전 2시간봉 바에서
    멀티-팩터 조건 충족 시 Telegram 메시지를 깔끔한 형식으로 전송합니다.
    """
    # 2H/8H 리샘플링
    df2h = df15.resample('2H').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()
    df8h = df15.resample('8H').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()

    regime8h = compute_regime_8h(df8h)
    regime2h = regime8h.reindex(df2h.index, method='ffill').fillna(False)
    df2     = compute_1h_indicators(df2h)
    if len(df2) < 2:
        return

    # 직전 바 분석
    row = df2.iloc[-2]
    t   = df2.index[-2]
    if not regime2h.iloc[-2]:
        return

    long_cond = (
        (row.ema_s > row.ema_l or row.close > row.bb_u)
        and row.adx1h > ADX_1H_TH
        and row.rsi1h < RSI_TH_LONG
        and row.volume > row.vol_ma * VOL_MUL
    )
    short_cond = (
        (row.ema_s < row.ema_l or row.close < row.bb_l)
        and row.adx1h > ADX_1H_TH
        and row.rsi1h > RSI_TH_SHORT
        and row.volume > row.vol_ma * VOL_MUL
    )

    if not (long_cond or short_cond):
        return

    direction = "LONG 📈" if long_cond else "SHORT 📉"
    msg = (
        f"📊 MultiFactorTrend Signal\n"
        f"• Symbol: {symbol}\n"
        f"• Direction: {direction}\n"
        f"• Time: {t.strftime('%Y-%m-%d %H:%M')}"
    )
    send_telegram(msg)
