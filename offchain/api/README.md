# HashCredit API (`offchain/api`)

FastAPI 기반의 HTTP API로, 프론트엔드가 **Bitcoin RPC / SPV proof 생성 / 온체인 트랜잭션 전송(운영키)** 를 쉽게 호출할 수 있게 하는 브리지입니다.

## 하는 일

- SPV proof 생성: `POST /spv/build-proof`
- 체크포인트 등록(온체인): `POST /checkpoint/set`
- borrower BTC 주소(pubkeyHash) 등록(온체인): `POST /borrower/set-pubkey-hash`
- borrower 등록(온체인): `POST /manager/register-borrower`
- proof 제출(온체인): `POST /spv/submit`
- (메인넷 권장) borrower 소유권 증명 기반 등록: `POST /claim/start`, `POST /claim/complete`
- 헬스체크: `GET /health`

## 설치

```bash
cd offchain/api
pip install -e .
```

개발용:

```bash
pip install -e ".[dev]"
```

## 환경 변수

```bash
cp .env.example .env
```

중요 포인트:

- `API_TOKEN`을 설정하면 **온체인 트랜잭션을 전송하는 엔드포인트**가 `X-API-Key` 헤더를 요구합니다.
  - claim 엔드포인트까지 토큰을 강제하려면 `CLAIM_REQUIRE_API_TOKEN=true`를 사용하세요.
- 메인넷급 매핑을 쓰려면 `BORROWER_MAPPING_MODE=claim`로 전환하고 `CLAIM_SECRET`을 설정합니다.
- `ALLOWED_ORIGINS`는 **JSON 배열 문자열**입니다.
  - 예: `["https://hashcredit.studioliq.com","http://localhost:5173"]`
- Bitcoin RPC가 public endpoint(무인증)인 경우 `BITCOIN_RPC_USER/PASSWORD`는 비워도 됩니다.

## 실행

```bash
hashcredit-api
```

또는:

```bash
uvicorn hashcredit_api.main:app --host 127.0.0.1 --port 8000
```

API 문서:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 인증

1. `.env`에 `API_TOKEN` 설정(권장: 항상 설정)
2. 모든 요청에 `X-API-Key: <API_TOKEN>` 추가

예:

```bash
curl -H "X-API-Key: <API_TOKEN>" http://localhost:8000/health
```

## 엔드포인트

### 1) 헬스체크

```bash
curl -H "X-API-Key: <API_TOKEN>" http://localhost:8000/health
```

### 2) 체크포인트 등록(온체인)

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/checkpoint/set \
  -d '{"height": 4842343, "dry_run": false}'
```

### 3) borrower BTC 주소(pubkeyHash) 등록(온체인)

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/borrower/set-pubkey-hash \
  -d '{"borrower":"0x...","btc_address":"tb1q...","dry_run": false}'
```

### 4) borrower 등록(온체인, Manager)

이 엔드포인트는 `btcPayoutKeyHash = keccak256(utf8(btc_address))`를 계산한 뒤,
`HashCreditManager.registerBorrower(borrower, btcPayoutKeyHash)`를 호출합니다.

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/manager/register-borrower \
  -d '{"borrower":"0x...","btc_address":"tb1q...","dry_run": false}'
```

### 5) SPV proof 생성

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/spv/build-proof \
  -d '{
    "txid": "e4c6...",
    "output_index": 0,
    "checkpoint_height": 4842333,
    "target_height": 4842343,
    "borrower": "0x..."
  }'
```

### 6) proof 제출(온체인)

```bash
curl -H "X-API-Key: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8000/spv/submit \
  -d '{"proof_hex":"0x...","dry_run": false}'
```

### 7) (메인넷 권장) borrower claim 기반 등록

`BORROWER_MAPPING_MODE=claim`일 때만 사용합니다.

이 플로우는 borrower가 아래를 제출하도록 설계되어 있습니다.
- EVM 서명: `personal_sign`로 message 서명
- BTC 서명: 지갑의 `signmessage` 출력(base64) 서명
  - 현재 구현은 BIP-137 스타일을 검증하며, repo에서 지원하는 주소 타입(p2pkh/p2wpkh)에 한해 동작합니다.

1) claim 시작:

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/start \
  -d '{"borrower":"0x...","btc_address":"bc1q..."}'
```

응답의 `message`를 **EVM 지갑과 BTC 지갑 둘 다**로 서명합니다.

2) claim 완료(검증 + 온체인 등록):

```bash
curl -H "Content-Type: application/json" \
  -X POST http://localhost:8000/claim/complete \
  -d '{
    "claim_token":"...",
    "evm_signature":"0x...",
    "btc_signature":"<base64>",
    "dry_run": false
  }'
```

## 보안/운영 메모(중요)

- 이 API는 운영키(`PRIVATE_KEY`)로 온체인 트랜잭션을 전송할 수 있으므로, 외부 노출 시 반드시:
  - `API_TOKEN`을 강하게 설정
  - CORS/방화벽/레이트리밋 등으로 접근을 제한
- borrower(EVM) <-> BTC 주소 매핑은 메인넷에서 임의 매핑 공격이 가능하므로, 프로덕션에서는 `BORROWER_MAPPING_MODE=claim`를 권장합니다.
- Claim 엔드포인트는 “유효한 서명”이 없으면 온체인 트랜잭션을 보내지 않지만, 운영 환경에서는 레이트리밋/방화벽/사용자 인증 등 추가 방어가 필요합니다.
