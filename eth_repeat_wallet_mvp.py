#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import os
import json
import sqlite3
import time
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

import requests

API_URL = "https://api.etherscan.io/v2/api"
METADATA_API_V1_URL = "https://api-metadata.etherscan.io/v1/api.ashx"
DB_PATH = "repeat_wallets.db"

ADDRESS_BOOK_PATH_DEFAULT = "address_book.json"
ADDRESS_BOOK_RELOAD_SECONDS_DEFAULT = 60
AUTO_EXCHANGE_ENRICH_LIMIT_DEFAULT = 25
AUTO_EXCHANGE_ENRICH_CACHE_HOURS_DEFAULT = 24 * 7
BOOTSTRAP_EXCHANGE_LABEL_SLUGS_DEFAULT = [
    "binance", "coinbase", "kraken", "bybit", "okx", "bitfinex", "kucoin", "htx", "huobi"
]

DEFAULT_EXCHANGE_WALLETS = {
    # BINANCE
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "BINANCE",
    "0x28c6c06298d514db089934071355e5743bf21d60": "BINANCE",
    "0xd551234ae421e3bcba99a0da6d736074f22192ff": "BINANCE",
    "0x564286362092d8e7936f0549571a803b203aaced": "BINANCE",
    # OKX
    "0x1ab4971b1a5d0b22c1ff6d69b6b437f93d1b6f54": "OKX",
    "0x4e9ce36e442e55ecd9025b9a6e0d88485d628a67": "OKX",
    # COINBASE
    "0x503828976d22510aad0201ac7ec88293211d23da": "COINBASE",
    "0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740": "COINBASE",
    # BYBIT
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "BYBIT",
    # KRAKEN
    "0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0": "KRAKEN",
    # BITFINEX
    "0x742d35cc6634c0532925a3b844bc454e4438f44e": "BITFINEX",
}

DEFAULT_ROUTER_OR_PROTOCOL_ADDRESSES = {
    "0x000000000004444c5dc75cb358380d2e3de08a90": "UNISWAP_V4_POOL_MANAGER",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "UNISWAP_V3_ROUTER",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "UNISWAP_V3_ROUTER_2",
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "UNISWAP_UNIVERSAL_ROUTER",
    "0x1111111254fb6c44bac0bed2854e76f90643097d": "1INCH_ROUTER",
    "0x5e1f62dac767b0491e3ce72469c217365d5b48cc": "OKX_DEX_ROUTER",
}

DEFAULT_IGNORE_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
}

EXCHANGE_WALLETS: Dict[str, str] = {}
ROUTER_OR_PROTOCOL_ADDRESSES: Dict[str, str] = {}
IGNORE_ADDRESSES: Set[str] = set()
ADDRESS_BOOK_STATE = {
    "path": None,
    "last_mtime": None,
    "last_loaded_at": 0.0,
}
KNOWN_EXCHANGE_KEYWORDS = {
    "binance": "BINANCE", "coinbase": "COINBASE", "kraken": "KRAKEN", "bybit": "BYBIT",
    "okx": "OKX", "okex": "OKX", "bitfinex": "BITFINEX", "kucoin": "KUCOIN",
    "htx": "HTX", "huobi": "HUOBI", "gate.io": "GATEIO", "gateio": "GATEIO",
    "mexc": "MEXC", "crypto.com": "CRYPTOCOM", "cryptocom": "CRYPTOCOM",
}

QUOTE_TOKENS = {"WETH", "ETH", "USDT", "USDC", "DAI", "WBTC"}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 알림 완화용 임계값
HUB_MIN_SHARED_FOR_ALERT = 3
HUB_MIN_SCORE_FOR_ALERT = 18
OUTFLOW_MIN_SHARED_FOR_ALERT = 3
OUTFLOW_MIN_SCORE_FOR_ALERT = 18

# flow 추적 관련 기본값
FLOW_MIN_SHARED_FOR_EXPANSION = 2
FLOW_MIN_SCORE_FOR_EXPANSION = 12
FLOW_MIN_AMOUNT_RATIO = 0.60
FLOW_MAX_NEXT_EDGES = 12
FLOW_MAX_TRACK_ADDRS = 30
FLOW_ALERT_EXCHANGE_ONLY_DEFAULT = True
FLOW_ALERT_MAX_AGE_HOURS_DEFAULT = 12
FLOW_MAX_ALERTS_PER_RUN_DEFAULT = 5

# active hub watcher 기본값
ACTIVE_HUB_MIN_SHARED = 2
ACTIVE_HUB_MIN_SCORE = 12
ACTIVE_HUB_TTL_HOURS = 168  # 7일
ACTIVE_HUB_MAX_TRACK = 40
ACTIVE_HUB_SCAN_MAX_PAGES = 3
ACTIVE_HUB_MIN_OUTGOING_COUNT_FOR_B = 2
ACTIVE_HUB_BURST_WINDOW_HOURS = 12


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


def build_default_address_book() -> dict:
    return {
        "exchange_wallets": dict(sorted((normalize(k), v) for k, v in DEFAULT_EXCHANGE_WALLETS.items())),
        "router_or_protocol_addresses": dict(sorted((normalize(k), v) for k, v in DEFAULT_ROUTER_OR_PROTOCOL_ADDRESSES.items())),
        "ignore_addresses": sorted(normalize(x) for x in DEFAULT_IGNORE_ADDRESSES),
    }


def write_default_address_book(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_default_address_book(), f, ensure_ascii=False, indent=2, sort_keys=True)


def apply_address_book(payload: dict) -> None:
    global EXCHANGE_WALLETS, ROUTER_OR_PROTOCOL_ADDRESSES, IGNORE_ADDRESSES

    exchange_wallets = {
        normalize(addr): str(label).strip()
        for addr, label in dict(payload.get("exchange_wallets", {})).items()
        if str(addr).strip() and str(label).strip()
    }
    router_addresses = {
        normalize(addr): str(label).strip()
        for addr, label in dict(payload.get("router_or_protocol_addresses", {})).items()
        if str(addr).strip() and str(label).strip()
    }
    ignore_addresses = {
        normalize(addr)
        for addr in list(payload.get("ignore_addresses", []))
        if str(addr).strip()
    }

    EXCHANGE_WALLETS = exchange_wallets
    ROUTER_OR_PROTOCOL_ADDRESSES = router_addresses
    IGNORE_ADDRESSES = ignore_addresses


def persist_current_address_book(path: Optional[str] = None) -> None:
    normalized_path = os.path.abspath(path or ADDRESS_BOOK_STATE.get("path") or ADDRESS_BOOK_PATH_DEFAULT)
    payload = {
        "exchange_wallets": dict(sorted(EXCHANGE_WALLETS.items())),
        "router_or_protocol_addresses": dict(sorted(ROUTER_OR_PROTOCOL_ADDRESSES.items())),
        "ignore_addresses": sorted(IGNORE_ADDRESSES),
    }
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    ADDRESS_BOOK_STATE["path"] = normalized_path
    ADDRESS_BOOK_STATE["last_mtime"] = os.path.getmtime(normalized_path) if os.path.exists(normalized_path) else None
    ADDRESS_BOOK_STATE["last_loaded_at"] = time.time()


def load_address_book(path: str, create_if_missing: bool = True) -> None:
    normalized_path = os.path.abspath(path)
    if create_if_missing and not os.path.exists(normalized_path):
        write_default_address_book(normalized_path)

    with open(normalized_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    apply_address_book(payload)
    ADDRESS_BOOK_STATE["path"] = normalized_path
    ADDRESS_BOOK_STATE["last_mtime"] = os.path.getmtime(normalized_path) if os.path.exists(normalized_path) else None
    ADDRESS_BOOK_STATE["last_loaded_at"] = time.time()

    print(
        f"[ADDR] 로드 완료 | exchanges={len(EXCHANGE_WALLETS)} | "
        f"routers={len(ROUTER_OR_PROTOCOL_ADDRESSES)} | ignore={len(IGNORE_ADDRESSES)} | "
        f"path={normalized_path}",
        flush=True,
    )


def maybe_reload_address_book(path: Optional[str] = None, min_interval_seconds: int = ADDRESS_BOOK_RELOAD_SECONDS_DEFAULT) -> bool:
    book_path = os.path.abspath(path or ADDRESS_BOOK_STATE.get("path") or ADDRESS_BOOK_PATH_DEFAULT)
    now = time.time()
    last_loaded_at = float(ADDRESS_BOOK_STATE.get("last_loaded_at") or 0.0)

    if min_interval_seconds > 0 and (now - last_loaded_at) < min_interval_seconds:
        return False

    if not os.path.exists(book_path):
        print(f"[ADDR] 주소록 파일 없음, 기본값 재생성: {book_path}", flush=True)
        write_default_address_book(book_path)

    current_mtime = os.path.getmtime(book_path)
    last_mtime = ADDRESS_BOOK_STATE.get("last_mtime")
    if last_mtime is not None and current_mtime == last_mtime:
        ADDRESS_BOOK_STATE["last_loaded_at"] = now
        return False

    load_address_book(book_path, create_if_missing=True)
    return True


def utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def shorten(addr: str, head: int = 6, tail: int = 4) -> str:
    addr = normalize(addr)
    if len(addr) <= head + tail:
        return addr
    return f"{addr[:head]}...{addr[-tail:]}"


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


def amount_as_float(value_raw: str, token_decimal: int) -> float:
    try:
        value_int = int(value_raw)
        decimals = max(int(token_decimal or 0), 0)
        return value_int / (10 ** decimals) if decimals else float(value_int)
    except Exception:
        return 0.0


def classify_address(addr: str) -> Tuple[str, str]:
    addr = normalize(addr)
    if addr in IGNORE_ADDRESSES:
        return "ignore", "IGNORE"
    if addr in EXCHANGE_WALLETS:
        return "exchange", EXCHANGE_WALLETS[addr]
    if addr in ROUTER_OR_PROTOCOL_ADDRESSES:
        return "protocol", ROUTER_OR_PROTOCOL_ADDRESSES[addr]
    return "unknown", ""


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
        CREATE TABLE IF NOT EXISTS exchange_labels (
            address TEXT PRIMARY KEY,
            label TEXT NOT NULL
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS address_metadata_cache (
            address TEXT PRIMARY KEY,
            chainid TEXT NOT NULL,
            source TEXT NOT NULL,
            nametag TEXT,
            labels_json TEXT,
            exchange_label TEXT,
            fetched_at INTEGER NOT NULL
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
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS active_hubs (
            address TEXT PRIMARY KEY,
            chainid TEXT NOT NULL,
            source_seeds TEXT NOT NULL,
            shared_seed_count INTEGER NOT NULL,
            score INTEGER NOT NULL,
            target_kind TEXT,
            target_label TEXT,
            first_seen_at INTEGER NOT NULL,
            activated_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            status TEXT NOT NULL,
            last_checked_at INTEGER,
            last_outgoing_at INTEGER,
            notes TEXT
        )
        '''
    )
    conn.commit()


def seed_exchange_labels(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for address, label in EXCHANGE_WALLETS.items():
        cur.execute(
            "INSERT OR REPLACE INTO exchange_labels (address, label) VALUES (?, ?)",
            (normalize(address), label),
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


def guess_exchange_label_from_metadata(nametag: str, labels: List[str]) -> str:
    joined = " | ".join([nametag or ""] + list(labels or [])).lower()
    if "exchange" not in joined and not any(k in joined for k in KNOWN_EXCHANGE_KEYWORDS):
        return ""
    for key, canon in KNOWN_EXCHANGE_KEYWORDS.items():
        if key in joined:
            return canon
    return ""


def get_cached_metadata(conn: sqlite3.Connection, address: str, chainid: str, cache_hours: int) -> Optional[dict]:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT source, nametag, labels_json, exchange_label, fetched_at
        FROM address_metadata_cache
        WHERE address = ? AND chainid = ?
        """,
        (normalize(address), chainid),
    ).fetchone()
    if not row:
        return None
    fetched_at = int(row[4] or 0)
    if cache_hours > 0 and fetched_at + cache_hours * 3600 < utc_now_ts():
        return None
    try:
        labels = json.loads(row[2] or "[]")
    except Exception:
        labels = []
    return {"source": row[0] or "cache", "nametag": row[1] or "", "labels": labels, "exchange_label": row[3] or "", "fetched_at": fetched_at}


def cache_metadata_result(conn: sqlite3.Connection, address: str, chainid: str, source: str, nametag: str, labels: List[str], exchange_label: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO address_metadata_cache (address, chainid, source, nametag, labels_json, exchange_label, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(address) DO UPDATE SET
            chainid=excluded.chainid, source=excluded.source, nametag=excluded.nametag,
            labels_json=excluded.labels_json, exchange_label=excluded.exchange_label, fetched_at=excluded.fetched_at
        """,
        (normalize(address), chainid, source, nametag or "", json.dumps(labels or [], ensure_ascii=False), exchange_label or "", utc_now_ts()),
    )
    conn.commit()


def add_exchange_address_to_books(conn: sqlite3.Connection, address: str, label: str, address_book_path: Optional[str] = None) -> bool:
    address = normalize(address)
    label = str(label or "").strip().upper()
    if not address or not label:
        return False
    existing = EXCHANGE_WALLETS.get(address)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO exchange_labels (address, label) VALUES (?, ?)", (address, label))
    conn.commit()
    if existing == label:
        return False
    EXCHANGE_WALLETS[address] = label
    persist_current_address_book(address_book_path)
    print(f"[ADDR][AUTO] 거래소 주소 추가: {address} -> {label}", flush=True)
    return True


def get_address_nametag_metadata(conn: sqlite3.Connection, address: str, chainid: str, cache_hours: int) -> Optional[dict]:
    cached = get_cached_metadata(conn, address, chainid, cache_hours)
    if cached is not None:
        return cached
    data = etherscan_get({"chainid": chainid, "module": "nametag", "action": "getaddresstag", "address": normalize(address)}, timeout=20)
    items = data.get("result", []) or []
    if not items:
        cache_metadata_result(conn, address, chainid, "getaddresstag", "", [], "")
        return None
    item = items[0]
    nametag = str(item.get("nametag") or "")
    labels = [str(x).strip() for x in list(item.get("labels") or []) if str(x).strip()]
    exchange_label = guess_exchange_label_from_metadata(nametag, labels)
    cache_metadata_result(conn, address, chainid, "getaddresstag", nametag, labels, exchange_label)
    return {"source": "getaddresstag", "nametag": nametag, "labels": labels, "exchange_label": exchange_label, "fetched_at": utc_now_ts()}


def collect_unknown_addresses_for_enrichment(conn: sqlite3.Connection, chainid: str, days: int, limit: int) -> List[str]:
    cutoff = utc_now_ts() - days * 86400
    cur = conn.cursor()
    rows = cur.execute(
        """
        WITH seen AS (
            SELECT from_addr AS address, COUNT(*) AS cnt FROM transfers WHERE chainid = ? AND timestamp >= ? GROUP BY from_addr
            UNION ALL
            SELECT to_addr AS address, COUNT(*) AS cnt FROM transfers WHERE chainid = ? AND timestamp >= ? GROUP BY to_addr
        )
        SELECT address, SUM(cnt) AS total_cnt FROM seen GROUP BY address ORDER BY total_cnt DESC LIMIT ?
        """,
        (chainid, cutoff, chainid, cutoff, max(limit * 8, limit)),
    ).fetchall()
    out = []
    for address, _ in rows:
        address = normalize(address)
        if not address or address in IGNORE_ADDRESSES or address in EXCHANGE_WALLETS or address in ROUTER_OR_PROTOCOL_ADDRESSES:
            continue
        out.append(address)
        if len(out) >= limit:
            break
    return out


def auto_enrich_exchange_addresses(conn: sqlite3.Connection, chainid: str, days: int, address_book_path: str, max_addresses: int, cache_hours: int, sleep_sec: float) -> int:
    if max_addresses <= 0:
        return 0
    candidates = collect_unknown_addresses_for_enrichment(conn, chainid, days, max_addresses)
    if not candidates:
        return 0
    added = 0
    for idx, address in enumerate(candidates, start=1):
        try:
            meta = get_address_nametag_metadata(conn, address, chainid, cache_hours=cache_hours)
        except Exception as e:
            print(f"[ADDR][AUTO] 메타데이터 조회 실패 {address}: {e}", flush=True)
            if idx == 1:
                print("[ADDR][AUTO] getaddresstag 사용 불가 시 Etherscan Pro Plus 이상 권한이 필요할 수 있습니다.", flush=True)
            break
        if not meta:
            continue
        exchange_label = meta.get("exchange_label") or ""
        if exchange_label and add_exchange_address_to_books(conn, address, exchange_label, address_book_path=address_book_path):
            added += 1
        time.sleep(max(sleep_sec, 0.55))
    return added


def etherscan_metadata_v1_get(params: Dict[str, str], timeout: int = 30) -> str:
    api_key = os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 ETHERSCAN_API_KEY가 없습니다.")
    full_params = dict(params)
    full_params["apikey"] = api_key
    resp = requests.get(METADATA_API_V1_URL, params=full_params, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def bootstrap_exchange_addresses_from_etherscan(conn: sqlite3.Connection, chainid: str, label_slugs: List[str], address_book_path: str) -> int:
    added = 0
    for slug in label_slugs:
        slug = str(slug or "").strip().lower()
        if not slug:
            continue
        try:
            csv_text = etherscan_metadata_v1_get({"module": "nametag", "action": "exportaddresstags", "label": slug, "format": "csv"}, timeout=60)
        except Exception as e:
            print(f"[ADDR][BOOTSTRAP] label={slug} export 실패: {e}", flush=True)
            continue
        reader = csv.DictReader(io.StringIO(csv_text), delimiter=';')
        for row in reader:
            address = normalize(row.get("address", ""))
            nametag = str(row.get("nametag") or "")
            labels_slug = str(row.get("labels_slug") or "")
            exchange_label = guess_exchange_label_from_metadata(nametag, [labels_slug, slug, row.get("labels") or ""]) or KNOWN_EXCHANGE_KEYWORDS.get(slug, slug.upper())
            if address:
                if add_exchange_address_to_books(conn, address, exchange_label, address_book_path=address_book_path):
                    added += 1
                cache_metadata_result(conn, address, chainid, f"exportaddresstags:{slug}", nametag, [row.get("labels") or "", labels_slug], exchange_label)
    return added


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


def collect_for_address(
    conn: sqlite3.Connection,
    address: str,
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
                address=address,
                chainid=chainid,
                page=page,
                offset=offset,
                sort="desc",
            )
        except Exception as e:
            print(f"[WARN] fetch 실패 address={address} page={page}: {e}")
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


def collect_for_seed(
    conn: sqlite3.Connection,
    seed: str,
    chainid: str,
    days: int,
    offset: int,
    max_pages: int,
    sleep_sec: float,
) -> int:
    return collect_for_address(conn, seed, chainid, days, offset, max_pages, sleep_sec)


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
            '''
            SELECT DISTINCT to_addr
            FROM transfers
            WHERE chainid = ?
              AND timestamp >= ?
              AND from_addr = ?
            ''',
            (chainid, cutoff, normalize(addr)),
        ).fetchall()

        for (to_addr,) in rows:
            to_addr = normalize(to_addr)
            if to_addr in EXCHANGE_WALLETS:
                hits[normalize(addr)].append(EXCHANGE_WALLETS[to_addr])

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
        '''
        SELECT wallet, from_addr, to_addr, timestamp, token_symbol, contract_address
        FROM transfers
        WHERE chainid = ? AND timestamp >= ?
        ''',
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

        kind, _ = classify_address(cp)
        if kind == "ignore":
            continue

        per_counterparty_seed_count[cp][wallet] += 1
        if token_symbol:
            token_set[cp].add(token_symbol)

    labels = dict(cur.execute("SELECT address, label FROM exchange_labels").fetchall())

    results = []
    for cp, seed_counter in per_counterparty_seed_count.items():
        shared_seed_count = len(seed_counter)
        if shared_seed_count < min_shared_seed_count:
            continue

        total_interactions = sum(seed_counter.values())
        out_cnt = direction_counts[cp]["out_from_seed"]
        in_cnt = direction_counts[cp]["into_seed"]
        directional_diversity = int(out_cnt > 0) + int(in_cnt > 0)
        target_kind, target_label = classify_address(cp)

        score = (
            shared_seed_count * 3
            + min(total_interactions, 10)
            + (2 if directional_diversity == 2 else 0)
            + min(len(token_set[cp]), 5)
        )

        label = labels.get(cp) or target_label
        if target_kind == "exchange":
            score += 5
        elif target_kind == "protocol":
            score += 1
        if label and target_kind not in {"exchange", "protocol"}:
            score += 3

        results.append(
            {
                "address": cp,
                "score": score,
                "shared_seed_count": shared_seed_count,
                "total_interactions": total_interactions,
                "out_from_seed": out_cnt,
                "into_seed": in_cnt,
                "token_variety": len(token_set[cp]),
                "label": label or "",
                "target_kind": target_kind,
                "target_label": target_label or label or "",
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


def infer_swap_action(
    conn: sqlite3.Connection,
    chainid: str,
    wallet: str,
    tx_hash: str,
) -> Tuple[str, str]:
    cur = conn.cursor()
    rows = cur.execute(
        '''
        SELECT from_addr, to_addr, token_symbol
        FROM transfers
        WHERE chainid = ? AND tx_hash = ?
        ''',
        (chainid, tx_hash),
    ).fetchall()

    wallet = normalize(wallet)
    out_tokens = set()
    in_tokens = set()

    for from_addr, to_addr, token_symbol in rows:
        token_symbol = (token_symbol or "").upper().strip()
        if not token_symbol:
            continue
        from_addr = normalize(from_addr)
        to_addr = normalize(to_addr)
        if from_addr == wallet:
            out_tokens.add(token_symbol)
        if to_addr == wallet:
            in_tokens.add(token_symbol)

    alt_in = sorted(t for t in in_tokens if t not in QUOTE_TOKENS)
    alt_out = sorted(t for t in out_tokens if t not in QUOTE_TOKENS)
    quote_in = sorted(t for t in in_tokens if t in QUOTE_TOKENS)
    quote_out = sorted(t for t in out_tokens if t in QUOTE_TOKENS)

    if quote_out and alt_in:
        return "BUY", ",".join(alt_in[:3])
    if alt_out and quote_in:
        return "SELL", ",".join(alt_out[:3])
    if alt_in and alt_out:
        return "SWAP", ",".join((alt_in or alt_out)[:3])
    return "", ""


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
            '''
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
            ''',
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
            candidate = candidate_map.get(to_addr)
            target_kind, target_label = classify_address(to_addr)
            swap_action, swap_token = infer_swap_action(conn, chainid, seed, tx_hash)

            outflows.append(
                {
                    "timestamp": int(timestamp),
                    "time_utc": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "seed": seed,
                    "seed_short": shorten(seed),
                    "to_addr": to_addr,
                    "to_short": shorten(to_addr),
                    "token_symbol": token_symbol or "-",
                    "token_name": token_name or "-",
                    "amount": format_token_amount(value_raw, token_decimal),
                    "amount_float": amount_as_float(value_raw, token_decimal),
                    "contract_address": normalize(contract_address or ""),
                    "tx_hash": tx_hash,
                    "target_kind": target_kind,
                    "target_label": target_label or "-",
                    "swap_action": swap_action or "-",
                    "swap_token": swap_token or "-",
                    "is_hub_candidate": "Y" if candidate else "",
                    "hub_score": candidate["score"] if candidate else "",
                    "hub_shared_seed_count": candidate["shared_seed_count"] if candidate else "",
                    "hub_total_interactions": candidate["total_interactions"] if candidate else "",
                    "hub_exchange_hits": candidate["exchange_hits"] if candidate else "",
                    "hub_label": candidate["label"] if candidate else "",
                }
            )

    outflows.sort(key=lambda x: (x["timestamp"], x["seed"], x["to_addr"]), reverse=True)
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
            f"kind={row['target_kind']}({row['target_label']}) | "
            f"swap={row['swap_action']} {row['swap_token']} | "
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
    print("\n=== 온체인 텔레그램 알림: 허브 후보(강한 것만) ===")
    sent_count = 0

    for row in hub_rows:
        shared = int(row.get("shared_seed_count") or 0)
        score = int(row.get("score") or 0)
        exchange = row.get("exchange_hits") or "-"
        target_kind = row.get("target_kind") or "unknown"

        if row["address"] in IGNORE_ADDRESSES:
            continue
        if target_kind == "protocol" and exchange == "-":
            continue
        if exchange == "-" and not (shared >= HUB_MIN_SHARED_FOR_ALERT and score >= HUB_MIN_SCORE_FOR_ALERT):
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
            "[ONCHAIN] 강한 허브 감지\n"
            f"hub: {shorten(row['address'])}\n"
            f"kind: {row.get('target_kind') or '-'}\n"
            f"label: {row.get('target_label') or row.get('label') or '-'}\n"
            f"score: {score}\n"
            f"shared: {shared}\n"
            f"interactions: {row.get('total_interactions', 0)}\n"
            f"exchange: {exchange}"
        )

        if send_telegram_message(msg):
            mark_alert_sent(conn, alert_key, alert_type)
            sent_count += 1

    print(f"[TG] 허브 후보 알림 전송 수: {sent_count}", flush=True)


def send_outflow_alerts(conn: sqlite3.Connection, outflow_rows: List[dict]) -> None:
    print("\n=== 온체인 텔레그램 알림: 출금 상세(강한 것만) ===")
    sent_count = 0

    for row in outflow_rows:
        exchange = row.get("hub_exchange_hits") or "-"
        is_hub = row.get("is_hub_candidate") == "Y"
        shared = int(row.get("hub_shared_seed_count") or 0)
        score = int(row.get("hub_score") or 0)
        target_kind = row.get("target_kind") or "unknown"
        swap_action = row.get("swap_action") or "-"

        if row["to_addr"] in IGNORE_ADDRESSES:
            continue

        should_alert = False
        alert_type = ""

        if exchange != "-":
            should_alert = True
            alert_type = "outflow_exchange"
        elif target_kind == "protocol":
            should_alert = False
        elif is_hub and shared >= OUTFLOW_MIN_SHARED_FOR_ALERT and score >= OUTFLOW_MIN_SCORE_FOR_ALERT:
            should_alert = True
            alert_type = "outflow_hub"

        if not should_alert:
            continue

        alert_key = make_alert_key(
            alert_type,
            row["tx_hash"],
            row["seed"],
            row["to_addr"],
            row["token_symbol"],
            row["amount"],
            exchange,
        )

        if has_sent_alert(conn, alert_key):
            continue

        msg = (
            "[ONCHAIN] 의미 있는 출금 감지\n"
            f"seed: {shorten(row['seed'])}\n"
            f"to: {shorten(row['to_addr'])}\n"
            f"kind: {target_kind}\n"
            f"label: {row.get('target_label') or '-'}\n"
            f"token: {row['token_symbol']}\n"
            f"amount: {row['amount']}\n"
            f"swap: {swap_action} {row.get('swap_token') or '-'}\n"
            f"hub: {'Y' if is_hub else '-'}\n"
            f"shared: {shared if is_hub else '-'}\n"
            f"score: {score if is_hub else '-'}\n"
            f"exchange: {exchange}"
        )

        if send_telegram_message(msg):
            mark_alert_sent(conn, alert_key, alert_type)
            sent_count += 1

    print(f"[TG] 출금 상세 알림 전송 수: {sent_count}", flush=True)


# -----------------------------
# flow tracking
# -----------------------------

def get_recent_outgoing_transfers(
    conn: sqlite3.Connection,
    wallet: str,
    chainid: str,
    days: int,
) -> List[dict]:
    cutoff = utc_now_ts() - days * 86400
    cur = conn.cursor()
    rows = cur.execute(
        '''
        SELECT timestamp, tx_hash, from_addr, to_addr, token_symbol, token_name,
               contract_address, value_raw, token_decimal
        FROM transfers
        WHERE chainid = ?
          AND timestamp >= ?
          AND wallet = ?
          AND from_addr = ?
        ORDER BY timestamp DESC
        ''',
        (chainid, cutoff, normalize(wallet), normalize(wallet)),
    ).fetchall()

    out: List[dict] = []
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
        kind, label = classify_address(to_addr)
        out.append(
            {
                "timestamp": int(timestamp),
                "time_utc": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "tx_hash": tx_hash,
                "from_addr": normalize(from_addr),
                "to_addr": to_addr,
                "token_symbol": token_symbol or "-",
                "token_name": token_name or "-",
                "contract_address": normalize(contract_address or ""),
                "value_raw": value_raw or "0",
                "token_decimal": int(token_decimal or 0),
                "amount_float": amount_as_float(value_raw or "0", int(token_decimal or 0)),
                "amount": format_token_amount(value_raw or "0", int(token_decimal or 0)),
                "target_kind": kind,
                "target_label": label or "-",
            }
        )
    return out


def select_flow_expansion_addresses(
    seeds: List[str],
    hub_rows: List[dict],
    outflow_rows: List[dict],
    max_track_addrs: int,
) -> List[str]:
    seeds_set = {normalize(s) for s in seeds}
    candidate_map = {normalize(r["address"]): r for r in hub_rows}
    selected: List[str] = []
    seen: Set[str] = set()

    for row in outflow_rows:
        to_addr = normalize(row["to_addr"])
        kind, _ = classify_address(to_addr)
        if to_addr in seeds_set or to_addr in seen:
            continue
        if kind in {"ignore", "exchange"}:
            continue
        hub = candidate_map.get(to_addr)
        if hub:
            shared = int(hub.get("shared_seed_count") or 0)
            score = int(hub.get("score") or 0)
            if shared >= FLOW_MIN_SHARED_FOR_EXPANSION or score >= FLOW_MIN_SCORE_FOR_EXPANSION:
                seen.add(to_addr)
                selected.append(to_addr)
        elif row.get("target_kind") == "unknown":
            seen.add(to_addr)
            selected.append(to_addr)
        if len(selected) >= max_track_addrs:
            return selected

    for row in hub_rows:
        addr = normalize(row["address"])
        kind, _ = classify_address(addr)
        if addr in seeds_set or addr in seen:
            continue
        if kind in {"ignore", "exchange", "protocol"}:
            continue
        shared = int(row.get("shared_seed_count") or 0)
        score = int(row.get("score") or 0)
        if shared >= FLOW_MIN_SHARED_FOR_EXPANSION or score >= FLOW_MIN_SCORE_FOR_EXPANSION:
            seen.add(addr)
            selected.append(addr)
        if len(selected) >= max_track_addrs:
            break

    return selected


def collect_for_flow_expansion(
    conn: sqlite3.Connection,
    addresses: List[str],
    chainid: str,
    days: int,
    offset: int,
    max_pages: int,
    sleep_sec: float,
) -> int:
    total_saved = 0
    for idx, addr in enumerate(addresses, start=1):
        print(f"[FLOW] ({idx}/{len(addresses)}) 확장 수집: {addr}")
        total_saved += collect_for_address(
            conn=conn,
            address=addr,
            chainid=chainid,
            days=days,
            offset=offset,
            max_pages=max_pages,
            sleep_sec=sleep_sec,
        )
    return total_saved


def build_flow_paths(
    conn: sqlite3.Connection,
    seeds: List[str],
    chainid: str,
    days: int,
    max_hops: int = 3,
    max_time_gap_hours: int = 24,
    min_amount_ratio: float = FLOW_MIN_AMOUNT_RATIO,
    max_next_edges: int = FLOW_MAX_NEXT_EDGES,
) -> List[dict]:
    if max_hops < 2:
        return []

    cutoff = utc_now_ts() - days * 86400
    max_gap_sec = max_time_gap_hours * 3600
    visited_alert_keys: Set[str] = set()
    results: List[dict] = []

    def candidate_next_edges(current_wallet: str, prev_edge: dict) -> List[dict]:
        rows = get_recent_outgoing_transfers(conn, current_wallet, chainid, days)
        out: List[dict] = []
        for row in rows:
            if row["timestamp"] < prev_edge["timestamp"]:
                continue
            if row["timestamp"] - prev_edge["timestamp"] > max_gap_sec:
                continue
            if normalize(row["contract_address"]) != normalize(prev_edge["contract_address"]):
                continue
            if normalize(row["token_symbol"]) != normalize(prev_edge["token_symbol"]):
                continue
            prev_amt = float(prev_edge.get("amount_float") or 0.0)
            curr_amt = float(row.get("amount_float") or 0.0)
            if prev_amt > 0 and curr_amt < prev_amt * min_amount_ratio:
                continue
            out.append(row)
            if len(out) >= max_next_edges:
                break
        return out

    seeds_norm = [normalize(s) for s in seeds]
    for seed in seeds_norm:
        first_edges = get_recent_outgoing_transfers(conn, seed, chainid, days)
        for edge1 in first_edges:
            if edge1["timestamp"] < cutoff:
                continue
            if edge1["to_addr"] in IGNORE_ADDRESSES:
                continue

            chain_edges = [dict(edge1, hop=1, hop_from=seed, hop_to=edge1["to_addr"])]
            if edge1["target_kind"] == "exchange":
                continue

            frontier = [(edge1["to_addr"], chain_edges, edge1, 2)]
            while frontier:
                current_wallet, path_edges, prev_edge, next_hop = frontier.pop(0)
                if next_hop > max_hops:
                    continue
                for nxt in candidate_next_edges(current_wallet, prev_edge):
                    nxt_addr = normalize(nxt["to_addr"])
                    if nxt_addr in {normalize(e["hop_from"]) for e in path_edges}:
                        continue
                    new_path = path_edges + [dict(nxt, hop=next_hop, hop_from=current_wallet, hop_to=nxt_addr)]
                    if nxt["target_kind"] == "exchange":
                        alert_key = make_alert_key(
                            "flow_exchange",
                            seed,
                            new_path[0]["tx_hash"],
                            nxt["tx_hash"],
                            nxt["contract_address"],
                            nxt_addr,
                        )
                        if alert_key in visited_alert_keys:
                            continue
                        visited_alert_keys.add(alert_key)
                        results.append(
                            {
                                "seed": seed,
                                "start_time_utc": new_path[0]["time_utc"],
                                "end_time_utc": new_path[-1]["time_utc"],
                                "token_symbol": new_path[0]["token_symbol"],
                                "token_name": new_path[0]["token_name"],
                                "contract_address": new_path[0]["contract_address"],
                                "start_amount": new_path[0]["amount"],
                                "end_amount": new_path[-1]["amount"],
                                "hop_count": len(new_path),
                                "exchange": nxt["target_label"],
                                "path": " -> ".join(shorten(e["hop_from"]) for e in new_path) + f" -> {shorten(new_path[-1]['hop_to'])}",
                                "path_addresses": " -> ".join([e["hop_from"] for e in new_path] + [new_path[-1]["hop_to"]]),
                                "first_tx_hash": new_path[0]["tx_hash"],
                                "last_tx_hash": new_path[-1]["tx_hash"],
                                "duration_min": max(0, int((new_path[-1]["timestamp"] - new_path[0]["timestamp"]) / 60)),
                            }
                        )
                    else:
                        if next_hop < max_hops and nxt["target_kind"] != "protocol":
                            frontier.append((nxt_addr, new_path, nxt, next_hop + 1))

    results.sort(key=lambda x: (x["end_time_utc"], x["hop_count"], x["exchange"]), reverse=True)
    return results


def print_flow_paths(rows: List[dict], top: int = 20) -> None:
    print("\n=== flow 추적 결과 (거래소 도착) ===")
    if not rows:
        print("(없음)")
        return
    for row in rows[:top]:
        print(
            f"{row['end_time_utc']} | seed={shorten(row['seed'])} | token={row['token_symbol']} | "
            f"hops={row['hop_count']} | exchange={row['exchange']} | dur={row['duration_min']}m | {row['path']}"
        )


def send_flow_alerts(
    conn: sqlite3.Connection,
    flow_rows: List[dict],
    max_age_hours: int = FLOW_ALERT_MAX_AGE_HOURS_DEFAULT,
    max_alerts_per_run: int = FLOW_MAX_ALERTS_PER_RUN_DEFAULT,
) -> None:
    print("\n=== 온체인 텔레그램 알림: flow exchange only ===")
    sent_count = 0

    cutoff_ts = utc_now_ts() - max(0, int(max_age_hours)) * 3600 if max_age_hours > 0 else 0

    filtered_rows: List[dict] = []
    for row in flow_rows:
        end_time_utc = row.get("end_time_utc") or row.get("start_time_utc") or ""
        try:
            end_ts = int(datetime.strptime(end_time_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            end_ts = 0
        row["_end_ts"] = end_ts
        if cutoff_ts and end_ts and end_ts < cutoff_ts:
            continue
        filtered_rows.append(row)

    dedup_map: Dict[Tuple[str, str, str, str], dict] = {}
    for row in filtered_rows:
        dedup_key = (
            normalize(row.get("seed") or ""),
            normalize(row.get("token_symbol") or ""),
            normalize(row.get("exchange") or ""),
            normalize(row.get("path_addresses") or row.get("path") or ""),
        )
        prev = dedup_map.get(dedup_key)
        if prev is None or int(row.get("_end_ts") or 0) > int(prev.get("_end_ts") or 0):
            dedup_map[dedup_key] = row

    dedup_rows = sorted(
        dedup_map.values(),
        key=lambda x: (int(x.get("_end_ts") or 0), int(x.get("hop_count") or 0)),
        reverse=True,
    )

    final_rows = dedup_rows[:max(1, int(max_alerts_per_run))] if max_alerts_per_run > 0 else dedup_rows

    print(
        f"[FLOW] 알림 필터링 결과: raw={len(flow_rows)} -> recent={len(filtered_rows)} -> dedup={len(dedup_rows)} -> final={len(final_rows)}",
        flush=True,
    )

    for row in final_rows:
        alert_key = make_alert_key(
            "flow_exchange",
            normalize(row.get("seed") or ""),
            normalize(row.get("token_symbol") or ""),
            normalize(row.get("exchange") or ""),
            normalize(row.get("path_addresses") or row.get("path") or ""),
        )
        if has_sent_alert(conn, alert_key):
            continue

        msg = (
            "[ONCHAIN] FLOW 거래소 도착 감지\n"
            f"seed: {shorten(row['seed'])}\n"
            f"token: {row['token_symbol']}\n"
            f"start_amt: {row['start_amount']}\n"
            f"end_amt: {row['end_amount']}\n"
            f"hops: {row['hop_count']}\n"
            f"exchange: {row['exchange']}\n"
            f"dur_min: {row['duration_min']}\n"
            f"path: {row['path']}"
        )

        if send_telegram_message(msg):
            mark_alert_sent(conn, alert_key, "flow_exchange")
            sent_count += 1

    print(f"[TG] flow 거래소 도착 알림 전송 수: {sent_count}", flush=True)


# -----------------------------
# active hub watcher
# -----------------------------

def expire_old_active_hubs(conn: sqlite3.Connection, chainid: str) -> int:
    cur = conn.cursor()
    cur.execute(
        '''
        UPDATE active_hubs
        SET status = 'expired'
        WHERE chainid = ?
          AND status = 'active'
          AND expires_at <= ?
        ''',
        (chainid, utc_now_ts()),
    )
    conn.commit()
    return cur.rowcount


def activate_hubs_from_candidates(
    conn: sqlite3.Connection,
    hub_rows: List[dict],
    chainid: str,
    ttl_hours: int,
    min_shared: int,
    min_score: int,
) -> int:
    now = utc_now_ts()
    expires_at = now + ttl_hours * 3600
    cur = conn.cursor()
    activated = 0

    for row in hub_rows:
        address = normalize(row["address"])
        shared = int(row.get("shared_seed_count") or 0)
        score = int(row.get("score") or 0)
        target_kind = row.get("target_kind") or "unknown"
        if address in IGNORE_ADDRESSES:
            continue
        if target_kind in {"ignore", "exchange", "protocol"}:
            continue
        if shared < min_shared or score < min_score:
            continue

        prev = cur.execute(
            "SELECT address FROM active_hubs WHERE address = ? AND chainid = ?",
            (address, chainid),
        ).fetchone()

        cur.execute(
            '''
            INSERT INTO active_hubs
            (address, chainid, source_seeds, shared_seed_count, score, target_kind, target_label,
             first_seen_at, activated_at, expires_at, status, last_checked_at, last_outgoing_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, ?)
            ON CONFLICT(address) DO UPDATE SET
                chainid=excluded.chainid,
                source_seeds=excluded.source_seeds,
                shared_seed_count=excluded.shared_seed_count,
                score=excluded.score,
                target_kind=excluded.target_kind,
                target_label=excluded.target_label,
                expires_at=CASE
                    WHEN active_hubs.status='expired' THEN excluded.expires_at
                    ELSE MAX(active_hubs.expires_at, excluded.expires_at)
                END,
                status='active',
                notes=excluded.notes
            ''',
            (
                address,
                chainid,
                row.get("seeds", ""),
                shared,
                score,
                target_kind,
                row.get("target_label") or row.get("label") or "",
                now,
                now,
                expires_at,
                f"shared={shared},score={score}",
            ),
        )
        if prev is None:
            activated += 1

    conn.commit()
    return activated


def get_active_hubs(conn: sqlite3.Connection, chainid: str, limit: int) -> List[dict]:
    cur = conn.cursor()
    rows = cur.execute(
        '''
        SELECT address, source_seeds, shared_seed_count, score, target_kind, target_label,
               first_seen_at, activated_at, expires_at, status, last_checked_at, last_outgoing_at, notes
        FROM active_hubs
        WHERE chainid = ? AND status = 'active'
        ORDER BY score DESC, shared_seed_count DESC, activated_at DESC
        LIMIT ?
        ''',
        (chainid, limit),
    ).fetchall()

    out = []
    for r in rows:
        out.append(
            {
                "address": normalize(r[0]),
                "source_seeds": r[1] or "",
                "shared_seed_count": int(r[2] or 0),
                "score": int(r[3] or 0),
                "target_kind": r[4] or "unknown",
                "target_label": r[5] or "-",
                "first_seen_at": int(r[6] or 0),
                "activated_at": int(r[7] or 0),
                "expires_at": int(r[8] or 0),
                "status": r[9] or "active",
                "last_checked_at": int(r[10] or 0) if r[10] is not None else None,
                "last_outgoing_at": int(r[11] or 0) if r[11] is not None else None,
                "notes": r[12] or "",
            }
        )
    return out


def collect_for_active_hubs(
    conn: sqlite3.Connection,
    active_hubs: List[dict],
    chainid: str,
    days: int,
    offset: int,
    max_pages: int,
    sleep_sec: float,
) -> int:
    total_saved = 0
    for idx, hub in enumerate(active_hubs, start=1):
        print(f"[HUB] ({idx}/{len(active_hubs)}) 활성 허브 수집: {hub['address']}")
        total_saved += collect_for_address(
            conn=conn,
            address=hub["address"],
            chainid=chainid,
            days=days,
            offset=offset,
            max_pages=max_pages,
            sleep_sec=sleep_sec,
        )
    return total_saved


def touch_active_hub_checked(
    conn: sqlite3.Connection,
    chainid: str,
    address: str,
    last_outgoing_at: Optional[int] = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        '''
        UPDATE active_hubs
        SET last_checked_at = ?,
            last_outgoing_at = CASE
                WHEN ? IS NULL THEN last_outgoing_at
                ELSE MAX(COALESCE(last_outgoing_at, 0), ?)
            END
        WHERE chainid = ? AND address = ?
        ''',
        (utc_now_ts(), last_outgoing_at, last_outgoing_at, chainid, normalize(address)),
    )
    conn.commit()


def scan_active_hub_outflows(
    conn: sqlite3.Connection,
    active_hubs: List[dict],
    chainid: str,
    days: int,
    burst_window_hours: int,
    min_outgoing_count_for_b: int,
) -> List[dict]:
    burst_window_sec = burst_window_hours * 3600
    results: List[dict] = []

    for hub in active_hubs:
        address = normalize(hub["address"])
        rows = get_recent_outgoing_transfers(conn, address, chainid, days)
        if not rows:
            touch_active_hub_checked(conn, chainid, address, None)
            continue

        last_seen = hub.get("last_outgoing_at") or 0
        fresh_rows = [r for r in rows if int(r["timestamp"]) > int(last_seen)]
        newest_ts = max(int(r["timestamp"]) for r in rows)
        touch_active_hub_checked(conn, chainid, address, newest_ts)

        if not fresh_rows:
            continue

        exchange_rows = [r for r in fresh_rows if r["target_kind"] == "exchange"]
        non_protocol_rows = [r for r in fresh_rows if r["target_kind"] not in {"protocol", "ignore"}]
        recent_burst_rows = [
            r for r in non_protocol_rows
            if newest_ts - int(r["timestamp"]) <= burst_window_sec
        ]
        unique_targets = sorted({normalize(r["to_addr"]) for r in recent_burst_rows})
        token_counter = collections.Counter(
            normalize(r["token_symbol"]) for r in recent_burst_rows if (r.get("token_symbol") or "-") != "-"
        )
        top_token = token_counter.most_common(1)[0][0].upper() if token_counter else "-"
        total_amount = sum(float(r.get("amount_float") or 0.0) for r in recent_burst_rows)

        if exchange_rows:
            for row in exchange_rows:
                results.append(
                    {
                        "level": "A",
                        "hub": address,
                        "shared_seed_count": hub["shared_seed_count"],
                        "score": hub["score"],
                        "source_seeds": hub["source_seeds"],
                        "time_utc": row["time_utc"],
                        "timestamp": row["timestamp"],
                        "token_symbol": row["token_symbol"],
                        "amount": row["amount"],
                        "amount_float": row["amount_float"],
                        "to_addr": row["to_addr"],
                        "to_label": row["target_label"],
                        "target_kind": row["target_kind"],
                        "tx_hash": row["tx_hash"],
                        "recent_outgoing_count": len(recent_burst_rows),
                        "unique_target_count": len(unique_targets),
                        "top_token": top_token,
                        "burst_total_amount": total_amount,
                        "note": "active hub -> exchange",
                    }
                )

        # 거래소 유입만 핵심으로 보기 위해 B급(연쇄 출금 시작) 이벤트는 생성하지 않는다.

    results.sort(key=lambda x: (x["timestamp"], x["level"], x["score"]), reverse=True)
    return results


def print_active_hub_scan(rows: List[dict], top: int = 20) -> None:
    print("\n=== active hub 감시 결과 ===")
    if not rows:
        print("(없음)")
        return
    for row in rows[:top]:
        print(
            f"{row['time_utc']} | level={row['level']} | hub={shorten(row['hub'])} | "
            f"token={row['token_symbol']} | score={row['score']} | shared={row['shared_seed_count']} | "
            f"targets={row['unique_target_count']} | note={row['note']} | to={row['to_addr']}"
        )


def send_active_hub_alerts(conn: sqlite3.Connection, rows: List[dict]) -> None:
    print("\n=== 온체인 텔레그램 알림: active hub watcher ===")
    sent_count = 0

    for row in rows:
        level = row["level"]
        if level == "A":
            alert_key = make_alert_key(
                "active_hub_A",
                row["hub"],
                row["tx_hash"],
                row["to_addr"],
                row["token_symbol"],
                row["amount"],
            )
            if has_sent_alert(conn, alert_key):
                continue
            msg = (
                "[ONCHAIN][A] 활성 허브 거래소 도착\n"
                f"hub: {shorten(row['hub'])}\n"
                f"token: {row['token_symbol']}\n"
                f"amount: {row['amount']}\n"
                f"exchange: {row['to_label']}\n"
                f"score: {row['score']}\n"
                f"shared: {row['shared_seed_count']}\n"
                f"source_seeds: {row['source_seeds']}\n"
                f"time: {row['time_utc']}"
            )
            if send_telegram_message(msg):
                mark_alert_sent(conn, alert_key, "active_hub_A")
                sent_count += 1
        # B급(연쇄 출금 시작) 알림은 비활성화: 거래소 도착 A급만 전송

    print(f"[TG] active hub 알림 전송 수: {sent_count}", flush=True)


def print_active_hubs_summary(rows: List[dict], top: int = 20) -> None:
    print("\n=== active hubs ===")
    if not rows:
        print("(없음)")
        return
    for row in rows[:top]:
        expires = datetime.fromtimestamp(row["expires_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"score={row['score']:>2} | shared={row['shared_seed_count']} | "
            f"status={row['status']} | expires={expires} | {row['address']}"
        )



def run_active_hub_fast_scan_loop(
    conn: sqlite3.Connection,
    chainid: str,
    days: int,
    address_book_path: str,
    address_book_reload_seconds: int,
    active_hub_max_track: int,
    active_hub_scan_max_pages: int,
    active_hub_burst_window_hours: int,
    active_hub_min_outgoing_count_for_b: int,
    offset: int,
    sleep_sec: float,
    interval_minutes: int,
    iterations: int,
    active_hub_csv: str,
    active_hub_scan_csv: str,
    auto_exchange_enrich: bool,
    auto_exchange_enrich_limit: int,
    auto_exchange_cache_hours: int,
) -> None:
    if interval_minutes <= 0 or iterations <= 0:
        return

    print(f"\n[FAST] 활성 허브 빠른 감시 시작: interval={interval_minutes}분, iterations={iterations}")
    for idx in range(1, iterations + 1):
        print(f"\n[FAST] ({idx}/{iterations}) 활성 허브 빠른 감시")
        if maybe_reload_address_book(address_book_path, address_book_reload_seconds):
            seed_exchange_labels(conn)

        expired = expire_old_active_hubs(conn, chainid)
        if expired:
            print(f"[FAST] 만료 처리 수: {expired}")

        active_hub_rows = get_active_hubs(conn, chainid=chainid, limit=active_hub_max_track)
        export_csv(active_hub_csv, active_hub_rows)

        if not active_hub_rows:
            print("[FAST] 활성 허브가 없습니다.")
        else:
            expanded_saved = collect_for_active_hubs(
                conn=conn,
                active_hubs=active_hub_rows,
                chainid=chainid,
                days=days,
                offset=offset,
                max_pages=active_hub_scan_max_pages,
                sleep_sec=sleep_sec,
            )
            print(f"[FAST] 활성 허브 수집 신규 저장 전송 수: {expanded_saved}")

            if auto_exchange_enrich:
                added = auto_enrich_exchange_addresses(conn=conn, chainid=chainid, days=days, address_book_path=address_book_path, max_addresses=auto_exchange_enrich_limit, cache_hours=auto_exchange_cache_hours, sleep_sec=sleep_sec)
                if added:
                    print(f"[ADDR][AUTO][FAST] 추가된 거래소 주소 수: {added}", flush=True)
            if maybe_reload_address_book(address_book_path, address_book_reload_seconds):
                seed_exchange_labels(conn)

            active_hub_scan_rows = scan_active_hub_outflows(
                conn=conn,
                active_hubs=active_hub_rows,
                chainid=chainid,
                days=days,
                burst_window_hours=active_hub_burst_window_hours,
                min_outgoing_count_for_b=active_hub_min_outgoing_count_for_b,
            )
            print_active_hub_scan(active_hub_scan_rows, top=min(10, len(active_hub_scan_rows) or 10))
            export_csv(active_hub_scan_csv, active_hub_scan_rows)
            send_active_hub_alerts(conn, active_hub_scan_rows)

        if idx < iterations:
            print(f"[FAST] 다음 빠른 감시까지 {interval_minutes}분 대기")
            time.sleep(max(1, interval_minutes) * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Etherscan V2 반복 지갑 탐지 MVP + light flow tracker + active hub watcher")
    parser.add_argument("--seeds", required=True, help="시드 주소 txt 파일 경로")
    parser.add_argument("--chainid", default="1", help="EVM chainid. Ethereum=1")
    parser.add_argument("--days", type=int, default=30, help="최근 며칠 데이터 볼지")
    parser.add_argument("--offset", type=int, default=100, help="페이지당 전송 수")
    parser.add_argument("--max-pages", type=int, default=10, help="주소당 최대 페이지 수")
    parser.add_argument("--sleep-sec", type=float, default=0.4, help="API 호출 간 대기")
    parser.add_argument("--top", type=int, default=20, help="상위 몇 개 허브 후보/상세 출력할지")
    parser.add_argument("--csv", default="hub_candidates.csv", help="결과 CSV 파일명")
    parser.add_argument("--address-book", default=ADDRESS_BOOK_PATH_DEFAULT, help="거래소/라우터/ignore 주소록 JSON 파일 경로")
    parser.add_argument("--address-book-reload-seconds", type=int, default=ADDRESS_BOOK_RELOAD_SECONDS_DEFAULT, help="주소록 파일 변경 재로딩 최소 간격(초)")
    parser.add_argument("--auto-exchange-enrich", action="store_true", help="알 수 없는 주소를 Etherscan 라벨로 조회해 거래소 주소를 자동 축적")
    parser.add_argument("--auto-exchange-enrich-limit", type=int, default=AUTO_EXCHANGE_ENRICH_LIMIT_DEFAULT, help="1회 분석당 자동 축적할 미확인 주소 최대 개수")
    parser.add_argument("--auto-exchange-cache-hours", type=int, default=AUTO_EXCHANGE_ENRICH_CACHE_HOURS_DEFAULT, help="주소 메타데이터 캐시 유지 시간")
    parser.add_argument("--bootstrap-exchange-labels", default=",".join(BOOTSTRAP_EXCHANGE_LABEL_SLUGS_DEFAULT), help="시작 시 exportaddresstags로 대량 반영할 라벨 slug 목록(콤마 구분)")
    parser.add_argument("--bootstrap-exchange-on-start", action="store_true", help="시작 시 Etherscan 라벨 export로 거래소 주소를 대량 반영")

    parser.add_argument("--enable-flow", action="store_true", help="seed -> hub -> ... -> exchange 흐름 추적 사용")
    parser.add_argument("--flow-max-hops", type=int, default=3, help="최대 hop 수. 기본 3")
    parser.add_argument("--flow-max-time-gap-hours", type=int, default=24, help="hop 간 최대 시간 간격(시간)")
    parser.add_argument("--flow-expand-max-pages", type=int, default=3, help="flow 확장 주소당 최대 페이지 수")
    parser.add_argument("--flow-max-track-addrs", type=int, default=FLOW_MAX_TRACK_ADDRS, help="확장 추적할 주소 최대 개수")
    parser.add_argument("--flow-min-amount-ratio", type=float, default=FLOW_MIN_AMOUNT_RATIO, help="이전 hop 대비 최소 금액 비율")
    parser.add_argument("--alerts-exchange-only", action="store_true", help="텔레그램은 거래소 도착 flow만 전송")
    parser.add_argument("--flow-alert-max-age-hours", type=int, default=FLOW_ALERT_MAX_AGE_HOURS_DEFAULT, help="flow 텔레그램 알림 최대 허용 신선도(시간). 0이면 전체 허용")
    parser.add_argument("--flow-max-alerts-per-run", type=int, default=FLOW_MAX_ALERTS_PER_RUN_DEFAULT, help="1회 실행당 flow 텔레그램 최대 전송 개수. 0 이하이면 전체 전송")

    parser.add_argument("--enable-active-hubs", action="store_true", help="활성 허브 감시 사용")
    parser.add_argument("--active-hub-ttl-hours", type=int, default=ACTIVE_HUB_TTL_HOURS, help="활성 허브 감시 유지 시간")
    parser.add_argument("--active-hub-min-shared", type=int, default=ACTIVE_HUB_MIN_SHARED, help="활성 허브 등록 최소 shared")
    parser.add_argument("--active-hub-min-score", type=int, default=ACTIVE_HUB_MIN_SCORE, help="활성 허브 등록 최소 score")
    parser.add_argument("--active-hub-max-track", type=int, default=ACTIVE_HUB_MAX_TRACK, help="활성 허브 최대 감시 수")
    parser.add_argument("--active-hub-scan-max-pages", type=int, default=ACTIVE_HUB_SCAN_MAX_PAGES, help="활성 허브 주소당 최대 페이지 수")
    parser.add_argument("--active-hub-burst-window-hours", type=int, default=ACTIVE_HUB_BURST_WINDOW_HOURS, help="B급 burst 판단 시간 창")
    parser.add_argument("--active-hub-min-outgoing-count-for-b", type=int, default=ACTIVE_HUB_MIN_OUTGOING_COUNT_FOR_B, help="B급 판단 최소 출금 수")
    parser.add_argument("--active-hub-fast-scan-minutes", type=int, default=0, help="메인 분석 후 활성 허브만 빠르게 다시 감시할 주기(분). 0이면 비활성화")
    parser.add_argument("--active-hub-fast-iterations", type=int, default=0, help="메인 분석 후 활성 허브 빠른 감시 반복 횟수. 0이면 비활성화")

    args = parser.parse_args()

    load_address_book(args.address_book, create_if_missing=True)

    seeds = read_seed_addresses(args.seeds)

    conn = sqlite3.connect(DB_PATH)
    ensure_db(conn)
    seed_exchange_labels(conn)

    bootstrap_label_slugs = [x.strip().lower() for x in str(args.bootstrap_exchange_labels or "").split(",") if x.strip()]
    if args.bootstrap_exchange_on_start and bootstrap_label_slugs:
        added = bootstrap_exchange_addresses_from_etherscan(conn=conn, chainid=args.chainid, label_slugs=bootstrap_label_slugs, address_book_path=args.address_book)
        if added:
            print(f"[ADDR][BOOTSTRAP] 추가된 거래소 주소 수: {added}", flush=True)

    print(f"[INFO] address_book={os.path.abspath(args.address_book)}")
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

    if args.auto_exchange_enrich:
        added = auto_enrich_exchange_addresses(conn=conn, chainid=args.chainid, days=args.days, address_book_path=args.address_book, max_addresses=args.auto_exchange_enrich_limit, cache_hours=args.auto_exchange_cache_hours, sleep_sec=args.sleep_sec)
        if added:
            print(f"[ADDR][AUTO] 이번 분석에서 자동 추가된 거래소 주소 수: {added}", flush=True)

    if maybe_reload_address_book(args.address_book, args.address_book_reload_seconds):
        seed_exchange_labels(conn)

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
            f"kind={row.get('target_kind') or '-'} | "
            f"label={row.get('target_label') or row.get('label') or '-'} | "
            f"exchange={row.get('exchange_hits') or '-'} | "
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

    alerts_exchange_only = args.alerts_exchange_only or FLOW_ALERT_EXCHANGE_ONLY_DEFAULT
    if not alerts_exchange_only:
        send_hub_candidate_alerts(conn, rows)
        send_outflow_alerts(conn, outflow_rows)
    else:
        print("[INFO] exchange-only 알림 모드: 허브/일반 출금 텔레그램 알림 생략")

    flow_rows: List[dict] = []
    flow_csv = f"flow_exchange_{args.csv}"
    if args.enable_flow:
        if maybe_reload_address_book(args.address_book, args.address_book_reload_seconds):
            seed_exchange_labels(conn)
        flow_track_addresses = select_flow_expansion_addresses(
            seeds=seeds,
            hub_rows=rows,
            outflow_rows=outflow_rows,
            max_track_addrs=args.flow_max_track_addrs,
        )
        print(f"\n[FLOW] 확장 추적 주소 수: {len(flow_track_addresses)}")
        if flow_track_addresses:
            expanded_saved = collect_for_flow_expansion(
                conn=conn,
                addresses=flow_track_addresses,
                chainid=args.chainid,
                days=args.days,
                offset=args.offset,
                max_pages=args.flow_expand_max_pages,
                sleep_sec=args.sleep_sec,
            )
            print(f"[FLOW] 확장 수집 신규 저장 전송 수: {expanded_saved}")

            if args.auto_exchange_enrich:
                added = auto_enrich_exchange_addresses(conn=conn, chainid=args.chainid, days=args.days, address_book_path=args.address_book, max_addresses=args.auto_exchange_enrich_limit, cache_hours=args.auto_exchange_cache_hours, sleep_sec=args.sleep_sec)
                if added:
                    print(f"[ADDR][AUTO][FLOW] 추가된 거래소 주소 수: {added}", flush=True)
            if maybe_reload_address_book(args.address_book, args.address_book_reload_seconds):
                seed_exchange_labels(conn)

            flow_rows = build_flow_paths(
                conn=conn,
                seeds=seeds,
                chainid=args.chainid,
                days=args.days,
                max_hops=args.flow_max_hops,
                max_time_gap_hours=args.flow_max_time_gap_hours,
                min_amount_ratio=args.flow_min_amount_ratio,
            )
            print_flow_paths(flow_rows, top=args.top)
            export_csv(flow_csv, flow_rows)
            send_flow_alerts(conn, flow_rows, max_age_hours=args.flow_alert_max_age_hours, max_alerts_per_run=args.flow_max_alerts_per_run)
        else:
            export_csv(flow_csv, flow_rows)
            print("[FLOW] 확장할 주소가 없습니다.")
    else:
        print("[FLOW] 비활성화. --enable-flow 옵션을 주면 seed -> hub -> exchange 추적을 수행합니다.")

    active_hub_rows: List[dict] = []
    active_hub_scan_rows: List[dict] = []
    active_hub_csv = f"active_hubs_{args.csv}"
    active_hub_scan_csv = f"active_hub_events_{args.csv}"
    if args.enable_active_hubs:
        if maybe_reload_address_book(args.address_book, args.address_book_reload_seconds):
            seed_exchange_labels(conn)
        expired = expire_old_active_hubs(conn, args.chainid)
        if expired:
            print(f"[HUB] 만료 처리 수: {expired}")

        activated = activate_hubs_from_candidates(
            conn=conn,
            hub_rows=rows,
            chainid=args.chainid,
            ttl_hours=args.active_hub_ttl_hours,
            min_shared=args.active_hub_min_shared,
            min_score=args.active_hub_min_score,
        )
        print(f"[HUB] 신규 활성 허브 수: {activated}")

        active_hub_rows = get_active_hubs(
            conn=conn,
            chainid=args.chainid,
            limit=args.active_hub_max_track,
        )
        print_active_hubs_summary(active_hub_rows, top=args.top)
        export_csv(active_hub_csv, active_hub_rows)

        if active_hub_rows:
            expanded_saved = collect_for_active_hubs(
                conn=conn,
                active_hubs=active_hub_rows,
                chainid=args.chainid,
                days=args.days,
                offset=args.offset,
                max_pages=args.active_hub_scan_max_pages,
                sleep_sec=args.sleep_sec,
            )
            print(f"[HUB] 활성 허브 수집 신규 저장 전송 수: {expanded_saved}")

            if args.auto_exchange_enrich:
                added = auto_enrich_exchange_addresses(conn=conn, chainid=args.chainid, days=args.days, address_book_path=args.address_book, max_addresses=args.auto_exchange_enrich_limit, cache_hours=args.auto_exchange_cache_hours, sleep_sec=args.sleep_sec)
                if added:
                    print(f"[ADDR][AUTO][HUB] 추가된 거래소 주소 수: {added}", flush=True)
            if maybe_reload_address_book(args.address_book, args.address_book_reload_seconds):
                seed_exchange_labels(conn)

            active_hub_scan_rows = scan_active_hub_outflows(
                conn=conn,
                active_hubs=active_hub_rows,
                chainid=args.chainid,
                days=args.days,
                burst_window_hours=args.active_hub_burst_window_hours,
                min_outgoing_count_for_b=args.active_hub_min_outgoing_count_for_b,
            )
            print_active_hub_scan(active_hub_scan_rows, top=args.top)
            export_csv(active_hub_scan_csv, active_hub_scan_rows)
            send_active_hub_alerts(conn, active_hub_scan_rows)
        else:
            export_csv(active_hub_scan_csv, active_hub_scan_rows)
            print("[HUB] 활성 허브가 없습니다.")
    else:
        print("[HUB] 비활성화. --enable-active-hubs 옵션을 주면 허브를 기억하고 장기 감시합니다.")

    if args.enable_active_hubs and args.active_hub_fast_scan_minutes > 0 and args.active_hub_fast_iterations > 0:
        run_active_hub_fast_scan_loop(
            conn=conn,
            chainid=args.chainid,
            days=args.days,
            address_book_path=args.address_book,
            address_book_reload_seconds=args.address_book_reload_seconds,
            active_hub_max_track=args.active_hub_max_track,
            active_hub_scan_max_pages=args.active_hub_scan_max_pages,
            active_hub_burst_window_hours=args.active_hub_burst_window_hours,
            active_hub_min_outgoing_count_for_b=args.active_hub_min_outgoing_count_for_b,
            offset=args.offset,
            sleep_sec=args.sleep_sec,
            interval_minutes=args.active_hub_fast_scan_minutes,
            iterations=args.active_hub_fast_iterations,
            active_hub_csv=active_hub_csv,
            active_hub_scan_csv=active_hub_scan_csv,
            auto_exchange_enrich=args.auto_exchange_enrich,
            auto_exchange_enrich_limit=args.auto_exchange_enrich_limit,
            auto_exchange_cache_hours=args.auto_exchange_cache_hours,
        )

    print(f"\n[INFO] 결과 CSV 저장: {args.csv}")
    print(f"[INFO] 시드 출금 상세 CSV 저장: {detail_csv}")
    if args.enable_flow:
        print(f"[INFO] flow 거래소 도착 CSV 저장: {flow_csv}")
    if args.enable_active_hubs:
        print(f"[INFO] active hub 목록 CSV 저장: {active_hub_csv}")
        print(f"[INFO] active hub 이벤트 CSV 저장: {active_hub_scan_csv}")
    print(f"[INFO] address book JSON: {os.path.abspath(args.address_book)}")
    print(f"[INFO] SQLite DB 저장: {DB_PATH}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
