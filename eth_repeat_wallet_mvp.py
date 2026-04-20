#!/usr/bin/env python3
"""
eth_repeat_wallet_mvp.py

Etherscan V2 기반 반복 지갑(허브 후보) 탐지 MVP
- 시드 주소 목록을 입력받아
- 최근 ERC-20 전송 내역을 수집하고
- 공통 상대 주소를 집계한 뒤
- 허브 후보 점수를 계산합니다.
- 허브 후보가 대표 거래소 주소로 전송한 흔적이 있으면 exchange_hits로 표시합니다.
- 시드 주소에서 어떤 토큰이 어디로 나갔는지 상세 출금 내역도 함께 출력/CSV 저장합니다.
- 의미 있는 온체인 결과는 텔레그램으로도 알림 전송합니다.

기본 체인: Ethereum Mainnet (chainid=1)
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Tuple

import requests


API_URL = "https://api.etherscan.io/v2/api"
DB_PATH = "repeat_wallets.db"

# 대표 거래소 핫월렛/입금 주소 일부
# 완전한 목록은 아니며, 강한 신호를 잡는 1차 필터 용도
EXCHANGE_WALLETS = {
    # Binance
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "BINANCE",
    "0xd551234ae421e3bcba99a0da6d736074f22192ff": "BINANCE",
    "0x564286362092d8e7936f0549571a803b203aaced": "BINANCE",
    "0x0681d8db095565fe8a346fa0277bffde9c0edbbf": "BINANCE",
    "0x28c6c06298d514db089934071355e5743bf21d60": "BINANCE",

    # OKX
    "0x1ab4971b1a5d0b22c1ff6d69b6b437f93d1b6f54": "OKX",
    "0x4e9ce36e442e55ecd9025b9a6e0d88485d628a67": "OKX",

    # Coinbase
    "0x503828976d22510aad0201ac7ec88293211d23da": "COINBASE",
    "0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740": "COINBASE",

    # Bybit
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "BYBIT",
}

ROUTER_OR_PROTOCOL_ADDRESSES = {
    "0x000000000004444c5dc75cb358380d2e3de08a90": "UNISWAP_V4_POOL_MANAGER",
    "0x5e1f62dac767b0491e3ce72469c217365d5b48cc": "OKX_DEX_ROUTER",
}

IGNORE_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
}

QUOTE_TOKENS = {
    "ETH", "WETH", "USDT", "USDC", "USDE", "DAI", "WBTC",
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


@dataclass
class Transfer:
    chainid: str
    wallet: str
    block_number: int
    timestamp: int
    tx_hash: str
    from_addr: str
    to_addr: str
    token_symbol: str
    token_name: str
    contract_address: str
    value_raw: str
    token_decimal: int


def normalize(addr: str) -> str:
    return addr.strip().lower()


def utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def shorten(addr: str, head: int = 6, tail: int = 4) -> str:
    addr = normalize(addr)
    if len(addr) <= head + tail:
        return addr
    return f"{addr[:head]}...{addr[-tail:]}"




def get_address_kind_and_label(addr: str) -> Tuple[str, str]:
    addr = normalize(addr)
    if addr in IGNORE_ADDRESSES:
        return "ignore", "ZERO_ADDRESS"
    if addr in EXCHANGE_WALLETS:
        return "exchange", EXCHANGE_WALLETS[addr]
    if addr in ROUTER_OR_PROTOCOL_ADDRESSES:
        return "protocol", ROUTER_OR_PROTOCOL_ADDRESSES[addr]
    return "unknown", ""


def is_quote_token(symbol: str) -> bool:
    return (symbol or "").upper() in QUOTE_TOKENS


def infer_swap_action_for_seed(
    conn: sqlite3.Connection,
    chainid: str,
    seed: str,
    tx_hash: str,
) -> Tuple[str, str]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT from_addr, to_addr, token_symbol, value_raw, token_decimal
        FROM transfers
        WHERE chainid = ? AND wallet = ? AND tx_hash = ?
        """,
        (chainid, normalize(seed), tx_hash),
    ).fetchall()

    sent_symbols = []
    recv_symbols = []

    for from_addr, to_addr, token_symbol, value_raw, token_decimal in rows:
        symbol = (token_symbol or "").upper().strip()
        if not symbol:
            continue

        from_addr = normalize(from_addr)
        to_addr = normalize(to_addr)

        try:
            value_int = int(value_raw or "0")
        except Exception:
            value_int = 0
        if value_int <= 0:
            continue

        if from_addr == normalize(seed) and to_addr != normalize(seed):
            sent_symbols.append(symbol)
        elif to_addr == normalize(seed) and from_addr != normalize(seed):
            recv_symbols.append(symbol)

    sent = sorted(set(sent_symbols))
    recv = sorted(set(recv_symbols))

    if not sent and not recv:
        return "OTHER", "-"

    sent_quote = [s for s in sent if is_quote_token(s)]
    sent_alt = [s for s in sent if not is_quote_token(s)]
    recv_quote = [s for s in recv if is_quote_token(s)]
    recv_alt = [s for s in recv if not is_quote_token(s)]

    if sent_quote and recv_alt:
        return "BUY", ", ".join(recv_alt)
    if sent_alt and recv_quote:
        return "SELL", ", ".join(sent_alt)
    if sent_alt and recv_alt:
        return "SWAP", f"{', '.join(sent_alt)} -> {', '.join(recv_alt)}"

    return "OTHER", "-"


def format_token_amount(value_raw: str, token_decimal: int) -> str:
    try:
        value_int = int(value_raw)
        decimals = max(int(token_decimal or 0), 0)
        value = value_int / (10 ** decimals) if decimals else float(value_int)

        if value == 0:
            return "0"
        if value >= 1:
            return f"{value:,.4f}".rstrip("0").rstrip(".")
        return f"{value:.8f}".rstrip("0").rstrip(".")
    except Exception:
        return value_raw


def ensure_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chainid TEXT NOT NULL,
            wallet TEXT NOT NULL,
            block_number INTEGER,
            timestamp INTEGER NOT NULL,
            tx_hash TEXT NOT NULL,
            from_addr TEXT NOT NULL,
            to_addr TEXT NOT NULL,
            token_symbol TEXT,
            token_name TEXT,
            contract_address TEXT,
            value_raw TEXT,
            token_decimal INTEGER,
            UNIQUE(chainid, wallet, tx_hash, from_addr, to_addr, contract_address, value_raw)
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS address_labels (
            address TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            label TEXT NOT NULL
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS sent_alerts (
            alert_key TEXT PRIMARY KEY,
            alert_type TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        '''
    )
    conn.commit()


def seed_exchange_labels(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    for address, label in EXCHANGE_WALLETS.items():
        cur.execute(
            "INSERT OR REPLACE INTO address_labels (address, kind, label) VALUES (?, ?, ?)",
            (normalize(address), "exchange", label),
        )

    for address, label in ROUTER_OR_PROTOCOL_ADDRESSES.items():
        cur.execute(
            "INSERT OR REPLACE INTO address_labels (address, kind, label) VALUES (?, ?, ?)",
            (normalize(address), "protocol", label),
        )

    for address in IGNORE_ADDRESSES:
        cur.execute(
            "INSERT OR REPLACE INTO address_labels (address, kind, label) VALUES (?, ?, ?)",
            (normalize(address), "ignore", "ZERO_ADDRESS"),
        )

    conn.commit()


def read_seed_addresses(path: str) -> List[str]:
    seeds = []
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            line = normalize(line)
            if line:
                seeds.append(line)
    if not seeds:
        raise ValueError("시드 주소가 없습니다. seed 파일을 확인하세요.")
    return list(dict.fromkeys(seeds))


def etherscan_get(params: Dict[str, str], timeout: int = 20) -> dict:
    api_key = os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 ETHERSCAN_API_KEY가 없습니다.")

    full_params = dict(params)
    full_params["apikey"] = api_key

    resp = requests.get(API_URL, params=full_params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    status = str(data.get("status", ""))
    message = str(data.get("message", ""))
    result = data.get("result")

    if status == "0":
        text = str(result)
        if "No transactions found" in text:
            return {"status": "1", "message": "OK", "result": []}
        raise RuntimeError(f"Etherscan error: message={message} result={result}")

    return data


def fetch_erc20_transfers(
    address: str,
    chainid: str = "1",
    page: int = 1,
    offset: int = 100,
    startblock: int = 0,
    endblock: int = 99999999,
    sort: str = "desc",
) -> List[Transfer]:
    data = etherscan_get(
        {
            "chainid": chainid,
            "module": "account",
            "action": "tokentx",
            "address": address,
            "page": str(page),
            "offset": str(offset),
            "startblock": str(startblock),
            "endblock": str(endblock),
            "sort": sort,
        }
    )

    items = data.get("result", [])
    out: List[Transfer] = []

    for item in items:
        out.append(
            Transfer(
                chainid=chainid,
                wallet=normalize(address),
                block_number=int(item.get("blockNumber", 0)),
                timestamp=int(item.get("timeStamp", 0)),
                tx_hash=item.get("hash", ""),
                from_addr=normalize(item.get("from", "")),
                to_addr=normalize(item.get("to", "")),
                token_symbol=item.get("tokenSymbol", ""),
                token_name=item.get("tokenName", ""),
                contract_address=normalize(item.get("contractAddress", "")),
                value_raw=item.get("value", "0"),
                token_decimal=int(item.get("tokenDecimal", 0) or 0),
            )
        )
    return out


def save_transfers(conn: sqlite3.Connection, transfers: Iterable[Transfer]) -> int:
    cur = conn.cursor()
    count = 0
    for t in transfers:
        cur.execute(
            '''
            INSERT OR IGNORE INTO transfers
            (chainid, wallet, block_number, timestamp, tx_hash, from_addr, to_addr,
             token_symbol, token_name, contract_address, value_raw, token_decimal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                t.chainid,
                t.wallet,
                t.block_number,
                t.timestamp,
                t.tx_hash,
                t.from_addr,
                t.to_addr,
                t.token_symbol,
                t.token_name,
                t.contract_address,
                t.value_raw,
                t.token_decimal,
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


def collect_for_seed(
    conn: sqlite3.Connection,
    seed: str,
    chainid: str,
    days: int,
    offset: int,
    max_pages: int,
    sleep_sec: float,
) -> int:
    cutoff = utc_now_ts() - days * 86400
    total_saved = 0

    for page in range(1, max_pages + 1):
        try:
            transfers = fetch_erc20_transfers(
                address=seed,
                chainid=chainid,
                page=page,
                offset=offset,
                sort="desc",
            )
        except Exception as e:
            print(f"[WARN] fetch 실패 seed={seed} page={page}: {e}")
            break

        if not transfers:
            break

        recent = [t for t in transfers if t.timestamp >= cutoff]
        if recent:
            saved = save_transfers(conn, recent)
            total_saved += saved

        oldest_ts = min(t.timestamp for t in transfers)
        if oldest_ts < cutoff:
            break

        time.sleep(sleep_sec)

    return total_saved


def find_exchange_hits(
    conn: sqlite3.Connection,
    candidate_addresses: List[str],
    chainid: str,
    days: int,
) -> Dict[str, List[str]]:
    cutoff = utc_now_ts() - days * 86400
    cur = conn.cursor()
    hits: Dict[str, List[str]] = collections.defaultdict(list)

    for addr in candidate_addresses:
        rows = cur.execute(
            """
            SELECT DISTINCT to_addr
            FROM transfers
            WHERE chainid = ?
              AND timestamp >= ?
              AND from_addr = ?
            """,
            (chainid, cutoff, normalize(addr)),
        ).fetchall()

        for (to_addr,) in rows:
            to_addr = normalize(to_addr)
            kind, label = get_address_kind_and_label(to_addr)
            if kind == "exchange":
                hits[normalize(addr)].append(label)

    return hits


def build_hub_scores(
    conn: sqlite3.Connection,
    chainid: str,
    days: int,
    min_shared_seed_count: int = 2,
) -> List[dict]:
    cutoff = utc_now_ts() - days * 86400
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT wallet, from_addr, to_addr, timestamp, token_symbol, contract_address
        FROM transfers
        WHERE chainid = ? AND timestamp >= ?
        """,
        (chainid, cutoff),
    ).fetchall()

    per_counterparty_seed_count: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    direction_counts: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    token_set: Dict[str, set] = collections.defaultdict(set)

    for wallet, from_addr, to_addr, timestamp, token_symbol, contract_address in rows:
        wallet = normalize(wallet)
        from_addr = normalize(from_addr)
        to_addr = normalize(to_addr)

        if from_addr == wallet:
            cp = to_addr
            direction_counts[cp]["out_from_seed"] += 1
        elif to_addr == wallet:
            cp = from_addr
            direction_counts[cp]["into_seed"] += 1
        else:
            continue

        addr_kind, _ = get_address_kind_and_label(cp)
        if addr_kind == "ignore":
            continue

        per_counterparty_seed_count[cp][wallet] += 1
        if token_symbol:
            token_set[cp].add(token_symbol)

    results = []
    for cp, seed_counter in per_counterparty_seed_count.items():
        shared_seed_count = len(seed_counter)
        if shared_seed_count < min_shared_seed_count:
            continue

        total_interactions = sum(seed_counter.values())
        out_cnt = direction_counts[cp]["out_from_seed"]
        in_cnt = direction_counts[cp]["into_seed"]
        directional_diversity = int(out_cnt > 0) + int(in_cnt > 0)
        addr_kind, addr_label = get_address_kind_and_label(cp)

        score = (
            shared_seed_count * 3
            + min(total_interactions, 10)
            + (2 if directional_diversity == 2 else 0)
            + min(len(token_set[cp]), 5)
        )

        if addr_kind == "exchange":
            score += 3
        elif addr_kind == "protocol":
            score += 1

        results.append(
            {
                "address": cp,
                "score": score,
                "shared_seed_count": shared_seed_count,
                "total_interactions": total_interactions,
                "out_from_seed": out_cnt,
                "into_seed": in_cnt,
                "token_variety": len(token_set[cp]),
                "label_kind": addr_kind,
                "label": addr_label or "",
                "exchange_hits": "",
                "seeds": ", ".join(sorted(seed_counter.keys())),
            }
        )

    candidate_addresses = [r["address"] for r in results]
    exchange_hits = find_exchange_hits(conn, candidate_addresses, chainid, days)

    for row in results:
        hits = exchange_hits.get(normalize(row["address"]), [])
        uniq_hits = sorted(set(hits))
        row["exchange_hits"] = ", ".join(uniq_hits) if uniq_hits else ""
        if uniq_hits:
            row["score"] += 5

    results.sort(key=lambda x: (-x["score"], -x["shared_seed_count"], -x["total_interactions"]))
    return results


def get_seed_outflow_details(
    conn: sqlite3.Connection,
    seeds: List[str],
    chainid: str,
    days: int,
    candidate_rows: List[dict],
) -> List[dict]:
    cutoff = utc_now_ts() - days * 86400
    cur = conn.cursor()

    candidate_map = {normalize(r["address"]): r for r in candidate_rows}
    outflows: List[dict] = []

    for seed in seeds:
        seed = normalize(seed)
        rows = cur.execute(
            """
            SELECT
                timestamp,
                tx_hash,
                from_addr,
                to_addr,
                token_symbol,
                token_name,
                contract_address,
                value_raw,
                token_decimal
            FROM transfers
            WHERE chainid = ?
              AND timestamp >= ?
              AND wallet = ?
              AND from_addr = ?
            ORDER BY timestamp DESC
            """,
            (chainid, cutoff, seed, seed),
        ).fetchall()

        for (
            timestamp,
            tx_hash,
            from_addr,
            to_addr,
            token_symbol,
            token_name,
            contract_address,
            value_raw,
            token_decimal,
        ) in rows:
            to_addr = normalize(to_addr)
            target_kind, target_label = get_address_kind_and_label(to_addr)
            candidate = candidate_map.get(to_addr)
            action, action_token = infer_swap_action_for_seed(conn, chainid, seed, tx_hash)

            outflows.append(
                {
                    "time_utc": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "seed": seed,
                    "seed_short": shorten(seed),
                    "to_addr": to_addr,
                    "to_short": shorten(to_addr),
                    "token_symbol": token_symbol or "-",
                    "token_name": token_name or "-",
                    "amount": format_token_amount(value_raw, token_decimal),
                    "contract_address": contract_address,
                    "tx_hash": tx_hash,
                    "target_kind": target_kind,
                    "target_label": target_label or "-",
                    "swap_action": action,
                    "swap_token": action_token,
                    "is_hub_candidate": "Y" if candidate else "",
                    "hub_score": candidate["score"] if candidate else "",
                    "hub_shared_seed_count": candidate["shared_seed_count"] if candidate else "",
                    "hub_total_interactions": candidate["total_interactions"] if candidate else "",
                    "hub_exchange_hits": candidate["exchange_hits"] if candidate else "",
                    "hub_label": candidate["label"] if candidate else "",
                    "hub_label_kind": candidate["label_kind"] if candidate else "",
                }
            )

    outflows.sort(key=lambda x: (x["time_utc"], x["seed"], x["to_addr"]), reverse=True)
    return outflows


def print_seed_outflow_details(rows: List[dict], top: int = 20) -> None:
    print("\n=== 시드 출금 상세 ===")
    if not rows:
        print("(없음)")
        return

    for row in rows[:top]:
        print(
            f"{row['time_utc']} | "
            f"seed={row['seed']} -> to={row['to_addr']} | "
            f"token={row['token_symbol']} | amount={row['amount']} | "
            f"kind={row.get('target_kind') or '-'} | label={row.get('target_label') or '-'} | "
            f"swap={row.get('swap_action') or '-'} {row.get('swap_token') or '-'} | "
            f"hub={row['is_hub_candidate'] or '-'} | "
            f"exchange={row['hub_exchange_hits'] or '-'}"
        )


def export_csv(path: str, rows: List[dict]) -> None:
    if not rows:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([])
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def send_telegram_message(msg: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TG] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 없음", flush=True)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10,
        )
        ok = resp.status_code == 200
        print(f"[TG] 전송 status={resp.status_code}", flush=True)
        if not ok:
            print(f"[TG] 응답={resp.text}", flush=True)
        return ok
    except Exception as e:
        print(f"[TG] 전송 오류: {e}", flush=True)
        return False


def make_alert_key(*parts: str) -> str:
    raw = "||".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def has_sent_alert(conn: sqlite3.Connection, alert_key: str) -> bool:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM sent_alerts WHERE alert_key = ?",
        (alert_key,),
    ).fetchone()
    return row is not None


def mark_alert_sent(conn: sqlite3.Connection, alert_key: str, alert_type: str) -> None:
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT OR IGNORE INTO sent_alerts (alert_key, alert_type, created_at)
        VALUES (?, ?, ?)
        ''',
        (alert_key, alert_type, utc_now_ts()),
    )
    conn.commit()


def send_hub_candidate_alerts(conn: sqlite3.Connection, hub_rows: List[dict]) -> None:
    print("\n=== 온체인 텔레그램 알림: 허브 후보 ===")
    sent_count = 0

    for row in hub_rows:
        shared = int(row.get("shared_seed_count") or 0)
        score = int(row.get("score") or 0)
        exchange = row.get("exchange_hits") or "-"

        if row["address"] in IGNORE_ADDRESSES:
            continue
        if shared < 2:
            continue
        if score < 12 and exchange == "-":
            continue

        alert_type = "hub_exchange" if exchange != "-" else "hub_candidate"
        alert_key = make_alert_key(
            alert_type,
            row["address"],
            score,
            shared,
            exchange,
            row.get("seeds", ""),
        )

        if has_sent_alert(conn, alert_key):
            continue

        msg = (
            "[ONCHAIN] 허브 감지\n"
            f"hub: {shorten(row['address'])}\n"
            f"score: {score}\n"
            f"shared: {shared}\n"
            f"interactions: {row.get('total_interactions', 0)}\n"
            f"exchange: {exchange}\n"
            f"kind: {row.get('label_kind') or '-'}\n"
            f"label: {row.get('label') or '-'}"
        )

        if send_telegram_message(msg):
            mark_alert_sent(conn, alert_key, alert_type)
            sent_count += 1

    print(f"[TG] 허브 후보 알림 전송 수: {sent_count}", flush=True)


def send_outflow_alerts(conn: sqlite3.Connection, outflow_rows: List[dict]) -> None:
    print("\n=== 온체인 텔레그램 알림: 출금 상세 ===")
    sent_count = 0

    for row in outflow_rows:
        exchange = row.get("hub_exchange_hits") or "-"
        is_hub = row.get("is_hub_candidate") == "Y"
        shared = int(row.get("hub_shared_seed_count") or 0)
        score = int(row.get("hub_score") or 0)
        target_kind = row.get("target_kind") or "-"
        target_label = row.get("target_label") or "-"
        swap_action = row.get("swap_action") or "-"
        swap_token = row.get("swap_token") or "-"

        should_alert = False
        alert_type = ""

        if exchange != "-":
            should_alert = True
            alert_type = "outflow_exchange"
        elif target_kind == "protocol" and swap_action in {"BUY", "SELL", "SWAP"}:
            should_alert = True
            alert_type = "outflow_protocol_swap"
        elif is_hub and shared >= 2 and score >= 12:
            should_alert = True
            alert_type = "outflow_hub"

        if not should_alert:
            continue
        if row["to_addr"] in IGNORE_ADDRESSES:
            continue

        alert_key = make_alert_key(
            alert_type,
            row["tx_hash"],
            row["seed"],
            row["to_addr"],
            row["token_symbol"],
            row["amount"],
            exchange,
            swap_action,
            swap_token,
        )

        if has_sent_alert(conn, alert_key):
            continue

        msg = (
            "[ONCHAIN] 시드 출금 감지\n"
            f"seed: {shorten(row['seed'])}\n"
            f"to: {shorten(row['to_addr'])}\n"
            f"kind: {target_kind}\n"
            f"label: {target_label}\n"
            f"token: {row['token_symbol']}\n"
            f"amount: {row['amount']}\n"
            f"swap: {swap_action}\n"
            f"swap_token: {swap_token}\n"
            f"hub: {'Y' if is_hub else '-'}\n"
            f"shared: {shared if is_hub else '-'}\n"
            f"score: {score if is_hub else '-'}\n"
            f"exchange: {exchange}"
        )

        if send_telegram_message(msg):
            mark_alert_sent(conn, alert_key, alert_type)
            sent_count += 1

    print(f"[TG] 출금 상세 알림 전송 수: {sent_count}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Etherscan V2 반복 지갑 탐지 MVP")
    parser.add_argument("--seeds", required=True, help="시드 주소 txt 파일 경로")
    parser.add_argument("--chainid", default="1", help="EVM chainid. Ethereum=1")
    parser.add_argument("--days", type=int, default=30, help="최근 며칠 데이터 볼지")
    parser.add_argument("--offset", type=int, default=100, help="페이지당 전송 수")
    parser.add_argument("--max-pages", type=int, default=10, help="주소당 최대 페이지 수")
    parser.add_argument("--sleep-sec", type=float, default=0.4, help="API 호출 간 대기")
    parser.add_argument("--top", type=int, default=20, help="상위 몇 개 허브 후보/상세 출력할지")
    parser.add_argument("--csv", default="hub_candidates.csv", help="결과 CSV 파일명")
    args = parser.parse_args()

    seeds = read_seed_addresses(args.seeds)

    conn = sqlite3.connect(DB_PATH)
    ensure_db(conn)
    seed_exchange_labels(conn)

    print(f"[INFO] seed 수: {len(seeds)}")
    print(f"[INFO] chainid={args.chainid}, days={args.days}, offset={args.offset}, max_pages={args.max_pages}")

    total_saved = 0
    for idx, seed in enumerate(seeds, start=1):
        print(f"[INFO] ({idx}/{len(seeds)}) 수집 중: {seed}")
        saved = collect_for_seed(
            conn=conn,
            seed=seed,
            chainid=args.chainid,
            days=args.days,
            offset=args.offset,
            max_pages=args.max_pages,
            sleep_sec=args.sleep_sec,
        )
        total_saved += saved
        print(f"       저장된 신규 전송: {saved}")

    print(f"[INFO] 총 신규 저장 전송 수: {total_saved}")

    rows = build_hub_scores(
        conn=conn,
        chainid=args.chainid,
        days=args.days,
        min_shared_seed_count=2,
    )

    export_csv(args.csv, rows)

    print("\n=== 상위 허브 후보 ===")
    for row in rows[: args.top]:
        print(
            f"score={row['score']:>2} | shared={row['shared_seed_count']} | "
            f"interactions={row['total_interactions']} | "
            f"exchange={row.get('exchange_hits') or '-'} | "
            f"kind={row.get('label_kind') or '-'} | "
            f"label={row['label'] or '-'} | "
            f"{row['address']}"
        )

    outflow_rows = get_seed_outflow_details(
        conn=conn,
        seeds=seeds,
        chainid=args.chainid,
        days=args.days,
        candidate_rows=rows,
    )
    print_seed_outflow_details(outflow_rows, top=args.top)

    detail_csv = f"seed_outflows_{args.csv}"
    export_csv(detail_csv, outflow_rows)

    send_hub_candidate_alerts(conn, rows)
    send_outflow_alerts(conn, outflow_rows)

    print(f"\n[INFO] 결과 CSV 저장: {args.csv}")
    print(f"[INFO] 시드 출금 상세 CSV 저장: {detail_csv}")
    print(f"[INFO] SQLite DB 저장: {DB_PATH}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
