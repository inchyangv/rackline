# HashCredit

**Bitcoin 채굴 수익 기반(RBF) 대출 프로토콜 on Creditcoin (SPV 모드)**

HashCredit는 Bitcoin 채굴자의 “풀 payout(수익 지급)” 트랜잭션을 SPV로 검증해, Creditcoin EVM에서 담보 없이도 대출 한도를 산정하고 스테이블코인을 빌릴 수 있게 합니다.

## 데모 링크

- Frontend: `https://hashcredit.studioliq.com`
- API: `https://api-hashcredit.studioliq.com`

## 개요(한 줄)

`Bitcoin payout(tx)` -> `SPV proof` -> `Creditcoin on-chain credit limit` -> `Borrow/Repay`

## 핵심 기능

- 수익 기반 신용 한도: trailing BTC 수익을 USD로 환산해 credit limit 계산
- SPV 검증: 체크포인트 + header chain + Merkle inclusion proof로 Bitcoin 트랜잭션 포함을 검증
- 리플레이 방지: 동일 payout은 1회만 반영
- 리스크 파라미터: advance rate, 신규 차입자 cap, 기간(window) 등

## 아키텍처

```text
Bitcoin(testnet/main)  ->  Railway(API/Worker/DB)  ->  Creditcoin EVM(contracts)
```

## 구성 요소

- On-chain (Creditcoin EVM)
  - `HashCreditManager`: 차입자 등록, payout 반영, credit limit 계산, borrow/repay
  - `LendingVault`: 스테이블코인 예치/대출 vault
  - `CheckpointManager`: Bitcoin 블록 헤더 체크포인트 저장
  - `BtcSpvVerifier`: SPV proof 검증
  - `RiskConfig`, `PoolRegistry`: 리스크/풀 설정
- Off-chain (Railway)
  - `offchain/api`: proof 생성 + 체크포인트/borrower 등록 + proof 제출(운영키)
  - `offchain/prover`: 감시 주소 폴링 및 자동 proof 제출(worker)
  - Postgres: worker 상태/중복 제출 방지
- Frontend (Vercel)
  - `apps/web`: 온체인 조회 + 데모 운영 버튼 + 데모 지갑 생성(로컬 저장)

## 데모/운영 플로우(요약)

1. 체크포인트를 온체인 등록 (`CheckpointManager`)
2. borrower(EVM) <-> BTC 주소(pubkeyHash)를 등록 (`BtcSpvVerifier`)
3. borrower 등록 (`HashCreditManager.registerBorrower`)
4. proof 생성 및 제출 (`HashCreditManager.submitPayout`)
5. 차입자가 `Borrow/Repay` 실행

## 중요한 보안 메모(메인넷)

테스트넷 데모에서는 운영자가 borrower(EVM) <-> BTC 주소를 등록합니다.

메인넷에서는 임의 매핑 공격을 막기 위해, **소유권 증명(양쪽 서명) 기반 claim**이 필요합니다.
- 서버가 nonce 발급
- borrower가 EVM 서명 + BTC 서명(BIP-322 권장)
- 검증 후에만 온체인에 pubkeyHash/borrower 등록 트랜잭션 실행

## 로컬 개발(요약)

```bash
# contracts
forge build
forge test

# API
cd offchain/api
cp .env.example .env
pip install -e .
hashcredit-api

# Prover/Worker
cd ../prover
cp .env.example .env
pip install -e .
hashcredit-prover --help

# Frontend
cd ../../apps/web
cp .env.example .env
npm install
npm run dev
```

## 문서

- `docs/hackathon/SUBMISSION_CHECKLIST.md`: 제출 체크리스트
- 배포/데모 운영 문서는 로컬 전용으로 관리합니다(레포에는 올라가지 않음).

## License

MIT

