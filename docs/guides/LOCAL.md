# LOCAL 개발/실행 가이드 (ctc-btc-miner / HashCredit)

이 문서는 **로컬에서 Anvil(로컬 EVM) + 컨트랙트 배포 + Python relayer 실행**을 끝까지 돌려보고,
문제가 생겼을 때 **인턴도 따라할 수 있는 수준으로 디버깅하는 방법**을 정리한 문서입니다.

> 주의
> - 로컬 Anvil에 쓰는 키(기본 제공 키)는 **로컬에서만** 사용하세요. 테스트넷/메인넷에 절대 재사용 금지.
> - `.env` / `.env.local`은 `.gitignore`에 포함되어 있으니 커밋하지 마세요.

---

## 0) TL;DR (처음 한 번에 로컬로 띄우기)

터미널 2개를 켭니다.

### 터미널 A: 로컬 체인 실행

```bash
make anvil
```

### 터미널 B: 배포 + relayer 실행

```bash
# 1) Foundry deps
forge install

# 2) Python venv (Python 3.11+ 권장)
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e "offchain/relayer[dev]"

# 3) 환경 파일 준비
cp .env.example .env

# 4) .env를 "로컬용"으로 수정 (예시는 아래 '2) .env(로컬용) 설정' 참고)

# 4-1) (추천) 현재 쉘에 .env 로드 (cast / make에서 변수 사용)
set -a
source .env
set +a

# 5) 컨트랙트 배포 (Anvil로)
make deploy-local

# 6) 배포 로그에 나온 주소들을 .env에 채우기
# - HASH_CREDIT_MANAGER=...
# - VERIFIER=...
# (선택) LENDING_VAULT=...

# 7) Borrower 등록
export RPC_URL=http://localhost:8545
export BORROWER_EVM=0x0000000000000000000000000000000000000000  # 예시(아래에서 실제로 설정)
export BTC_ADDR=bc1qexampleaddress                               # 예시(아래에서 실제로 설정)
export BTC_KEY_HASH=$(cast keccak "$BTC_ADDR")
cast send $HASH_CREDIT_MANAGER "registerBorrower(address,bytes32)" \
  $BORROWER_EVM \
  $BTC_KEY_HASH \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY

# 8) Relayer 단발 실행 (payout 있으면 submit)
hashcredit-relayer run --once --btc-address "$BTC_ADDR" --evm-address "$BORROWER_EVM"
```

> `BTC_ADDR`는 mempool.space에 트랜잭션 히스토리가 있는 주소여야 실제로 “감지 → 제출”이 발생합니다.
> 히스토리가 없는 주소면 “0건 처리”가 정상입니다.

---

## 1) 사전 준비물 (로컬 개발 환경)

### 필수

- **Foundry** (forge / cast / anvil)
  - 설치: `curl -L https://foundry.paradigm.xyz | bash && foundryup`
  - 확인: `forge --version`, `cast --version`, `anvil --version`
- **Python 3.11+**
  - 확인: `python3 --version`
- macOS 기준: `make` 사용 가능해야 함 (`Makefile` 기반)

### 선택(있으면 편함)

- `direnv` (환경변수 자동 로딩)
- VS Code / PyCharm (디버거)
- `sqlite3` CLI (relayer DB 확인)

---

## 2) .env(로컬용) 설정

루트의 `.env.example`을 복사해서 `.env`를 만든 다음, **로컬 Anvil 기준으로 값을 바꿉니다.**

```bash
cp .env.example .env
```

`.env`에서 아래 항목들을 최소로 맞추면 로컬에서 돌아갑니다.

### EVM (로컬 Anvil)

```dotenv
RPC_URL=http://localhost:8545
CHAIN_ID=31337
```

### 키 설정 (중요: 2개의 키가 등장함)

Relayer는 키를 2개 씁니다.

- `PRIVATE_KEY`: **EVM 트랜잭션을 보내는 키** (submitPayout 호출 주체)
- `RELAYER_PRIVATE_KEY`: **EIP-712 서명을 만드는 키** (RelayerSigVerifier가 검증하는 서명자)

가장 단순한 로컬 구성은 **둘을 같은 키로 두는 것**입니다.

```dotenv
PRIVATE_KEY=0x...
RELAYER_PRIVATE_KEY=0x...
```

> `make anvil`을 켜면 터미널에 10개 계정 주소/프라이빗키가 출력됩니다.  
> 그중 아무 키나 골라서 `PRIVATE_KEY`/`RELAYER_PRIVATE_KEY`에 동일하게 넣으면 됩니다.

### 컨트랙트 주소 (배포 후 채움)

배포 전에는 비워두고, `make deploy-local` 실행 후 콘솔에 찍힌 주소를 그대로 넣습니다.

```dotenv
HASH_CREDIT_MANAGER=0x...
VERIFIER=0x...
LENDING_VAULT=0x...   # 선택(문서/툴링용)
```

> `hashcredit-relayer`가 실제로 필요로 하는 건 `HASH_CREDIT_MANAGER`, `VERIFIER` 두 개입니다.

### Bitcoin 데이터 소스 (MVP)

Relayer는 기본적으로 mempool.space API로 주소 트랜잭션을 읽습니다.

```dotenv
BITCOIN_API_URL=https://mempool.space/api
CONFIRMATIONS_REQUIRED=0
POLL_INTERVAL_SECONDS=10
```

로컬에서 빨리 확인하려면 `CONFIRMATIONS_REQUIRED=0`으로 두는 걸 추천합니다.

### Relayer DB (중복 제출 방지)

```dotenv
DATABASE_URL=sqlite:///./relayer.db
```

`relayer.db`는 “이미 처리한 (txid,vout)”를 저장해서 같은 payout을 다시 제출하지 않게 합니다.
테스트를 반복하다 꼬이면 DB 파일을 지우고 다시 시작하면 됩니다.

---

## 3) 로컬에서 컨트랙트 띄우기 (Anvil + Deploy)

### 3-1. Anvil 실행

```bash
make anvil
```

기본 포트는 `8545`, 체인 ID는 `31337`입니다. (Makefile 기준)

### 3-2. 컨트랙트 배포

새 터미널에서:

```bash
make deploy-local
```

배포 로그에서 아래 항목을 찾아 `.env`에 채웁니다.

- `HashCreditManager deployed at: ...` → `HASH_CREDIT_MANAGER=...`
- `RelayerSigVerifier deployed at: ...` → `VERIFIER=...`
- (선택) `LendingVault deployed at: ...` → `LENDING_VAULT=...`

> 배포 스크립트(`script/Deploy.s.sol`)는 `PRIVATE_KEY`를 읽어 배포합니다.  
> `.env`에 `PRIVATE_KEY`가 없거나 잘못되면 배포가 실패합니다.

---

## 4) 로컬 데모 플로우 (등록 → payout 제출 → credit 확인 → borrow)

### 4-1. borrower EVM 주소 선택

Anvil이 출력하는 accounts 중 하나를 borrower로 씁니다. 예:

- 터미널(Anvil) 출력에서 **Address #1** 같은 걸 복사해 `BORROWER_EVM`로 둡니다.

```bash
export BORROWER_EVM=0x...
```

### 4-2. borrower 등록 (owner만 가능)

`registerBorrower`는 `HashCreditManager.owner()`만 호출할 수 있습니다.
로컬에서는 보통 배포에 쓴 `PRIVATE_KEY`가 owner입니다.

BTC 주소는 아무 문자열을 넣어도 되지만(현재 MVP에서는 엄격 검증 없음),
일단 실제로 감시할 주소를 넣고 그 해시를 등록하는 걸 추천합니다.

```bash
export BTC_ADDR=bc1q...
export BTC_KEY_HASH=$(cast keccak "$BTC_ADDR")

cast send "$HASH_CREDIT_MANAGER" "registerBorrower(address,bytes32)" \
  "$BORROWER_EVM" \
  "$BTC_KEY_HASH" \
  --rpc-url "$RPC_URL" \
  --private-key "$PRIVATE_KEY"
```

등록 확인:

```bash
cast call "$HASH_CREDIT_MANAGER" "getBorrowerInfo(address)(uint8,bytes32,uint128,uint128,uint128,uint128,uint64,uint64,uint32)" \
  "$BORROWER_EVM" \
  --rpc-url "$RPC_URL"
```

> 반환값이 길어서 보기 불편하면, 최소한 `status`(첫 번째 값)가 1(Active)인지 확인하세요.

### 4-3. Relayer로 payout 감지/제출

1) 해당 BTC 주소에 payout이 있는지 먼저 확인:

```bash
hashcredit-relayer check "$BTC_ADDR" --confirmations 0
```

2) 단발 실행(한 번만 돌고 종료):

```bash
hashcredit-relayer run --once --btc-address "$BTC_ADDR" --evm-address "$BORROWER_EVM"
```

정상이라면 “Submitted: 0x…” 같은 트랜잭션 해시가 출력됩니다.

### 4-4. Credit / Borrow 확인

credit 확인:

```bash
cast call "$HASH_CREDIT_MANAGER" "getAvailableCredit(address)(uint256)" \
  "$BORROWER_EVM" \
  --rpc-url "$RPC_URL"
```

borrow(USDC 6 decimals, 예: $1000 = 1000_000000):

```bash
export BORROWER_PK=0x... # borrower 주소에 해당하는 프라이빗키(Anvil 출력에서 복사)

cast send "$HASH_CREDIT_MANAGER" "borrow(uint256)" \
  1000000000 \
  --rpc-url "$RPC_URL" \
  --private-key "$BORROWER_PK"
```

borrow 후 borrower의 USDC 잔액 확인(컨트랙트에서 stablecoin 주소 조회 후 balanceOf):

```bash
export USDC=$(cast call "$HASH_CREDIT_MANAGER" "stablecoin()(address)" --rpc-url "$RPC_URL")
cast call "$USDC" "balanceOf(address)(uint256)" "$BORROWER_EVM" --rpc-url "$RPC_URL"
```

---

## 5) 디버깅 가이드 (실패했을 때 어디부터 볼지)

### 5-1. “일단 이것부터” 체크리스트

1) Anvil이 떠 있는가? (`RPC_URL`이 맞는가?)
2) `.env`의 `CHAIN_ID`가 Anvil 체인 ID(기본 31337)와 같은가?
3) `.env`에 `HASH_CREDIT_MANAGER`, `VERIFIER`가 실제 배포 주소로 채워졌는가?
4) `RELAYER_PRIVATE_KEY`의 주소가, 컨트랙트의 `RelayerSigVerifier.relayerSigner()`와 일치하는가?
5) borrower가 등록(Active) 되어 있는가?

Relayer signer 일치 여부 확인:

```bash
cast call "$VERIFIER" "relayerSigner()(address)" --rpc-url "$RPC_URL"
cast wallet address --private-key "$RELAYER_PRIVATE_KEY"
```

### 5-2. Foundry(컨트랙트) 디버깅

#### 테스트로 먼저 재현

```bash
make test
```

특정 테스트만:

```bash
forge test --match-test test_submitPayout -vvvv
```

#### 트랜잭션 리버트 이유 보기

`cast send`가 실패하면 `--trace`를 붙이면 원인 파악이 빨라집니다.

```bash
cast send ... --trace
```

#### 컨트랙트 상태 확인에 자주 쓰는 call들

```bash
# owner 확인
cast call "$HASH_CREDIT_MANAGER" "owner()(address)" --rpc-url "$RPC_URL"

# borrower 상태/부채/한도 확인
cast call "$HASH_CREDIT_MANAGER" "getBorrowerInfo(address)(uint8,bytes32,uint128,uint128,uint128,uint128,uint64,uint64,uint32)" \
  "$BORROWER_EVM" --rpc-url "$RPC_URL"

# payout 처리 여부
cast call "$HASH_CREDIT_MANAGER" "isPayoutProcessed(bytes32,uint32)(bool)" \
  0x...txid_bytes32 0 --rpc-url "$RPC_URL"
```

### 5-3. Relayer(Python) 디버깅

#### 단발 모드로 돌리기

무조건 `--once`부터 사용하세요. 반복 루프에서 디버깅하기 훨씬 어렵습니다.

```bash
hashcredit-relayer run --once --btc-address "$BTC_ADDR" --evm-address "$BORROWER_EVM"
```

#### .env를 못 읽는 것 같을 때

Relayer는 기본적으로 **현재 작업 디렉토리의 `.env`**를 읽습니다.
루트에서 실행하거나, `--config`로 경로를 명시하세요.

```bash
hashcredit-relayer run --config .env --once --btc-address "$BTC_ADDR" --evm-address "$BORROWER_EVM"
```

#### pdb로 브레이크포인트 걸기 (CLI)

```bash
python -m pdb -m hashcredit_relayer run --once --btc-address "$BTC_ADDR" --evm-address "$BORROWER_EVM"
```

#### relayer DB 확인 (중복처리/상태 꼬임)

```bash
sqlite3 relayer.db "select txid, vout, borrower, status, tx_hash, submitted_at from processed_payouts order by id desc limit 20;"
```

초기화(주의: 로컬에서만):

```bash
rm -f relayer.db
```

---

## 6) 자주 나는 에러와 해결법

### A) `Invalid signature`

원인: `RELAYER_PRIVATE_KEY`로 만든 서명자의 주소가, 온체인 `relayerSigner`와 다름.

해결:
- 가장 쉬운 방법: 로컬에서는 `PRIVATE_KEY`와 `RELAYER_PRIVATE_KEY`를 같은 키로 둔다.
- 키를 분리하려면 배포 때 `RELAYER_SIGNER`를 맞춰야 함.

배포 시 relayer signer를 명시해서 맞추는 방법:

```bash
export RELAYER_ADDR=$(cast wallet address --private-key "$RELAYER_PRIVATE_KEY")
export RELAYER_SIGNER=$RELAYER_ADDR
make deploy-local
```

### B) `Deadline expired`

원인: 서명에 포함된 `deadline`(기본: 현재시간+1h)이 지나서 제출됨.

해결:
- relayer를 다시 돌려 새 서명을 만들고 제출.
- 로컬에서 시간 꼬이면(슬립/서스펜드) Anvil과 relayer를 재시작.

### C) `Payout already processed`

원인: 같은 `(txid, vout)`가 이미 처리됨 (온체인/로컬DB 둘 다 가능).

해결:
- 다른 BTC 주소/다른 payout으로 테스트.
- 로컬에서만: `relayer.db` 삭제 후 재시도(온체인 처리는 그대로 남음).

### D) `EVM client not configured - dry run mode`

원인: `.env`에 `PRIVATE_KEY` 또는 `HASH_CREDIT_MANAGER`가 비어있어서 EVM submit을 안 함.

해결:
- `.env`에 `PRIVATE_KEY`, `HASH_CREDIT_MANAGER`를 채우고 다시 실행.

### E) `ConnectionError` / RPC 연결 실패

원인: Anvil이 안 떠있거나 `RPC_URL`이 틀림.

해결:
- `make anvil` 실행 상태 확인
- `.env`의 `RPC_URL=http://localhost:8545` 확인

---

## 7) SPV 모드 실행 가이드 (Creditcoin Testnet + Bitcoin Testnet)

SPV 모드는 Bitcoin SPV proof를 사용하여 payout을 검증합니다.
RelayerSigVerifier 대신 BtcSpvVerifier를 사용합니다.

### 7-1. SPV 모드 배포

로컬 `.env`와 섞이지 않게 하려면 `.env.spv` 같은 별도 파일을 만들어 쓰는 걸 추천합니다.
(`set -a; source .env.spv; set +a`로 로드)

```bash
# Creditcoin testnet에 SPV 스택 배포
forge script script/DeploySpv.s.sol \
    --rpc-url "$EVM_RPC_URL" \
    --broadcast
```

먼저 `.env`(또는 `.env.spv`)에 아래 기본 값을 세팅한 뒤, 배포 로그에 나온 주소들을 채웁니다:

```dotenv
# Creditcoin testnet
EVM_RPC_URL=https://rpc.cc3-testnet.creditcoin.network
CHAIN_ID=102031
PRIVATE_KEY=0x...

# SPV Contracts
CHECKPOINT_MANAGER=0x...
BTC_SPV_VERIFIER=0x...
HASH_CREDIT_MANAGER=0x...
```

### 7-2. Bitcoin Testnet Checkpoint 등록

Bitcoin Core (testnet mode)가 필요합니다:

```bash
# bitcoin.conf
testnet=1
txindex=1
rpcuser=your_user
rpcpassword=your_password
```

Bitcoin testnet RPC 환경변수:

```dotenv
BITCOIN_RPC_URL=http://127.0.0.1:18332
BITCOIN_RPC_USER=your_user
BITCOIN_RPC_PASSWORD=your_password
```

Checkpoint 등록 (예: height 2500000):

```bash
hashcredit-prover set-checkpoint 2500000 \
    --checkpoint-manager $CHECKPOINT_MANAGER \
    --private-key $PRIVATE_KEY
```

### 7-3. Borrower BTC 주소 등록

1. Borrower 등록 (Manager):

```bash
cast send $HASH_CREDIT_MANAGER \
    "registerBorrower(address,bytes32)" \
    $BORROWER_EVM \
    $(cast keccak "$BORROWER_BTC_ADDRESS") \
    --rpc-url $EVM_RPC_URL \
    --private-key $PRIVATE_KEY
```

2. Borrower pubkey hash 등록 (SPV Verifier):

```bash
hashcredit-prover set-borrower-pubkey-hash \
    $BORROWER_EVM \
    $BORROWER_BTC_ADDRESS \
    --spv-verifier $BTC_SPV_VERIFIER \
    --private-key $PRIVATE_KEY
```

### 7-4. SPV Proof 제출 (단발)

Bitcoin testnet에서 borrower 주소로 payout이 완료된 후:

```bash
hashcredit-prover submit-proof \
    <TXID> <OUTPUT_INDEX> $BORROWER_EVM \
    --checkpoint <CHECKPOINT_HEIGHT> \
    --target <TX_BLOCK_HEIGHT> \
    --manager $HASH_CREDIT_MANAGER \
    --private-key $PRIVATE_KEY
```

예시:
```bash
hashcredit-prover submit-proof \
    abc123...txid \
    0 \
    0x1234...borrower \
    --checkpoint 2500000 \
    --target 2500010 \
    --manager $HASH_CREDIT_MANAGER
```

### 7-5. SPV Relayer 실행 (자동 감시)

addresses.json 준비:
```json
[
    {"btc_address": "tb1q...", "borrower": "0x1234...", "enabled": true}
]
```

Relayer 실행:
```bash
hashcredit-prover run-relayer addresses.json \
    --manager $HASH_CREDIT_MANAGER \
    --checkpoint-manager $CHECKPOINT_MANAGER \
    --confirmations 6 \
    --poll-interval 60
```

### 7-6. SPV 모드 디버깅

#### Checkpoint 확인

```bash
# 최신 checkpoint height
cast call $CHECKPOINT_MANAGER "latestCheckpointHeight()(uint32)" --rpc-url $EVM_RPC_URL

# Checkpoint 상세 정보
cast call $CHECKPOINT_MANAGER "getCheckpoint(uint32)((bytes32,uint32,uint256,uint32))" <HEIGHT> --rpc-url $EVM_RPC_URL
```

#### Borrower pubkey hash 확인

```bash
cast call $BTC_SPV_VERIFIER "getBorrowerPubkeyHash(address)(bytes20)" $BORROWER_EVM --rpc-url $EVM_RPC_URL
```

#### SPV Proof Format and Confirmations

The SPV proof includes:
- `checkpointHeight`: Height of anchor checkpoint block
- `headers[]`: Array of 80-byte headers from checkpoint+1 to **tip** (not target block)
- `txBlockIndex`: Index within `headers[]` where the transaction is included (0-based)
- `rawTx`: Full serialized Bitcoin transaction
- `merkleProof[]`: Merkle branch for transaction inclusion
- `txIndex`: Transaction's index in the block (for merkle proof direction)
- `outputIndex`: Output index (vout) in transaction
- `borrower`: Claimed borrower address

**Confirmations calculation:**
```
confirmations = headers.length - txBlockIndex
```

For example:
- If `headers.length = 11` and `txBlockIndex = 5`, then `confirmations = 6`
- The merkle proof is verified against `headers[txBlockIndex].merkleRoot`
- `PayoutEvidence.blockHeight` is calculated as `checkpointHeight + 1 + txBlockIndex`

#### SPV Validation Rules

- **Header chain max 144 blocks** (~1 day)
- **Min 6 confirmations** required (calculated as `headers.length - txBlockIndex >= 6`)
- **No retarget boundary crossing** (checkpoint and tip must be in same 2016-block epoch)
- **Difficulty validation**: All headers must have same bits as checkpoint
- **Supported scripts**: P2WPKH, P2PKH only

If checkpoint is too old, the header chain may exceed 144 blocks.
In that case, register a new checkpoint.

---

## 8) (참고) Prover CLI 전체 명령어

```bash
# Prover 설치
pip install -e "offchain/prover[dev]"

# 명령어 목록
hashcredit-prover --help

# 개별 명령어
hashcredit-prover build-proof --help
hashcredit-prover verify-local --help
hashcredit-prover set-checkpoint --help
hashcredit-prover set-borrower-pubkey-hash --help
hashcredit-prover submit-proof --help
hashcredit-prover run-relayer --help
```

자세한 사용법은 `offchain/prover/README.md` 참고.

---

## 9) (선택) 프론트 대시보드 (apps/web)

컨트랙트 상태 조회 + 일부 트랜잭션(예: `submitPayout`, `borrow`, `repay`)을 클릭으로 실행할 수 있는 간단한 UI가 있습니다.

```bash
cd apps/web
cp .env.example .env
# apps/web/.env 에서 VITE_* 주소들 채우기
npm install
npm run dev
```

메타마스크를 쓴다면 Creditcoin testnet을 추가/전환해야 합니다:
- chainId: `102031`
- RPC: `.env`의 `VITE_RPC_URL` (기본값: `https://rpc.cc3-testnet.creditcoin.network`)

---

## Appendix A: Bitcoin txid Format Standard

This section documents the protocol's standard for representing Bitcoin transaction IDs (`txid`) across all components.

### Background

Bitcoin uses different byte orderings for txid:
- **Internal byte order**: The raw sha256d hash result (as stored in Bitcoin data structures)
- **Display format**: Reversed bytes (as shown in block explorers like blockchain.info, mempool.space)

Example for the genesis block coinbase tx:
- Display: `4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b`
- Internal: `3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a`

### Protocol Standard

**On-chain (smart contracts)**: All `bytes32 txid` values use **internal byte order**.

This is consistent with how Bitcoin itself stores txids internally and is required for:
- Merkle proof verification (txid must match merkle tree entries)
- Replay protection (consistent hashing of txid+vout)

### Off-chain Conversion

When working with external APIs (mempool.space, block explorers):
1. Receive txid in **display format** (reversed)
2. Convert to **internal format** before sending to contracts

Python utilities:
```python
# offchain/prover
from hashcredit_prover.bitcoin import txid_display_to_internal, txid_internal_to_display

# offchain/relayer
from hashcredit_relayer.signer import txid_to_bytes32, bytes32_to_txid_display
```

### Example

```python
# API returns display format
display_txid = "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"

# Convert for on-chain use
internal = txid_display_to_internal(display_txid)  # or txid_to_bytes32()
# internal = bytes starting with 0x3b...

# To log/debug, convert back to display
display = txid_internal_to_display(internal)  # or bytes32_to_txid_display()
# display = "4a5e1e4b..."
```

### Verification

Both `offchain/relayer` and `offchain/prover` implement identical conversion logic. Unit tests verify consistency:
- `offchain/relayer/tests/test_signer.py`
- `offchain/prover/tests/test_bitcoin.py`
