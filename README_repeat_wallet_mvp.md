# Etherscan 반복 지갑 탐지 MVP

이 프로젝트는 **시드 주소 여러 개**를 기준으로 최근 ERC-20 전송 내역을 수집하고,
여러 시드와 반복적으로 연결되는 **허브 후보 주소**를 점수화합니다.

## 준비
1. Etherscan API Key 발급
2. `seed_addresses_example.txt`를 복사해서 실제 주소 넣기
3. 환경변수 설정
   - mac/linux: `export ETHERSCAN_API_KEY=YOUR_KEY`
   - windows powershell: `setx ETHERSCAN_API_KEY "YOUR_KEY"`

## 실행
```bash
pip install requests
python eth_repeat_wallet_mvp.py --seeds seed_addresses_example.txt --days 30 --offset 100 --top 20
```

## 출력물
- `repeat_wallets.db`: 수집 데이터 SQLite
- `hub_candidates.csv`: 허브 후보 결과

## BSC 확장
문서상 Etherscan V2는 `chainid=56`으로 BNB Smart Chain Mainnet도 지원합니다.
실행 예:
```bash
python eth_repeat_wallet_mvp.py --seeds seed_addresses_example.txt --chainid 56 --days 30
```

단, 현재 문서 기준 BSC는 Free Tier 미지원일 수 있으니 플랜/제한을 확인하세요.
