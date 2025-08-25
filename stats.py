# stats.py
import threading, time, csv, os
from collections import deque

_LOCK = threading.Lock()
_BUF  = deque(maxlen=2000)
_CNT  = 0
CSV_PATH = os.getenv("MF_METRICS_CSV", "/tmp/mf_metrics.csv")  # 필요시 환경변수로 경로 변경

def record(symbol: str, direction_hint: str, raw: float, p: float,
           cond_15m: bool, cond_5m: bool, rsi: float, vol_ok: bool):
    global _CNT
    with _LOCK:
        _BUF.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "dir_hint": direction_hint,
            "raw": round(raw, 3),
            "p": round(p, 3),
            "c15": int(cond_15m),
            "c5": int(cond_5m),
            "rsi": round(rsi, 1),
            "vol": int(vol_ok),
        })
        _CNT += 1
        _append_csv(_BUF[-1])
        if _CNT % 100 == 0:
            _print_summary()

def _append_csv(row: dict):
    exists = os.path.exists(CSV_PATH)
    try:
        with open(CSV_PATH, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"[stats] CSV write error: {e}", flush=True)

def _print_summary():
    # 최근 500건 기준 분포 요약
    last = list(_BUF)[-500:] if len(_BUF) > 500 else list(_BUF)
    if not last:
        return
    bins = {"<0.1":0, "0.1~0.3":0, "0.3~0.5":0, "0.5~0.58":0, ">=0.58":0}
    core_on = near = 0
    for r in last:
        p = r["p"]
        if p < 0.1: bins["<0.1"] += 1
        elif p < 0.3: bins["0.1~0.3"] += 1
        elif p < 0.5: bins["0.3~0.5"] += 1
        elif p < 0.58: bins["0.5~0.58"] += 1
        else: bins[">=0.58"] += 1
        if r["c15"] and r["c5"]:
            core_on += 1
        if 0.55 <= p < 0.58:
            near += 1
    total = len(last)
    print(
        "[STATS] recent={} p-dist {} | CORE(15m&5m ON)={} | NEAR(0.55~0.58)={}".format(
            total, bins, core_on, near
        ),
        flush=True
    )
