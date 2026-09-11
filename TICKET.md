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
    - `DEMO.md` 작성
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
- Status: [ ] TODO
- 목적: 복잡한 “watcher/relayer” 전에, **Bitcoin testnet txid 한 건을 입력하면** proof를 만들고 `HashCreditManager.submitPayout()`까지 끝내는 단발 플로우를 제공한다.
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
    - “txid 1건” 입력으로 on-chain payout 반영 트랜잭션이 성공한다.

---

### T1.10 SPV Relayer(감시/자동 제출) + dedupe/confirmations
- Priority: P1
- Status: [ ] TODO
- 목적: 운영 가능한 최소 relayer를 만들어 **Bitcoin testnet 주소 감시 → confirmations 충족 → proof 생성 → submit → dedupe**까지 자동화한다.
- 작업:
    - Bitcoin Core RPC 기반 주소 감시(최소: txid 리스트/블록 스캔 전략 중 하나)
    - checkpoint 선택 로직:
        - header chain 길이 제약(≤144) 만족하도록 `checkpointHeight` 자동 선택
    - sqlite dedupe(기존 relayer DB 재사용 가능)
    - 실패 케이스(재시도/로그/원인 노출) 정리
- 완료 조건:
    - 한 주소를 지정하면 payout 트랜잭션을 자동으로 찾아 submit하고, 중복 제출이 방지된다.

---

### T1.11 결정적(offline) SPV fixtures + Manager E2E 테스트 + 문서
- Priority: P1
- Status: [ ] TODO
- 목적: 네트워크 없이도 검증 가능한 형태로 **Bitcoin testnet 기반 SPV proof 검증/제출의 회귀 테스트**를 만들고, Creditcoin testnet 기준 운영 문서를 완성한다.
- 작업:
    - `test/fixtures/`에 실제 메인넷/테스트넷 tx 기반(또는 최소한 고정 데이터 기반) proof 구성요소 저장
    - `BtcSpvVerifier.verifyPayout()` 성공/실패 테스트 추가(머클/헤더체인/출력 불일치 등)
    - `HashCreditManager.submitPayout()`까지 이어지는 E2E 테스트 추가(creditLimit 증가 + replay 방지)
    - `LOCAL.md`에 Creditcoin testnet SPV 모드 실행/디버깅 섹션 추가
- 완료 조건:
    - `forge test`로 SPV 경로의 핵심 검증이 안정적으로 재현되고, 문서만 보고 testnet에서 end-to-end 실행 가능하다.

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
- Status: [ ] TODO
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
