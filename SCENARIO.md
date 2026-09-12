# HashCredit User Scenarios

> 유저 관점에서 모든 시나리오를 상세하게 정리한 문서.
> 역할: **Borrower (채굴자)**, **LP (유동성 공급자)**, **공통 (모든 유저)**

---

## 유저 역할 정의

| 역할 | 설명 | 핵심 동기 |
|------|------|----------|
| **Borrower** | BTC 채굴자. 채굴 수익을 담보로 스테이블코인 대출을 받고 싶다 | 운영 자금(전기료, 장비) 확보 |
| **LP** | 유동성 공급자. mUSDT를 예치하고 이자 수익을 얻고 싶다 | 안정적인 수익률 (현재 8% APR) |

---

## A. 공통 시나리오 — 지갑 연결 & 네트워크

### A-1. 최초 방문 (지갑 미연결)

**전제조건:** 사이트에 처음 접속, MetaMask 미연결 상태

**유저가 보는 화면:**
- 상단 메트릭 바: 모든 값이 "—"
- Wallet Panel: "Disconnected" 표시
- Dashboard 탭: 온보딩 스테퍼 표시
  - Step 1: Connect Wallet (미완료)
  - Step 2: Link BTC Wallet (비활성)
  - Step 3: Start Borrowing (비활성)
- 모든 액션 버튼(Borrow, Repay, Deposit, Withdraw) 비활성

**유저 행동:** "Connect" 버튼 클릭

**결과:**
- MetaMask 팝업 → 계정 선택 → 승인
- 지갑 주소 표시, 잔액 로딩
- 메트릭 바에 실제 값 표시 시작

**실패 시나리오:**
| 상황 | 유저가 보는 것 | 유저가 해야 할 것 |
|------|-------------|----------------|
| MetaMask 미설치 | 에러 또는 무반응 | MetaMask 설치 후 재시도 |
| 유저가 팝업에서 거부 | 연결 실패, Disconnected 유지 | 다시 Connect 클릭 |
| MetaMask 잠김 | MetaMask 잠금해제 팝업 | 비밀번호 입력 후 재시도 |

---

### A-2. 네트워크 전환 (잘못된 체인 연결)

**전제조건:** MetaMask가 Ethereum Mainnet 등 다른 네트워크에 연결된 상태

**유저가 보는 화면:**
- Wallet Panel에 현재 체인 표시 (예: "Chain: 1")
- "Switch Network" 버튼 표시

**유저 행동:** "Switch Network" 클릭

**결과:**
- MetaMask 네트워크 전환 팝업
  - HashKey Chain Testnet (chainId 133)이 이미 추가되어 있으면 → 전환 승인
  - 추가되어 있지 않으면 → "네트워크 추가" 팝업 → 승인 → 자동 전환
- 전환 완료 후: "HashKey Testnet" 표시, 컨트랙트 데이터 로딩 시작

**실패 시나리오:**
| 상황 | 유저가 보는 것 | 유저가 해야 할 것 |
|------|-------------|----------------|
| 유저가 전환 거부 | 기존 네트워크 유지 | 수동으로 네트워크 변경 |
| RPC 장애 | 데이터 로딩 실패 / Skeleton 표시 지속 | 잠시 후 재시도 |

---

### A-3. 지갑 연결 해제

**전제조건:** 지갑이 연결된 상태

**유저 행동:** "Disconnect" 클릭

**결과:**
- 지갑 주소 제거
- 모든 메트릭 "—"로 복귀
- 모든 액션 버튼 비활성

---

### A-4. 트랜잭션 상태 추적 (모든 TX 공통)

모든 온체인 트랜잭션은 다음 상태 순서를 따른다:

```
idle → signing → pending → confirmed
                         ↘ error
```

| 상태 | 유저가 보는 것 | 유저가 할 수 있는 것 |
|------|-------------|-------------------|
| **idle** | 버튼 활성 상태, 이전 TX 결과 없음 | 새로운 TX 시작 |
| **signing** | "서명 대기 중..." + 라벨 | MetaMask에서 서명 승인/거부 |
| **pending** | "TX 대기 중..." + tx hash | 블록 컨펌 대기 (다른 액션 불가) |
| **confirmed** | "완료" + tx hash | 다음 액션 가능, 잔액 자동 갱신 |
| **error** | 에러 메시지 표시 + 라벨 | 원인 확인 후 재시도 |

**에러 케이스 상세:**
| 에러 유형 | 원인 | 유저가 보는 메시지 (예시) |
|----------|------|------------------------|
| 서명 거부 | MetaMask에서 "Reject" | "User rejected the request" |
| 가스 부족 | HSK 잔액 부족 | "insufficient funds for gas" |
| 컨트랙트 revert | 비즈니스 로직 위반 | revert 사유 (예: "ExceedsCreditLimit") |
| 네트워크 장애 | RPC 무응답 | "network error" / timeout |

---

## B. Borrower 시나리오 — BTC 지갑 연동

### B-1. BTC 지갑 링크 — 전체 플로우 (정상)

**전제조건:** MetaMask 연결됨, HashKey Testnet, BTC 지갑(Sparrow 등) 보유

**유저가 보는 화면:** Dashboard 탭 → "Link BTC Wallet" 섹션 (3단계 아코디언)

#### Step 1: BTC 주소 입력

**유저 행동:** BTC 주소 입력란에 주소 입력 (예: `tb1q...`)

**결과:**
- Step 1 완료 표시
- Step 2 자동 활성화/확장
- 서명할 메시지 생성: `"HashCredit: Link BTC to 0x{EVM주소}"`

**실패 시나리오:**
| 상황 | 결과 |
|------|------|
| 빈 주소 입력 | Step 2 진행 불가 |
| 잘못된 형식 | 이후 단계에서 검증 실패 |

#### Step 2: BTC 메시지 서명

**유저가 보는 화면:**
- "Message to sign" 텍스트 영역에 정확한 메시지 표시
- "Copy" 버튼
- "BTC Signature" 입력란

**유저 행동:**
1. "Copy" 버튼으로 메시지 복사
2. BTC 지갑(Sparrow, Electrum 등)에서 해당 메시지를 정확히 서명
3. base64로 인코딩된 서명값을 입력란에 붙여넣기

**결과:**
- Step 2 완료 표시
- Step 3 활성화

**실패 시나리오:**
| 상황 | 결과 |
|------|------|
| 메시지를 변형해서 서명 | Step 3에서 on-chain 검증 실패 |
| base64가 아닌 형식 | API에서 파싱 실패 |
| 다른 BTC 주소로 서명 | Step 1 주소와 불일치 → 검증 실패 |

#### Step 3: On-chain 검증 & Borrower 등록

**유저 행동:** "Verify & Register" 버튼 클릭

**내부 처리 (유저에게 로그로 표시):**

```
[1/3] API로 서명 파라미터 추출 중...
      POST /claim/extract-sig-params
      → pubKeyX, pubKeyY, btcMsgHash, v, r, s 반환

[2/3] On-chain BTC 주소 클레임 중...
      BtcSpvVerifier.claimBtcAddress(pubKeyX, pubKeyY, btcMsgHash, v, r, s)
      → MetaMask 서명 요청 #1
      → TX pending → confirmed

[3/3] Borrower 등록 + 크레딧 부여 중...
      POST /claim/register-and-grant
      → 서버에서 registerBorrower() 호출
      → 1,000 mUSDT 테스트넷 크레딧 자동 부여
```

**유저가 보는 최종 결과:**
- BTC Status: "Linked" (초록색)
- Available Credit: 1,000.000000 mUSDT
- 온보딩 스테퍼 Step 2 완료
- Borrow 버튼 활성화

**실패 시나리오:**
| 상황 | 에러 메시지 / 로그 | 해결 방법 |
|------|-------------------|----------|
| API 서버 다운 | "Failed to fetch" / "Network error" | API 복구 대기 |
| 서명 파라미터 추출 실패 | "Invalid signature format" | 올바른 BIP-137 서명 재생성 |
| claimBtcAddress revert | "Invalid signature" / "Address already claimed" | 서명/주소 재확인. 이미 클레임한 주소는 재사용 불가 |
| MetaMask에서 서명 거부 | "User rejected" | 재시도 |
| registerBorrower revert | "BorrowerAlreadyRegistered" | 이미 등록됨 → Borrow 진행 |
| HSK 가스 부족 | "insufficient funds for gas" | Faucet에서 HSK 수령 |

---

### B-2. BTC 지갑 링크 — 이미 등록된 유저가 재방문

**전제조건:** 이전에 BTC 링크 + Borrower 등록을 완료한 유저

**유저가 보는 화면:**
- BTC Status: "Linked" (초록색)
- Available Credit: 잔여 크레딧 표시
- Link BTC Wallet 섹션은 접힌 상태 (이미 완료)
- 온보딩 스테퍼 모든 단계 완료

---

## C. Borrower 시나리오 — 대출 (Borrow)

### C-1. 대출 실행 (정상)

**전제조건:**
- 지갑 연결됨 + HashKey Testnet
- Borrower 등록 완료 (status = Active)
- BTC 지갑 링크 완료
- Available Credit > 0

**유저가 보는 화면:** Dashboard 탭 → Actions 섹션 → Borrow 탭

**Credit Overview (읽기 전용):**
| 항목 | 값 (예시) |
|------|----------|
| Available Credit | 1,000.000000 mUSDT |
| Balance (mUSDT) | 0.000000 mUSDT |
| Outstanding Debt | 0.000000 mUSDT |
| Accrued Interest | 0.000000 mUSDT |
| Borrow APR | 8.00% |
| BTC Status | Linked |

**유저 행동:**
1. Borrow 금액 입력 (예: `500`)
   - 또는 "Max" 버튼 클릭 → Available Credit 전액 자동 입력
2. "Borrow" 버튼 클릭

**결과:**
- MetaMask 서명 요청: `HashCreditManager.borrow(500000000)` (6 decimals)
- TX 상태: signing → pending → confirmed
- 갱신된 지표:
  - Available Credit: 500.000000 mUSDT
  - Balance: 500.000000 mUSDT (지갑에 mUSDT 입금됨)
  - Outstanding Debt: 500.000000 mUSDT

**실패 시나리오:**
| 상황 | 에러 | 해결 |
|------|------|------|
| 크레딧 초과 금액 입력 | `ExceedsCreditLimit` revert | Available Credit 이하로 입력 |
| 0 입력 | `ZeroAmount` revert | 양수 입력 |
| Borrower 미등록 | `BorrowerNotRegistered` revert | BTC 링크 먼저 완료 |
| Borrower Frozen 상태 | `BorrowerNotActive` revert | 관리자에게 연락 |
| Vault 유동성 부족 | revert (Vault 잔액 부족) | LP 유동성 공급 대기 |
| 컨트랙트 Paused 상태 | revert | 관리자가 unpause할 때까지 대기 |

---

### C-2. 대출 후 상태 확인

**전제조건:** 500 mUSDT 대출 완료

**유저가 보는 화면:**
| 항목 | 변화 |
|------|------|
| Available Credit | 1,000 → 500 mUSDT |
| Balance | 0 → 500 mUSDT |
| Outstanding Debt | 0 → 500 mUSDT |
| Accrued Interest | 0 → 시간이 지나면 점진적으로 증가 |

**시간 경과에 따른 이자 발생:**
- APR 8% 기준, 500 mUSDT × 8% / 365일 ≈ 0.109589 mUSDT/일
- 유저가 페이지를 새로고침하면 Accrued Interest 값이 갱신됨

---

### C-3. 추가 대출 (기존 대출 있는 상태에서)

**전제조건:** 이미 500 mUSDT 대출, Available Credit 500 남음

**유저 행동:** 추가로 300 mUSDT 대출

**결과:**
- 이자가 원금에 복리로 합산된 후 새 대출 추가
- Available Credit: 200 mUSDT
- Outstanding Debt: 500 + 발생이자 + 300 mUSDT
- Balance: 기존 잔액 + 300 mUSDT

---

### C-4. 최대 크레딧 전액 대출 시도

**유저 행동:** "Max" 버튼 → "Borrow" 클릭

**결과:**
- Available Credit 전액 대출
- Available Credit: 0 mUSDT
- 이후 추가 대출 불가 (0원 이상 대출 시 `ExceedsCreditLimit`)

---

## D. Borrower 시나리오 — 상환 (Repay)

### D-1. Approve 후 상환 (정상)

**전제조건:**
- Outstanding Debt > 0
- 지갑에 충분한 mUSDT 잔액 보유

**유저 행동 (2단계):**

#### 단계 1: Approve (필요한 경우)

- mUSDT를 HashCreditManager가 사용할 수 있도록 승인해야 함
- Approve 금액 입력 → "Approve" 클릭
- MetaMask 서명: `mUSDT.approve(HashCreditManager, amount)`
- TX confirmed

#### 단계 2: Repay

- Repay 금액 입력 (예: `200`)
  - 또는 "Max" 버튼 → 현재 채무 전액 자동 입력
- "Repay" 클릭
- MetaMask 서명: `HashCreditManager.repay(200000000)`
- TX confirmed

**결과:**
- Outstanding Debt: 감소
- Available Credit: 증가 (상환한 만큼)
- Balance: 감소 (mUSDT 지출)
- 전액 상환 시 Debt = 0

**실패 시나리오:**
| 상황 | 에러 | 해결 |
|------|------|------|
| Approve 미실행 | ERC20 revert (allowance 부족) | Approve 먼저 실행 |
| Approve 금액 부족 | ERC20 revert | 더 큰 금액으로 Approve 재실행 |
| mUSDT 잔액 부족 | ERC20 revert (transfer failed) | 충분한 mUSDT 확보 |
| 0 입력 | `ZeroAmount` revert | 양수 입력 |
| 채무가 0인데 상환 시도 | revert 또는 0 처리 | 불필요한 상환 |

---

### D-2. 부분 상환

**전제조건:** Outstanding Debt 500 mUSDT + 이자

**유저 행동:** 200 mUSDT 상환

**결과:**
- 상환금은 **이자 먼저** 차감, 나머지가 원금 차감
- Outstanding Debt: ~300 mUSDT + 잔여 이자
- Available Credit: 상환 금액만큼 증가

---

### D-3. 전액 상환

**유저 행동:** "Max" 버튼 → 전액 상환

**결과:**
- Outstanding Debt: 0 mUSDT
- Available Credit: 원래 Credit Limit으로 복귀
- 이자 포함 전액 정산

**주의:** 이자가 시간에 따라 계속 발생하므로, "Max"를 눌렀을 때의 금액이 TX 확정 시점의 실제 채무보다 미세하게 적을 수 있음. 컨트랙트는 잔액 이하만 정산하도록 처리.

---

### D-4. Approve 없이 Repay 시도

**유저 행동:** Approve 건너뛰고 바로 Repay 클릭

**결과:**
- ERC20 `transferFrom` 실패 → revert
- 에러 메시지: allowance 관련 에러
- **해결:** Approve 먼저 실행

---

## E. LP 시나리오 — 예치 (Deposit)

### E-1. mUSDT 예치 (정상)

**전제조건:**
- 지갑 연결됨 + HashKey Testnet
- mUSDT 잔액 보유

**유저가 보는 화면:** Pool 탭 → Deposit 탭

**표시 정보:**
| 항목 | 값 (예시) |
|------|----------|
| Vault Contract | 0x3517...15fb (explorer 링크) |
| Total Pool Assets | 10,000.000000 mUSDT |
| Total Borrowed | 3,000.000000 mUSDT |
| Available Liquidity | 7,000.000000 mUSDT |
| Utilization Rate | 30.00% |
| Borrow APR | 8.00% |
| My Shares | 0.000000 |
| Current Value | 0.000000 mUSDT |
| My mUSDT Balance | 5,000.000000 mUSDT |

**유저 행동 (2단계):**

#### 단계 1: Approve

- 금액 입력 또는 "Max" 클릭
- "Approve" 버튼 클릭
- MetaMask: `mUSDT.approve(LendingVault, amount)`
- TX confirmed

#### 단계 2: Deposit

- 금액 입력 (예: `1000`) 또는 "Max" 클릭
- Expected Shares 미리보기 확인 (예: "Expected Shares: 1000.000000")
- "Deposit" 버튼 클릭
- MetaMask: `LendingVault.deposit(1000000000)`
- TX confirmed

**결과:**
- My Shares: 0 → 1000.000000 (또는 exchange rate에 따른 값)
- Current Value: 0 → 1000.000000 mUSDT
- My mUSDT Balance: 5000 → 4000 mUSDT
- Total Pool Assets: 증가
- Available Liquidity: 증가

**실패 시나리오:**
| 상황 | 에러 | 해결 |
|------|------|------|
| Approve 미실행 | ERC20 revert | Approve 먼저 |
| mUSDT 잔액 부족 | ERC20 revert | 잔액 확보 |
| 0 입력 | revert | 양수 입력 |
| 컨트랙트 Paused | revert | 관리자 조치 대기 |

---

### E-2. 추가 예치

**전제조건:** 이미 1000 mUSDT 예치됨

**유저 행동:** 추가로 500 mUSDT 예치

**결과:**
- My Shares: 증가 (현재 exchange rate 기준)
- Current Value: 기존 + 새 예치분
- 추가 예치 시 exchange rate가 변동했을 수 있음 (이자 수익으로 share 가치 상승)

---

### E-3. 예치 직후 상태 확인

**유저가 보는 화면:**
| 항목 | 변화 |
|------|------|
| My Shares | 신규 share 수량 반영 |
| Current Value | share × exchange rate로 계산된 mUSDT 가치 |
| Total Pool Assets | 내 예치금만큼 증가 |
| Utilization Rate | 분모 증가로 소폭 감소 |

---

## F. LP 시나리오 — 출금 (Withdraw)

### F-1. mUSDT 출금 (정상)

**전제조건:**
- My Shares > 0
- Available Liquidity >= 출금 희망 금액

**유저가 보는 화면:** Pool 탭 → Withdraw 탭

**표시 정보:**
| 항목 | 값 (예시) |
|------|----------|
| My Shares | 1000.000000 |
| Current Value | 1,005.000000 mUSDT (이자 수익 반영) |

**유저 행동:**
1. mUSDT 금액 입력 (예: `500`)
   - 또는 "Max" 버튼 → 전체 가치 자동 입력
   - "Shares to Redeem" 자동 계산 표시
2. "Withdraw" 버튼 클릭
3. MetaMask: `LendingVault.withdraw(shares)` — 필요한 share 수량 기준으로 호출
4. TX confirmed

**결과:**
- My Shares: 감소
- Current Value: 감소
- My mUSDT Balance: 증가 (출금된 mUSDT 수령)
- Total Pool Assets: 감소
- Available Liquidity: 감소

---

### F-2. 전액 출금

**유저 행동:** "Max" → "Withdraw"

**결과:**
- My Shares: 0
- Current Value: 0
- 예치 원금 + 발생 이자 전액 수령

---

### F-3. 유동성 부족으로 출금 실패

**전제조건:**
- Current Value: 1,000 mUSDT
- Available Liquidity: 200 mUSDT (대부분 대출로 나감)

**유저가 보는 화면:**
- 500 mUSDT 입력 시 → 에러 배너: "Withdrawal exceeds available liquidity"
- Withdraw 버튼 비활성

**유저가 할 수 있는 것:**
| 옵션 | 설명 |
|------|------|
| 부분 출금 | Available Liquidity 이하로 금액 변경 (예: 200 mUSDT) |
| 대기 | Borrower가 상환하면 유동성 회복 → 이후 출금 |

---

### F-4. Shares 개념 이해

**유저 혼란 포인트:** "Shares가 뭐지? 내 돈은 얼마지?"

**현재 UX:**
- My Shares 라벨 옆에 info 아이콘(i) → 툴팁: "풀 지분을 나타내는 토큰. 풀 수익에 비례해 가치 상승"
- Withdraw 탭에서 mUSDT 기준으로 입력 가능 (shares 자동 계산)

**Shares ↔ mUSDT 관계:**
- 초기: 1 Share ≈ 1 mUSDT
- 시간 경과: 대출 이자 수익이 풀에 쌓이면서 1 Share > 1 mUSDT
- 예: 1000 Shares → Current Value 1,050 mUSDT (50 mUSDT 이자 수익)

---

## G. Borrower 시나리오 — SPV 증명 & 크레딧 갱신 (메인넷)

> 테스트넷에서는 auto-grant로 크레딧이 부여되지만,
> 메인넷에서는 실제 BTC 채굴 수익의 SPV 증명을 통해 크레딧이 결정된다.
> 아래는 메인넷 시나리오이며, 유저에게는 백그라운드로 처리됨.

### G-1. 채굴 수익 자동 감지 & 증명 제출 (자동)

**전제조건:**
- Borrower 등록 완료
- BTC 지갑 링크 완료
- Off-chain Prover Worker가 해당 BTC 주소를 모니터링 중
- 마이닝풀에서 BTC payout 발생

**자동 처리 흐름 (유저 개입 없음):**

```
1. Worker가 BTC 주소의 새 payout 감지 (폴링 간격: 60초)
2. 6 confirmations 대기
3. SPV proof 자동 생성:
   - Checkpoint → target block까지의 header chain
   - Merkle branch (tx inclusion)
   - Raw tx + output index
4. HashCreditManager.submitPayout(proof) 자동 호출
5. On-chain 검증:
   - Header chain PoW 검증
   - Merkle inclusion 검증
   - Output이 borrower의 pubkeyHash로 지불되는지 확인
   - Replay protection (txid + vout 중복 방지)
6. 크레딧 갱신:
   - trailingRevenueSats 업데이트 (30일 윈도우)
   - creditLimit 재계산
```

**유저가 보는 변화 (Dashboard 새로고침 시):**
- Available Credit: 증가 (채굴 수익에 비례)
- "총 수익" 증가

---

### G-2. 크레딧 계산 로직 (유저 관점)

**유저가 알아야 할 것:**
- 최근 30일간의 **검증된** 채굴 수익 누적액이 크레딧 산정 기준
- 크레딧 = 30일 trailing revenue × BTC/USD × 50% (advance rate)
- 더 많이 채굴할수록 크레딧 증가
- 30일이 지난 오래된 payout은 윈도우에서 탈락 → 크레딧 감소 가능

**예시:**
```
최근 30일 검증된 수익: 0.5 BTC
BTC/USD: $60,000
채굴 수익 USD 가치: $30,000
Advance Rate: 50%
→ Credit Limit: $15,000 (15,000 mUSDT)
```

**크레딧 감소 시나리오:**
| 상황 | 결과 |
|------|------|
| 30일 전 payout이 윈도우에서 빠짐 | Credit Limit 소폭 감소 |
| 장기간 채굴 중단 | 윈도우 내 revenue 감소 → Credit Limit 크게 감소 |
| Credit Limit < Current Debt | 추가 대출 불가 (기존 대출은 유지, 상환만 가능) |

---

### G-3. 대규모 payout 디스카운트

- 단일 payout이 0.1 BTC 초과 시 → 해당 payout의 50%만 크레딧 계산에 반영
- **이유:** 비정상적으로 큰 단일 지급의 위험 완화
- 유저에게 직접 표시되지 않으나 Credit Limit에 영향

---

### G-4. 신규 Borrower 캡

- 등록 후 30일 이내: 최대 $10,000 크레딧 한도
- **이유:** 새 borrower의 채굴 이력이 충분히 쌓이기 전 보호
- 30일 이후: 실제 trailing revenue 기반 한도로 전환

---

## H. 복합 시나리오 — Borrower + LP 동시 운영

### H-1. 채굴자가 LP도 겸하는 경우

**유저 목표:** 채굴 수익으로 대출도 받고, 여유 mUSDT는 풀에 예치

**시나리오 흐름:**
1. BTC 지갑 링크 → Borrower 등록 (Credit 1,000 mUSDT)
2. 500 mUSDT 대출
3. 대출받은 500 mUSDT 중 200을 Pool에 예치
4. Pool에서 이자 수익 발생
5. 수익으로 대출 상환

**주의점:**
- 대출 이자 (8% APR) = LP 수익 이자 (8% APR에서 파생)
- 자기 대출금을 자기 풀에 넣는 것은 순환 참조이므로 경제적 의미 제한적
- 다만 다른 borrower의 이자 수익을 함께 받을 수 있음

---

### H-2. LP만 하는 유저 (채굴자 아님)

**시나리오:**
1. MetaMask 연결
2. Dashboard 탭은 거의 무시 (BTC 링크 불필요)
3. Pool 탭으로 바로 이동
4. mUSDT 예치
5. 이자 수익 확인 및 출금

**유저가 보는 Dashboard:**
- Available Credit: 0 (미등록)
- BTC Status: "Not linked"
- Borrow 버튼 비활성

---

## I. 에러 & 엣지 케이스 시나리오

### I-1. 네트워크 장애 중 TX 전송

**상황:** TX를 보냈는데 RPC가 응답 안 함

**유저가 보는 것:**
- TX 상태가 "pending"에서 멈춤
- 일정 시간 후 timeout 에러

**유저 행동:**
- MetaMask에서 직접 TX 상태 확인
- Explorer에서 tx hash로 조회
- 네트워크 복구 후 페이지 새로고침

---

### I-2. 같은 BTC 주소를 두 번 클레임

**상황:** 이미 `claimBtcAddress`를 완료한 BTC 주소로 다시 시도

**결과:**
- 컨트랙트 revert
- 에러: "Address already claimed" 또는 유사

---

### I-3. Frozen 상태 Borrower

**상황:** 관리자가 borrower를 freeze 처리

**유저가 보는 것:**
- Borrow 버튼: 비활성 또는 클릭 시 `BorrowerNotActive` revert
- Repay: **가능** (Frozen 상태에서도 상환은 허용)
- 새 payout 제출: 불가

---

### I-4. 컨트랙트 Pause 상태

**상황:** 관리자가 긴급 상황으로 HashCreditManager를 pause

**유저가 보는 것:**
- 모든 write 함수 (borrow, repay, submitPayout) revert
- 읽기 전용 데이터(잔액, 크레딧 등)는 정상 표시

---

### I-5. mUSDT 잔액 0에서 Repay 시도

**상황:** 대출 받은 mUSDT를 다른 곳에 사용/전송하여 잔액 0

**결과:**
- Repay 시도 → ERC20 transfer 실패
- 유저는 mUSDT를 확보(구매, 수령 등)한 후 상환

---

### I-6. Pool 유동성 0에서 Borrow 시도

**상황:** LP 예치금 전액이 대출로 나가서 Available Liquidity = 0

**결과:**
- Available Credit이 있어도 Borrow 실패
- Vault에서 transfer할 mUSDT가 없음
- LP가 추가 예치하거나 다른 borrower가 상환해야 유동성 회복

---

### I-7. 매우 작은 금액 대출/상환 (더스트)

**상황:** 0.000001 mUSDT (1 wei) 대출 시도

**결과:**
- 가스비가 대출 금액보다 클 수 있음
- 컨트랙트는 0 초과면 허용하나, 경제적으로 비효율적

---

### I-8. 동시 다발적 TX 충돌

**상황:** 두 브라우저 탭에서 동시에 같은 지갑으로 Borrow

**결과:**
- MetaMask가 nonce 관리
- 하나는 성공, 다른 하나는 nonce 충돌 또는 상태 변경으로 revert 가능

---

## J. 온보딩 플로우 전체 요약

### J-1. Borrower 온보딩 (처음부터 대출까지)

```
1. 사이트 접속
   └─ 모든 값 "—", Connect 버튼만 활성

2. Connect Wallet (MetaMask)
   ├─ 성공 → 지갑 주소 표시, 네트워크 확인
   └─ 실패 → 재시도

3. (필요시) Switch Network → HashKey Testnet (133)
   ├─ 성공 → 데이터 로딩
   └─ 실패 → 수동 네트워크 추가

4. Link BTC Wallet (3단계)
   ├─ Step 1: BTC 주소 입력
   ├─ Step 2: 메시지 서명 (BTC 지갑)
   └─ Step 3: On-chain 검증 & 등록
       ├─ claimBtcAddress TX (MetaMask 서명)
       └─ registerBorrower (API → 서버 TX)
           └─ 1,000 mUSDT 테스트넷 크레딧 자동 부여

5. Borrow
   ├─ 금액 입력 또는 Max
   └─ Borrow TX (MetaMask 서명)
       └─ mUSDT 수령

6. Repay (나중에)
   ├─ Approve TX
   └─ Repay TX
```

### J-2. LP 온보딩 (처음부터 예치까지)

```
1. 사이트 접속

2. Connect Wallet (MetaMask)

3. (필요시) Switch Network → HashKey Testnet (133)

4. Pool 탭으로 이동

5. Deposit
   ├─ Approve TX (mUSDT → LendingVault 승인)
   └─ Deposit TX
       └─ Shares 수령

6. 이자 수익 확인 (시간 경과 후)
   └─ Current Value > 예치 원금

7. Withdraw (원할 때)
   └─ Withdraw TX
       └─ mUSDT + 이자 수령
```

---

## K. 페이지별 유저 인터랙션 요약

### Dashboard 탭

| 영역 | 인터랙션 | 트리거 조건 |
|------|---------|-----------|
| 온보딩 스테퍼 | 시각적 진행률 표시 | 항상 (미완료 단계 있을 때) |
| Credit Overview | 읽기 전용 | 항상 |
| Borrow 입력 + Max + 버튼 | 금액 입력 → TX | 등록 완료 + Credit > 0 |
| Approve 입력 + 버튼 | 금액 입력 → TX | 지갑 연결 |
| Repay 입력 + Max + 버튼 | 금액 입력 → TX | Debt > 0 |
| BTC 링크 Step 1 | BTC 주소 입력 | 미링크 상태 |
| BTC 링크 Step 2 | 메시지 복사 + 서명 붙여넣기 | Step 1 완료 |
| BTC 링크 Step 3 | Verify & Register 버튼 | Step 2 완료 |

### Pool 탭

| 영역 | 인터랙션 | 트리거 조건 |
|------|---------|-----------|
| Pool Status | 읽기 전용 (Vault explorer 링크) | 항상 |
| My Position | 읽기 전용 (Shares 툴팁) | 지갑 연결 |
| Deposit: Approve | 금액 입력 → TX | 지갑 연결 + mUSDT 보유 |
| Deposit: Deposit | 금액 입력 + Max → TX | Approve 완료 |
| Withdraw: Withdraw | mUSDT 금액 입력 + Max → TX | Shares > 0 + Liquidity >= 금액 |

---

## L. 용어 설명 (유저가 궁금해할 수 있는 것)

| 용어 | 의미 |
|------|------|
| **mUSDT** | Mock USDT — 테스트넷 전용 스테이블코인. 실제 가치 없음. 메인넷에서는 진짜 USDT 사용 |
| **Shares** | 풀 지분 토큰. 예치 시 수령, 출금 시 반환. 풀 수익에 비례해 1 Share의 가치가 상승 |
| **Available Credit** | 현재 추가로 대출 가능한 금액 = Credit Limit - Outstanding Debt |
| **Outstanding Debt** | 현재 갚아야 할 총 채무 (원금 + 이자) |
| **Accrued Interest** | 대출 원금에 대해 시간에 따라 발생한 이자 (APR 8% 기준) |
| **Utilization Rate** | 풀 자산 중 대출로 나간 비율 = Total Borrowed / Total Assets |
| **APR** | 연간 이자율 (Annual Percentage Rate). 현재 8% 고정 |
| **SPV Proof** | Simplified Payment Verification — 비트코인 트랜잭션이 실제 블록에 포함되었음을 증명하는 방식 |
| **Trailing Window** | 크레딧 계산에 사용되는 최근 30일 기간. 이 기간 내 검증된 수익만 반영 |
| **BIP-137** | 비트코인 메시지 서명 표준. BTC 지갑 소유권 증명에 사용 |
| **HSK** | HashKey Chain의 가스 토큰. TX 수수료 지불에 필요 |
| **Checkpoint** | 신뢰할 수 있는 비트코인 블록 헤더 앵커. SPV 증명의 시작점 |

---

## M. 테스트넷 vs 메인넷 차이 (유저 관점)

| 항목 | 테스트넷 (현재) | 메인넷 (향후) |
|------|---------------|-------------|
| 크레딧 부여 | 등록 시 1,000 mUSDT 자동 | SPV 증명 기반 동적 계산 |
| 스테이블코인 | mUSDT (가치 없음) | USDT (실제 가치) |
| BTC 채굴 | 불필요 | 실제 채굴 수익 필요 |
| SPV Worker | 데모용 | 실시간 payout 자동 감지 |
| 가스 토큰 | HSK (테스트넷 Faucet) | HSK (실제 구매) |
| Borrower 캡 | 없음 (고정 1,000) | 신규 $10,000 → 이후 동적 |
| Pool 원천 | 테스트 유동성 | 실제 LP 예치 |
| 리스크 | 없음 (가치 없는 토큰) | 실제 자금 리스크 존재 |
