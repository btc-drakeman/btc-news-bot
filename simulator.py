import json, os, csv, time
from datetime import datetime
from typing import Dict, Any
from config import SYMBOLS, SPIKE_POLL_INTERVAL_SECONDS
from price_fetcher import get_all_prices

LOG_DIR = "simulation_logs"
POSITIONS_FILE = os.path.join(LOG_DIR, "positions.json")
RESULTS_FILE = os.path.join(LOG_DIR, "results.json")
BALANCE_FILE = os.path.join(LOG_DIR, "balance.txt")
CSV_EXPORT_FILE = os.path.join(LOG_DIR, "results_export.csv")
CSV_BY_COIN_DIR = os.path.join(LOG_DIR, "export_by_coin")

INITIAL_BALANCE = 100.0  # 단위: 가상 포인트

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CSV_BY_COIN_DIR, exist_ok=True)

def _load_json(path: str, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_balance() -> float:
    if not os.path.exists(BALANCE_FILE):
        with open(BALANCE_FILE, "w") as f: f.write(str(INITIAL_BALANCE))
        return INITIAL_BALANCE
    try:
        return float(open(BALANCE_FILE).read().strip())
    except Exception:
        return INITIAL_BALANCE

def _save_balance(v: float):
    with open(BALANCE_FILE, "w") as f: f.write(f"{v:.4f}")

def add_virtual_trade(entry: Dict[str, Any]):
    positions = _load_json(POSITIONS_FILE, [])
    entry["status"] = "OPEN"
    entry["open_time"] = datetime.utcnow().isoformat()
    positions.append(entry)
    _save_json(POSITIONS_FILE, positions)

def _close_position(p: Dict[str, Any], price: float, reason: str):
    results = _load_json(RESULTS_FILE, [])
    balance = _load_balance()

    direction = p["direction"]
    entry = p["entry"]
    pnl = (price - entry) if direction == "LONG" else (entry - price)

    p["status"] = reason
    p["close_time"] = datetime.utcnow().isoformat()
    p["pnl"] = round(pnl, 6)
    p["current_balance"] = round(balance + pnl, 4)

    results.append(p)
    _save_json(RESULTS_FILE, results)

    _save_balance(balance + pnl)

def export_results_csv():
    results = _load_json(RESULTS_FILE, [])
    if not results: return
    keys = ['symbol','direction','entry','tp','sl','score','status','pnl','current_balance','open_time','close_time']
    with open(CSV_EXPORT_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in results:
            w.writerow({k: row.get(k, "") for k in keys})
    by_coin = {}
    for r in results:
        by_coin.setdefault(r["symbol"], []).append(r)
    for sym, rows in by_coin.items():
        path = os.path.join(CSV_BY_COIN_DIR, f"{sym}.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in keys})

def check_positions():
    """퍼센트 기반 TP/SL 판정 루프."""
    while True:
        prices = get_all_prices(SYMBOLS)
        positions = _load_json(POSITIONS_FILE, [])
        changed = False

        for p in positions:
            if p.get("status") != "OPEN":
                continue
            sym = p["symbol"]
            if sym not in prices:
                continue
            price = prices[sym]

            if p["direction"] == "LONG":
                if price >= p["tp"]:
                    _close_position(p, price, "TP"); changed = True
                elif price <= p["sl"]:
                    _close_position(p, price, "SL"); changed = True
            else:
                if price <= p["tp"]:
                    _close_position(p, price, "TP"); changed = True
                elif price >= p["sl"]:
                    _close_position(p, price, "SL"); changed = True

        if changed:
            _save_json(POSITIONS_FILE, positions)
            export_results_csv()

        time.sleep(SPIKE_POLL_INTERVAL_SECONDS)
