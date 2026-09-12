# UX Improvement TODO

시니어 프로덕트 디자이너 관점에서 평가한 직관성/이해도 개선 사항.
우선순위: P0(심각) > P1(중요) > P2(개선) > P3(나이스투해브)

---

## 1. 정보 구조 & 중복 제거

### P0 — Borrower Address 입력이 3곳에 중복
- **현재:** Chrome panel 검색바, BorrowerCard 내 Wallet Address 인풋, ClaimSection이 같은 store 값 공유
- **문제:** 어디에 입력해야 하는지 혼란. 같은 값인데 3군데서 보임
- **개선:** Chrome panel의 borrower search strip 제거. BorrowerCard의 인풋은 지갑 연결 시 자동 세팅 + 필요할 때만 수정 가능하게 축소

### P0 — TX Status가 2곳에 중복
- **현재:** Metrics bar의 "Status" 카드 + 페이지 하단 "Transaction Status" 섹션이 동일 정보 표시
- **문제:** 시선이 분산되고 두 곳의 관계가 불명확
- **개선:** 하단 TX Status 섹션을 제거하고 Metrics bar의 Status만 유지. 클릭 시 상세 내용 확장되는 형태로

### P1 — Metrics bar가 탭과 무관한 정보 표시
- **현재:** Available Credit, Balance는 Dashboard 전용 지표인데 Pool 탭에서도 보임
- **문제:** Pool 탭에서는 의미 없는 숫자가 항상 상단 차지
- **개선:** 탭별로 Metrics bar 내용 분리 — Dashboard: Credit/Balance/Debt, Pool: My Shares/Pool TVL/APR

### P1 — "Network" 메트릭 카드가 정적 텍스트
- **현재:** "HashKey Chain Testnet"이 MetricCard로 표시
- **문제:** 변하지 않는 값이 동적 지표와 같은 무게로 표시됨
- **개선:** 네트워크 정보는 Wallet Panel 영역에 배지로 통합. 메트릭 슬롯을 유용한 지표로 교체

---

## 2. 온보딩 & 첫 사용자 경험

### P0 — 신규 사용자에게 시작 지점이 없음
- **현재:** 첫 접속 시 "My Credit"(대시 투성이)과 "Link BTC Wallet"이 동일 가중치로 2컬럼에 나열
- **문제:** 뭘 먼저 해야 하는지 모름. 모든 값이 "—"인 상태에서 행동 유도 없음
- **개선안:**
  1. BTC 미연결 시 BorrowerCard를 축소하고 "BTC 지갑을 연결하세요" CTA 카드로 대체
  2. 또는 BorrowerCard 상단에 프로그레스 바 (Step 1: 지갑 연결 → Step 2: BTC 연동 → Step 3: 대출) 표시
  3. 이미 연동 완료 시에만 전체 크레딧 정보 표시

### P1 — BTC 연동 3단계 프로세스가 한 번에 다 보여서 위압감
- **현재:** Step 1, 2, 3이 모두 펼쳐진 채로 긴 폼 형태
- **문제:** 처음 보는 사용자는 "이걸 다 해야 해?" 느낌. 특히 서명 생성 안내가 복잡
- **개선:** 스텝별 아코디언/위자드 UI — 이전 단계 완료 후 다음 단계 활성화. 현재 단계만 확장, 나머지는 접힘

### P2 — Approve → Action 2단계가 설명 없이 분리
- **현재:** Borrow 하려면 Approve를 먼저 해야 하는데, 두 인풋/버튼이 별개로 나열
- **문제:** DeFi 초보는 왜 Approve가 필요한지, 어떤 순서인지 모름
- **개선:** Borrow 버튼 클릭 시 allowance 부족하면 자동으로 Approve 플로우 진행. 또는 "Step 1: Approve → Step 2: Borrow" 인라인 안내

---

## 3. Dashboard 탭 — "My Credit" 카드

### P1 — 읽기 전용 상태와 액션 폼이 한 카드에 혼재
- **현재:** 6개 KV 행 + Borrow 폼 + Approve 폼 + Repay 폼이 한 SectionCard
- **문제:** 스크롤이 길고, 정보 확인과 행동 수행의 경계가 불분명
- **개선:** 상단을 "Credit Overview" 읽기 전용 카드로 분리, 하단을 "Actions" 카드로 분리. Actions 내에서 Borrow/Repay를 탭 전환

### P1 — "Total Repayment" 라벨이 모호
- **현재:** 코드에서는 `currentDebt`인데 라벨이 "Total Repayment"
- **문제:** "총 상환금"인지 "현재 채무"인지 불분명
- **개선:** "Outstanding Debt" 또는 "현재 채무"로 변경

### P2 — Borrow 인풋에 Max 버튼 없음
- **현재:** Withdraw에는 Max 있는데 Borrow에는 없음
- **문제:** 가용 크레딧 전액 대출하려면 숫자를 직접 복사해야 함
- **개선:** Available Credit 기준 Max 버튼 추가

### P2 — Repay 인풋 근처에 현재 채무 표시 없음
- **현재:** 얼마를 갚아야 하는지 위로 스크롤해서 확인해야 함
- **개선:** Repay 라벨 옆에 "Current debt: X mUSDT" 인라인 표시 + Max 버튼

---

## 4. Pool 탭

### P1 — 4개 카드가 개념적으로 너무 잘게 나뉨
- **현재:** Pool Status / My Position / Deposit / Withdraw가 각각 별도 카드
- **문제:** My Position은 2줄짜리인데 별도 카드를 차지. 시선 분산
- **개선:**
  - Pool Status + My Position 합치기 (같은 카드, 섹션 구분)
  - Deposit/Withdraw를 탭 전환 1개 카드로 통합 (Uniswap, Aave 등 대부분의 DeFi가 이 패턴)

### P1 — Withdraw 인풋이 "Shares" 단위
- **현재:** 사용자가 Shares 숫자를 입력하고 "Expected mUSDT"를 확인
- **문제:** 일반 사용자는 mUSDT로 생각하지 Shares 단위로 생각하지 않음
- **개선:** mUSDT 기준 입력 → 필요한 shares 자동 계산 + "X shares will be redeemed" 보조 표시. 기존 shares 입력도 토글로 유지

### P2 — "Shares"가 무엇인지 설명 없음
- **현재:** My Shares: 500.000000 — 이게 뭔지 모르는 사용자 다수
- **개선:** "Shares" 라벨에 info 아이콘 + 툴팁: "풀 지분을 나타내는 토큰. 풀 수익에 비례해 가치 상승"

---

## 5. Wallet Panel

### P1 — Chain ID가 숫자로만 표시
- **현재:** "Chain: 133"
- **문제:** 133이 뭔지 아는 사용자 거의 없음
- **개선:** "HashKey Testnet" 텍스트 + 연결 상태 dot(초록/빨강). 숫자는 hover 시 표시

### P1 — "Chain 133" 버튼 라벨이 의미 불명
- **현재:** 버튼에 "Chain 133"이라고만 표시
- **문제:** 이 버튼이 네트워크 전환인지 체인 정보인지 모름
- **개선:** "Switch to HashKey Testnet" 또는 아이콘 + "Switch Network"

### P2 — 지갑 미연결 시 빈 상태 처리 미흡
- **현재:** "Disconnected"라는 텍스트만 표시
- **개선:** "MetaMask를 연결해서 시작하세요" 같은 안내 문구 + Connect 버튼 강조

---

## 6. 시각 디자인 & 인터랙션

### P1 — KeyValueRow마다 개별 border/background → 과도한 시각적 노이즈
- **현재:** 각 행이 `rounded-xl border bg-gradient` 처리된 개별 박스
- **문제:** 카드 안에 카드 안에 행별 카드 — 3중 중첩으로 시각적으로 무겁고 데이터 스캔이 어려움
- **개선:** KV 행은 단순 행(구분선/스트라이프)으로, 컨테이너 카드만 테두리 유지. 정보 밀도는 높이되 시각적 잡음은 줄이기

### P2 — 주요 액션과 보조 액션의 시각적 구분 부족
- **현재:** Borrow, Repay, Approve, Deposit, Withdraw 버튼이 비슷한 크기/스타일
- **문제:** 핵심 행동(Borrow, Deposit)과 보조 행동(Approve)이 같은 무게
- **개선:** 핵심 CTA는 크고 bold하게, Approve는 inline link 스타일 또는 자동화

### P2 — 라벨 10px이 가독성 한계
- **현재:** `text-[10px] uppercase tracking-widest`가 여러 곳에 사용
- **문제:** 10px + 대문자 + 넓은 자간은 세련돼 보이나 실제 읽기 어려움
- **개선:** 최소 11px(0.6875rem) 이상으로 상향, 또는 대문자 제거하고 12px semibold로 변경

### P3 — 카드 hover시 -translate-y-0.5 효과가 정보 UI에 불필요
- **현재:** SectionCard에 hover 시 살짝 떠오르는 효과
- **문제:** 클릭 가능한 카드가 아닌데 hover 효과가 있으면 오인 유발
- **개선:** 정보 표시 카드에서 hover 이동 효과 제거

---

## 7. 컨텍스트 & 설명

### P2 — "mUSDT"가 무엇인지 어디에도 설명 없음
- **문제:** mock USDT? milli USDT? 첫 방문자는 모름
- **개선:** 첫 등장 시 툴팁 또는 footer에 "mUSDT = Mock USDT (testnet stablecoin)" 안내

### P2 — 금액 인풋에 단위 표시 없음
- **현재:** placeholder "e.g. 1000"만 있고 단위 없음
- **개선:** 인풋 우측에 "mUSDT" suffix 표시 (InputGroup 패턴)

### P3 — 트랜잭션 확인 다이얼로그 없음
- **현재:** Borrow/Repay/Deposit 버튼 클릭 즉시 서명 요청
- **개선:** 금액과 예상 결과를 보여주는 확인 모달 추가 (실수 방지)

---

## 8. 요약 — 우선순위별 Quick Wins

| 우선순위 | 항목 | 예상 효과 |
|---------|------|----------|
| P0 | Borrower address 중복 입력 제거 | 혼란 제거 |
| P0 | TX Status 중복 제거 | 시각적 정리 |
| P0 | 신규 사용자 온보딩 CTA 추가 | 이탈률 감소 |
| P1 | BTC 연동 위자드/아코디언 UI | 위압감 해소 |
| P1 | Metrics bar 탭별 분리 | 맥락에 맞는 정보 |
| P1 | BorrowerCard 읽기/액션 분리 | 인지 부하 감소 |
| P1 | Pool Deposit/Withdraw 탭 통합 | 공간 효율 + 표준 DeFi 패턴 |
| P1 | Withdraw를 mUSDT 기준 입력으로 | 직관성 향상 |
| P1 | Chain 표시 개선 | 네트워크 혼란 방지 |
| P1 | KV Row 시각적 노이즈 줄이기 | 데이터 스캔 용이 |
| P2 | Approve 자동화/통합 | 스텝 수 감소 |
| P2 | Max 버튼 추가 (Borrow/Repay) | 편의성 |
| P2 | 라벨 가독성 개선 | 접근성 |
| P2 | mUSDT/Shares 용어 설명 | 이해도 |
