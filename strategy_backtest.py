import pandas as pd
import numpy as np

# ✅ 최적 보유시간 계산 함수 (백테스트 기반)
def get_optimal_hold_period(df: pd.DataFrame, direction: str, max_hold: int = 24) -> int:
    """
    df: 최근 15분봉 데이터 (close 컬럼 포함)
    direction: 'long' or 'short'
    max_hold: 최대 보유 봉 수 (기본 24봉 = 6시간)
    """
    best_hold = 1
    best_return = -np.inf

    for hold in range(1, max_hold + 1):
        returns = []
        for i in range(len(df) - hold):
            entry = df['close'].iloc[i]
            exit = df['close'].iloc[i + hold]

            if direction == 'long':
                r = (exit - entry) / entry
            elif direction == 'short':
                r = (entry - exit) / entry
            else:
                continue

            returns.append(r)

        if not returns:
            continue

        avg_return = np.mean(returns)
        if avg_return > best_return:
            best_return = avg_return
            best_hold = hold

    return best_hold
