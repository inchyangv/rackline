# HashCredit — TICKET.md
> 규칙: 가장 위의 미완료 티켓부터 순서대로 처리한다.  
> 각 티켓은 (1) 코드 변경 (2) 테스트 (3) 문서/티켓 업데이트까지 포함해야 Done이다.

---

## 상태 표기
- [ ] TODO
- [~] IN PROGRESS
- [x] DONE
- [!] BLOCKED (사유 기재)

---

## P0 — Hackathon MVP (Relayer Signature Oracle)

### T0.1 Repository Skeleton + Tooling
- Priority: P0
- Status: [x] DONE
- 목적: 레포 기본 구조, 빌드/테스트/포맷 환경을 만든다.
- 작업:
    - Foundry 초기화, 기본 CI 스크립트(로컬 기준) 작성
    - solidity formatter / lint(선택) 설정
    - `/offchain/relayer` 파이썬 패키지 스켈레톤
    - `.env.example` 작성
- 산출물:
    - `foundry.toml`, `remappings.txt` (필요 시)
    - `Makefile` 또는 `justfile` (선택)
    - 폴더 구조 확정
- 완료 조건:
    - `forge test`가 빈 테스트라도 통과
    - 파이썬 패키지가 실행 진입점(`python -m ...`)을 가진다

---

### T0.2 Define Interfaces & Data Types (Core ABI Fixation)
- Priority: P0
- Status: [x] DONE
- 목적: Verifier Adapter, Manager/Vault의 외부 인터페이스를 먼저 고정한다(향후 교체 최소화).
- 작업:
    - `IVerifierAdapter` 인터페이스 정의
    - 공통 `PayoutEvidence` struct 정의(또는 반환값 세트)
    - 이벤트 목록 정의
    - 에러 타입 정의(custom errors)
- 완료 조건:
    - 인터페이스가 문서화되고, 이후 티켓에서 변경 최소화 원칙 적용

---

### T0.3 LendingVault (Single Stablecoin) — Minimal Viable Vault
- Priority: P0
- Status: [x] DONE
- 목적: 스테이블코인 유동성을 받아 borrow/repay/interest를 처리한다.
- 스코프:
    - 단일 ERC20 stablecoin (mock로 시작)
    - 이자 모델: 고정 APR 또는 간단 utilization 기반 중 하나 선택
    - 예치/인출(대출 유동성 공급) 기능 포함
- 작업:
    - `deposit/withdraw` (LP shares 모델은 단순화 가능)
    - `borrow/repay`는 `HashCreditManager`만 호출 가능(onlyManager)
    - 이자 누적: block.timestamp 기반 단순 방식
- 테스트:
    - deposit/withdraw
    - borrow 시 vault balance 감소
    - repay 시 증가 + debt 감소
- 완료 조건:
    - `HashCreditManager` 연동 가능한 ABI 제공
    - 최소 단위 테스트 통과

---

### T0.4 HashCreditManager — Borrower Registry + Credit Line Core
- Priority: P0
- Status: [x] DONE
- 목적: Borrower 등록, 상태 관리, payout 반영, creditLimit 산출을 구현한다.
- 작업:
    - borrower 등록(`registerBorrower`)
    - borrower 상태(Frozen 등)
    - `submitPayout(payload)`가 verifier를 호출하고 payout을 기록
    - replay protection(txid/vout)
    - creditLimit 업데이트 로직(단순 버전)
    - borrow/repay 라우팅(vault 호출)
- 테스트:
    - 등록 성공/중복 방지
    - replay 방지
    - payout 1회 반영 시 limit 증가
    - limit 초과 borrow revert
- 완료 조건:
    - MVP 데모 플로우(등록→payout→limit→borrow/repay) 온체인 완성

---

### T0.5 RelayerSigVerifier — EIP-712 Signature Verification
- Priority: P0
- Status: [x] DONE
- 목적: 오프체인 relayer가 서명한 payout payload를 온체인에서 검증한다.
- 작업:
    - EIP-712 domain/struct 정의
    - authorized relayer signer address 관리(setter는 owner/role)
    - payload: borrowerId, txid, vout, amountSats, blockHeight, nonce, deadline, chainId 등
    - nonce 정책(옵션) + txid/vout replay와 병행
- 테스트:
    - 올바른 서명 통과
    - signer 불일치 revert
    - deadline 초과 revert
    - 동일 payload 재제출 revert(또는 txid/vout 기준)
- 완료 조건:
    - `HashCreditManager.submitPayout()`에서 완전 동작

---

### T0.6 RiskConfig + Admin Controls (Minimal)
- Priority: P0
- Status: [x] DONE
- 목적: 하드코딩을 제거하고 리스크 파라미터를 교체 가능하게 만든다.
- 파라미터:
    - confirmationsRequired (MVP에서는 relayer가 준수, 온체인에서는 로그로만)
    - advanceRateBps
    - windowSeconds(or payoutCount window)
    - newBorrowerCap
    - globalCap (선택)
- 작업:
    - owner/role 기반 set 함수
    - 이벤트 발행
- 완료 조건:
    - 파라미터 변경이 즉시 반영되고 테스트로 검증

---

### T0.7 PoolRegistry Hook (MVP-Ready)
- Priority: P0
- Status: [x] DONE
- 목적: “풀 출처 검증”을 1차에 완벽 구현 못하더라도, 코드 구조에 훅을 박아둔다.
- 작업:
    - `PoolRegistry` 컨트랙트(allowlist 기반)
    - `HashCreditManager`에서 `isEligiblePayoutSource(...)` 같은 훅 호출 가능 구조
    - MVP에서는 `true` 반환 또는 관리자 allowlist만 적용
- 완료 조건:
    - production에서 provenance 강화 시 ABI/스토리지 변경 최소화

---

### T0.8 Offchain Relayer (Python) — Watch + Sign + Submit
- Priority: P0
- Status: [x] DONE
- 목적: Bitcoin payout을 감지하고 EVM에 제출한다(해커톤 데모 핵심).
- 작업:
    - 데이터 소스 선택:
        - (A) Bitcoin Core RPC
        - (B) mempool/esplora API (해커톤 간편)
    - 감시 로직:
        - 특정 payout address 목록을 감시
        - txid/vout/amount/blockHeight 획득
        - confirmations 체크(가능하면)
    - EIP-712 서명 생성
    - EVM tx 제출(web3.py/ethers-rs 등)
    - 로컬 DB(최소 sqlite)로 dedupe
- 완료 조건:
    - 실제(또는 테스트넷) tx 1건으로 demo가 돌아간다

---

### T0.9 End-to-End Demo Script + README (Hackathon Submission Ready)
- Priority: P0
- Status: [x] DONE
- 목적: 심사위원이 5분 내 이해 가능한 실행 절차를 제공한다.
- 작업:
    - `docs/guides/DEMO.md` 작성
    - 실행 순서(배포 → borrower 등록 → relayer 실행 → payout 감지 → borrow/repay)
    - 스크린샷/로그 예시(선택)
- 완료 조건:
    - 신규 환경에서 문서만 보고 재현 가능(최소한 개발자 기준)

---

## P1 — Production Track: Bitcoin SPV (Checkpoint 기반)

### T1.1 SPV Design Finalization (ADR)
- Priority: P1
- Status: [x] DONE
- 목적: Bitcoin SPV를 어떤 안전/가스/운영 가정으로 구현할지 ADR로 고정한다.
- 포함:
    - checkpoint trust model(멀티시그/attestor set)
    - 허용 범위(리타겟 경계 거부, header chain 길이 제한)
    - 지원 scriptPubKey 타입(P2WPKH 우선)
- 완료 조건:
    - `docs/adr/0001-btc-spv.md` 작성 및 승인

---

### T1.2 CheckpointManager Contract
- Priority: P1
- Status: [x] DONE
- 목적: checkpoint header를 온체인에 등록/관리한다.
- 작업:
    - 멀티시그/owner 권한으로 checkpoint set
    - checkpoint 변경 이벤트
    - height monotonic 증가 강제
- 테스트:
    - 권한 없는 set revert
    - height 감소 revert
- 완료 조건:
    - `BtcSpvVerifier`가 checkpoint를 참조 가능

---

### T1.3 BtcSpvVerifier — Header PoW + Merkle Inclusion + Output Parse (MVP 수준)
- Priority: P1
- Status: [x] DONE
- 목적: rawTx가 특정 블록에 포함되었고, vout이 borrower payout key와 일치함을 온체인에서 검증한다.
- 작업:
    - sha256d(header) <= target(bits) 검증(프리컴파일 sha256 사용)
    - prevHash 체인 연결 검증
    - txid = sha256d(rawTx)
    - merkle branch로 merkleRoot 도달 검증(Bitcoin 규칙)
    - rawTx vout parsing(최소 P2WPKH)
- 테스트:
    - 고정된 test vector(실데이터)로 verify 성공/실패
- 완료 조건:
    - `HashCreditManager`가 verifier를 교체해도 동작

---

### T1.4 Proof Builder/Prover (Python)
- Priority: P1
- Status: [x] DONE
- 목적: 제출에 필요한 header chain + merkle branch + rawTx를 구성한다.
- 작업:
    - data source: Bitcoin Core RPC 권장(txindex 필요 가능)
    - 증명 payload 생성
    - 제출 tx 생성 및 전송
- 완료 조건:
    - 지정 txid로 proof 생성 → on-chain verify 성공

---

### T1.5 Provenance 강화(선택): Pool Cluster Registry + Heuristic Rules
- Priority: P1
- Status: [x] DONE
- 목적: self-transfer 조작 가능성을 낮춘다.
- 작업:
    - 풀 payout 클러스터 allowlist (운영 시작)
    - payout 패턴 룰(간단):
        - 최소 payout count 충족 전 cap 고정
        - 단발성 대형 입금은 부분 반영
- 완료 조건:
    - 공격 시나리오(자기자금 순환)에서 한도 상승이 제한됨을 테스트/문서로 제시

---

### T1.6 Creditcoin Testnet SPV 배포 스크립트 + Wiring
- Priority: P1
- Status: [x] DONE
- 목적: Creditcoin testnet(chainId=102031)에서 SPV 스택을 **재현 가능하게 배포**하고, Manager가 SPV verifier를 쓰도록 연결한다.
- 작업:
    - `CheckpointManager` + `BtcSpvVerifier` 포함한 배포 스크립트 추가(예: `script/DeploySpv.s.sol`)
    - 배포 후 `HashCreditManager.setVerifier(BtcSpvVerifier)` 호출(또는 처음부터 SPV verifier로 Manager 배포)
    - 콘솔에 주소 요약 출력 + `.env`에 넣을 키 목록 정리(문서/로그)
- 완료 조건:
    - Creditcoin testnet에서 스크립트 1회 실행으로 SPV 관련 컨트랙트 주소를 얻고, Manager verifier가 SPV로 설정된다.
- 완료 요약:
    - Created `script/DeploySpv.s.sol` - full SPV mode deployment script
    - Deploys: MockUSDC → CheckpointManager → BtcSpvVerifier → RiskConfig → PoolRegistry → LendingVault → HashCreditManager
    - Manager is deployed with BtcSpvVerifier as verifier (not RelayerSigVerifier)
    - Console output includes all addresses and .env configuration guide
    - Usage: `forge script script/DeploySpv.s.sol --rpc-url $CREDITCOIN_TESTNET_RPC --broadcast`

---

### T1.7 Checkpoint 등록 툴링 (Bitcoin Core RPC → CheckpointManager)
- Priority: P1
- Status: [x] DONE
- 목적: **Bitcoin testnet** Bitcoin Core RPC에서 블록 헤더/메타를 읽어서 `CheckpointManager.setCheckpoint()`를 **실수 없이** 실행한다.
- 작업:
    - `hashcredit-prover`에 `set-checkpoint` 커맨드 추가(또는 별도 스크립트)
    - 입력: `height` (또는 `--height`), EVM `RPC_URL`, `PRIVATE_KEY`, `CHECKPOINT_MANAGER` 주소, Bitcoin RPC 접속정보
        - 기본값(권장): `BITCOIN_RPC_URL=http://127.0.0.1:18332` (Bitcoin Core `-testnet` RPC)
    - `blockHash`는 **헤더 bytes로 sha256d 계산한 내부 endian(bytes32)** 을 사용(엔디안 혼동 방지)
    - `timestamp`, `chainWork`를 Bitcoin Core 결과에서 안전하게 파싱
- 완료 조건:
    - 지정 height로 checkpoint 등록 트랜잭션이 성공하고, `latestCheckpointHeight()`가 갱신된다.
- 완료 요약:
    - Created `hashcredit_prover/evm.py` with EVMClient for contract interactions
    - Added `set-checkpoint` command to CLI
    - Fetches block header from Bitcoin RPC, computes internal hash, and calls setCheckpoint()
    - Supports --dry-run mode for testing without sending transactions
    - Updated README.md with command documentation

---

### T1.8 Borrower BTC Address → pubkeyHash 등록 툴링 (BtcSpvVerifier)
- Priority: P1
- Status: [x] DONE
- 목적: borrower의 **Bitcoin testnet** 주소(P2WPKH bech32 `tb1...` / P2PKH base58 `m...`/`n...`)를 받아 **20-byte pubkey hash**를 추출하고 `BtcSpvVerifier.setBorrowerPubkeyHash()`를 실행한다.
- 작업:
    - 주소 디코더 구현(bech32 v0 + base58check 최소 구현; 외부 무거운 라이브러리 의존 최소화)
    - `hashcredit-prover set-borrower-pubkey-hash --borrower 0x.. --btc-address ...` 커맨드 추가
    - 성공 후 `getBorrowerPubkeyHash(borrower)`로 검증
- 완료 조건:
    - 실제 BTC 주소 1개로 pubkey hash가 올바르게 등록되고, 이후 SPV proof가 해당 주소로만 통과한다.
- 완료 요약:
    - Created `hashcredit_prover/address.py` with bech32 and base58check decoders
    - Supports P2WPKH (tb1q.../bc1q...) and P2PKH (m.../n.../1...) addresses
    - Added `set-borrower-pubkey-hash` CLI command
    - Calls BtcSpvVerifier.setBorrowerPubkeyHash() with extracted pubkey hash
    - Added unit tests in tests/test_address.py
    - Updated README.md with command documentation

---

### T1.9 SPV Proof 생성 + EVM 제출 커맨드 (txid 단발)
- Priority: P1
- Status: [x] DONE
- 목적: 복잡한 "watcher/relayer" 전에, **Bitcoin testnet txid 한 건을 입력하면** proof를 만들고 `HashCreditManager.submitPayout()`까지 끝내는 단발 플로우를 제공한다.
- 작업:
    - `hashcredit-prover submit-proof` 커맨드 추가
    - 입력:
        - Bitcoin: `txid`(display), `outputIndex`, `targetHeight`, `checkpointHeight`(또는 자동 선택)
        - EVM: `RPC_URL`(Creditcoin), `CHAIN_ID=102031`, `PRIVATE_KEY`, `HASH_CREDIT_MANAGER`
        - borrower EVM address
    - 내부:
        - ProofBuilder로 `abi.encode(SpvProof)` 생성
        - web3.py로 `HashCreditManager.submitPayout(bytes)` 전송 + receipt 확인
- 완료 조건:
    - "txid 1건" 입력으로 on-chain payout 반영 트랜잭션이 성공한다.
- 완료 요약:
    - Added `submit-proof` CLI command to hashcredit-prover
    - Uses existing ProofBuilder to generate SPV proof
    - Calls HashCreditManager.submitPayout(bytes) via EVMClient
    - Supports --dry-run and --hex-only modes for testing
    - Updated README.md with command documentation and examples

---

### T1.10 SPV Relayer(감시/자동 제출) + dedupe/confirmations
- Priority: P1
- Status: [x] DONE
- 목적: 운영 가능한 최소 relayer를 만들어 **Bitcoin testnet 주소 감시 → confirmations 충족 → proof 생성 → submit → dedupe**까지 자동화한다.
- 작업:
    - Bitcoin Core RPC 기반 주소 감시(최소: txid 리스트/블록 스캔 전략 중 하나)
    - checkpoint 선택 로직:
        - header chain 길이 제약(≤144) 만족하도록 `checkpointHeight` 자동 선택
    - sqlite dedupe(기존 relayer DB 재사용 가능)
    - 실패 케이스(재시도/로그/원인 노출) 정리
- 완료 조건:
    - 한 주소를 지정하면 payout 트랜잭션을 자동으로 찾아 submit하고, 중복 제출이 방지된다.
- 완료 요약:
    - Created `watcher.py` with AddressWatcher and PayoutStore (SQLite dedupe)
    - Created `relayer.py` with SPVRelayer class for automatic proof submission
    - Added `run-relayer` CLI command with JSON addresses file input
    - Auto checkpoint selection within max_header_chain constraint
    - Configurable confirmations, poll interval
    - Updated README.md with relayer documentation

---

### T1.11 결정적(offline) SPV fixtures + Manager E2E 테스트 + 문서
- Priority: P1
- Status: [x] DONE
- 목적: 네트워크 없이도 검증 가능한 형태로 **Bitcoin testnet 기반 SPV proof 검증/제출의 회귀 테스트**를 만들고, Creditcoin testnet 기준 운영 문서를 완성한다.
- 작업:
    - `test/fixtures/`에 실제 메인넷/테스트넷 tx 기반(또는 최소한 고정 데이터 기반) proof 구성요소 저장
    - `BtcSpvVerifier.verifyPayout()` 성공/실패 테스트 추가(머클/헤더체인/출력 불일치 등)
    - `HashCreditManager.submitPayout()`까지 이어지는 E2E 테스트 추가(creditLimit 증가 + replay 방지)
    - `docs/guides/LOCAL.md`에 Creditcoin testnet SPV 모드 실행/디버깅 섹션 추가
- 완료 조건:
    - `forge test`로 SPV 경로의 핵심 검증이 안정적으로 재현되고, 문서만 보고 testnet에서 end-to-end 실행 가능하다.
- 완료 요약:
    - Created `test/SpvE2E.t.sol` with 8 E2E tests for SPV verification flow
    - Tests: deployment, borrower registration, checkpoint registration, error cases
    - Uses synthetic but structurally valid Bitcoin data for deterministic testing
    - Updated `docs/guides/LOCAL.md` with comprehensive SPV mode execution guide
    - Includes checkpoint registration, borrower setup, proof submission, relayer usage
    - All 143 tests passing

---

### T1.12 Frontend 스캐폴딩 (Vite + React) + 컨트랙트 조회 대시보드
- Priority: P1
- Status: [x] DONE
- 목적: 인턴/심사위원이 “지금 상태가 어떤지”를 바로 볼 수 있는 **웹 대시보드**를 만든다(일단 읽기 위주).
- 작업:
    - `apps/web` 생성(Vite + React + TS)
    - 환경변수 템플릿: `apps/web/.env.example` (`VITE_RPC_URL`, `VITE_CHAIN_ID=102031`, `VITE_HASH_CREDIT_MANAGER`, `VITE_BTC_SPV_VERIFIER`, `VITE_CHECKPOINT_MANAGER` 등)
    - 화면:
        - 연결 상태(지갑 연결 여부 / chainId / 현재 계정)
        - Manager 정보: `owner`, `verifier`, `stablecoin`, `getAvailableCredit(borrower)`, `getBorrowerInfo(borrower)` 조회
        - Checkpoint 정보: `latestCheckpointHeight`, `getCheckpoint(height)` 조회(읽기)
    - 배포/실행 명령 문서화(`npm/pnpm install`, `dev`, `build`)
- 완료 조건:
    - 브라우저에서 RPC read-only로 Manager/Checkpoint 상태를 조회할 수 있다(지갑 없이도).
- 완료 요약:
    - `apps/web` Vite + React + TS 스캐폴딩 추가
    - `apps/web/.env.example`로 Creditcoin testnet RPC/주소 설정 지원
    - Manager/Borrower/Checkpoint/SPV verifier read-only 대시보드 구현
    - `apps/web`에서 `npm run lint`, `npm run build` 통과 확인

---

### T1.13 Frontend 쓰기 플로우 (Submit Payout Proof / Borrow / Repay)
- Priority: P1
- Status: [x] DONE
- 목적: SPV E2E에서 필요한 “쓰기”를 UI로도 수행할 수 있게 한다(운영 편의).
- 작업:
    - 지갑 연결(MetaMask 등) + Creditcoin testnet 네트워크 안내(또는 자동 추가)
    - `submitPayout(bytes)`:
        - 사용자가 `hashcredit-prover`가 뽑아준 proof hex(`0x...`)를 붙여넣고 제출
        - tx hash/receipt/에러 메시지 표시
    - `borrow(uint256)`:
        - amount 입력(6 decimals 가이드 포함) 후 borrow tx 전송
    - `repay(uint256)`:
        - repay 전에 `stablecoin.approve(manager, amount)` 버튼 제공(필요 시)
        - repay tx 전송
- 완료 조건:
    - UI에서 proof 제출 1회 성공 + borrower borrow/repay(approve 포함)가 실행된다.
- 완료 요약:
    - 지갑 연결 + `wallet_switchEthereumChain`/`wallet_addEthereumChain` 기반 체인 전환 버튼 추가
    - UI에서 `submitPayout(bytes)`/`borrow(uint256)`/`approve(spender,amount)`/`repay(uint256)` 전송 가능
    - 관리자용 버튼 추가: `registerBorrower`, `setVerifier`, `setBorrowerPubkeyHash`
    - 트랜잭션 상태(pending/confirmed/error) 표시 패널 추가

---

### T1.14 (선택) Frontend ↔ Prover/Bitcoin Core 브리지 API
- Priority: P2
- Status: [x] DONE
- 목적: 브라우저가 Bitcoin Core RPC에 직접 붙을 수 없으므로, **로컬/서버에서 prover를 실행**해주는 얇은 API를 제공한다(완전 자동화 옵션).
- 작업:
    - `apps/api`(또는 `offchain/api`)에 최소 HTTP API:
        - `POST /spv/build-proof` (txid/outputIndex/targetHeight/borrower → proof hex)
        - `POST /checkpoint/set` (height → checkpoint tx)
    - 인증/보안:
        - 로컬 전용(기본 `127.0.0.1` 바인딩) + 간단 토큰/allowlist
    - `apps/web`에서 API를 호출해 proof 생성/체크포인트 등록을 UI에서 원클릭으로 수행(선택)
- 완료 조건:
    - (로컬 기준) UI에서 txid만 넣으면 proof 생성+제출까지 한 번에 가능하다(옵션).
- 완료 요약:
    - Created `offchain/api` with FastAPI-based HTTP server
    - Endpoints: `POST /spv/build-proof`, `POST /spv/submit`, `POST /checkpoint/set`, `POST /borrower/set-pubkey-hash`, `GET /health`
    - Local-only binding (127.0.0.1) with optional token authentication via X-API-Key header
    - CORS configured for frontend integration
    - Auto-generated OpenAPI docs at /docs and /redoc
    - 11 unit tests passing

---

## P2 — Polishing / Security / Launch Readiness

### T2.1 Gas Profiling + Limits
- Priority: P2
- Status: [x] DONE
- 목적: proof 제출 비용, 루프 길이(merkle branch/hdr chain) 상한을 설정한다.
- 작업:
    - branch length max
    - header chain max
    - revert reason 명확화
- 완료 조건:
    - 비용/상한 문서화
- 완료 요약:
    - Limits already defined in BtcSpvVerifier: MAX_HEADER_CHAIN=144, MAX_MERKLE_DEPTH=20, MAX_TX_SIZE=4096, MIN_CONFIRMATIONS=6
    - Created `test/GasProfile.t.sol` with 23 gas profiling tests
    - Created `docs/gas-limits.md` documenting all gas costs and limits
    - Key findings: verifyMerkleProof scales ~1,640 gas/level, submitPayout ~150K gas, worst-case SPV proof ~450K gas

---

### T2.2 Audit Checklist + Threat Model Doc
- Priority: P2
- Status: [x] DONE
- 목적: 심사위원/VC/외주 인수인계를 위한 보안 문서를 만든다.
- 산출물:
    - `docs/threat-model.md`
    - `docs/audit-checklist.md`
- 완료 조건:
    - 주요 위협(oracle compromise, replay, reorg, self-transfer, key loss) 대응이 정리됨
- 완료 요약:
    - Created `docs/threat-model.md` covering 8 threat categories with mitigations
    - Created `docs/audit-checklist.md` with 15 sections for comprehensive code review
    - Documented oracle compromise, replay, reorg, self-transfer, key loss threats and defenses
    - Includes trust boundaries diagram, defense-in-depth layers, incident response guidance

---

### T2.3 (Critical) SPV Difficulty(bits) 검증 + Retarget Boundary 차단
- Priority: P0
- Status: [x] DONE
- 목적: `BtcSpvVerifier`가 **임의로 낮춘 bits(쉬운 난이도)** 를 받아들이는 취약점을 제거해, 가짜 헤더 체인/가짜 payout으로 한도 무제한 상승이 불가능하도록 한다.
- 배경:
    - 현재 `contracts/BtcSpvVerifier.sol`의 `_verifyHeaderChain()`은 `header.bits`가 "해당 height에서 기대되는 값"인지 검증하지 않는다(주석만 있음).
    - 이 상태에선 공격자가 `bits`를 쉽게 만들고 짧은 시간에 헤더를 "채굴"해 SPV를 위조할 수 있다.
- 작업:
    - 체크포인트에 **난이도 앵커**(예: `bits` 또는 `header` bytes)를 저장하도록 `CheckpointManager`/`ICheckpointManager` 확장
        - 옵션 A: `Checkpoint { ... uint32 bits; }`
        - 옵션 B: `Checkpoint`에 `bytes header` 저장 + `blockHash == sha256d(header)` 검증
    - `_verifyHeaderChain()`에서 아래를 강제:
        - retarget boundary crossing 금지: `(checkpointHeight / 2016) == (targetHeight / 2016)` (메인넷 기준)
        - 체인 전체 `header.bits == checkpointBits` (동일 난이도 epoch 가정)
    - (테스트넷/리그테스트 지원 시) testnet special difficulty rule 사용 여부를 명시하고, 지원하지 않으면 명확히 revert 사유/문서화
    - `offchain/prover`의 `set-checkpoint`/API도 새 필드에 맞게 업데이트(비트/헤더 추출)
    - ADR/문서 업데이트: `docs/adr/0001-btc-spv.md`에 실제 구현 제약/지원 네트워크를 명시
- 테스트:
    - "bits 낮춤" 공격 케이스: 올바른 prevHash 링크 + 쉬운 bits로 만든 헤더 체인을 제출하면 **반드시 revert**
    - retarget boundary crossing 케이스: boundary를 넘는 proof는 **반드시 revert**
    - 정상 케이스: 올바른 bits/epoch 내에서 헤더 체인 검증 성공(가능하면 fixture 기반)
- 완료 조건:
    - `BtcSpvVerifier`가 **checkpoint 난이도와 일치하지 않는 bits** 를 가진 헤더 체인을 거부한다.
    - 위 테스트가 `forge test`에 포함되어 회귀를 막는다.
- 완료 요약:
    - ICheckpointManager.Checkpoint struct에 `uint32 bits` 필드 추가
    - CheckpointManager.setCheckpoint()에 bits 파라미터 추가 및 검증
    - BtcSpvVerifier._verifyHeaderChain()에서 bits 검증 및 retarget boundary crossing 검증 추가
    - 새로운 에러 타입: `DifficultyMismatch(expected, actual)`, `RetargetBoundaryCrossing(checkpointHeight, targetHeight)`
    - offchain prover/API에서 bits 추출 및 제출 지원
    - 테스트: test_verifyPayout_revertsOnDifficultyMismatch, test_verifyPayout_revertsOnRetargetBoundaryCrossing
    - ADR 0001 문서 업데이트

---

### T2.4 (Critical) SPV Confirmations 정의/검증 방식 수정
- Priority: P0
- Status: [x] DONE
- 목적: `MIN_CONFIRMATIONS`가 “checkpoint↔txBlock 거리”가 아니라 **tx 포함 블록이 tip 대비 몇 블록 깊이인지** 를 의미하도록 proof 구조/검증을 바로잡는다.
- 배경:
    - 현재 `contracts/BtcSpvVerifier.sol`은 `headers.length >= MIN_CONFIRMATIONS`만 확인하는데, 이는 일반적인 confirmations 의미와 다르다.
- 작업:
    - proof 포맷 재정의(권장안):
        - `headers`를 `checkpoint+1 → tip`까지 제공
        - `txBlockIndex`(= headers 내 tx가 포함된 블록 인덱스) 필드 추가
        - confirmations 검증: `headers.length - 1 - txBlockIndex >= MIN_CONFIRMATIONS - 1`
        - merkle proof 검증 시 `headers[txBlockIndex]`의 `merkleRoot` 사용
    - 기존 `offchain/prover`의 proof builder/CLI/API를 새 포맷에 맞춰 수정
    - `PayoutEvidence.blockHeight`가 “tx 포함 블록 height”로 정확히 산출되도록 정리
- 테스트:
    - confirmations 부족 케이스: tip 체인 내에서 txBlockIndex가 tip에 너무 가까우면 revert
    - 정상 케이스: MIN_CONFIRMATIONS 충족 시 verify 성공
    - 문서/예제: `docs/guides/LOCAL.md`(또는 관련 가이드)에 proof 입력값 의미 갱신
- 완료 조건:
    - "confirmations"가 일반적인 정의로 동작하고, 테스트로 보장된다.
- 완료 요약:
    - SpvProof struct에 `txBlockIndex` 필드 추가 (uint32)
    - Confirmations 계산: `headers.length - txBlockIndex >= MIN_CONFIRMATIONS`
    - Merkle proof는 `headers[txBlockIndex]`의 merkleRoot로 검증
    - `PayoutEvidence.blockHeight`가 tx 포함 블록 height로 정확히 계산
    - 새 에러 타입: `TxBlockIndexOutOfRange(txBlockIndex, headersLength)`
    - `_verifyHeaderChainFull()` 함수 추가하여 모든 헤더 파싱/반환
    - offchain prover의 `build_proof()`에 `tip_height` 파라미터 추가 (기본: target+5)
    - 테스트: txBlockIndex 범위 초과, confirmations 부족, confirmations 계산 검증
    - `docs/guides/LOCAL.md`에 SPV Proof Format 문서 추가

---

### T2.5 (Critical) Verifier 직접 호출로 인한 Griefing/DoS 방지
- Priority: P0
- Status: [x] DONE
- 목적: 제3자가 `RelayerSigVerifier.verifyPayout()`/`BtcSpvVerifier.verifyPayout()`을 **직접 호출**하여 `_processedPayouts`를 선점해 `HashCreditManager.submitPayout()`을 영구적으로 막는 DoS를 제거한다.
- 작업(택1 또는 조합):
    - 옵션 A(권장): verifier에서 `_processedPayouts`/replay 체크 제거 → replay는 `HashCreditManager.processedPayouts` 단일 레이어로 통일
    - 옵션 B: verifier에 `manager`를 저장하고 `onlyManager`로 `verifyPayout()` 제한(+ manager 변경/이벤트)
    - 옵션 C: verifier는 replay를 “검증 실패”로 보지 않고 evidence 반환(단, manager가 최종 replay 방지)
    - `contracts/interfaces/IVerifierAdapter.sol` 설계 정리(verify가 stateful이어야 하는지 재검토)
- 테스트:
    - 공격 시나리오 재현: attacker가 verifier를 먼저 호출해도, 이후 `HashCreditManager.submitPayout()`이 정상 처리되는지
    - replay는 manager에서만 막히는지(동일 txid/vout 2회 제출 revert)
- 완료 조건:
    - verifier 직접 호출로 payout 처리가 막히지 않는다.
    - replay 방지가 단일 레이어(또는 의도된 레이어)에서만 일관되게 동작한다.
- 완료 요약:
    - 옵션 A 구현: verifier에서 `_processedPayouts` 제거, replay는 Manager 단일 레이어로 통일
    - BtcSpvVerifier: `_processedPayouts` 매핑/체크/마킹 제거, `isPayoutProcessed()` 항상 false 반환
    - RelayerSigVerifier: 동일하게 stateless로 수정
    - MockVerifier: 테스트용 mock도 stateless로 수정
    - 테스트 추가: `test_griefingPrevention_verifierDirectCall()`, `test_replayProtectionOnlyInManager()`
    - 기존 테스트 수정: verifier replay 테스트를 stateless 동작으로 업데이트

---

### T2.6 (High) LendingVault 이자 누적(totalAssets) 버그 수정 + Share Dilution 방지
- Priority: P1
- Status: [x] DONE
- 목적: `LendingVault`에서 `_accrueInterest()`로 누적한 `accumulatedInterest`가 `totalAssets()`에 반영되지 않아, 중간 호출(예: deposit/withdraw/borrow/repay) 시 **share 가격이 왜곡/희석**되는 문제를 해결한다.
- 작업:
    - `contracts/LendingVault.sol`:
        - `totalAssets()`에 `accumulatedInterest`를 포함(또는 누적 변수 제거 후 항상 정확히 계산되는 구조로 리팩터링)
        - `PRECISION` 등 미사용 상수/변수 정리
        - (선택) `repayFunds`의 `actualRepay` 네이밍/주석을 “principal vs interest”로 명확화
- 테스트:
    - “이자 발생 후 추가 deposit” 시 신규 depositor가 이자를 공짜로 가져가지 못함(share dilution 방지) 테스트 추가
    - “이자 발생 후 withdraw” 시 기대값과 일치하는지 테스트 보강
- 완료 조건:
    - 이자 누적이 어떤 호출 순서에서도 `totalAssets()/convertToShares/convertToAssets`에 일관되게 반영된다.
- 완료 요약:
    - `totalAssets()` 수정: `balanceOf + totalBorrowed + accumulatedInterest + _pendingInterest()`
    - `repayFunds()` 수정: 이자 부분이 들어오면 `accumulatedInterest` 차감 (중복 계산 방지)
    - Share dilution 방지 테스트 추가: `test_shareDilutionPrevention_depositAfterInterestAccrual()`
    - `accumulatedInterest` 반영 테스트: `test_accumulatedInterestIncludedInTotalAssets()`
    - 이자 차감 테스트: `test_interestDeductionOnRepay()`, `test_partialInterestRepay()`

---

### T2.7 (High) Manager/Vault 이자 모델 정합성(부채 이자 반영) 구현
- Priority: P1
- Status: [x] DONE
- 목적: 현재 `HashCreditManager.currentDebt`는 이자를 반영하지 않아 borrower가 이자를 상환할 수 없고, `LendingVault`의 이자 모델과 불일치한다. borrower debt에 이자를 반영해 vault에 이자 수익이 실제로 귀속되도록 한다.
- 작업:
    - 설계 선택:
        - (A) Manager에서 이자 지표(borrowIndex)로 `currentDebt`를 시간에 따라 증가시키고 repay가 이자→원금 순으로 상환
        - (B) Vault가 “이자 포함 debt”를 추적하고 manager는 원금만 추적(단, borrower 상환 UX/정확한 debt 산출 필요)
    - `HashCreditManager.repay()`가 “원금+이자” 상환을 지원하도록 수정(현 cap 로직 재검토)
    - UI/오프체인: borrower가 현재 debt(이자 포함)를 조회/상환할 수 있게 endpoint/뷰 추가
- 테스트:
    - borrow → 시간 경과 → repay 시 debt가 이자 포함으로 증가하고, repay 후 vault balance/totalBorrowed(또는 accounting)가 기대대로 변화
    - 상환액이 이자 미만/이자+원금/초과 등 엣지 케이스
- 완료 조건:
    - borrower가 이자를 실제로 상환 가능하고, LP 수익이 회계상/실제 토큰 흐름 모두 일치한다.
- 완료 요약:
    - `IHashCreditManager.BorrowerInfo`에 `lastDebtUpdateTimestamp` 필드 추가
    - `IHashCreditManager`에 `getCurrentDebt(address)`, `getAccruedInterest(address)` 함수 추가
    - `HashCreditManager._calculateAccruedInterest()` 구현: Vault의 borrowAPR()을 조회하여 시간 기반 이자 계산
    - `borrow()` 수정: 기존 accrued interest를 principal에 합산 후 새 borrow 추가
    - `repay()` 수정: 이자 우선 상환, 남은 금액으로 원금 상환, Vault에 전체 금액 전달
    - `getAvailableCredit()` 수정: 이자 포함한 총 debt 기준으로 available credit 계산
    - 7개 테스트 추가: interest accrual, repay interest first, repay capped, compound interest, available credit with interest, vault receives interest

---

### T2.8 ERC20 안전성(SafeERC20) + Approval 호환성 + Reentrancy 방어
- Priority: P2
- Status: [x] DONE
- 목적: 비표준 ERC20(리턴값 false, approve=0 선행 요구 등) 및 토큰 콜백 기반 reentrancy에 대한 방어를 추가한다.
- 작업:
    - OpenZeppelin `SafeERC20`/`ReentrancyGuard` 도입
    - `contracts/HashCreditManager.sol`/`contracts/LendingVault.sol`:
        - `transfer/transferFrom/approve`를 `safeTransfer/safeTransferFrom/safeIncreaseAllowance`(또는 safeApprove 패턴)로 교체
        - `deposit/withdraw/repay` 등 외부 토큰 호출 경로에 `nonReentrant` 적용 및 상태 업데이트 순서 재검토(특히 deposit)
- 테스트:
    - “false 반환 ERC20”, “approve 0 필요 ERC20” mock으로 회귀 테스트 추가
    - reentrancy 시나리오(가능하면 ERC777 스타일 mock)에서 share/부채 불변식이 깨지지 않음을 확인
- 완료 조건:
    - 토큰 호환성/재진입 공격면이 줄고, 테스트로 보장된다.
- 완료 요약:
    - OpenZeppelin `SafeERC20` 및 `ReentrancyGuard` 도입 (lib/openzeppelin-contracts)
    - `LendingVault.sol`: `transfer` → `safeTransfer`, `transferFrom` → `safeTransferFrom`
    - `LendingVault.sol`: `deposit`, `withdraw`, `borrowFunds`, `repayFunds`에 `nonReentrant` 적용
    - `HashCreditManager.sol`: `transferFrom` → `safeTransferFrom`, `approve` → `forceApprove`
    - `HashCreditManager.sol`: `borrow`, `repay`에 `nonReentrant` 적용
    - Mock 토큰 추가: `MockUSDT` (approve 0 필요), `MockNoReturnERC20` (리턴값 없음), `ReentrantToken` (callback 기반)
    - 9개 테스트 추가: USDT-style 호환성, no-return 토큰 호환성, reentrancy 방어

---

### T2.9 Trailing Revenue Window 실제 적용 + Min Payout 필터링
- Priority: P1
- Status: [x] DONE
- 목적: `RiskConfig.windowSeconds`에 맞는 trailing revenue window를 실제로 적용하고, `minPayoutSats` 이하의 스팸/미세 payout이 한도에 누적되지 않도록 한다.
- 작업:
    - `contracts/HashCreditManager.sol`:
        - payout 이벤트를 시간 기반으로 윈도우에서 제외(pruning)하는 로직 추가(가스/스토리지 고려한 자료구조 선택)
        - `evidence.blockTimestamp`의 유효성(미래/과거 허용 범위) 검증 정책 명시
        - `minPayoutSats` 미만은 effectiveAmount=0 처리 또는 아예 revert/ignore 정책 결정
    - `contracts/RiskConfig.sol`/문서:
        - trailing window와 new borrower period가 같은 `windowSeconds`를 공유하는 현재 의미 혼선을 정리(필요 시 파라미터 분리)
- 테스트:
    - 윈도우 경계에서 payout이 만료되면 creditLimit이 감소/재계산되는지
    - min payout 미만이 creditLimit에 영향 주지 않는지
- 완료 조건:
    - trailing window가 실제로 동작하고, 스팸 payout으로 한도 누적이 불가하다.
- 완료 요약:
    - Add payout history storage with MAX_PAYOUT_RECORDS=100 DoS protection
    - Implement lazy pruning of expired payouts in trailing window
    - Add minPayoutSats filtering (below-minimum payouts marked processed but don't count toward credit)
    - Separate newBorrowerPeriodSeconds from windowSeconds in RiskParams
    - Add PayoutRecord struct, PayoutBelowMinimum and PayoutWindowPruned events
    - Add getPayoutHistoryCount() and getPayoutRecord() view functions
    - 8 new tests for trailing window, min payout filtering, and DoS protection

---

### T2.10 txid Endianness/표준화(온체인↔오프체인 일관성)
- Priority: P2
- Status: [x] DONE
- 목적: txid 표현(디스플레이 big-endian vs 내부 little-endian)이 컴포넌트별로 달라 verifier 교체/운영 시 혼선을 만들 수 있으므로, "프로토콜 표준 txid 바이트 순서"를 정하고 전 구간에 적용한다.
- 작업:
    - 표준 정의: `bytes32 txid`는 "Bitcoin 내부 바이트(sha256d 결과 그대로)"로 통일(권장)
    - `offchain/relayer`의 `txid_to_bytes32` 동작/주석 정정 및 reverse 처리 적용
    - `offchain/prover` proof builder도 표준에 맞춰 txid 계산/검증 로직 정리
    - 문서/예제 업데이트(입력 txid 포맷, hex reverse 여부)
- 테스트:
    - 동일 tx에 대해 relayer/프로버/온체인에서 txid가 동일하게 취급됨을 단위 테스트로 확인
- 완료 조건:
    - txid 관련 버그/운영 혼선(중복 처리, 검증 실패)이 표준화로 제거된다.
- 완료 요약:
    - Fix relayer's txid_to_bytes32() to reverse bytes (display -> internal format)
    - Add bytes32_to_txid_display() for reverse conversion (debugging)
    - Add explicit txid_display_to_internal() and txid_internal_to_display() to prover
    - Update docstrings with clear byte order documentation
    - Add unit tests for txid conversion in both relayer and prover
    - Add consistency test verifying same display txid produces identical bytes
    - Document txid format standard in LOCAL.md appendix
    - Protocol standard: bytes32 txid = internal byte order (sha256d result without reversal)

---

### T2.11 Offchain API 인증/배포 하드닝(토큰/CSRF/프록시 안전)
- Priority: P2
- Status: [x] DONE
- 목적: 로컬 API를 0.0.0.0로 노출하거나 리버스 프록시 뒤에 둘 때 `request.client.host` 기반 로컬 바이패스가 인증 우회를 만들 수 있으므로 안전한 기본값/정책으로 강화한다.
- 작업:
    - `offchain/api/hashcredit_api/auth.py`:
        - `API_TOKEN`이 설정되어 있으면 **항상 토큰 필수**(로컬 바이패스 제거)
        - query param 토큰(`?api_key=`) 지원 제거(로그/리퍼러 유출 위험)
        - (선택) `Origin`/`Host` 기반 최소 CSRF 방어(쓰기 endpoint에 한해)
    - 문서: `HOST=0.0.0.0` 사용 시 경고 및 권장 배포(방화벽/프록시) 명시
- 테스트:
    - 로컬/비로컬 요청 각각에 대해 토큰 정책이 의도대로 동작하는지 단위 테스트
- 완료 조건:
    - API를 잘못 노출해도 "무토큰"으로 키 사용/트랜잭션 전송이 불가하다.
- 완료 요약:
    - Remove local bypass in auth.py: when API_TOKEN is set, ALL requests require token
    - Remove query param token support (?api_key=) to prevent log/referrer leakage
    - Add security documentation warnings for HOST=0.0.0.0 usage
    - Add WWW-Authenticate header to 401 responses
    - 6 new authentication tests: token required, valid/invalid token, no local bypass, no query param
    - Update README.md with security notes and deployment guidelines

---

### T2.12 Offchain Watcher: BTC value → satoshis 변환에서 float 제거
- Priority: P2
- Status: [x] DONE
- 목적: Bitcoin Core RPC의 `vout.value`를 float로 처리(`* 1e8`)하면 반올림/정밀도 문제로 amount 오차가 발생할 수 있으므로, Decimal 기반으로 satoshis를 **정확히** 계산한다.
- 작업:
    - `offchain/prover/hashcredit_prover/watcher.py`:
        - `Decimal(str(value)) * Decimal("1e8")`로 변환 후 정수화(정확성 보장)
        - value가 문자열/정수/float 등으로 들어오는 케이스 처리
- 테스트:
    - 대표값(0.1, 0.00000001 등)에 대해 satoshis 변환이 정확한지 단위 테스트 추가
- 완료 조건:
    - amount_sats 산출이 float 정밀도에 의존하지 않는다.
- 완료 요약:
    - Add btc_to_sats() function using Decimal arithmetic for exact conversion
    - Handle int, float, str, Decimal inputs with proper type handling
    - Raise ValueError for fractional satoshis (more than 8 decimal places)
    - Replace `int(value * 1e8)` with btc_to_sats() in AddressWatcher.scan_block()
    - 17 unit tests covering precision edge cases (0.1, 0.2, 0.3 BTC), type handling, and float vs Decimal comparison

---

### T2.13 Security CI/검증 자동화(slither/fuzz/invariant)
- Priority: P2
- Status: [x] DONE
- 목적: 회귀 방지를 위해 정적 분석/퍼징/불변식 테스트를 CI에 포함한다.
- 작업:
    - (선택) `slither`/`solhint` 도입 및 CI 워크플로우 추가
    - Foundry fuzz/invariant 테스트 추가:
        - vault share 불변식(totalAssets 대비 share pricing)
        - manager replay 불변식(동일 txid/vout 중복 불가)
        - borrow/repay 불변식(totalGlobalDebt 일관성)
- 완료 조건:
    - PR/로컬에서 최소 보안 체크가 자동으로 돌아가고, 실패 시 원인 파악이 가능하다.
- 완료 요약:
    - Add `test/invariant/Invariant.t.sol` with 6 invariant tests:
      - VaultInvariantTest: totalAssetsGeShares, roundingFavorsVault, ghostAccounting
      - ManagerInvariantTest: noReplayPossible, debtAccountingConsistent, borrowNeverExceedsLimit
    - Update `.github/workflows/test.yml`:
      - Add invariant test step with FOUNDRY_INVARIANT_RUNS=50
      - Add slither static analysis job with artifact upload
      - Add Python tests job for offchain components
    - Add `slither.config.json` for Slither configuration
    - All 6 invariant tests passing

---

### T2.14 (Ops) Multisig/Timelock/Pause 등 운영 안전장치 추가
- Priority: P2
- Status: [x] DONE
- 목적: 단일 admin 키 리스크를 줄이고(멀티시그/타임락), 사고 대응(일시정지)을 가능하게 한다.
- 작업:
    - 문서/스크립트:
        - 프로덕션 배포 시 owner를 멀티시그로 설정하는 가이드/스크립트 정리
        - 민감 파라미터 변경(Verifier/Vault/RiskConfig) 타임락 적용 방안 정리
    - (선택) 온체인:
        - `pause()/unpause()`를 `HashCreditManager`/`LendingVault`에 추가(쓰기 함수 가드)
        - 2-step ownership(Ownable2Step) 패턴 도입 검토
- 완료 조건:
    - 운영자가 키 사고/이상 징후에 대응할 수 있는 "절차+기술적 훅"이 마련된다.
- 완료 요약:
    - Add OpenZeppelin Pausable to HashCreditManager
    - Implement pause()/unpause() functions (onlyOwner)
    - Apply whenNotPaused modifier to submitPayout(), borrow(), repay()
    - Update docs/guides/DEPLOY.md with:
      - Pause functionality documentation
      - Gnosis Safe multisig setup guide
      - Timelock integration guidance
      - Key management checklist
      - Incident response procedures
      - Contract upgrade path documentation
    - All 186 tests passing

---

### T2.15 Offchain DB: SQLite → Postgres 포팅(공통 스키마/마이그레이션)
- Priority: P1
- Status: [x] DONE
- 목적: Railway 배포에서 파일 기반 SQLite(`relayer.db`) 의존을 제거하고, 모든 오프체인 컴포넌트가 **Postgres(DATABASE_URL)** 를 사용하도록 포팅한다.
- 작업:
    - 목표 범위:
        - `offchain/relayer`(MVP relayer) dedupe DB
        - `offchain/prover`(SPV relayer/watcher) dedupe DB
    - 공통 스키마 설계(최소):
        - `processed_payouts`(txid,vout unique) 또는 `submitted_payouts`/`pending_payouts` 등 현재 테이블을 Postgres로 이관
        - 멱등성 보장: `UNIQUE(txid, vout)` + upsert 패턴
    - DB 접근 레이어 추가:
        - `DATABASE_URL` 기반으로 엔진/커넥션 생성(Postgres URL 우선, 로컬은 sqlite 허용 가능)
        - (권장) SQLAlchemy 2.x + `psycopg`(sync) / `asyncpg`(async) 중 하나로 통일
    - 마이그레이션:
        - Alembic 도입 또는 "스키마 init 커맨드" 제공(운영에서 재현 가능해야 함)
        - Railway deploy 시 마이그레이션 실행 플로우 정의(Release Command 등)
    - 문서 업데이트:
        - `docs/guides/LOCAL.md`의 `DATABASE_URL=sqlite...` 섹션을 Postgres 옵션 포함으로 갱신
- 테스트:
    - 로컬 Postgres(예: docker compose)에서:
        - 중복(txid,vout) 처리 시 1회만 저장/제출되는지
        - 프로세스 재시작 후에도 dedupe가 유지되는지
- 완료 조건:
    - Railway Postgres를 붙였을 때 로컬 파일 없이 relayer/prover가 정상 동작한다.
- 완료 요약:
    - Migrate relayer PayoutDatabase to SQLAlchemy with SQLite/PostgreSQL support
    - Migrate prover PayoutStore to SQLAlchemy with SQLite/PostgreSQL support
    - Add psycopg2-binary to both relayer and prover dependencies
    - Support postgres:// URL format (Railway) with automatic conversion to postgresql://
    - Use ON CONFLICT DO UPDATE/DO NOTHING for PostgreSQL idempotent upserts
    - Use INSERT OR REPLACE/IGNORE for SQLite backwards compatibility
    - Auto-detect backend from DATABASE_URL and use appropriate SQL dialect

---

### T2.16 hashcredit-relayer(Postgres) 적용 + DATABASE_URL 표준화
- Priority: P2
- Status: [x] DONE
- 목적: `offchain/relayer`가 `DATABASE_URL=postgresql://...`를 받아 Postgres로 동작하도록 한다(현재는 sqlite path만 파싱).
- 작업:
    - `offchain/relayer/hashcredit_relayer/config.py`:
        - `DATABASE_URL`을 Railway Postgres URL과 호환되게 표준화(`postgresql://` / `postgres://` 지원)
    - `offchain/relayer/hashcredit_relayer/db.py`:
        - sqlite3 직접 사용 제거 또는 Postgres 지원 구현
        - 트랜잭션/격리 수준/동시성에서 UNIQUE 충돌 시 멱등 처리(upsert)
    - `offchain/relayer/hashcredit_relayer/relayer.py`:
        - sqlite URL 파싱 로직 제거(또는 fallback만 남기기)
- 테스트:
    - pytest로 Postgres 연결 시 `is_processed/mark_processed/update_status`가 동작하는지
- 완료 조건:
    - `DATABASE_URL`만으로 SQLite ↔ Postgres를 스위칭할 수 있다(운영은 Postgres).
- 완료 요약:
    - (Completed as part of T2.15)
    - Replaced sqlite3 with SQLAlchemy in db.py
    - Added parse_database_url() to handle postgres:// → postgresql:// conversion
    - Updated relayer.py to pass database_url directly to PayoutDatabase
    - All 6 relayer tests passing

---

### T2.17 hashcredit-prover(SPV relayer) Postgres 포팅 + Watcher DB URL화
- Priority: P2
- Status: [x] DONE
- 목적: `offchain/prover`의 `PayoutStore`/`run-relayer --db`가 파일 경로가 아니라 **DB URL**로도 동작하도록 만들어 Railway에서 운영 가능하게 한다.
- 작업:
    - `offchain/prover/hashcredit_prover/watcher.py`:
        - sqlite3 직접 사용 제거 또는 Postgres 지원 구현
        - `pending_payouts/submitted_payouts`에 대한 멱등 upsert 및 인덱스 정의
    - `offchain/prover/hashcredit_prover/cli.py`:
        - `--db`를 `--database-url`(또는 `DATABASE_URL` envvar)로 확장/변경(기존 호환 유지 여부 결정)
    - `offchain/prover/hashcredit_prover/relayer.py`:
        - store 생성/close 등 라이프사이클 정리(커넥션 누수 방지)
- 테스트:
    - 동일 payout이 여러 번 관측되어도 pending/submitted가 중복 생성되지 않는지
- 완료 조건:
    - Railway worker로 `hashcredit-prover run-relayer`를 띄워도 DB가 영속적으로 유지된다.
- 완료 요약:
    - (Completed as part of T2.15)
    - Replaced sqlite3 with SQLAlchemy in watcher.py PayoutStore
    - Added parse_database_url() for URL normalization (supports file paths for backwards compat)
    - Use ON CONFLICT DO NOTHING for PostgreSQL idempotent inserts
    - Added close() method for proper connection lifecycle
    - sqlalchemy and psycopg2-binary added to prover dependencies
    - All 17 prover watcher tests passing

---

### T2.18 Railway 배포 준비(서비스 분리, 환경변수, 마이그레이션, 헬스체크)
- Priority: P1
- Status: [x] DONE
- 목적: Railway에서 오프체인 컴포넌트를 **API 서비스 + Worker(relayer/prover)** 로 배포 가능하게 구성한다.
- 작업:
    - 서비스 설계(권장):
        - Service A: `offchain/api` (FastAPI) — FE가 호출
        - Service B: `offchain/prover` 또는 `offchain/relayer` worker — 주기적으로 watch/submit
        - Railway Postgres add-on 연결
    - 실행 커맨드/포트:
        - `offchain/api`는 `0.0.0.0:$PORT`로 바인딩되게 설정(`PORT` env 지원)
        - worker는 영구 실행 커맨드 정의(예: `hashcredit-prover run-relayer ...`)
    - 마이그레이션 실행:
        - deploy/release 단계에서 DB migrate를 1회 실행하도록 스크립트/문서화
    - 설정/시크릿:
        - `PRIVATE_KEY`, `BITCOIN_RPC_PASSWORD`, `API_TOKEN` 등은 Railway secrets로만 주입
        - 컨트랙트 주소(`HASH_CREDIT_MANAGER`, `CHECKPOINT_MANAGER`, `BTC_SPV_VERIFIER`)는 환경변수로 주입
    - 문서:
        - `docs/guides/DEPLOY.md`에 Railway 섹션 추가(또는 `docs/guides/RAILWAY.md` 신설)
- 테스트:
    - Railway staging(또는 로컬 docker)에서:
        - API `/health` 확인
        - worker가 실제로 DB에 기록/중복 방지하며 submit하는지 로그로 확인
- 완료 조건:
    - Railway에서 "API + Worker + Postgres" 조합으로 재현 가능한 배포 절차가 문서화된다.
- 완료 요약:
    - Add PORT env var support to API config (Railway standard via pydantic validation_alias)
    - Add HOST alias for external binding configuration (0.0.0.0)
    - Change prover CLI --db to --database-url with DATABASE_URL env var support
    - Update RelayerConfig.db_path to database_url for consistency with PostgreSQL support
    - Add Procfile for API service (`python -m hashcredit_api.main`)
    - Add Procfile for prover worker service (`hashcredit-prover run-relayer`)
    - Create comprehensive docs/guides/RAILWAY.md with architecture, deployment steps, env vars reference, security checklist
    - All 186 Solidity tests passing, 61 prover tests passing, 17 API tests passing

---

### T2.19 Vercel FE 배포 준비(API URL/CORS/환경변수)
- Priority: P2
- Status: [ ] TODO
- 목적: FE를 Vercel에 올리고, Railway API와 안전하게 통신할 수 있도록 환경변수/CORS를 정리한다.
- 작업:
    - `apps/web`:
        - `VITE_API_URL`(Railway API base URL) 추가 및 `.env.example` 갱신
        - (선택) proof build/submit 등 API 연동 플로우가 있으면 Vercel 환경변수에 맞춰 정리
    - `offchain/api`:
        - `ALLOWED_ORIGINS`에 Vercel 도메인을 넣는 가이드 추가
        - (보안 티켓 T2.11과 연계) 토큰/인증 정책을 배포 기본값으로 강화
    - 문서:
        - Vercel 환경변수 목록/설정 방법을 `docs/guides/DEPLOY.md`에 추가
- 완료 조건:
    - Vercel FE ↔ Railway API 호출이 CORS 에러 없이 동작하고, 운영 시크릿이 FE로 노출되지 않는다.
