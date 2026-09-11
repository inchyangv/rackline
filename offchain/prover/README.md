# HashCredit Prover/Worker (`offchain/prover`)

Bitcoin 트랜잭션에 대한 **SPV proof(헤더 체인 + Merkle inclusion)** 를 만들고, 필요하면 온체인에 제출까지 자동화하는 CLI/워커입니다.

## 하는 일

- `build-proof`: txid/vout/height 입력으로 SPV proof 생성
- `submit-proof`: proof를 만들어 `HashCreditManager.submitPayout`까지 제출
- `set-checkpoint`: `CheckpointManager`에 체크포인트(블록 헤더) 등록
- `set-borrower-pubkey-hash`: `BtcSpvVerifier`에 borrower(EVM) ↔ BTC 주소(pubkeyHash) 등록
- `run-relayer`: 감시 주소 목록을 폴링하며 자동으로 proof 생성/제출(worker)

## 설치

```bash
cd offchain/prover
pip install -e .
```

개발용:

```bash
pip install -e ".[dev]"
```

## 환경 변수

Railway 배포 시에는 `.env` 대신 Railway Variables/Secrets에 동일 키를 넣으면 됩니다.

```bash
cp .env.example .env
```

필수(라이브 proof 기준):

- `BITCOIN_RPC_URL`
  - 본인 노드(testnet): 보통 `http://127.0.0.1:18332`
  - 퍼블릭(testnet, 무인증 예시): `https://bitcoin-testnet-rpc.publicnode.com`
- `EVM_RPC_URL` (Creditcoin testnet RPC)
- `CHAIN_ID` (기본 102031)
- `PRIVATE_KEY` (온체인 트랜잭션 서명 키)
- `HASH_CREDIT_MANAGER`
- `CHECKPOINT_MANAGER`

## SPV proof 제약(실전 팁)

가스/비용 상, proof에 포함되는 **header chain 길이를 제한**하는 전략을 사용합니다.

- `checkpoint_height`와 `target_height` 차이는 보통 **1..144** 범위로 유지하는 것을 권장합니다.

## 사용법

### 1) 체크포인트 등록

```bash
hashcredit-prover set-checkpoint <height> \
  --checkpoint-manager $CHECKPOINT_MANAGER
```

### 2) borrower BTC 주소(pubkeyHash) 등록

```bash
hashcredit-prover set-borrower-pubkey-hash \
  <borrower_evm> <btc_address> \
  --spv-verifier $BTC_SPV_VERIFIER
```

지원 주소 형식:

- bech32 P2WPKH: testnet `tb1q...`, mainnet `bc1q...`
- base58 P2PKH: testnet `m.../n...`, mainnet `1...`

### 3) proof 생성(HEX)

```bash
hashcredit-prover build-proof \
  <txid> <output_index> <checkpoint_height> <target_height> <borrower_evm> \
  --hex
```

### 4) proof 생성 + 제출

```bash
hashcredit-prover submit-proof \
  <txid> <output_index> <borrower_evm> \
  --checkpoint <checkpoint_height> \
  --target <target_height> \
  --manager $HASH_CREDIT_MANAGER
```

옵션:

- `--dry-run`: proof는 만들되 제출하지 않음
- `--hex-only`: 제출 없이 proof hex만 출력

### 5) 워커(run-relayer)

감시 주소 목록을 JSON으로 준비:

```json
[
  {"btc_address": "tb1q...", "borrower": "0x1234...", "enabled": true}
]
```

로컬:

```bash
hashcredit-prover run-relayer addresses.json \
  --manager $HASH_CREDIT_MANAGER \
  --checkpoint-manager $CHECKPOINT_MANAGER
```

Railway 권장(환경 변수로 주입):

- `ADDRESSES_JSON_B64`: 위 JSON을 base64로 인코딩한 문자열

```bash
base64 < addresses.json | tr -d '\n'
```

## 요구 사항

- Python 3.11+
- Bitcoin RPC 접근
  - 라이브 proof는 임의 txid 조회가 필요하므로, 본인 노드라면 `txindex=1`을 권장합니다.
