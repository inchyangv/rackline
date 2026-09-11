# HashCredit 배포 가이드 (인턴용)

목표:
- 컨트랙트는 **별도 배포**
- FE는 **Vercel**
- 그 외(오프체인)는 **Railway**에 모두 배포 (API + Worker + Postgres)

기본 타겟:
- Creditcoin EVM testnet (`CHAIN_ID=102031`)
- RPC: `https://rpc.cc3-testnet.creditcoin.network`

중요:
- `docs/guides/` 아래 문서들은 **로컬 전용**이며 git에 올라가지 않습니다. (이미 `.gitignore` 처리됨)
- 실제 제출/공유에 필요한 값(주소/URL)은 `docs/hackathon/SUBMISSION_VALUES.md`에 정리합니다.

---

## 0. 먼저 결정할 것 (SPV vs MVP)

한 번 정하면, 컨트랙트 배포/Worker 구성/ENV가 모두 그 모드에 맞아야 합니다.

### A) SPV 모드 (권장)

- 온체인 verifier: `BtcSpvVerifier` + `CheckpointManager`
- Railway worker: `offchain/prover` (SPV relayer)
- Bitcoin 데이터: **Bitcoin Core RPC 필요** (권장: `txindex=1`)
- 장점: “진짜” SPV 증명 흐름 (실전형)

### B) MVP 모드 (데모용, 단순)

- 온체인 verifier: `RelayerSigVerifier`
- Railway worker: `offchain/relayer` (EIP-712 relayer)
- Bitcoin 데이터: Esplora API (예: mempool.space)
- 장점: Bitcoin Core 없이 빠르게 데모

---

## 1. 배포 전에 반드시 수집할 값

### 1) 공통 (컨트랙트 주소)

아래 주소들은 “컨트랙트 별도 배포”가 끝나는 즉시 받아서 기록합니다.

- `HASH_CREDIT_MANAGER`
- `LENDING_VAULT`

모드별 추가:
- SPV: `CHECKPOINT_MANAGER`, `BTC_SPV_VERIFIER`
- MVP: `VERIFIER` (RelayerSigVerifier)

권장 검증(컨트랙트 배포가 끝난 뒤 1회 확인):
```bash
cast call <HASH_CREDIT_MANAGER> "verifier()(address)" --rpc-url https://rpc.cc3-testnet.creditcoin.network
```

### 2) Bitcoin 데이터 소스

SPV 모드:
- `BITCOIN_RPC_URL` (예: `http://<host>:18332` testnet)
- `BITCOIN_RPC_USER`
- `BITCOIN_RPC_PASSWORD`

MVP 모드:
- `BITCOIN_API_URL` (예: `https://mempool.space/testnet/api`)

### 3) 오프체인 트랜잭션 서명 키(중요)

Railway의 API/Worker는 체인 트랜잭션을 전송합니다.

- `PRIVATE_KEY`: Railway에서 사용할 EVM 키 (테스트넷 가스 필요)
- (권장) 컨트랙트 배포 키와 분리

---

## 2. Railway 배포 (API + Worker + Postgres)

Railway 프로젝트에는 서비스 3개를 만들면 됩니다.

1. Postgres (DB)
2. API 서비스 (`offchain/api`)
3. Worker 서비스 (SPV: `offchain/prover`, MVP: `offchain/relayer`)

### Step 2.1 Railway 프로젝트 생성 + Postgres 추가

1. Railway에서 새 프로젝트를 생성합니다.
2. `New` → `Database` → `PostgreSQL` 추가
3. 생성된 `DATABASE_URL`을 Worker 서비스에서 참조할 예정입니다.

### Step 2.2 Railway API 배포 (SPV 모드에서 권장)

API는 주로 SPV 운영(체크포인트/증명 생성/제출)을 위한 브리지입니다.

- SPV 모드: API 배포 권장
- MVP 모드만 사용할 경우: API는 생략해도 됩니다 (Worker만 배포)

배포:
1. Railway `New` → GitHub Repo로 서비스 추가
2. Root directory를 `offchain/api`로 설정
3. Dockerfile 기반으로 빌드/실행됩니다 (기본 CMD: `python -m hashcredit_api.main`)

API 서비스 ENV (Railway Variables):

공통:
- `HOST=0.0.0.0`
- `EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`
- `CHAIN_ID=102031`
- `PRIVATE_KEY=<Railway용 EVM private key>` (Secret)
- `HASH_CREDIT_MANAGER=0x...`

권장(외부 공개 시 사실상 필수):
- `API_TOKEN=<강한 랜덤 토큰>` (Secret)
- `ALLOWED_ORIGINS=["https://<vercel-domain>","http://localhost:5173"]`

SPV 모드 전용:
- `CHECKPOINT_MANAGER=0x...`
- `BTC_SPV_VERIFIER=0x...`
- `BITCOIN_RPC_URL=http://...`
- `BITCOIN_RPC_USER=...`
- `BITCOIN_RPC_PASSWORD=...` (Secret)

검증:
- `https://<railway-api-domain>/health` 호출
- `API_TOKEN`을 설정했다면 `X-API-Key` 헤더를 포함해야 합니다.

```bash
curl -H "X-API-Key: <API_TOKEN>" https://<railway-api-domain>/health
```

### Step 2.3 Railway Worker 배포 (SPV 또는 MVP 중 1개만)

Worker는 “비트코인 이벤트를 감시하고, 조건이 맞으면 증명/제출”을 수행합니다.

중요:
- 한 매니저 배포에 대해 Worker는 **1개만** 운영하세요 (SPV 또는 MVP).

#### A) SPV Worker (권장): `offchain/prover`

배포:
1. Railway `New` → GitHub Repo로 서비스 추가
2. Root directory를 `offchain/prover`로 설정
3. Dockerfile 기반으로 실행됩니다 (기본 CMD: `sh ./start-worker.sh`)

Worker ENV (SPV):
- `DATABASE_URL=${{Postgres.DATABASE_URL}}`
- `BITCOIN_RPC_URL=http://...`
- `BITCOIN_RPC_USER=...`
- `BITCOIN_RPC_PASSWORD=...` (Secret)
- `EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`
- `CHAIN_ID=102031`
- `PRIVATE_KEY=<Railway용 EVM private key>` (Secret)
- `HASH_CREDIT_MANAGER=0x...`
- `CHECKPOINT_MANAGER=0x...`

감시 주소 목록(택 1):
- `ADDRESSES_JSON='[{"btc_address":"tb1q...","borrower":"0x...","enabled":true}]'`
- `ADDRESSES_JSON_B64=<base64(JSON)>` (권장: 따옴표/개행 이슈 회피)
- `ADDRESSES_FILE=/app/addresses.json` (파일 마운트 구성 시)

권장 워크플로(로컬 파일은 git에 안 올리기):
1. `docs/hackathon/addresses.template.json` → `docs/hackathon/addresses.json` 복사
2. `docs/hackathon/addresses.json`에 borrower 매핑을 채움 (이 파일은 `.gitignore`로 제외됨)
3. base64로 인코딩해서 Railway `ADDRESSES_JSON_B64`에 붙여넣기

```bash
base64 < docs/hackathon/addresses.json | tr -d '\n'
```

튜닝(선택):
- `SPV_CONFIRMATIONS=6`
- `SPV_POLL_INTERVAL=60`

검증:
- Worker Logs에서 주기적으로 polling 로그가 찍혀야 합니다.
- 조건이 맞는 payout이 잡히면 `HashCreditManager`에 트랜잭션 제출 로그가 나옵니다.

#### B) MVP Worker (데모용): `offchain/relayer`

배포:
1. Railway `New` → GitHub Repo로 서비스 추가
2. Root directory를 `offchain/relayer`로 설정

Worker ENV (MVP):
- `BITCOIN_API_URL=https://mempool.space/testnet/api`
- `RPC_URL=https://rpc.cc3-testnet.creditcoin.network` (주의: MVP relayer는 `RPC_URL`을 사용)
- `CHAIN_ID=102031`
- `PRIVATE_KEY=<Railway용 EVM private key>` (Secret)
- `RELAYER_PRIVATE_KEY=<EIP-712 서명 키>` (Secret)
- `HASH_CREDIT_MANAGER=0x...`
- `VERIFIER=0x...` (RelayerSigVerifier, 그리고 `manager.verifier()`와 동일해야 함)

검증:
- Logs에서 스캔/제출이 진행되는지 확인합니다.

---

## 3. Vercel 배포 (Frontend: `apps/web`)

배포:
1. Vercel에서 새 프로젝트 생성 (GitHub repo 연결)
2. Root directory를 `apps/web`로 설정
3. Framework preset: Vite

Vercel ENV (Secrets 금지, 전부 공개값):
- `VITE_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`
- `VITE_CHAIN_ID=102031`
- `VITE_HASH_CREDIT_MANAGER=0x...`
- `VITE_BTC_SPV_VERIFIER=0x...` (SPV 모드일 때만)
- `VITE_CHECKPOINT_MANAGER=0x...` (SPV 모드일 때만)
- `VITE_API_URL=https://<railway-api-domain>` (선택: FE에서 API를 직접 호출하는 경우에만)

검증:
- 페이지 로드
- 지갑 연결
- 컨트랙트 상태 조회가 정상적으로 보이는지 확인

주의:
- Railway API에 `API_TOKEN`을 켜둔 경우, 토큰을 브라우저로 노출하면 안 됩니다.
- 즉, “운영자 전용 API”로 쓰거나, FE가 호출해야 한다면 별도의 서버 프록시 설계를 추가로 해야 합니다.

---

## 4. 최종 정리 (해커톤 제출값)

1. `docs/hackathon/SUBMISSION_VALUES.template.md`를 복사해서 `docs/hackathon/SUBMISSION_VALUES.md`를 만듭니다.
2. 아래 항목을 채웁니다:
   - 컨트랙트 주소
   - Vercel FE URL
   - Railway API URL (운영 여부에 따라)
   - Deck/Whitepaper PDF URL
   - Demo Video URL

참고:
- `docs/hackathon/SUBMISSION_VALUES.md`는 `.gitignore`로 제외되어 커밋되지 않습니다.
