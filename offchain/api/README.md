# HashCredit API (`offchain/api`)

FastAPI 기반의 HTTP API로, 프론트엔드가 **Bitcoin RPC / SPV proof 생성 / 온체인 트랜잭션 전송(운영키)** 를 쉽게 호출할 수 있게 하는 브리지입니다.

## 하는 일

- SPV proof 생성: `POST /spv/build-proof`
- 체크포인트 등록(온체인): `POST /checkpoint/set`
- borrower BTC 주소(pubkeyHash) 등록(온체인): `POST /borrower/set-pubkey-hash`
- borrower 등록(온체인): `POST /manager/register-borrower`
- proof 제출(온체인): `POST /spv/submit`
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

- `API_TOKEN`을 설정하면 **모든 요청이 `X-API-Key` 헤더를 요구**합니다.
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

## 보안/운영 메모(중요)

- 이 API는 운영키(`PRIVATE_KEY`)로 온체인 트랜잭션을 전송할 수 있으므로, 외부 노출 시 반드시:
  - `API_TOKEN`을 강하게 설정
  - CORS/방화벽/레이트리밋 등으로 접근을 제한
- borrower(EVM) <-> BTC 주소 매핑은 메인넷에서 임의 매핑 공격이 가능하므로, 프로덕션에서는:
  - nonce 기반 challenge
  - EVM 서명 + BTC 서명(BIP-322 권장)
  - 검증 후에만 온체인 등록
  방식을 권장합니다.

