# HashCredit (CTC Hackathon) — PROJECT.md

## 0) 프로젝트 한 줄 정의
HashCredit는 **Bitcoin 채굴자의 미래 채굴 수익(해시레이트 기반 매출)을 담보로** Creditcoin(EVM)에서 **스테이블코인 Revolving Credit Line(한도형 대출)**을 제공하는 프로토콜이다.  
핵심은 “물리적 장비 실사”가 아니라 **Bitcoin 체인 위에서 관측 가능한 Proof-of-Work 기반 지급(Payout) 이벤트를 암호학적으로(또는 MVP에서는 서명 오라클로) 증명**하여 신용한도를 자동으로 개설/증액하는 것이다.

---

## 1) 배경과 문제 정의(Why)
### 1.1 채굴자의 구조적 유동성 문제
- 채굴자는 ASIC/인프라(생산 자산)와 미래 현금흐름(채굴 수익)이 있다.
- 그러나 비용(전기/호스팅/운영/정비)은 즉시 발생하고, 수익은 변동성과 지연이 있다.
- 결과적으로 채굴자는 운영비 마련을 위해 BTC를 “강제 매도”하는 경우가 많고, 이는 장기 업사이드 희생 + 가격 하락 구간에서 손실 확정으로 이어진다.

### 1.2 기존 금융/DeFi 대안의 한계
- 전통 대출(장비 담보/기업대출): 실사, 담보관리, 법적 집행, 느린 언더라이팅, 시장 하락 시 담보가치 급락.
- DeFi 대출: 대부분 유동성 토큰 기반 과담보(청산 위험), BTC 잠금/브릿지/랩핑 의존, 채굴 매출을 직접 “보는” 신용평가 레이어가 없다.

---

## 2) 목표(What)
### 2.1 목표
1. Bitcoin 채굴자 Payout을 “검증 가능한 매출 이벤트(Verifiable Revenue Event)”로 정의한다.
2. 검증된 매출 이벤트를 누적하여 **대출 한도(Credit Limit)를 결정론적으로 산출**한다.
3. Creditcoin(EVM)에서 스테이블코인 **대출/상환**을 제공한다.
4. (Hackathon) 현재 USC용 Bitcoin SPV SDK 부재/미성숙을 고려해 **하이브리드 오라클(MVP Relayer)**로 동작 가능한 데모를 완성한다.
5. (Production) 향후 “신뢰 최소화(Trust-minimized)” 방향으로 **Bitcoin SPV 검증을 온체인**에서 수행하거나, USC의 Bitcoin proof 지원이 성숙하면 **Verifier Adapter만 교체**한다.

### 2.2 비목표(Non-goals, 1차)
- 완전한 DAO/거버넌스, 기관급 KYC/AML, 다중체인/다중자산 확장, 복잡한 ML 신용평가
- 강제 청산(liquidation) 기반 모델(우리는 “수익 기반 한도” + 보수적 캡/동결로 리스크 관리)

---

## 3) 핵심 컨셉(Concept)
### 3.1 “Revenue-Based Financing(RBF)” on-chain
- Borrower(채굴자)는 매출 이벤트(풀 Payout)를 증명하고, 프로토콜은 이를 기반으로 신용한도를 부여한다.
- 담보를 토큰으로 예치하는 대신, **생산 활동으로 생성되는 매출**이 신용의 근거가 된다.

### 3.2 HashCredit의 차별점
- “장비 담보”가 아닌 “온체인 PoW 활동(=Payout)” 기반 신용평가.
- 대출 한도 산정, 이벤트 검증, replay 방지, 리스크 파라미터가 **스마트컨트랙트로 표준화**됨.
- USC/Offchain worker 패턴에 정합적인 구조(검증 모듈만 교체 가능).

---

## 4) 아키텍처(Architecture)
### 4.1 공통 설계 원칙
- **Verifier Adapter Pattern:** “payout 증명 방식”은 교체 가능, “Credit Line 로직”은 고정.
- **Event-sourced Credit:** payout 인증 이벤트가 쌓이고 한도는 결정론적으로 업데이트.
- **Idempotency/Replay protection:** 동일 tx 증빙은 1회만 반영.
- **Defense-in-depth:** 포함 증명 + 의미 검증(수신자/금액) + 출처 검증(풀/패턴) + 리스크 파라미터(캡/헤어컷).

### 4.2 컴포넌트
#### On-chain (Creditcoin EVM)
- `HashCreditManager` (Core)
    - Borrower 등록/상태
    - payout 인증 반영
    - 한도 산출/업데이트
    - borrow/repay 라우팅
- `LendingVault` (단일 stablecoin 기준)
    - liquidity deposit/withdraw
    - borrow/repay
    - 이자 모델(단순 고정 APR 또는 kink model)
- `IVerifierAdapter` + 구현체 2종
    - `RelayerSigVerifier` (Hackathon MVP)
    - `BtcSpvVerifier` (Production: 자체 SPV, checkpoint 기반)
- (권장) `PoolRegistry`
    - “credit-eligible payout”의 출처(풀/클러스터/패턴) 관리
- (권장) `RiskConfig`
    - advance rate, caps, confirmation policy, 신규 borrower 제한

#### Off-chain
- (MVP) `Relayer`
    - Bitcoin mempool/blocks 감시 → payout 감지 → confirmations 대기 → EIP-712 payload 서명 → `submitPayout()` 호출
- (Production) `Proof Builder/Prover`
    - (checkpoint 이후) header chain + merkle branch + rawTx 구성 → `submitPayoutProof()` 호출

---

## 5) 두 가지 실행 모드(중요)
### 5.1 Hackathon MVP: Hybrid Oracle (Relayer Mock)
**왜 필요한가:** USC testnet이 열려 있어도 Bitcoin SPV SDK/문서/도구가 해커톤 기간 내에 사용 불가 수준일 수 있음.  
**해결:** payout 포함 증명을 “서명 오라클”로 시뮬레이션하되, 온체인 인터페이스와 credit 로직은 production과 동일하게 유지.

- Relayer가 신뢰 경계(authorized signer)
- 컨트랙트는 서명 검증 + replay 방지 + 리스크 정책으로 방어
- 메인넷/production에서는 Verifier만 교체

### 5.2 Production: Bitcoin SPV (Checkpointed Header + Merkle Inclusion)
**핵심:** Bitcoin의 tx inclusion은 SHA256d + Bitcoin merkle 규칙이므로, USC 문서의 Keccak 기반 Merkle 설명과 직접 결합이 어려울 수 있다.  
따라서 “Bitcoin proof”는 우리가 구현한다는 가정으로 설계한다.

- 온체인에 **checkpoint header**를 주기적으로 등록(멀티시그/attestor set)
- payout proof 제출 시:
    1) checkpoint 이후 target block까지 짧은 header chain 제출(PrevHash 링크 + PoW 검증)
    2) rawTx + merkle branch로 tx inclusion 검증
    3) rawTx 디코딩하여 vout의 수신자 scriptPubKey + amount 검증
- 리타겟 경계(2016 블록) 넘어가는 증명은 1차 거부(운영으로 회피)

---

## 6) 프로토콜 동작(Flows)
### 6.1 Borrower 등록
입력:
- borrower EVM address
- BTC payout identifier(권장: address 문자열이 아니라 scriptPubKey 해시 형태)

필수 보안 고려:
- “남의 payout address를 등록”하는 공격 방지 필요
- Hackathon: 관리자 승인 + 오프체인 소유 증명(메시지 서명)로 대체 가능
- Production: 등록 커밋 트랜잭션(예: OP_RETURN에 borrowerEvm 커밋) 방식 고려

### 6.2 Payout 인증
- MVP: Relayer signed payload 제출 → on-chain signature verify → revenue 기록
- Production: SPV proof 제출 → on-chain proof verify → revenue 기록

### 6.3 Credit Limit 산출(결정론)
기본 형태:
- trailing revenue window W(예: 30일)
- advance rate α(예: 0.2~0.6)
- `creditLimit = α * trailingRevenueUSD(W)`  
  (해커톤에서는 단순화를 위해 payout을 “USD 환산 없이” sat 기반으로 계산하거나, 고정 BTCUSD price를 config로 둬도 됨. 단, 심사/VC 관점에서 “가격 오라클”은 향후 모듈화 가능하게 명시.)

### 6.4 Borrow/Repay
- `borrow(amount)`는 `debt + amount <= creditLimit`를 만족해야 한다.
- `repay(amount)`로 debt 감소.
- 이자 모델은 단순 고정 APR로 시작 가능(해커톤), production에서 utilization 기반 모델로 확장.

### 6.5 Freeze/Offboarding(운영 필수)
- 이상 징후 발생 시 borrower를 Frozen으로 전환 → 추가 borrow 차단
- 강제 청산이 아니라 “추가 대출 차단 + 상환 유도”가 기본

---

## 7) 공격 모델과 방어(심사/VC 핵심)
### 7.1 가장 큰 구멍: Self-transfer로 가짜 매출 만들기
단순히 “내 주소로 입금”을 매출로 인정하면, 공격자가 자기자금 순환으로 한도를 부풀리고 stablecoin을 빌린 뒤 디폴트 가능.

### 7.2 방어 레이어(우선순위)
1) **Pool provenance (필수)**
- payout이 “등록된 풀 출처”에서 발생했음을 최대한 확인
- Hackathon: relayer가 provenance 판정 후 서명(온체인 registry는 훅만 제공)
- Production: 풀 클러스터 registry + 패턴 기반 판정(완전한 입력 UTXO 추적은 비용이 큼)

2) **Underwriting haircut + caps (필수)**
- 신규 borrower cap, 낮은 α(advance rate), 기간 window 확장(조작 비용 증가)

3) **Replay protection + confirmations (필수)**
- txid/vout 1회 반영, confirmations 정책(예: 6 conf)

4) **행동 기반 휴리스틱(선택)**
- 단발성 대형 입금은 limit 반영 지연/부분 반영
- payout 주기/분산이 풀 패턴과 일치하는지

---

## 8) 납품물(Deliverables)
### 8.1 Hackathon MVP 납품
- 스마트컨트랙트:
    - HashCreditManager + LendingVault + RelayerSigVerifier + (옵션) PoolRegistry/RiskConfig
- 오프체인:
    - Python Relayer(감시/서명/전송)
- 테스트:
    - Foundry unit tests(등록, replay, limit 업데이트, borrow/repay)
- 데모:
    - E2E 데모 스크립트 + 최소 UI/CLI

### 8.2 Production SPV 납품(2차)
- BtcSpvVerifier(Checkpointed header + merkle inclusion + vout parsing 최소)
- Proof builder(헤더/머클/tx 구성)
- 실제 메인넷 tx 샘플로 테스트 벡터 구축

---

## 9) 기술 스택/레포 구조(권장)
- Solidity + Foundry(테스트/배포)
- (선택) Hardhat for scripts
- Python 3.11+ (Relayer/Prover)
- Docker compose(옵션): Bitcoin Core, indexer, relayer

권장 레포 구조:
- `/contracts` solidity
- `/test` foundry tests
- `/script` deployment scripts
- `/offchain/relayer` python
- `/offchain/prover` python
- `/docs` additional docs
- `PROJECT.md`, `TICKET.md`

---

## 10) 완료 기준(Definition of Done)
각 기능은 아래를 만족해야 “Done”:
- 코드 + 테스트 + 최소 문서 업데이트
- 재현 가능한 데모 시나리오(스크립트)
- 보안/리스크 관련 파라미터가 코드에 하드코딩되지 않고 config로 제어 가능
- replay/nonce/confirmations 정책이 명확히 구현/문서화

---
