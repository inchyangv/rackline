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
- Status: [ ]
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
- Status: [ ]
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
- Status: [ ]
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
- Status: [ ]
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
- Status: [ ]
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
- Status: [ ]
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
- Status: [ ]
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
- Status: [ ]
- 목적: self-transfer 조작 가능성을 낮춘다.
- 작업:
    - 풀 payout 클러스터 allowlist (운영 시작)
    - payout 패턴 룰(간단):
        - 최소 payout count 충족 전 cap 고정
        - 단발성 대형 입금은 부분 반영
- 완료 조건:
    - 공격 시나리오(자기자금 순환)에서 한도 상승이 제한됨을 테스트/문서로 제시

---

## P2 — Polishing / Security / Launch Readiness

### T2.1 Gas Profiling + Limits
- Priority: P2
- Status: [ ]
- 목적: proof 제출 비용, 루프 길이(merkle branch/hdr chain) 상한을 설정한다.
- 작업:
    - branch length max
    - header chain max
    - revert reason 명확화
- 완료 조건:
    - 비용/상한 문서화

---

### T2.2 Audit Checklist + Threat Model Doc
- Priority: P2
- Status: [ ]
- 목적: 심사위원/VC/외주 인수인계를 위한 보안 문서를 만든다.
- 산출물:
    - `docs/threat-model.md`
    - `docs/audit-checklist.md`
- 완료 조건:
    - 주요 위협(oracle compromise, replay, reorg, self-transfer, key loss) 대응이 정리됨

---
