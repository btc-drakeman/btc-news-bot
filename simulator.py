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
    data.append(result | entry)
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

# 진입 포지션 기록
def add_virtual_trade(entry):
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
        if p['status'] != 'OPEN':
            updated.append(p)
            continue
        symbol = p['symbol']
        price = current_prices.get(symbol)
        if not price:
            updated.append(p)
            continue

        pnl = 0
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
            save_result(p, p)
            update_balance(pnl)
            print(f"✅ [포지션 종료] {symbol} {p['status']} | PnL: {pnl:.4f}")
        updated.append(p)

    save_positions(updated)

# CSV 파일로 결과 전체 내보내기
def export_results_to_csv(results):
    if not results:
        return
    keys = [
        'symbol', 'direction', 'entry', 'tp', 'sl', 'score', 'status',
        'pnl', 'open_time', 'close_time'
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
        if symbol not in coins:
            coins[symbol] = []
        coins[symbol].append(row)

    keys = [
        'symbol', 'direction', 'entry', 'tp', 'sl', 'score', 'status',
        'pnl', 'open_time', 'close_time'
    ]

    for symbol, rows in coins.items():
        filename = os.path.join(CSV_BY_COIN_DIR, f"{symbol}.csv")
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, '') for k in keys})
