# Railway 배포 (모노레포, FE=Vercel / 나머지=Railway)

이 문서는 HashCredit 모노레포를 Railway에 "깔끔하게" 배포하기 위해, 오프체인 컴포넌트를 **서비스 단위로 분리**해서 올리는 절차를 정리합니다.

- Frontend: Vercel (`apps/web`)
- Backend/API: Railway (`offchain/api`)
- Worker(Prover): Railway (`offchain/prover`)
- DB: Railway Postgres 플러그인(권장)

운영 도메인(고정):

- FE: `https://hashcredit.studioliq.com`
- API: `https://api-hashcredit.studioliq.com`

## 0) 사전 체크

1. Railway 계정/워크스페이스가 준비되어 있어야 합니다.
2. GitHub에서 이 레포를 Railway에 연결할 권한이 있어야 합니다.
3. API 운영키(Private Key), API_TOKEN, CLAIM_SECRET 등 **시크릿은 절대 git에 커밋하지 않습니다.**

## 1) (추천) Compose로 서비스 2개를 한번에 분리 생성

Railway는 Compose 파일을 드래그 앤 드롭하면 서비스들을 한번에 만들어줍니다.

1. Railway에서 새 프로젝트를 만듭니다.
2. 프로젝트 캔버스에 레포 루트의 `railway.compose.yml`을 드래그 앤 드롭합니다.
3. 아래 2개 서비스가 생성되는지 확인합니다.
   - `hashcredit-api`
   - `hashcredit-prover`

주의:

- 이 단계는 "서비스 생성/분리" 목적입니다.
- 실제 운영 변수/시크릿은 다음 단계에서 Railway Variables/Secrets로 설정합니다.

## 2) Postgres 추가 및 연결

Worker(Prover)는 dedupe/상태 저장을 위해 DB가 필요합니다. 운영에서는 Railway Postgres 플러그인을 권장합니다.

1. Railway 프로젝트에서 Postgres 플러그인을 추가합니다.
2. 플러그인이 제공하는 `DATABASE_URL`을 아래 서비스에 연결합니다.
   - `hashcredit-prover` (필수)
   - (선택) API도 DB를 쓰도록 확장할 경우 `hashcredit-api`에 연결 가능

참고:

- Railway Postgres는 `postgres://...` 형식일 수 있습니다.
- prover/relayer 코드는 Railway 포맷을 자동으로 `postgresql://...`로 변환해 처리합니다.

## 3) 서비스별 빌드/런 설정

이 레포는 오프체인 서비스들이 각자 `Dockerfile`을 가지고 있습니다.

- `offchain/api/Dockerfile`
- `offchain/prover/Dockerfile`

Railway에서 각 서비스의 Root Directory는 다음을 사용합니다.

- `hashcredit-api` -> `offchain/api`
- `hashcredit-prover` -> `offchain/prover`

Compose로 만들었다면 이미 이 구조대로 잡히는 것이 정상입니다.

## 4) API 서비스(`hashcredit-api`) Variables/Secrets

Railway -> `hashcredit-api` 서비스 -> Variables/Secrets에 아래를 설정합니다.

필수/권장:

- `API_TOKEN` (Secrets): API 전체 보호용. 생성 예시:
  - `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `ALLOWED_ORIGINS` (Variables): CORS 허용 origin(JSON 배열 문자열)
  - 예시: `["https://hashcredit.studioliq.com","http://localhost:5173","http://127.0.0.1:5173"]`
- `BITCOIN_RPC_URL` (Variables)
  - 데모(테스트넷): `https://bitcoin-testnet-rpc.publicnode.com`
- `BITCOIN_RPC_USER` (Secrets, 선택)
- `BITCOIN_RPC_PASSWORD` (Secrets, 선택)
- `EVM_RPC_URL` (Variables)
  - 예시: `https://rpc.cc3-testnet.creditcoin.network`
- `CHAIN_ID` (Variables)
  - 예시: `102031`
- `PRIVATE_KEY` (Secrets): 컨트랙트 호출/등록/제출 트랜잭션 서명키(운영키)

컨트랙트 주소(Variables):

- `HASH_CREDIT_MANAGER`
- `CHECKPOINT_MANAGER`
- `BTC_SPV_VERIFIER`

Borrower 매핑 모드:

- 테스트넷/데모: `BORROWER_MAPPING_MODE=demo`
  - 운영자가 borrower(EVM) <-> BTC 주소 매핑을 직접 등록합니다.
- 메인넷: `BORROWER_MAPPING_MODE=claim` (권장)
  - borrower가 BTC/EVM 서명으로 소유권을 증명(클레임)하면 서버가 온체인 등록합니다.
  - 이 모드에서는 아래 시크릿이 필요합니다:
    - `CLAIM_SECRET` (Secrets)
    - (선택) `CLAIM_REQUIRE_API_TOKEN=true`

포트/바인딩:

- Railway는 `PORT`를 자동 주입합니다.
- Dockerfile 기본값으로 `HOST=0.0.0.0`가 설정되어 있습니다.

## 5) Worker 서비스(`hashcredit-prover`) Variables/Secrets

Railway -> `hashcredit-prover` 서비스 -> Variables/Secrets에 아래를 설정합니다.

필수:

- `DATABASE_URL` (Variables/Reference): Railway Postgres의 `DATABASE_URL`을 참조
- `BITCOIN_RPC_URL` (Variables)
  - 데모: `https://bitcoin-testnet-rpc.publicnode.com`
- `EVM_RPC_URL` (Variables)
- `CHAIN_ID` (Variables)
- `PRIVATE_KEY` (Secrets): proof 제출 트랜잭션 서명키(운영키)
- `HASH_CREDIT_MANAGER` (Variables)
- `CHECKPOINT_MANAGER` (Variables)

Watched addresses(필수, 아래 3개 중 하나만):

- `ADDRESSES_JSON_B64` (추천, Secrets): base64(JSON)
- `ADDRESSES_JSON` (Secrets): JSON 문자열
- `ADDRESSES_FILE` (비추천): 컨테이너 내부 파일 경로(볼륨 전제)

`ADDRESSES_JSON_B64` 생성 예시:

```bash
cat <<'JSON' | base64
[
  { "btc_address": "tb1q...", "borrower": "0x..." }
]
JSON
```

튜닝(선택):

- `SPV_CONFIRMATIONS` (기본 6)
- `SPV_POLL_INTERVAL` (기본 60초)
- `SPV_RUN_ONCE` (기본 false)
- `RELAYER_ARGS` (start-worker.sh가 그대로 CLI 인자로 전달)

네트워킹:

- `hashcredit-prover`는 외부 HTTP가 필요 없습니다.
- Railway에서 Public Networking을 끄는 것을 권장합니다.

## 6) 커스텀 도메인 연결(API)

API는 `api-hashcredit.studioliq.com`을 사용합니다.

1. Railway에서 `hashcredit-api` 서비스 -> Networking/Domain에서 커스텀 도메인을 추가합니다.
2. Railway가 안내하는 DNS 레코드(CNAME/A)를 등록합니다.
3. HTTPS 발급이 완료되면 FE에서 `VITE_API_URL=https://api-hashcredit.studioliq.com`로 호출합니다.

## 7) 배포 후 검증(체크리스트)

API:

1. `GET /health`가 200을 반환하는지 확인합니다.
2. FE에서 API URL이 맞는지 확인합니다.
3. 운영 엔드포인트 호출 시 `X-API-Key: <API_TOKEN>`이 필요합니다.

Worker:

1. 로그에 `Loaded N watched addresses`가 출력되는지 확인합니다.
2. Postgres 연결 오류가 없는지 확인합니다.
3. (데모) watched 주소로 들어오는 테스트넷 payout을 감지해 proof 제출까지 진행되는지 확인합니다.

## 8) 모노레포 주의사항(Railway)

1. Railway에서 서비스 Root Directory를 잘못 잡으면(레포 루트 등) 빌드가 꼬일 수 있습니다.
2. Railway Config as Code(`railway.toml`)를 쓰는 경우:
   - **Config file path는 Root Directory를 따라가지 않습니다.**
   - 설정했다면 `/offchain/api/railway.toml` 같은 "절대 경로"로 지정해야 합니다.
   - 이 프로젝트는 Dockerfile 기반 배포가 기본이므로, 별도 `railway.toml` 없이도 배포 가능합니다.

