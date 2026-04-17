#!/usr/bin/env python3
"""
eth_repeat_wallet_mvp.py

Etherscan V2 기반 반복 지갑(허브 후보) 탐지 MVP
- 시드 주소 목록을 입력받아
- 최근 ERC-20 전송 내역을 수집하고
- 공통 상대 주소를 집계한 뒤
- 허브 후보 점수를 계산합니다.

기본 체인: Ethereum Mainnet (chainid=1)
나중에 BSC 등 EVM 체인은 chainid만 바꿔 확장 가능

필수 준비
1) Etherscan API Key 발급
2) seed_addresses.txt 파일 준비 (한 줄에 주소 1개)
3) 환경변수 ETHERSCAN_API_KEY 설정
   - mac/linux: export ETHERSCAN_API_KEY=YOUR_KEY
   - windows powershell: setx ETHERSCAN_API_KEY "YOUR_KEY"

실행 예시
python eth_repeat_wallet_mvp.py --seeds seed_addresses_example.txt --days 30 --offset 100 --top 20
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import requests


API_URL = "https://api.etherscan.io/v2/api"
DB_PATH = "repeat_wallets.db"


@dataclass
class Transfer:
    chainid: str
    wallet: str          # 조회 기준 시드 주소
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


def ensure_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
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
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS exchange_labels (
            address TEXT PRIMARY KEY,
            label TEXT NOT NULL
        )
        """
    )
    conn.commit()


def seed_exchange_labels(conn: sqlite3.Connection) -> None:
    """
    수동 라벨용 샘플.
    실제로는 네가 알고 있는 거래소/입금 주소를 계속 추가해가면 좋다.
    """
    labels = [
        # 형식 예시:
        # ("0x1234....", "Binance"),
        # ("0xabcd....", "OKX"),
    ]
    cur = conn.cursor()
    for address, label in labels:
        cur.execute(
            "INSERT OR IGNORE INTO exchange_labels (address, label) VALUES (?, ?)",
            (normalize(address), label),
        )
    conn.commit()


def read_seed_addresses(path: str) -> List[str]:
    seeds = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = normalize(line)
            if not line or line.startswith("#"):
                continue
            seeds.append(line)
    if not seeds:
        raise ValueError("시드 주소가 없습니다. seed 파일을 확인하세요.")
    return list(dict.fromkeys(seeds))  # 중복 제거, 순서 유지


def etherscan_get(params: Dict[str, str], timeout: int = 20) -> dict:
    api_key = os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 ETHERSCAN_API_KEY가 없습니다.")

    full_params = dict(params)
    full_params["apikey"] = api_key

    resp = requests.get(API_URL, params=full_params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    # Etherscan은 에러여도 200으로 오는 경우가 많음
    status = str(data.get("status", ""))
    message = str(data.get("message", ""))
    result = data.get("result")

    if status == "0":
        text = str(result)
        # 빈 결과는 정상 취급
        if "No transactions found" in text:
            return {"status": "1", "message": "OK", "result": []}

        # rate limit 등은 호출측에서 재시도 가능하게 예외
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
            """
            INSERT OR IGNORE INTO transfers
            (chainid, wallet, block_number, timestamp, tx_hash, from_addr, to_addr,
             token_symbol, token_name, contract_address, value_raw, token_decimal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
    """
    시드 주소 1개에 대해 최근 ERC20 전송 수집
    - Etherscan의 tokentx는 정확한 시간 필터를 직접 주지 못하므로
      최신순으로 페이지를 보면서 cutoff 이전이면 중단
    """
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

        # 가장 오래된 tx가 cutoff보다 이전이면 종료
        oldest_ts = min(t.timestamp for t in transfers)
        if oldest_ts < cutoff:
            break

        time.sleep(sleep_sec)

    return total_saved


def build_hub_scores(
    conn: sqlite3.Connection,
    chainid: str,
    days: int,
    min_shared_seed_count: int = 2,
) -> List[dict]:
    """
    반복 등장 허브 후보 점수 계산

    규칙(단순 MVP)
    - 시드 여러 개와 연결된 상대 주소일수록 점수 ↑
    - 거래소 라벨이 있으면 별도 표시
    - in/out 방향 다양성 있으면 점수 약간 ↑
    """
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

    # 상대 주소별 집계
    # target 상대 주소가 각 seed와 몇 번 연결됐는지
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
            # 안전장치: 조회 기준 wallet과 무관한 이상 데이터는 스킵
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

        # MVP 점수
        score = (
            shared_seed_count * 3
            + min(total_interactions, 10)
            + (2 if directional_diversity == 2 else 0)
            + min(len(token_set[cp]), 5)
        )

        label = labels.get(cp)
        is_exchange_labeled = 1 if label else 0
        if is_exchange_labeled:
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
                "seeds": ", ".join(sorted(seed_counter.keys())),
            }
        )

    results.sort(key=lambda x: (-x["score"], -x["shared_seed_count"], -x["total_interactions"]))
    return results


def export_csv(path: str, rows: List[dict]) -> None:
    if not rows:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "address",
                    "score",
                    "shared_seed_count",
                    "total_interactions",
                    "out_from_seed",
                    "into_seed",
                    "token_variety",
                    "label",
                    "seeds",
                ]
            )
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Etherscan V2 반복 지갑 탐지 MVP")
    parser.add_argument("--seeds", required=True, help="시드 주소 txt 파일 경로")
    parser.add_argument("--chainid", default="1", help="EVM chainid. Ethereum=1, BSC=56")
    parser.add_argument("--days", type=int, default=30, help="최근 며칠 데이터 볼지")
    parser.add_argument("--offset", type=int, default=100, help="페이지당 전송 수")
    parser.add_argument("--max-pages", type=int, default=10, help="주소당 최대 페이지 수")
    parser.add_argument("--sleep-sec", type=float, default=0.4, help="API 호출 간 대기")
    parser.add_argument("--top", type=int, default=20, help="상위 몇 개 허브 후보 출력할지")
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
            f"interactions={row['total_interactions']} | label={row['label'] or '-'} | "
            f"{row['address']}"
        )

    print(f"\n[INFO] 결과 CSV 저장: {args.csv}")
    print(f"[INFO] SQLite DB 저장: {DB_PATH}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
