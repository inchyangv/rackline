# CEIP (Creditcoin Ecosystem Investment Program) 리서치

> 2026-03 v1(HashCredit) 2위 수상 직후 작성한 리서치를 2026-09-14 v2(Rackline, GPU 매출채권 금융, R2) 기준으로 갱신했다. 프로그램 사실은 원문 유지, 우리 제품 관련 항목(§3·§4·§6·§7)만 갱신. 상태 근거는 `docs/gpu/execution/ATTESTCOIN_GAP.md`.

## 1. 프로그램 개요

| 항목 | 내용 |
|---|---|
| 정식 명칭 | Creditcoin Ecosystem Investment Program (CEIP) |
| 운영 주체 | Credit Labs (Creditcoin 핵심 팀) |
| 총 펀드 규모 | $10M (1천만 달러) |
| 프로젝트당 투자 규모 | $25,000 ~ $250,000 |
| 투자 형태 | Equity 또는 Token 투자 (그랜트가 아닌 투자) |
| 신청 포탈 | https://creditcoin.org/CEIP/ |
| 런칭일 | 2025년 1월 27일 |
| 상태 | 상시 접수 (rolling basis) |

## 2. 우리의 포지션: Fast Track

BUIDL CTC 해커톤 **Top 3 수상팀**은 CEIP **Fast Track** 대상이다.

### Fast Track이 의미하는 것

- 일반 지원 절차(서류 심사 등)를 **건너뛰고** 바로 **Due Diligence 단계**로 진입
- 일반 지원자 대비 펀딩 접근 속도가 빠름
- Credit Labs 팀과의 직접 커뮤니케이션 채널 확보

### Fast Track에서 제공되는 것

1. **투자금**: $25K ~ $250K (프로젝트 성숙도/규모에 따라 결정)
2. **엔지니어링 & 프로덕트 자문**: Creditcoin 코어 팀의 기술 지원
3. **파트너 네트워크 접근**: 에코시스템 파트너, VC 연결
4. **후속 펀딩/그랜트 가능성**: 추가 자금 지원 경로
5. **퍼블릭 론칭 준비 지원**: 마켓 진입 전략 등

## 3. 투자 우선순위 (평가 기준 추정)

공식적으로 명시된 CEIP 투자 우선 영역:

1. **탈중앙 신용 & 결제 솔루션 강화** — Rackline(구 HashCredit)의 핵심 영역과 직접 부합
2. **금융 접근성 & 포용성 개선** — 94개국 롱테일 GPU 운영자 운전자금은 은행 서비스 사각지대
3. **Creditcoin 블록체인 인프라 활용한 실제 응용** — CTC EVM 대출 원장 + 공식 Attestcoin native 검증
4. **Web3 기술의 대중 채택 확대**

### 추정되는 평가 포인트

| 기준 | Rackline 해당 여부 |
|---|---|
| 라이브 또는 명확한 개발 로드맵 | △ — v1 테스트넷 배포(레거시) + v2 R2 실행 원장 83티켓·게이트(G-ASC/G1~G4). v2 컨트랙트·워커·UI는 2026-09-14 기준 미구현 |
| 크로스체인 호환성 / Creditcoin 활용 | O — CTC EVM 대출 원장, 공식 Attestcoin native 검증만 사용(자체 SPV/서명 fallback 없음); 공식 아티팩트 고정·테스트넷 probe 완료(GPU-075) |
| 실제 문제 해결 | O — DePIN GPU 운영자의 45~180일 정산 지연 운전자금 갭 |
| 투명한 자금 사용 | 제시 필요 (DECK §15: 엔지니어링 35 / 감사 20 / 법무·파트너 구조화 20 / first-loss reserve 15 / GTM 10) |
| 이머징 마켓 사용자 혜택 | O — 94개국 롱테일 GPU 운영자, 베스팅 토큰 정산 |
| 지속가능한 비즈니스 모델 | 제시 필요 (이자 스프레드·취급·서비싱 수수료, first-loss reserve; 최소 경제적 거래 규모는 GPU-007 검증 항목) |

## 4. Due Diligence 단계 — 예상 준비 사항

공식 Due Diligence 프로세스는 비공개이지만, 일반적인 에코시스템 투자 DD 기준으로 아래 준비가 필요할 것으로 예상:

### 4.1 팀 & 법적 구조

- 법인 설립 여부 (또는 설립 계획)
- 팀 구성원 이력 및 역할
- 투자 구조 (SAFE? Equity? Token?) 협상 준비

### 4.2 프로덕트 & 기술

- 테스트넷 데모: v1 완료(레거시); v2는 G-ASC(실제 공개 테스트넷 native 검증 E2E, GPU-080) 이후
- 스마트 컨트랙트 코드 리뷰 / 감사 계획 (GPU-058)
- 메인넷 배포 로드맵 (GPU-062/063, G4)
- 기술 아키텍처 문서 (`TECH.md`, `PIVOT.md`, `docs/gpu/decisions/attestcoin-first.md`)

### 4.3 비즈니스 & 시장

- TAM/SAM/SOM 분석 (DePIN GPU 운영자 정산 규모; DECK §9)
- 수익 모델 (이자 스프레드, 취급·서비싱 수수료; 고정 LP 수익률 없음)
- 경쟁사 분석
- GTM (Go-to-Market) 전략

### 4.4 리스크 관리

- 위협 모델 (v1 `docs/threat-model.md`는 레거시; v2는 GPU-058)
- 부실 채권 처리 방안 (E2 지급 통제, first-loss reserve, 회수 워크플로 GPU-041/044; 실물 담보는 E3 별도)
- 규제 리스크 대응

### 4.5 자금 사용 계획

- 투자금 사용처 세분화 (개발, 감사, 마케팅, 운영)
- 마일스톤별 집행 계획

## 5. Creditcoin 현재 상태 & 에코시스템

### 5.1 체인 기술 현황

| 항목 | 상태 |
|---|---|
| Creditcoin EVM 메인넷 | 2024년 8월 라이브 (Chain ID: 102030) |
| 블록 타임 | ~15초 (NPoS 전환 후) |
| USC (Universal Smart Contracts) | 테스트넷 v2 (2026년 1월 28일) |
| Creditcoin 3.0 | 멀티체인 RWA 인프라 준비 중 (2025~2026) |
| 토큰 통합 | ERC-20 G-CRE + 메인넷 CTC → 단일 토큰 진행 중 |
| Wormhole 연동 | CTC NTT (Native Token Transfer) only — CTC↔Ethereum/BSC |
| 스테이블코인 | **메인넷에 USDC/USDT 없음** — Wormhole은 CTC 전용, 스테이블코인 브릿지 미지원 |
| 오라클 | **Chainlink/Pyth 미지원** — CreditUSD가 Orakl Network 연동 시도 중이나 현황 불명 |
| 익스플로러 | Blockscout (creditcoin.blockscout.com), Subscan (creditcoin.subscan.io) |

### 5.2 에코시스템 프로젝트

| 프로젝트 | 설명 | 상태 |
|---|---|---|
| Penguinswap | 네이티브 DEX | 메인넷 라이브 |
| Penguinbase | 커뮤니티 플랫폼 (에어드랍, 게임) | 라이브 (2025년 8월~) |
| CreditX | Universal Reputation Lending — 온체인 평판 기반 무담보 대출 | 해커톤 프로젝트, 개발 중 |
| CreditUSD (crdUSD) | CDP 스테이블코인 — wCTC 담보로 crdUSD 발행 (Liquity 스타일) | MVP 완료, 메인넷 Q4 2026 |
| Credefi | EU SME 렌딩 — NFT Bond, 파생상품 | Creditcoin 전략 파트너십 (2024년 7월~) |
| Spacecoin | 위성 인터넷 DePIN | 에코시스템 파트너 |
| Mini_CTO | AI 기반 IP | 에코시스템 파트너 |
| Aella | 핀테크 렌더 (아프리카) | Creditcoin 원년 파트너 |

### 5.3 핵심 파트너십

- **Plume Network**: RWA 전략 파트너십 (L2 모듈러 체인)
- **SubWallet**: 인프라 & UX 개선
- **Google Cloud**: 서울 아이디어톤 공동 주최
- **Wormhole**: 멀티체인 유틸리티 (CTC 크로스체인 전송)

### 5.4 시장 포지셔닝

- **초점**: 이머징 마켓 금융 포용성 (vs Ondo의 기관 RWA 초점)
- **실적**: 427만 실제 신용 거래, $79.7M 거래량, 33.7만+ 사용자
- **TVL**: 약 $257M (DeFi 렌딩 기준)

## 6. Rackline과 CEIP의 전략적 적합성

### 완벽히 부합하는 점

1. **"탈중앙 신용" 그 자체** — Rackline은 Creditcoin이 추구하는 "온체인 신용 인프라"의 가장 직접적인 구현(검증된 정산·인출·수령 = 신용 기록)
2. **공식 Attestcoin 필수 사용** — 외부 체인 정산 이벤트를 공식 native 검증(0x0FD2 + EvmV1Decoder)으로만 인정. v1의 자체 SPV를 버리고 체인 고유 기능을 제품의 유일한 증거 경로로 채택
3. **실제 사용자 & 실제 수익** — 추상적인 DeFi가 아닌, DePIN GPU 운영자의 실제 운전자금 갭(45~180일 정산 지연) 해결
4. **이머징 마켓 접점** — 94개국 롱테일 GPU 운영자; Creditcoin의 금융 포용성 비전과 연결

### 보완이 필요한 점

1. **법인 구조** — Due Diligence에 필수
2. **자금 사용 계획서** — 구체적 마일스톤별 예산
3. **v2 구현 실적** — 2026-09-14 기준 v2 컨트랙트·워커·UI 미구현, native proof 미제출. G-ASC(GPU-080)와 G1(첫 파트너·상품·자금 조건)이 DD 전 최소 증거
4. **파트너 E2 실증** — Aethir/GPU.net 중 한 곳의 실제 지급 통제 시험(GPU-009); 파트너십은 주장하지 않음
5. **감사 계획** — 스마트 컨트랙트 보안 감사 일정/예산 (GPU-058)
6. **CTC 체인의 스테이블코인·정산 레일** — 대출 통화 issuer 지원·실제 contract·유동성(R2-O06), source escrow→환전→destination 수령 레일(R2-O05) 확인 필요

## 7. 타임라인 추정

```
2026-03 중순  Demo Day (서울) — v1 2위, CEIP Fast Track 대화 시작; BTC 마이닝 풀 협업 불가로 v1 상품화 보류
2026-09       GPU 매출채권 금융으로 피벗 결정(R2), BUIDL CTC 2026 Fall
2026-Q4       G-ASC(공개 테스트넷 native 검증) + 첫 파트너 실사·E2 통제 시험 → G1
2026-Q4~27-Q1 금융 코어(G2), 단일 파트너 E2E(G3) → CEIP DD 자료 완성
2027-Q2       감사·메인넷·제한 파일럿(G4) — 자금 집행 목표
```
원래 추정(2026-04~06 DD·체결)은 v1 기준이었고 실행되지 않았다. 위 일정은 파트너 응답·감사에 따라 달라지는 계획 범위다.

## Sources

- [CEIP 공식 블로그](https://creditcoin.org/blog/unlocking-innovation-launching-the-creditcoin-ecosystem-investment-program/)
- [CEIP 포탈](https://creditcoin.org/CEIP/)
- [BUIDL CTC 해커톤](https://creditcoin.org/blog/buidl-ctc-hackathon/)
- [Chainwire 런칭 기사](https://chainwire.org/2025/01/27/creditcoin-launches-10m-ecosystem-investment-program-to-accelerate-web3-innovation/)
- [Creditcoin DeFi 렌딩 베이스 레이어](https://creditcoin.org/blog/creditcoin-defi-lending-base-layer/)
- [USC 문서](https://docs.creditcoin.org/usc)
- [Creditcoin 로드맵](https://creditcoin.org/blog/creditcoin-roadmap/)
- [Plume 파트너십](https://creditcoin.org/blog/creditcoinxplume/)
- [Penguinswap 메인넷](https://creditcoin.org/blog/penguinswap-mainnet/)
- [EVM 호환성 문서](https://docs.creditcoin.org/evm-compatibility)
