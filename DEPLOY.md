# HashCredit 배포 가이드 (SPV 모드 고정, 인턴용)

목표(반드시 이대로):
- 컨트랙트는 **별도 배포**(우리가 여기서 배포하지 않음, 주소만 받음)
- FE는 **Vercel**에 배포
- 오프체인은 **전부 Railway**에 배포
  - Postgres (DB)
  - API 서비스 (`offchain/api`)
  - SPV Worker 서비스 (`offchain/prover`)

이 문서는 “아키텍처 소개”가 아니라 **체크리스트 + 실행 절차**입니다. 순서대로 하면 배포가 끝납니다.

---

## 0) 준비물 체크리스트 (시작 전 100% 확보)

### A. 온체인(컨트랙트) 주소 4개

컨트랙트 배포가 끝나면 아래 주소를 반드시 받습니다.

- `HASH_CREDIT_MANAGER`
- `LENDING_VAULT`
- `CHECKPOINT_MANAGER`
- `BTC_SPV_VERIFIER`

필수 검증(배포자에게 요청해서 캡처/로그로 남기기):

```bash
# HashCreditManager가 SPV verifier를 바라보는지 확인
cast call <HASH_CREDIT_MANAGER> "verifier()(address)" --rpc-url https://rpc.cc3-testnet.creditcoin.network
```

위 결과 주소가 `BTC_SPV_VERIFIER`와 같아야 합니다.

### B. Creditcoin 테스트넷 정보

- `CHAIN_ID=102031`
- `EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`

### C. Bitcoin Core RPC (SPV 필수)

SPV 모드는 **Bitcoin Core RPC가 필수**입니다.

필수:
- `BITCOIN_RPC_URL` (보통 testnet: `http://<host>:18332`)
- `BITCOIN_RPC_USER` (엔드포인트가 인증을 요구하면 설정)
- `BITCOIN_RPC_PASSWORD` (엔드포인트가 인증을 요구하면 설정)

필수 조건:
- `txindex=1` (임의 txid 조회 필요)
- Railway에서 접근 가능해야 함(네트워크/방화벽/프록시 포함)

Bitcoin Core 쪽 체크 항목(운영자가 준비):
- RPC가 외부에서 접근 가능한가
- 인증이 설정되어 있는가
- testnet인지(mainnet이면 주소/체크포인트/txid 전부 달라짐)
- `txindex=1`로 동기화/리인덱스가 끝났는가

퍼블릭 RPC 사용(해커톤용, 책임 하에):
- 예: `https://bitcoin-testnet-rpc.publicnode.com`
- 장점: Bitcoin Core를 직접 운영하지 않아도 됨
- 주의: 서비스 제공자의 정책(레이트리밋/가용성)에 따라 Worker가 불안정해질 수 있음

### D. Railway에서 사용할 EVM 서명키 1개 (필수)

Railway의 API/Worker는 트랜잭션을 전송합니다. 키는 하나로 통일합니다(인턴 실수 방지).

- `PRIVATE_KEY` (Railway Secrets에 저장)
- 이 키 주소는 **Creditcoin 테스트넷 가스가 충분히 있어야 함**

권장:
- 컨트랙트 배포 키와 분리(운영키)

### E. API 보안 토큰(필수)

API는 외부에 노출될 수 있으므로 토큰을 무조건 겁니다.

- `API_TOKEN` (Railway Secrets)

생성 예시:
```bash
openssl rand -hex 32
```

---

## 1) 로컬에 “제출/운영 값” 파일 만들기 (git에 안 올라감)

이 단계는 “배포값 정리”를 위해 필요합니다.

1. `docs/hackathon/SUBMISSION_VALUES.template.md`를 복사해 `docs/hackathon/SUBMISSION_VALUES.md`를 만듭니다.
2. `docs/hackathon/TEAM_INFO.template.md`를 복사해 `docs/hackathon/TEAM_INFO.md`를 만듭니다.
3. `docs/hackathon/addresses.template.json`를 복사해 `docs/hackathon/addresses.json`를 만듭니다.

참고:
- 위 3개 파일은 `.gitignore`로 제외되어 커밋되지 않습니다.

---

## 2) Railway 프로젝트 생성 + Postgres 만들기

1. Railway에서 새 프로젝트를 생성합니다.
2. `New` → `Database` → `PostgreSQL`을 추가합니다.
3. 생성된 Postgres의 `DATABASE_URL`이 있는지 확인합니다.

성공 기준:
- Railway에 Postgres 서비스가 Running
- Postgres가 `DATABASE_URL`을 제공

---

## 3) Railway API 배포 (`offchain/api`)

### 3.1 서비스 생성

1. Railway `New` → GitHub Repo로 서비스 생성
2. Root directory를 `offchain/api`로 설정
3. Dockerfile 기반 배포(레포에 Dockerfile 있음)

### 3.2 API ENV 설정(필수)

Railway API 서비스 Variables에 아래를 **그대로** 설정합니다.

서버:
- `HOST=0.0.0.0`

보안:
- `API_TOKEN=<강한 랜덤 토큰>`
- `ALLOWED_ORIGINS=["https://<Vercel 도메인>","http://localhost:5173"]`

EVM:
- `EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`
- `CHAIN_ID=102031`
- `PRIVATE_KEY=<운영키>` (Secret)

컨트랙트:
- `HASH_CREDIT_MANAGER=0x...`
- `CHECKPOINT_MANAGER=0x...`
- `BTC_SPV_VERIFIER=0x...`

Bitcoin Core RPC:
- `BITCOIN_RPC_URL=http://...`
- `BITCOIN_RPC_USER=...`
- `BITCOIN_RPC_PASSWORD=...` (Secret)

성공 기준:
- 서비스가 Deploy 성공
- `/health`가 200으로 응답

검증:
```bash
curl -H "X-API-Key: <API_TOKEN>" https://<railway-api-domain>/health
```

응답에서 아래가 만족되어야 정상입니다:
- `status`가 `ok`
- `bitcoin_rpc`가 `true`
- `evm_rpc`가 `true`
- 컨트랙트 주소들이 채워져 있음

---

## 4) Railway SPV Worker 배포 (`offchain/prover`)

### 4.1 서비스 생성

1. Railway `New` → GitHub Repo로 서비스 생성
2. Root directory를 `offchain/prover`로 설정
3. Dockerfile 기반 배포(기본 CMD: `sh ./start-worker.sh`)

### 4.2 Worker ENV 설정(필수)

Railway Worker 서비스 Variables에 아래를 **그대로** 설정합니다.

DB:
- `DATABASE_URL=${{Postgres.DATABASE_URL}}`

Bitcoin Core RPC:
- `BITCOIN_RPC_URL=http://...`
- `BITCOIN_RPC_USER=...`
- `BITCOIN_RPC_PASSWORD=...` (Secret)

EVM:
- `EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`
- `CHAIN_ID=102031`
- `PRIVATE_KEY=<운영키>` (Secret)

컨트랙트:
- `HASH_CREDIT_MANAGER=0x...`
- `CHECKPOINT_MANAGER=0x...`

감시 주소 목록(필수, 아래 방식 고정):
- `ADDRESSES_JSON_B64=<base64 인코딩된 addresses.json>`

튜닝(필수로 고정, 바꾸지 말 것):
- `SPV_CONFIRMATIONS=6`
- `SPV_POLL_INTERVAL=60`

### 4.3 addresses.json 만들기(필수)

`docs/hackathon/addresses.json`에 아래 형식으로 작성합니다:

```json
[
  {"btc_address":"tb1q...","borrower":"0x1234...","enabled":true}
]
```

이때:
- `btc_address`는 testnet 주소(`tb1...`)를 사용합니다.
- `borrower`는 EVM 주소(차용자)입니다.

base64 인코딩:
```bash
base64 < docs/hackathon/addresses.json | tr -d '\n'
```

위 출력 문자열을 Railway Worker의 `ADDRESSES_JSON_B64`에 붙여넣습니다.

성공 기준:
- Worker가 Deploy 성공
- Logs에 주기적인 폴링 로그가 출력됨
- 조건을 만족하는 payout이 발견되면 on-chain 제출 트랜잭션 로그가 출력됨

---

## 5) 운영 초기 세팅(반드시 수행)

SPV 모드는 “체크포인트 + borrower pubkey hash”가 없으면 진행이 막힙니다.
이 작업은 Railway API를 통해 수행합니다(운영키로 트랜잭션 전송).

### 5.1 체크포인트 등록(필수)

원칙:
- 너무 오래된 체크포인트는 부적합할 수 있습니다.
- 최근 높이로 설정합니다(운영자가 정함).

API 호출:
```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST https://<railway-api-domain>/checkpoint/set \
  -d '{"height": <CHECKPOINT_HEIGHT>, "dry_run": false}'
```

성공 기준:
- API가 tx hash를 반환하거나 성공 응답을 줌
- 이후 Worker가 “suitable checkpoint 없음” 같은 로그를 계속 내지 않음

### 5.2 borrower pubkey hash 등록(필수)

각 borrower에 대해 1회 수행합니다.

API 호출:
```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST https://<railway-api-domain>/borrower/set-pubkey-hash \
  -d '{"borrower":"0x...","btc_address":"tb1q...","dry_run": false}'
```

성공 기준:
- API가 성공 응답을 줌
- 이후 해당 주소의 payout에 대한 SPV 증명 제출이 가능해짐

---

## 6) Vercel 배포 (Frontend: `apps/web`)

### 6.1 프로젝트 생성

1. Vercel에서 새 프로젝트 생성(GitHub repo 연결)
2. Root directory: `apps/web`
3. Framework preset: Vite

### 6.2 Vercel ENV 설정(필수)

Secrets 금지(전부 공개값):
- `VITE_RPC_URL=https://rpc.cc3-testnet.creditcoin.network`
- `VITE_CHAIN_ID=102031`
- `VITE_HASH_CREDIT_MANAGER=0x...`
- `VITE_BTC_SPV_VERIFIER=0x...`
- `VITE_CHECKPOINT_MANAGER=0x...`

`VITE_API_URL`:
- 이 프로젝트에서는 API에 `API_TOKEN`을 걸기 때문에, FE에 토큰을 넣을 수 없습니다.
- 따라서 FE에서 API를 직접 호출하는 구성은 기본적으로 금지합니다.
- (필요하면 별도 “백엔드 프록시”를 설계해야 함)

성공 기준:
- FE가 정상 로드
- 지갑 연결
- 컨트랙트 읽기/쓰기 동작이 정상

---

## 7) 최종 제출값 정리(필수)

1. `docs/hackathon/SUBMISSION_VALUES.md`에 아래를 채웁니다:
   - SPV 모드 고정
   - 4개 컨트랙트 주소
   - Vercel FE URL
   - Railway API URL(운영자용)
   - Deck/Whitepaper PDF URL
   - Demo Video URL
2. `docs/hackathon/TEAM_INFO.md`를 채웁니다.

참고:
- `docs/hackathon/SUBMISSION_VALUES.md` / `docs/hackathon/TEAM_INFO.md`는 git에 올라가지 않습니다.
