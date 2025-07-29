import json
import os
import csv
from datetime import datetime

# 저장 경로 설정
LOG_DIR = "simulation_logs"
POSITIONS_FILE = os.path.join(LOG_DIR, "positions.json")
RESULTS_FILE = os.path.join(LOG_DIR, "results.json")
BALANCE_FILE = os.path.join(LOG_DIR, "balance.txt")
CSV_EXPORT_FILE = os.path.join(LOG_DIR, "results_export.csv")
CSV_BY_COIN_DIR = os.path.join(LOG_DIR, "export_by_coin")

# 초기 잔고 설정
INITIAL_BALANCE = 100.0

# 디렉터리 생성
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CSV_BY_COIN_DIR, exist_ok=True)

# 가상 지갑 초기화
if not os.path.exists(BALANCE_FILE):
    with open(BALANCE_FILE, 'w') as f:
        f.write(str(INITIAL_BALANCE))

# 기존 포지션 불러오기
def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, 'r') as f:
            return json.load(f)
    return []

# 포지션 저장
def save_positions(positions):
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(positions, f, indent=2)

# 결과 저장
def save_result(entry, result):
    data = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, 'r') as f:
            data = json.load(f)
    # result dict may include updated fields (pnl, real_pnl, current_balance, etc.)
    data.append({**entry, **result})
    with open(RESULTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    export_results_to_csv(data)
    export_results_by_coin(data)

# 잔고 업데이트
def update_balance(pnl):
    with open(BALANCE_FILE, 'r') as f:
        balance = float(f.read())
    balance += pnl
    with open(BALANCE_FILE, 'w') as f:
        f.write(str(balance))

# 현재 열린 포지션 조회
def get_open_position(symbol):
    positions = load_positions()
    for p in positions:
        if p.get('symbol') == symbol and p.get('status') == 'OPEN':
            return p
    return None

# 진입 포지션 기록 (기존보다 score 높으면 교체)
def add_virtual_trade(entry):
    current = get_open_position(entry['symbol'])
    new_score = entry.get('score', 0)

    if current:
        current_score = current.get('score', 0)
        if new_score > current_score:
            # 기존 포지션 종료 처리
            current['status'] = 'CLOSED_BY_SIGNAL'
            current['close_time'] = datetime.now().isoformat()
            current['pnl'] = 0  # 중립 종료
            save_result(current, current)
            print(f"🔁 [전환] {entry['symbol']} 기존 포지션 종료 후 점수 높은 신호로 진입")
        else:
            print(f"⛔ {entry['symbol']} 기존 포지션 점수가 더 높거나 같음 → 진입 무시")
            return

    positions = load_positions()
    entry['open_time'] = datetime.now().isoformat()
    entry['status'] = 'OPEN'
    positions.append(entry)
    save_positions(positions)
    print(f"💾 [모의 진입 기록] {entry['symbol']} {entry['direction']} @ {entry['entry']}")

# 실시간 가격 기반 포지션 체크 (외부에서 호출)
def check_positions(current_prices: dict):
    positions = load_positions()
    updated = []
    for p in positions:
        if p.get('status') != 'OPEN':
            updated.append(p)
            continue
        symbol = p['symbol']
        price = current_prices.get(symbol)
        if price is None:
            updated.append(p)
            continue

        pnl = 0.0
        if p['direction'] == 'LONG':
            if price >= p['tp']:
                pnl = (p['tp'] - p['entry']) * 20  # 레버리지 20배
                p['status'] = 'TP'
            elif price <= p['sl']:
                pnl = (p['sl'] - p['entry']) * 20
                p['status'] = 'SL'
        else:
            if price <= p['tp']:
                pnl = (p['entry'] - p['tp']) * 20
                p['status'] = 'TP'
            elif price >= p['sl']:
                pnl = (p['entry'] - p['sl']) * 20
                p['status'] = 'SL'

        if p['status'] in ('TP', 'SL'):
            p['close_time'] = datetime.now().isoformat()
            p['pnl'] = round(pnl, 4)

            # 💰 실질 수익 계산 (기본 자본 100 USDT × 레버리지 20)
            position_size = INITIAL_BALANCE * 20
            qty = position_size / p['entry']
            if p['status'] == 'TP':
                real_pnl = (p['entry'] - p['tp']) * qty if p['direction'] == 'SHORT' else (p['tp'] - p['entry']) * qty
            else:
                real_pnl = (p['sl'] - p['entry']) * qty if p['direction'] == 'SHORT' else (p['entry'] - p['sl']) * qty
            p['real_pnl'] = round(real_pnl, 4)

            # 💵 잔고 반영 및 기록
            with open(BALANCE_FILE, 'r') as f:
                balance = float(f.read())
            updated_balance = balance + real_pnl
            p['current_balance'] = round(updated_balance, 4)

            save_result(p, p)
            update_balance(real_pnl)
            print(f"✅ [포지션 종료] {symbol} {p['status']} | Real PnL: {real_pnl:.4f}, Balance: {updated_balance:.4f}")
        updated.append(p)

    save_positions(updated)

# CSV 파일로 결과 전체 내보내기
def export_results_to_csv(results):
    if not results:
        return
    keys = [
        'symbol', 'direction', 'entry', 'tp', 'sl', 'score', 'status',
        'pnl', 'real_pnl', 'current_balance', 'open_time', 'close_time'
    ]
    with open(CSV_EXPORT_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, '') for k in keys})

# CSV 파일로 코인별 내보내기
def export_results_by_coin(results):
    if not results:
        return
    coins = {}
    for row in results:
        symbol = row.get('symbol')
        if not symbol:
            continue
        coins.setdefault(symbol, []).append(row)

    keys = [
        'symbol', 'direction', 'entry', 'tp', 'sl', 'score', 'status',
        'pnl', 'real_pnl', 'current_balance', 'open_time', 'close_time'
    ]

    for symbol, rows in coins.items():
        filename = os.path.join(CSV_BY_COIN_DIR, f"{symbol}.csv")
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, '') for k in keys})
