# CEIP (Creditcoin Ecosystem Investment Program) 리서치

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

1. **탈중앙 신용 & 결제 솔루션 강화** — HashCredit의 핵심 영역과 직접 부합
2. **금융 접근성 & 포용성 개선** — 마이너 대출은 은행 서비스 사각지대 해소
3. **Creditcoin 블록체인 인프라 활용한 실제 응용** — CTC EVM 위에 풀스택 배포
4. **Web3 기술의 대중 채택 확대**

### 추정되는 평가 포인트

| 기준 | HashCredit 해당 여부 |
|---|---|
| 라이브 또는 명확한 개발 로드맵 | O — 테스트넷 배포 완료, 풀스택 작동 |
| 크로스체인 호환성 / Creditcoin 활용 | O — CTC EVM 네이티브, BTC SPV 크로스체인 |
| 실제 문제 해결 | O — 마이너 운영자금 유동성 문제 |
| 투명한 자금 사용 | 제시 필요 |
| 이머징 마켓 사용자 혜택 | O — 무담보 신용 대출, 언뱅크드 마이너 |
| 지속가능한 비즈니스 모델 | 제시 필요 (수수료 구조, Coverage Pool 등) |

## 4. Due Diligence 단계 — 예상 준비 사항

공식 Due Diligence 프로세스는 비공개이지만, 일반적인 에코시스템 투자 DD 기준으로 아래 준비가 필요할 것으로 예상:

### 4.1 팀 & 법적 구조

- 법인 설립 여부 (또는 설립 계획)
- 팀 구성원 이력 및 역할
- 투자 구조 (SAFE? Equity? Token?) 협상 준비

### 4.2 프로덕트 & 기술

- 테스트넷 데모 (이미 완료)
- 스마트 컨트랙트 코드 리뷰 / 감사 계획
- 메인넷 배포 로드맵
- 기술 아키텍처 문서 (PROJECT.md 기반)

### 4.3 비즈니스 & 시장

- TAM/SAM/SOM 분석 (BTC 마이닝 시장 규모)
- 수익 모델 (이자 수수료, LP 수수료 등)
- 경쟁사 분석
- GTM (Go-to-Market) 전략

### 4.4 리스크 관리

- 위협 모델 (threat-model.md 기반)
- 부실 채권 처리 방안 (Coverage Pool, Reserve)
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

## 6. HashCredit과 CEIP의 전략적 적합성

### 완벽히 부합하는 점

1. **"탈중앙 신용" 그 자체** — HashCredit은 Creditcoin이 추구하는 "온체인 신용 인프라"의 가장 직접적인 구현
2. **BTC ↔ CTC 크로스체인** — SPV 검증으로 비트코인 데이터를 CTC EVM에 직접 가져옴 → USC 비전과 방향 일치
3. **실제 사용자 & 실제 수익** — 추상적인 DeFi가 아닌, 실제 마이너의 실제 운영자금 문제 해결
4. **이머징 마켓 접점** — Creditcoin의 아프리카/동남아 금융 포용성 비전과 연결 가능

### 보완이 필요한 점

1. **법인 구조** — Due Diligence에 필수
2. **자금 사용 계획서** — 구체적 마일스톤별 예산
3. **메인넷 배포 계획** — 테스트넷 → 메인넷 전환 타임라인
4. **감사 계획** — 스마트 컨트랙트 보안 감사 일정/예산
5. **CTC 체인의 스테이블코인 가용성** — 메인넷에서 USDC/USDT 지원 여부 확인 필요

## 7. 타임라인 추정

```
2026-03 중순  Demo Day (서울) — 완료 (수상)
2026-03 하순  CEIP Fast Track 진입 통보
2026-04~05    Due Diligence 진행
2026-05~06    투자 조건 협상 & 체결
2026-06~      자금 집행 & 메인넷 로드맵 실행
```

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
