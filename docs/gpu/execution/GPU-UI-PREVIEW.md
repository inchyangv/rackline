# GPU UI preview — frontend-first checkpoint

작성: 2026-09-14 · 실행: Codex + 병렬 UI/거래/QA 작업자 · 기준: `f01b2f8`, 검증 중 backend HEAD `4ed5362`

사용자 최신 지시: backend 완성을 기다리지 않고 화면에 보이는 기능과 디자인을 먼저 완성한다. Morpho를 시각 참고로 사용하고 병렬 실행한다. **이 기록은 GPU-047~052/066의 LOCAL 화면 체크포인트이지, 해당 부모 티켓 전체의 DONE이나 출시 승인이 아니다.** 기존 TICKET 상태는 동시 backend 실행자가 관리하므로 부모 완료로 올리지 않는다.

## 범위와 증거 수준

- 증거 수준: LOCAL, browser-only fixtures.
- `executionProfile=LOCAL_MOCK`, `verificationMethod=LOCAL_MOCK`, 실제 `nativeStatus=NOT_SUBMITTED`.
- GPU 매출 출처·미지급 잔액·E2·심사·destination cash 모두 synthetic scenario. 실제 partner authentication/source binding/native verification 없음.
- CTC = 의도된 Creditcoin 네트워크 가스, Attestcoin = 의도된 공식 검증 경로, 화면의 USDC = **데모 표시 단위**. USDC production 채택이나 실제 토큰 주소를 확정하지 않았다.
- 화면에서 보이는 sample approval/E2/checks는 실환경 증거로 승격할 수 없다. 실지갑 요청, API/RPC 요청, 서명, broadcast 없음.
- R2-D01~08, D10, D12~14 적용. GPU-045/046/079~082 및 파트너/출시 gate를 우회하지 않는다.

## 구현한 화면

| 티켓 연결 | LOCAL 구현 | 실제 연결 시 남은 일 |
| --- | --- | --- |
| GPU-047 | Overview/Earn/Borrow/Providers/Activity/Operations 해시 탐색, 모바일 메뉴, 독립 demo wallet/state, 명시적 demo 안내 | manifest 기반 profile·chain guard, 실제 wallet/account 전환, read model invalidation |
| GPU-048 | Aethir/GPU.net sample 카드, 연결 wizard/동의, 권리/E2/심사/native 상태 분리, 채권 필터·검색·상세 timeline | 실제 provider 인증, 권리·약정/심사 입력, native source와 capability 확인 |
| GPU-049 | 한도·원금·미납이자·만기·차입/상환, MAX/금액 경계/검토/성공, proof/control 장애 시 draw 차단·repay 유지 | 생성 ABI/DTO, quote expiry, reservation, 승인/전송/pending/reorg/revert와 canonical 실제 원장 |
| GPU-050 | 예치/출금, NAV/cash/deployed 분리, sample APY/APR 구분, 출금 queue/cancel/settle/claim, 위험/수수료 설명 | 실제 shares/decimals/slippage/fees, impairment·epoch·partial settlement·realized yield 원장 |
| GPU-051 | exception 필터·검색·상세, 사유 필수 배정/ack/retry, 증거와 cash trace 분리 | 서버 RBAC, 실제 업무 version/idempotency/audit, 운영 데이터·runbook·실제 retry |
| GPU-052 | 상태 unit tests, desktop/mobile browser E2E, 외부 HTTP/RPC·실지갑 호출 방지 검사 | 실제 API/Anvil wallet/chain/profile 통합 E2E, 완전한 접근성 감사 |
| GPU-066 | Rackline blue/light visual system, GPU rack CSS illustration, typography/card/chart/header/footer, SVG favicon | backend 연결 후 카피·배포 자원 전수 정합화, 실제 공개 배포 |

Morpho의 절제된 내비게이션·큰 헤드라인·블루 포인트·여백 중심 구성을 참고했다. 로고·문구·이미지는 복사하지 않았다. 참고: https://morpho.org/ .

## 파일 소유권 / backend 작업자 인수인계

- 진입: `apps/web/src/App.tsx` → `features/preview/preview-app.tsx`.
- 디자인: `features/preview/preview.css`, `provider-pages.css`, `transaction-dialog.css`.
- 로컬 상태/거래: `features/preview/demo-store.ts`, `transaction-dialog.tsx`.
- 공급자/운영: `provider-page.tsx`, `operations-page.tsx`.
- 검증: `apps/web/tests/demo-store.test.mjs`, `preview.spec.ts`, `playwright.config.ts`, web package/lock.
- 메타: `apps/web/index.html`, `public/favicon.svg`, `public/site.webmanifest`.
- 기존 `AppShell`, BTC/testnet hooks/stores/ABI/설정 및 기존 배포·잔액은 보존했다. 현재 진입에서 해당 컴포넌트를 mount하지 않는다. backend/contracts/keys/기존 미추적 문서는 편집하지 않았다.
- 실제 GPU API가 완성되더라도 이 demo store를 production store로 재사용하거나 fixture를 자동 fallback으로 삼지 않는다. 명시적인 production profile + 생성 타입/manifest 기반 별도 data adapter를 연결하고, current preview는 격리된 demo route/profile로 유지한다.
- 금액은 데모에서 소수점 2자리 정수 cents로 계산한다. production token decimals/minShares/minAssets 구현이 아니다.

## 상태와 데모 재현

`rackline:gpu:preview:v1`만 localStorage에 저장한다. 레거시 storage는 읽거나 삭제하지 않는다. 금액·잔액·거래·대기열·facility scenario는 새로고침 후 유지된다. 공급자 신규 연결과 운영 case triage는 현재 탭 수명 동안만 유지되고, 화면 탭 이동에는 보존된다. Reset demo는 확인 후 데모 상태와 session panels만 초기화한다.

1. `npm --prefix apps/web run dev -- --host 127.0.0.1 --port 4173 --strictPort` → http://127.0.0.1:4173/ .
2. Connect demo wallet → Earn → Supply → 금액 → Review → Confirm → Done. 잔액/NAV/cash/Activity에 반영된다.
3. Borrow → Borrow/Repay. 상환은 미납이자 먼저, 이후 원금에 배분한다. MAX는 실제 demo headroom/wallet/cash를 반영한다.
4. Borrow의 Native proof pending 또는 Payment control expired를 선택한다. 신규 차입은 막히고 기존 채무는 유지되며 직접 상환은 가능하다.
5. Earn → Try limited liquidity: vault cash를 synthetic 다른 차주 대출로 재배치하여 5,000으로 만든다. NAV/본인 wallet/debt를 바꾸지 않는다. Withdraw 6,000 → queue → Borrow에서 Repay 1,000 또는 Earn에서 Supply 1,000 → Earn에서 Simulate settlement → Claim demo funds. 부족한 cash로 settlement 성공이나 중복 claim을 허용하지 않는다.
6. Providers → Connect provider → sample account/동의/review/add. 신규 connection은 pending이고 credit limit을 늘리지 않는다. receivable 상세는 source/native/economic/cash/allocation을 분리한다.
7. Operations → 사유 입력 → Assign/Acknowledge/Simulate retry. Retry는 Requested → Awaiting proof까지만 가고 VERIFIED나 repayment로 바뀌지 않는다.
8. Activity → 유형 필터/CSV export. CSV와 거래 기록은 LOCAL_MOCK, fake transaction hash나 explorer receipt 없음.

## 검증

실행 위치: repository root. 실제 partner/native/mainnet 검증과 독립이다.

- `npm --prefix apps/web run test:unit`: exit 0, **24 passed / 0 skipped**. cent precision, full/partial repay, proof/control freeze, queue reservation/FIFO/settlement/claim/cancel, storage 복구, liquidity fixture.
- `npm --prefix apps/web run lint`: exit 0.
- `npm --prefix apps/web run build`: exit 0, TypeScript + Vite production bundle.
- `git diff --check`: exit 0.
- `npm --prefix apps/web run test:e2e`: 최종 결과는 아래 browser checkpoint에 기록한다.
- 로컬 Chrome 152.0.7977.83, desktop 1440px / mobile 390px, 포트 4173. 모든 E2E에 external HTTP/API/RPC와 injected wallet.request 호출 및 uncaught browser error를 거부하는 검사 포함.
- Browser 설치: macOS 로컬 Chrome 자동 사용. 다른 환경은 `npm --prefix apps/web exec -- playwright install chromium`; 또는 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`로 기존 Chrome 지정.
- 최종 스크린샷/실패 trace: ignored `apps/web/node_modules/.cache/playwright/test-results/`. 참고 디자인/초기 시각 점검은 `/tmp/rackline-*.png`에 로컬 저장.

### Browser checkpoint

`npm --prefix apps/web run test:e2e`: **exit 0, 12 passed / 0 skipped**, desktop/mobile 각 6개. 탐색/실제 viewport 기준 overflow, 네 종류 거래·새로고침, 금액 오류, provider 동의 wizard, proof/control 장애 중 상환, 출금 대기→부족한 cash 거절→repay→settlement→일회성 claim을 검증했다. 모든 테스트에서 실제 지갑/API/RPC 호출·uncaught browser error 0건.

모바일 provider dialog 클릭을 막던 table 접근성 label의 viewport 확장(390→602px)을 발견·수정하고 회귀 통과했다. 운영 화면의 사유 없는 조작 거부, 배정, Requested→Awaiting proof, acknowledge/filter는 별도 실제 브라우저 walkthrough로 확인했다. Overview/Earn/Borrow/Providers/Operations desktop/mobile 시각 확인 완료. GPU-052의 실API/지갑 통합 및 완전한 접근성 감사까지 DONE으로 해석하지 않는다.

## 미실행 / 다음 작업

공개 배포, 실제 지갑 연동, Creditcoin/Attestcoin/파트너 API 호출, 실제 source proof, 실제 수령/상환 검증, 권리/E2 실증, 출시 승인은 이 작업에서 실행하지 않았다. backend의 GPU-045/046 및 금융 연결 산출물이 준비되면 preview 디자인을 유지하면서 실제 adapter와 오류/권한/전송 상태를 연결한다. 브라우저-only 데모를 실대출 시스템 완료라고 기록하지 않는다.
