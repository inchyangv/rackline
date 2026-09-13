# GPU Lending 전환 티켓 — 공식 Attestcoin 필수 / Claude Code 실행 명세

기준일: 2026-09-14 · 개정: R2 / Attestcoin-first · 입력: [PIVOT.md](PIVOT.md) + 사용자의 공식 Attestcoin 필수 요구 · 기준 코드: `c1f839a` + 현재 작업 트리 · 티켓: 83개(GPU-000~082)

이 문서는 GPU 렌딩 피벗의 전체 작업을 구현·실사·검증·출시 티켓으로 분해한다. **티켓 작성은 완료되었지만 아래 티켓의 구현/외부 검증이 완료된 것은 아니다.** 기존 `docs/process/TICKET.md`는 BTC/SPV 과거 작업 기록이며 GPU 진행 상태의 근거로 사용하지 않는다.

R2의 확정 변경은 **Creditcoin의 공식 Attestcoin Readability를 외부 체인 증거 검증의 필수 경로로 사용하는 것**이다. 자체 EIP-712 oracle·BTC SPV로 대체하거나 낮은 advance rate를 이유로 미지원 체인을 자동 활성화하지 않는다. 기존 GPU-000~073 ID와 금융·권리·레거시 요구는 보존하고 공식 통합 전용 GPU-074~082를 추가했다. 새 ID가 뒤라고 실행을 뒤로 미루지 않는다.

문서 충돌 시 적용되는 저장소 지침과 사용자의 최신 요구를 먼저 준수하고, 본 문서 §0.9의 R2 실행 결정 → PIVOT의 나머지 제품/금융 조건 → 승인된 상세 ADR 순서로 해석한다. PIVOT §10의 선택적 자체 서명/다른 execution chain 안, TECH의 자동 attested fallback, NFT·trailing payout 중심 해커톤 데모는 R2 production 결정을 대신하지 않는다. 새로운 상품 변경이 필요하면 OPEN 결정으로 올리고 임의 채택하지 않는다. 이번 R2 편집 범위는 TICKET.md뿐이며 관련 문서의 실제 정합화는 GPU-074/065가 담당한다.

실행 대상은 사용자가 지정한 Claude Code / Opus 5.1이다. 특정 모델의 성능·지원 여부·CLI model ID·컨텍스트 크기를 가정하지 않는다. 실제 설치 환경에서 지원되는 모델 선택 방법을 사용한다. 실행 품질은 작은 작업 범위, 명시적 선행 산출물, 구체적 실패 사례, 재현 가능한 검증과 인수인계로 확보한다. 이는 Claude Code 공식 지침의 검증 기준·파일 맥락·짧은 프로젝트 지침·세션 관리 원칙을 적용한 구성이다. [Claude Code best practices](https://code.claude.com/docs/en/best-practices), [프로젝트 메모리](https://code.claude.com/docs/en/memory)

## 0. 후속 에이전트 실행 계약

### 0.1 읽는 순서와 범위

1. 적용되는 `AGENTS.md`/`CLAUDE.md` 및 `AGENT.md`, 이 절, 선택 티켓을 읽는다.
2. 해당 티켓의 PIVOT 참조 절과 선행 티켓의 실제 산출물·결정 기록을 읽는다. 이름만 보고 선행 완료를 추정하지 않는다.
3. `git status --short`로 기존 변경을 확인하고 대상 파일의 현재 코드를 읽는다. 문서의 줄 번호는 검색 단서이며 이후 변경에 맞춰 재확인한다.
4. 한 번에 한 티켓을 완료하는 것을 기본으로 한다. 큰 티켓은 하위 ID(`GPU-033.a`)와 체크포인트로 나눌 수 있으나 부모의 완료 기준을 줄이지 않는다.
5. 구현 → 해당 테스트 → 영향 범위 검토 → 필요한 통합 검사 → 티켓 결과 기록 순서로 진행한다. 정책 변경·금융 가정 변경은 코드 안에 숨기지 않는다.

이 문서 전체를 매 세션의 `CLAUDE.md`에 복제하지 않는다. GPU-000에서 짧은 진입 지침을 만들고 선택 티켓·관련 코드·선행 결과만 가져온다. 세션을 재개할 때 채팅 기억보다 저장된 실행 기록과 실제 diff를 우선한다.

### 0.2 상태·유형·완료의 의미

상태의 원장은 각 티켓의 `상태` 필드다. 색인/로드맵은 상태 원장이 아니다.

| 상태 | 의미 |
| --- | --- |
| READY | 선행과 로컬 입력이 충족되어 시작 가능 |
| TODO | 아직 시작하지 않았거나 선행 티켓 대기 |
| IN_PROGRESS | 담당 실행자가 작업 중 |
| IN_REVIEW | 구현·검증 결과를 작성했고 독립 확인 중 |
| BLOCKED_EXTERNAL | 파트너 자료/권한/실제 지급/사업 결정이 필요; 준비한 산출물과 필요한 입력을 기록 |
| DONE | 이 티켓의 모든 완료 조건과 요구되는 증거 수준 충족 |
| DEFERRED | 첫 파일럿 이후 확장 또는 아직 채택하지 않은 선택 경로 |

유형: `SPEC` 설계/결정 자료, `CODE` 로컬 구현, `DD` 파트너·사업·계약 실사, `LIVE` 승인된 환경에서 실제 통합 검증, `RELEASE` 외부 배포/자금/운영 전환. P0는 실자금 전 필수, P1은 파일럿 운영 전 필수, P2는 확장이다. 우선순위가 선행 관계를 무시하지는 않는다.

증거 수준을 `LOCAL`(fixture/mock), `SANDBOX`(파트너 승인 환경), `NATIVE_TESTNET`(공개 testnet의 실제 source 거래와 공식 native 검증), `LIVE`(확인된 실제 파트너 계정·거래), `ACCEPTED`(책임 있는 사업/신용/법률 결정)로 기록한다. 이는 단일 승급 척도가 아니다. 공식 testnet proof 성공은 파트너 지급/E2/사업 승인의 증거가 아니다. LOCAL 통과를 NATIVE_TESTNET/LIVE/ACCEPTED로 승격하지 않는다.

증거 수준과 별개로 `executionProfile=LOCAL_MOCK|NATIVE_TESTNET|PRODUCTION`, `verificationMethod=ATTESTCOIN_NATIVE|LOCAL_MOCK|OFFCHAIN_ASSERTION`, `nativeStatus`, `earningsProvenance`, `controlGrade`, `cashState`를 각각 기록한다. enum 세부 값은 GPU-011/076에서 고정한다. OFFCHAIN_ASSERTION은 보조 사실/승인 유형이지 production native proof의 fallback이 아니다. `PRODUCTION` 설정 자체는 실제 출시 승인이나 LIVE 통과를 뜻하지 않는다.

본 문서에서 native profile의 **mock 금지**는 대체 verifier/precompile·mock RPC·강제 VERIFIED 설정을 뜻한다. NATIVE_TESTNET에서는 실제 공개 체인에 배포한 TEST_ONLY MockDePIN source/test token으로 진짜 native 검증을 시험할 수 있으며 `partnerRevenue=SIMULATED`를 표시한다. 이는 production 적격 provider/token이 아니고 mock partner E2를 실제 권리로 인정하지도 않는다.

실사/실증의 판정 자체가 산출물인 GPU-004/005/006/009/010은 확인된 거절·불가 판정도 `DONE + outcome=NO_GO`로 종료할 수 있다. 자료 부족은 NO_GO 확정과 다르므로 BLOCKED_EXTERNAL이다. 의존 티켓은 상태만 보지 말고 필요한 capability·등급·승인 outcome을 검사한다. 특히 G1/G3/G4 통과는 해당 결과가 PASS/APPROVED여야 한다.

### 0.3 변경 원칙과 필수 금융 조건

- 첫 제품은 GPU 운영자의 확정·양도 가능한 매출채권을 기반으로 한 자금 대출이다. GPU 임대 마켓플레이스·node NFT 대출·토큰 투자는 별도 결정 없이 구현하지 않는다.
- E2는 담보로 인정한 채권의 지급 경로를 차주 단독으로 우회할 수 없는 상태다. `isLocked=true`, API 연결, 수령자 지정, 위반 후 draw 중단만으로 E2를 만들 수 없다.
- 확정채권의 지급 권리가 운영 종료 후에도 존속하면 탈퇴 자체를 전부 금지할 필요는 없다. 미래 매출 유지·실물 담보 집행은 별도 조건이다.
- source receipt, claimable amount, oracle assertion, cross-chain message는 상환이 아니다. 지정 상환 계좌/Vault가 실제 대출 통화를 수령하고 facility에 배분한 범위만 채무에서 차감한다.
- 원금·미납이자·수수료·회수·손실의 계산 원천은 하나다. 차주 미수채권은 borrowing base이며 Vault 대출채권에 더해 LP 자산으로 합산하지 않는다.
- cap은 해당 범주의 **모든 facility 미결 노출 + 실행 예약**을 반영한다. EVM nonce와 대출 예약/승인 nonce는 서로 다르다.
- 부실 상각은 채무 면제가 아니다. 차주 소유 reserve·초과 입금·환불 의무를 LP 현금과 혼합하지 않는다.
- 차입 중단과 상환 중단을 구분한다. 기존 BTC manager의 global pause는 상환도 막으므로 레거시 회수에 그대로 사용하지 않는다.
- production GPU 경로에서 testnet credit grant, 공개 owner-key API, permissive source admission을 허용하지 않는다.
- 외부 체인 사실의 금융 반영은 공식 native 검증 결과에 귀속된다. proof API의 HTTP 200, SDK의 로컬 성공, keeper 서명만으로 `nativeStatus=VERIFIED`를 기록하지 않는다. source proof로 입금이 확인돼도 영업매출·미지급채권·E2·실수령 상환 여부는 각각 검증한다.
- proof 미지원/실패/기한 경과는 그 증거에 의존하는 신규 승인·한도 증액·draw를 차단한다. 기존에 검증된 증거는 정책 유효기간 내에서만 사용한다. native 장애를 자체 서명/관리자 override로 우회하지 않으며 destination 직접 수령금의 정상 repayFor·회수·기존 권리 행사는 불필요하게 막지 않는다.
- 파트너 endpoint·ABI·token/chain 주소·서명 권한을 만들어내지 않는다. 내부 제안 인터페이스와 실제 파트너 인터페이스를 문서에서 구분한다.
- 기존 dirty worktree·미추적 문서·키·레거시 자금과 기록을 보존한다. 이름만 바꾸는 전역 치환이나 무관한 정리를 묶지 않는다.

코드/문서 티켓은 로컬 변경·검증 범위다. `LIVE`/`RELEASE`에서는 기존에 부여된 권한과 범위를 확인하고 준비물·simulation을 먼저 완성한다. 부족한 외부 권한만 요청한다. 티켓 존재 자체를 실서비스 배포·자금 전송·담보 처분·파트너 연락 허가로 해석하지 않는다.

### 0.4 선행 관계와 차단 처리

`선행`의 쉼표는 AND다. `선택 선행`은 명시한 둘 중 선택된 첫 파트너의 한 경로만 요구한다. Aethir/GPU.net을 모두 완료해야 첫 파트너를 출시할 수 있는 구조로 만들지 않는다. `출시 조건`은 로컬 CODE 티켓의 완료와 구분한다.

외부 자료가 없으면 접근 방법·자료 양식·mock/fixture·차단 검증까지 준비하고, 남은 요구를 `BLOCKED_EXTERNAL`로 기록한다. `unsupported`를 성공 응답으로 바꾸지 않는다. 다른 READY 로컬 작업은 계속할 수 있다. 코드 티켓의 로컬 완료와 고객/LP 자금을 취급하는 파일럿 실행은 구분하며 후자는 GPU-010과 GPU-063 승인이 필요하다.

GPU-009/056의 **사전 승인된 제한 실험**은 일반 파일럿과 구분한다. GPU-009는 승인된 계정의 지급 통제 시험이며, GPU-056은 G1 승인·시험 전용 자금 한도·대상 계약·기간·담당자가 확정되면 GPU-063 전에 소액 시험 대출/상환을 수행할 수 있다. 공개 LP 모집·일반 고객 대출·상한 확대는 허용하지 않는다. 이 구분으로 “실제 상환을 검증해야 출시 승인, 출시 승인 없이는 검증 불가”의 순환을 방지한다.

GPU-080은 파트너 실증과 독립인 **기술 통합 시험**이다. source/destination testnet·시험 계약·전용 지갑·가스/테스트 토큰 한도·기간을 승인받은 범위에서만 broadcast한다. G1·실제 파트너·GPU-063을 선행으로 요구하지 않는다. read-only 환경 확인과 로컬 harness는 먼저 준비할 수 있지만 권한/테스트 자금/실제 proof가 없으면 NATIVE_TESTNET 완료는 BLOCKED_EXTERNAL이다. GPU-080 성공으로 GPU-009/056을 대체하지 않는다.

SPEC의 초안은 `DRAFT`/`OPEN` 항목을 명시한 검토 가능한 문서로 완료할 수 있다. 실제 약정·금리·법적 효력·수익 통제·체인 선택의 승인을 모델이 대신 만들어서는 안 된다. GPU-010에서 파일럿 경로의 OPEN 항목을 해소하고 변경된 결정에 영향을 받는 티켓을 다시 검증한다.

### 0.5 경로·공유 인터페이스·병렬 작업

현재 경로는 `contracts/`, `test/`, `offchain/api/hashcredit_api/`, `offchain/prover/hashcredit_prover/`, `offchain/relayer/`, `apps/web/`다. 다음은 GPU-011에서 확정할 **신규 경로 제안**이다.

| 용도 | 제안 경로 |
| --- | --- |
| v2 컨트랙트 / 테스트 | `contracts/gpu/`, `test/gpu/` |
| Python 공통 도메인·DB·connector | `offchain/gpu/hashcredit_gpu/`, `offchain/gpu/tests/`, `offchain/gpu/migrations/` |
| GPU API / worker | `offchain/api/hashcredit_api/gpu/`, `offchain/prover/hashcredit_prover/gpu/` |
| 공식 SDK proof client / tests | `offchain/attestcoin/` (TypeScript, 독립 package/lockfile, 좁은 JSON 입출력) |
| source 이벤트 계약 / native verifier | `contracts/gpu/source/`, `contracts/gpu/AttestcoinRevenueVerifier.sol` |
| 공식 환경/ABI·proof fixture | `config/attestcoin/`, `test/fixtures/gpu/attestcoin/` |
| 설계·결정·실사 | `docs/gpu/`, `docs/gpu/decisions/`, `docs/gpu/partners/` |
| 티켓별 결과 | `docs/gpu/execution/GPU-NNN.md` |

경로가 바뀌면 GPU-011의 경로표와 영향을 받는 티켓을 함께 갱신한다. 기능상 이유 없이 새 프레임워크·언어·마이크로서비스를 추가하지 않는다. 금융 불변식이 같은 객체를 여러 곳에서 재구현하지 않는다.

공식 SDK가 TS/JS이므로 GPU-075/079에서 좁은 TypeScript package를 쓰는 것은 허용된 기술 선택이다. 기존 Python API/DB/worker를 통째로 다시 작성하지 않는다. Python↔TS 경계는 versioned JSON + 제한된 CLI/subprocess 또는 승인된 단일 worker 구성이며 public proof microservice를 불필요하게 만들지 않는다. 공식 SDK를 웹 번들에 넣지 않고, 다른 언어에서 proof/ABI를 독자 재구현하는 대안은 동등성 증거와 ADR 없이는 채택하지 않는다.

병렬 작업은 인터페이스/스키마 확정 뒤 파일 소유권이 겹치지 않을 때만 한다. Solidity ABI/이벤트는 GPU-029, DB migration 순서는 GPU-015/016, API DTO는 GPU-011/045, 생성물은 GPU-046 담당이 조정한다. 같은 manager/vault 또는 migration head를 여러 세션이 동시에 편집하지 않는다. 중앙 TICKET 상태 갱신은 한 통합 담당자가 수행한다.

### 0.6 검증 명령 계약

아래 현재 명령은 저장소 기준이다. 티켓에 `SOL(GPU033)`처럼 쓰면 정확한 명령으로 확장해 실행 기록에 남긴다. 예시 test 이름은 앞으로 만들어야 할 명명 계약이며 기존에 있다고 가정하지 않는다.

| 별칭 | 실행 위치·명령 | 조건 |
| --- | --- | --- |
| DIFF | repo root: `git diff --check` | 생성한 미추적 파일은 별도 검사도 필요 |
| SOL(name) | root: `forge test --match-contract 'name' -vvv` | name을 티켓의 contract/pattern으로 교체하고 따옴표 유지. 0 tests를 통과로 취급 금지 |
| SOL-FULL | root: `forge build --sizes`, `forge test --summary`, `forge fmt --check` | 돈/권한 관련 통합 시 실행; 매 문서 수정에 반복하지 않음 |
| PY-API | `offchain/api`: `python -m pytest tests/ -q` | 프로젝트용 Python 3.11+ 환경 및 dev 의존성 |
| PY-PROVER | `offchain/prover`: `python -m pytest tests/ -q` | 위와 같음 |
| PY-RELAYER | `offchain/relayer`: `python -m pytest tests/ -q` | 레거시 영향이 있을 때 |
| WEB | root: `npm --prefix apps/web run lint`, `npm --prefix apps/web run build` | `apps/web/package-lock.json` 사용, root workspace에 web이 없다는 점 유의 |
| PY-GPU(path) | root: `python -m pytest offchain/gpu/tests/path -q` | **GPU-015에서 공통 package/dev 설치를 구성한 뒤** 사용 |
| WEB-TEST | root: `npm --prefix apps/web run test -- --run` | **GPU-052에서 추가할 명령** |
| WEB-E2E | root: `npm --prefix apps/web run test:e2e` | **GPU-052에서 추가할 명령** |
| V2-E2E | root: `bash script/gpu/e2e_local.sh` | **GPU-057에서 추가할 명령**; 로컬 전용, 실환경 broadcast 없음 |
| ASC-CHECK | root: `npm --prefix offchain/attestcoin run check` | **GPU-075에서 추가**; typecheck·고정 ABI/schema/lock 검증, 네트워크/서명 없음 |
| ASC-TEST | root: `npm --prefix offchain/attestcoin run test -- --run` | **GPU-075/079에서 추가**; 로컬 unit/contract tests, 0 tests 금지 |
| ASC-PROBE | root: `npm --prefix offchain/attestcoin run probe -- --manifest <path>` | **GPU-075에서 추가**; 명시 manifest의 read-only RPC/API/공식 지원 조회, 비밀정보 출력 금지 |
| ASC-NATIVE | root: `bash script/gpu/attestcoin_native_e2e.sh --manifest <path> --approval <ref>` | **GPU-080에서 추가**; 승인된 공개 testnet 전용, 기본 broadcast 거부·mainnet 거부 |

GPU-000에서 도구 버전과 재현 환경을 기록한다. root `Makefile`은 `.env`를 읽으므로 진단 시 의도하지 않은 환경 로드/외부 broadcast를 피한다. 의존성 누락과 제품 오류를 구분하고 테스트 skip으로 문제를 숨기지 않는다.

PIVOT의 이전 검사 결과는 Solidity 192 passed, 일부 Python 72 passed, web lint 통과다. Python 전체는 `coincurve` 누락으로 수집 중단했고 web build/E2E는 검증하지 않았다. 이 결과를 새 작업의 검증 결과로 복사하지 않는다.

### 0.7 티켓 인수인계 형식

모든 작업은 `docs/gpu/execution/GPU-NNN.md`에 다음을 남긴다. 민감한 원문·credentials는 저장하지 않고 접근 통제된 증거 참조를 사용한다.

```text
Ticket / 상태 / 작성자 또는 실행자 / 기준 commit·dirty 범위
증거 수준: LOCAL | SANDBOX | NATIVE_TESTNET | LIVE | ACCEPTED (복수이면 항목별 기록)
executionProfile / verificationMethod / nativeStatus / earningsProvenance / controlGrade / cashState:
공식 통합: manifestHash·SDK/ABI/decoder 버전·source/destination chain·검증 block/tx·proof artifact 참조
바뀐 동작과 파일:
적용한 결정 ID·버전 / 가정 / OPEN 항목:
완료 기준별 확인 결과:
실행 명령·cwd·exit code·test 개수·중요 결과:
실패/미실행과 이유:
외부 검증: 계정/환경/시각/증거 참조(비밀정보 제외)
남은 작업·차단 입력·다음 READY 티켓:
재개 시 필요한 파일·실행 중 프로세스/포트·변경 소유권:
```

`DONE`은 구현 코드의 존재만으로 기록하지 않는다. 관련 회귀·권한·실패 경로까지 확인한다. 무관한 기존 실패는 baseline과 구분해 기록하되 해당 티켓의 실패를 “기존 문제”로 넘기지 않는다.

### 0.8 Claude Code에 전달할 시작 프롬프트

첫 세션:

```text
이 저장소의 TICKET.md §0과 GPU-000을 읽고 GPU-000만 실행하라.
PIVOT.md는 제품 근거이며 docs/process/TICKET.md는 레거시 기록이다.
공식 Attestcoin 필수 요구와 문서 충돌은 TICKET.md §0.9/R2를 우선 적용하라.
현재 dirty worktree를 보존하라. 티켓의 실제 선행/파일을 확인하라.
환경·검증·짧은 CLAUDE.md·실행 기록을 준비하고 결과를 저장하라.
다른 티켓 구현이나 외부 배포/자금 이동은 수행하지 말라.
```

일반 구현 세션:

```text
TICKET.md §0과 GPU-NNN을 읽고 해당 티켓을 구현하라.
공식 Attestcoin native proof가 필수다. GPU-074~082와 §0.9를 적용하라.
참조된 PIVOT 절, 선행 티켓 산출물, 실제 코드를 먼저 확인하라.
티켓 범위 안에서 구현과 필요한 회귀/실패 테스트를 완료하라.
파트너 API·권한·주소·사업 승인을 추측하지 말라.
자체 서명·관리자 override·LOCAL_MOCK으로 production proof를 대체하지 말라.
proof 성공, GPU 매출 출처, 미지급채권, E2, 실제 상환을 별도로 검증하라.
외부 입력이 부족하면 준비 가능한 산출물을 완성하고 차단 조건을 기록하라.
DONE 여부는 완료 기준과 요구 증거 수준으로 판정하라.
docs/gpu/execution/GPU-NNN.md와 티켓 상태를 갱신하고
변경 파일, 검증 결과, 잔여 위험, 다음 READY 티켓을 보고하라.
```

독립 리뷰 세션:

```text
GPU-NNN의 티켓·선행 결정·실행 기록·실제 diff를 리뷰하라.
자금 보존, 지급 통제, 권한, 중복 처리, 실패 복구, 테스트 누락을 우선 보라.
완료 기준을 충족하지 못하면 구체적 입력·기대값·파일로 지적하라.
mock 통과를 실제 파트너/자금/법률 검증으로 인정하지 말라.
공식 native 호출·검증된 bytes에서의 event 추출·보조 서명 분리·downgrade 거부를 확인하라.
Anvil precompile mock과 NATIVE_TESTNET, native proof와 영업매출/회수권을 구분하라.
코드를 고치지 말고 결과를 같은 실행 기록의 Review 절에 작성하라.
```

연속 실행 세션:

```text
TICKET.md R2를 실행 원장으로 삼고 §0 전체와 GPU-000부터 시작하라.
GPU-074/075를 초기 우선 작업으로 두고 실제 선행이 충족된 티켓을 순서대로
구현·실패 테스트·검증·기록까지 완료하라. 계획만 작성하고 끝내지 말라.
공식 Attestcoin native 검증을 필수로 유지하고 자동 자체 서명 fallback은 금지한다.
PIVOT/TECH/해커톤 문서의 충돌은 §0.9와 결정 원장으로 해결하라.
외부 자료/승인 없이 만들 수 없는 사실은 BLOCKED_EXTERNAL로 기록하고
다른 독립적인 READY 로컬 작업을 계속하라. 티켓 존재를 broadcast/자금 이동/
파트너 연락/DEFERRED 상품 변경 허가로 해석하지 말라.
각 티켓의 상태와 docs/gpu/execution/GPU-NNN.md를 갱신하고, 세션 종료 전
검증 결과·실패·실제 native E2E 여부·차단 입력·다음 READY·재개 파일을 남겨라.
권한 있는 READY 작업이 더 없으면 완료와 차단을 구분하여 보고하라.
```

### 0.9 R2의 확정 아키텍처·공식 근거·인정 경계

**제품 실행 체인과 대출 원장은 Creditcoin, 외부 체인 검증 기반은 공식 Attestcoin Readability다.** CTC 가스/네트워크, Attestcoin 프로토콜, 대출 stablecoin은 별개로 설정한다. 이 요구를 CTC/ATC 담보·대출통화 변경이나 토큰 구매 승인으로 해석하지 않는다. 공식 SDK의 USC 이름은 구 명칭이 남은 것이며 자체 USC 모사 구현을 뜻하지 않는다. [공식 SDK 설명](https://docs.attestcoin.org/attestcoin-protocol/dapp-builder-infrastructure/attestcoin-sdk-usc-sdk.md)

필수 연결 경로:

```text
승인된 provider의 source 사건 / 통제 계좌의 출처가 검증된 지급
  → GPU-077 source event 또는 검증된 기존 provider contract event
  → GPU-079 공식 SDK·Proof Builder (proof는 신뢰하지 않는 입력)
  → GPU-078 Creditcoin BlockProver + 검증된 bytes의 decoder/event 검증
  → GPU-031 EvidenceBook: canonical 사건 기록·소비·정정
  → GPU-081 / GPU-035~036: 미지급 적격채권·E2·심사·한도 조건 결합

별도 자금 경로: source escrow → 승인된 환전/정산 → destination 실수령 → repayFor
보조 경로: provider API/권리자료/심사 서명 → 보조 판단 (native proof 대체 불가)
```

2026-09-14 문서 확인값은 구현 시작점이며 실환경 검증 완료값이 아니다. GPU-075가 선택 배포의 지원/버전/주소를 다시 검증하고 manifest를 고정한다. [공식 환경 표](https://docs.attestcoin.org/attestcoin-protocol/attestcoin-protocol-chains-environments.md)

| Creditcoin 환경 | 문서상 source / chain key | 공식 자원 확인점 |
| --- | --- | --- |
| CC3 mainnet | Ethereum mainnet / 1 | BlockProver `0x0000000000000000000000000000000000000FD2`, ChainInfo `0x0000000000000000000000000000000000000fd3` |
| CC3 testnet | Sepolia / 1, Ethereum mainnet / 3 | 동일 precompile 주소라도 환경·지원표·runtime이 같다고 추정 금지 |
| decoder / proof service | 환경별 상이 | 공식 환경 표와 선택한 package/artifact를 대조; 주소·URL을 사용자 입력으로 임의 교체하지 않음 |

SDK 안내에는 `@gluwa/usc-sdk`(TS/JS, ethers v6 peer), 지원 source 조회·attestation 대기·proof 생성 흐름이 있다. testnet endpoint 표기에는 `proof-gen-api.cc3-testnet.creditcoin.network`와 SDK 예제의 `prover.cc3-testnet.creditcoin.network`가 공존한다. 별칭/호환성을 추정하지 않고 선택 endpoint의 응답 schema·버전을 확인한다. 의존성은 `latest` 대신 검증한 버전/commit/lock으로 고정한다. [공식 SDK](https://docs.attestcoin.org/attestcoin-protocol/dapp-builder-infrastructure/attestcoin-sdk-usc-sdk.md), [공식 예제 저장소](https://github.com/gluwa/attestcoin-protocol-examples)

BlockProver는 source transaction 포함·continuity를 검증한다. 거래 성공과 event의 의미는 앱이 검사해야 한다. 문서의 예제 코드는 교육용이며 그대로 production 배포하지 않는다. precompile은 일반 계약처럼 bytecode가 존재해야 한다고 판정하지 않고 공식 ABI 호출과 성공/실패 벡터로 확인한다. [공식 ASC 계약 문서](https://docs.attestcoin.org/attestcoin-protocol/dapp-builder-infrastructure/attestcoin-smart-contracts.md)

판정의 필수 분리:

| 증거/상태 | 인정 가능한 것 | 이것만으로 인정 불가 |
| --- | --- | --- |
| 공식 native proof + 검증된 event | 지정 source의 해당 사건 발생 | GPU 영업매출 출처, 미지급 잔액, 물리 소유권, 법적 양도/E2 |
| 우리 서버가 올린 statement hash/서명 event | 그 주장이 체인에 기록됐다는 사실 | 주장 내용의 독립 검증; OFFCHAIN_ASSERTION을 native GPU 매출로 세탁 금지 |
| 지급 완료 event | 정산·지급 이력, 해당 채권의 감소 자료 | 이미 완납된 채권 재담보, 과거 payout 합계로 새 미지급채권 생성 |
| API·계약·심사 승인 | 명시된 신뢰 주체의 보조 사실/권리/판단 | native proof 또는 차주 단독 우회 불가의 자동 충족 |
| destination 대출통화 실수령 | 시설 귀속·배분 확인 후 상환 | 다른 차주의 상환, source와 destination 이중 차감 |

첫 상품은 확정 미지급채권 금융을 유지한다. GPU-008/076은 대출 전에 증명 가능한 채무자의 확정/양도 사건과 남은 채권을 식별해야 한다. provider API를 우리 서명으로 감싸는 것만 가능하거나 과거 지급만 증명 가능하면 그 사실을 드러내고 first-product admission을 보류한다. 미래 현금흐름/NFT 담보 상품으로 바꾸는 것은 GPU-072 등 별도 사용자 결정 없이는 금지다. 보조 서명이 합법적 심사 입력인 것과 검증되지 않은 source 사실로 borrowing base를 만드는 것은 다르다.

**과거 사건의 inclusion은 현재 미지급 상태나 이후 지급/취소의 부재를 증명하지 않는다.** `paid event를 못 봄 ⇒ unpaid` 추론과 오래된 proof를 이제 제출해 freshness를 갱신하는 동작을 금지한다. GPU-076은 source 권한자가 유지하는 최신 잔액/revision·decision challenge에 귀속된 checkpoint와 그 이후 상태 변화 위험을 명세한다. draw까지 유효한 source assignment/reservation으로 상태를 보호하거나, 실증·승인된 제한 지연/누락 탐지·보수적 buffer 정책으로 잔여 위험을 다뤄야 한다. 별도 최신성 보장이 없으면 즉시 최신 상태를 안다고 주장하지 않고 신규 draw를 차단한다. API watermark만으로 native 필수 source 사실을 대체하지 않는다.

Aethir/GPU.net의 실제 source가 공식 지원 밖이면 그 경로는 `UNSUPPORTED_SOURCE`, admission off다. 자체 emitter를 지원 체인에 배포하거나 bridge 후 도착만 증명해 원래 미지원 체인의 지급까지 증명했다고 주장하지 않는다. 현재 source 지원을 확보하거나 증명 범위·추가 신뢰·상품 변경을 명시해 별도 승인을 받기 전 출시하지 않는다.

Writability는 확인한 공식 문서상 테스트·감사 단계다. 현재 사용 가능하다고 가정한 cross-chain claim/receiver 변경·무신뢰 bridge는 구현 범위가 아니다. 원격 지급 통제는 GPU-009/038의 실제 권한, 자금 이동은 GPU-040의 검증된 정산 레일을 사용한다. 향후 Writability 도입은 새 지원 확인·위협 모델·승인 티켓이 필요하다. [공식 Writability 상태](https://docs.attestcoin.org/attestcoin-protocol/attestcoin-writability.md)

## 1. 실행 지도

| 구간 | 티켓 | 목적 |
| --- | --- | --- |
| 시작·현재 위험 | GPU-000~002 | 실행 환경·공개 관리자 경로·알려진 오류 기준선 |
| 공식 검증 결정·기반 | GPU-074~076 | 문서 충돌 정리, 공식 SDK/ABI/환경 고정, 증명·업무 의미 명세 |
| 제품·외부 집행 | GPU-003~010 | 두 파트너 실사, 계약·자금·체인 결정, 실제 E2 조건 |
| 공유 설계 | GPU-011~014 | 도메인/회계/권한/증거 명세 확정 |
| 데이터·오프체인 | GPU-015~028, GPU-073 | DB, 인증, connector, 정산·현금·실행·전체 이벤트 인덱싱 |
| 금융 컨트랙트 | GPU-029~043 | 검증·원장·한도·Vault·escrow·상환·손실·권한 |
| 공식 검증 구현·검증 | GPU-077~082 | source event, native verifier, proof worker, 공개 testnet, 금융 연결, 공격/호환성 검사 |
| 운영 API·화면 | GPU-044~052 | 모니터링, 제품 API, ABI/타입, 차주·LP·운영 UI |
| 배포·검증 | GPU-053~059 | 재현 환경, CI, 불변식, 실제 통합, 감사·복구 |
| 전환·파일럿 | GPU-060~067 | legacy 보존, 배포, 실자금 파일럿, 문서·브랜드·종료 |
| 후속 확장 | GPU-068~072 | 두 번째 파트너 활성화, 실물 금융·회수, 미래 현금흐름 |

기본 로컬 순서: GPU-000 → GPU-074/075와 GPU-001/002 → GPU-003/008/011~013/076/014 → 공통 package/DB/interfaces → GPU-077/078/079와 금융 코어 → GPU-031/081/082 → 제품 API/화면 → 로컬 E2E. 이 표는 요약이며 각 티켓 `선행`이 실제 AND 원장이다. 외부 실사·E2 실험은 병행한다. 첫 파트너 정식 연결은 GPU-020 또는 GPU-021 한 경로만 필요하다.

빠른 공식 기술 검증 경로는 GPU-075의 환경/SDK → GPU-076/029의 schema → GPU-077/078 + GPU-031/079 → GPU-080이다. 필요한 공유 설계·DB/dispatcher 선행도 완료해야 하지만 파트너 DD·G1·전체 프런트엔드·일반 배포 티켓을 기다리지 않는다. GPU-080에서 막혀도 mock를 명시한 나머지 로컬 구현은 계속한다.

출시 gate:

- G0: GPU-000의 재현 환경과 작업 보존 확인.
- G1: GPU-010의 제품·자금·지급 통제 결정 수용. CODE의 로컬 시작 gate가 아니라 실자금 준비 gate.
- G2: GPU-055·057·081·082의 회계/권한/공식-required 경계/복구 로컬 통합 검증. native network 통과와는 별개.
- G-ASC: GPU-080의 실제 source testnet 거래 → 공식 proof → 실제 Creditcoin native 검증·앱 event 소비 PASS. 구현 commit/manifest/ABI에 귀속; 유효하지 않은 이전 결과 재사용 금지.
- G3: GPU-056의 선택 파트너 실제 source 공식 검증·매출 출처·지급 통제·실수령 상환 검증. G-ASC만으로 G3 통과 불가.
- G4: GPU-063의 배포·감사·legacy·운영·계약·자금 승인.
- G5: GPU-064의 실제 정산 주기를 거친 파일럿 평가. 두 번째 파트너/장비 금융은 이후 별도 승인.

## 2. 시작·위험 기준선

### GPU-000 — 재현 환경과 Claude Code 작업 진입점

- 상태: DONE (2026-09-13, docs/gpu/execution/GPU-000.md)
- 유형/우선순위: CODE / P0
- 선행: 없음
- 근거/읽기: PIVOT §2, §12; `AGENT.md`, `foundry.toml`, root 및 web `package.json`, `offchain/*/pyproject.toml`, `.github/workflows/test.yml`.
- 범위/산출물: 짧은 root `CLAUDE.md` 신규, `docs/gpu/execution/BASELINE.md`, 실행 기록 디렉터리. 기존 지침이 생겼으면 병합 전 내용 확인.
- 작업: Python 전용 환경·고정 가능한 의존성·Foundry·Node 버전 기록. `coincurve` 포함 실제 API test 환경 구성. web lockfile 기준 설치 방법 명시. `CLAUDE.md`에는 이 문서 진입, 명령, PIVOT 핵심 금융 조건, 변경 보존·인수인계만 담는다.
- 완료 기준: 기존 suite를 실행해 통과/실패/환경 차이를 실제 기록한다. 지원하지 않는 Opus model ID나 무검증 CLI 옵션을 생성하지 않는다. 사용자 키·환경값은 로그에 없다.
- 검증: DIFF, SOL-FULL, PY-API/PY-PROVER/PY-RELAYER, WEB. 아직 없는 GPU/web test script를 실행했다고 기록하지 않는다.
- R2 필수 작업·완료/검증: 공식 native 구현 유무와 BTC proof builder를 실제 코드로 구분하고 TECH/README의 현재형을 완료 증거로 사용하지 않는다. 짧은 CLAUDE.md에 R2 결정과 GPU-074/075 진입을 넣고 GPU-075 이전에 ASC 명령이 존재한다고 기록하지 않는다.

### GPU-001 — 공개 관리자 등록/신용 부여 경로와 데모 권한 격리

- 상태: DONE (2026-09-14, docs/gpu/execution/GPU-001.md; 실서비스 secret/profile 재배포는 GPU-063)
- 유형/우선순위: CODE / P0
- 선행: GPU-000
- 근거/읽기: PIVOT §2.2, §8; `offchain/api/hashcredit_api/main.py`, `evm.py`, `config.py`, `tests/test_api.py`, web `claim-section.tsx`, `script/DeploySpv.s.sol`.
- 범위: production API의 `/claim/register-and-grant` 제거/명시적 거부. 필요한 데모 기능은 별도 실행 경로·테스트 체인 allowlist·한도·별도 키로 격리. GPU 배포에 auto grant가 들어가지 않는 검사 기반 마련.
- 작업: 인증 헤더 하나만 추가해 공개 서버에 owner key를 계속 두는 수정을 피한다. UI의 자동 grant 요청도 새 production 모드에서 제거한다. 기존 testnet demo의 필요한 동작은 명시적 fixture에서만 유지한다.
- 완료 기준: 익명·타 차주·가짜 BTC 주소·chain 변경·external stablecoin 입력으로 관리자 tx를 만들 수 없다. 일반 API 프로세스가 owner key 없이 실행된다. legacy 조회/상환 UX 영향이 기록된다.
- 검증: PY-API의 endpoint 부재/거부·서명 함수 미호출 검사, WEB, 관련 script 설정 검사. 실서비스 secret 변경/재배포는 GPU-063에서 수행.

### GPU-002 — 알려진 금융·주소 귀속 결함의 재현 벡터

- 상태: DONE (2026-09-14, docs/gpu/execution/GPU-002.md; RED 모드 0/8 → v2 인수 기준)
- 유형/우선순위: CODE / P0
- 선행: GPU-000
- 근거/읽기: PIVOT §2.2, §12; `HashCreditManager.sol`, `LendingVault.sol`, `BtcSpvVerifier.sol`, `test/HashCreditManager.t.sol`, `test/invariant/Invariant.t.sol`.
- 산출물: `docs/gpu/accounting-regressions.md`, 별도 diagnostic test/fixture. 레거시 계약을 v2로 바꾸는 티켓은 아님.
- 작업: 부분 이자 소실, Manager/Vault 배분 차이, 재차입 자본화, APR 소급, stale 한도, 과거 증거 재사용, claim domain 누락, share donation을 최소 입력/기대값으로 고정한다.
- 완료 기준: $5,000·10%·365일·$250 상환의 올바른 잔액 $5,250과 현재 결과를 구분. donation은 base-unit 예시를 실제 EVM으로 재현하거나 미검증으로 명시. 알려진 버그를 올바른 v2 기대값으로 옮길 수 있다.
- 검증: 기존 `forge test --match-test test_repay_interestFirst -vvvv`와 별도 diagnostic 명령/exit 기록. 의도적 red 재현은 기본 CI 통과 suite와 분리; xfail/skip만으로 수정 완료를 주장하지 않는다.

## 3. 제품·파트너·외부 집행

### GPU-003 — 첫 상품 term sheet와 결정 원장

- 상태: DONE (2026-09-14, DRAFT v0.1 + OPEN TS-O01~O11; docs/gpu/execution/GPU-003.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-000, GPU-074
- 근거: PIVOT §1, §5, §6, §11.
- 산출물: `docs/gpu/product-term-sheet.md`, `docs/gpu/decisions/REGISTER.md`.
- 작업: 차주/자금 공급자/통화/관할/용도, loan 대 receivable purchase, 정산기·만기·금리·최소 상환·waterfall·reserve·출금 조건을 정의한다. 첫 상품은 확정채권 금융 초안으로 작성하고 법적 형태·실제 수치를 OPEN으로 남긴다.
- 완료 기준: GPU 임대·토큰담보·장비 재판매와 경계가 명확하다. 모든 OPEN 결정에 담당 역할·필요 자료·영향 티켓이 있다. 임의 APR/LTV는 TEST_ONLY로 표시한다.
- 검증: term sheet의 현금 흐름과 PIVOT 대응 검토. 승인 기록의 부재를 허위 ACCEPTED로 채우지 않는다.
- R2 필수 작업·완료/검증: Creditcoin execution + 공식 Attestcoin 외부 증거 검증은 확정 요구다. CTC/ATC 대출통화·GPU NFT 담보·과거 payout 기반 현금흐름 상품은 별도 승인 없이 채택하지 않는다.

### GPU-004 — Aethir 공급자 실사와 공식 capability 명세

- 상태: TODO
- 유형/우선순위: DD / P0
- 선행: GPU-000
- 근거: PIVOT §3.1~3.2, §3.4, §4.
- 산출물: `docs/gpu/partners/aethir.md`, 자료 요청 양식·비밀정보 제거 샘플·권한 그래프.
- 작업: Host/group/실물 식별, service fee/reward 분리, ATH 환산·vesting·claim/withdraw·unstake, receiver/계정 변경·복구·admin override·slashing을 확인한다. 실제 API/ABI/contract/token/chain·auth scope·KYC·contract receiver 지원을 자료와 연결한다.
- 완료 기준: 공개 문서 확인/파트너 답변/실제 시험을 구분한 capability 표가 있다. Checker API를 Host API로 오용하지 않는다. RWA Capital 기존 금융·선순위·제휴 조건을 확인한다.
- 외부 조건: 최신 supplier 자료·승인 계정·정산 및 실제 지급 샘플. 없으면 준비 문서 작성 후 BLOCKED_EXTERNAL; 공개 자료만으로 integration-ready 판정 금지.
- 검증: 공식 원문 URL·확인일·적용 버전·답변 참조, statement와 tx의 필드 대응. 테스트/자금 이동 권한은 별도 기록.
- R2 필수 작업·완료/검증: 실제 지급/채권 source chain ID·contract·event·payer·token과 GPU-075 지원표를 매핑한다. native 증명 가능/API-only/우리 oracle 주장만 있는 항목을 분리한다. 미지원 또는 대출 전 확정채권 입증 경로 부재는 OPEN/NO_GO로 남기고 자체 Ethereum anchor로 해소했다고 하지 않는다.

### GPU-005 — GPU.net 현행 supplier 실사와 상품 구분

- 상태: TODO
- 유형/우선순위: DD / P0
- 선행: GPU-000
- 근거: PIVOT §3.1, §3.3~3.4, §4.
- 산출물: `docs/gpu/partners/gpunet.md`, 현행 supplier contract/API 체크리스트·권한 그래프.
- 작업: 실제 GPU 공급자 계정/정산 주체·수익 유형·지급 asset/chain·receiver 변경/탈퇴·보상 정책을 확인한다. 2024 guide, 고객 VM API, GAN 보상, NFT/TBA, Polygon credits, RWA 장비 재판매를 분리한다.
- 완료 기준: rental revenue와 emissions의 매칭 규칙, 실제 지급 자료, write capability 지원/미지원이 명확하다. RWA 페이지의 상충된 설명을 임의 해결하지 않는다.
- 외부 조건: 최신 공급계약·API·샘플 계정·실제 지급 자료. 없으면 BLOCKED_EXTERNAL; 첫 Aethir 출시의 AND 의존성으로 만들지 않는다.
- 검증: 날짜·공식 문서·파트너 답변·실제 tx의 근거표. node 실행 키와 treasury 키의 분리 확인.
- R2 필수 작업·완료/검증: 현행 supplier 지급/채권 event·issuer 권한·source chain ID와 GPU-075/076을 대조한다. EVM 호환성은 Attestcoin 지원 증거가 아니다. 미지원 원천을 bridge/자체 hash로 옮겨 원래 매출까지 증명됐다고 표시하지 않는다.

### GPU-006 — 차주·채권·지급 통제의 계약 및 권리 패키지

- 상태: TODO
- 유형/우선순위: DD / P0
- 선행: GPU-003
- 근거: PIVOT §3.4, §4, §11.
- 산출물: `docs/gpu/rights-and-contracts.md`, 법인/실소유자·소유/리스·선순위·채권 양도·보관자 자료 목록.
- 작업: 차주, 자산 소유자, Host, 데이터센터, 정산 채무자, 대주/servicer의 권한을 연결한다. 지급 assignment 인정, set-off/환불/penalty 순위, 종료 후 기발생 채권, 서명 권한·적용 관할을 검토할 자료를 만든다. 데이터 사용·보관/삭제·국외 이전·서비스 제공 요건도 포함한다.
- 완료 기준: E2와 E3 증거 요구가 다르고, 법적 효력을 코드/문서 hash로 대체하지 않는다. 권리 검토·필요한 계약 체결의 담당자와 증거 참조가 있다.
- 외부 조건: 파일럿 당사자 자료와 권한 있는 법률/사업 판단. 문서 초안은 만들 수 있으나 실제 권리 승인 전 DD 완료 금지.
- 검증: 각 상환·회수 조치에 권리/의무 주체·조건·실행자·기한·우선순위를 매핑.

### GPU-007 — 자금 공급·신용 정책·단위 경제성 결정 자료

- 상태: DONE (2026-09-14, DRAFT/TEST_ONLY; docs/gpu/execution/GPU-007.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-003
- 근거: PIVOT §6.3, §11.
- 산출물: `docs/gpu/underwriting-policy.md`, `docs/gpu/unit-economics.md`, TEST_ONLY 시나리오 데이터.
- 작업: 90~180일 정산/가동 자료 요구, 적격 채권·haircut·인센티브 제외, SKU/차주그룹/고객/파트너/지역 집중도, freshness, 만기·reserve·DSCR를 정의한다. LP 자금 원가·이자/수수료·예상손실·환전·심사·회수 비용을 반영한다.
- 완료 기준: borrower APR ≠ LP yield, facility 구분 ≠ LP 손실 격리. 실제 수치가 없으면 TEST_ONLY와 승인 필요를 명시하고 최소 거래 규모/민감도 표를 제공한다.
- 검증: 지급 지연, ATH/$GPU 하락, 가동률/단가 하락, 플랫폼 공제 증가의 복합 stress 시나리오. 마케팅 가동률을 실매출로 입력하지 않는다.
- R2 필수 작업·완료/검증: native 유효성·매출 출처·미지급 잔액·E2를 별도 적격 조건으로 둔다. 과거 완납 payout은 심사 이력이며 현재 borrowing base 원금이 아니다. 낮은 advance rate 자체 서명으로 native 필수 조건을 우회하는 정책을 금지한다.

### GPU-008 — Creditcoin·공식 source 적합성·자산·환전·결제 레일 ADR

- 상태: TODO
- 유형/우선순위: SPEC / P0
- 선행: GPU-003, GPU-075
- 선택 선행: 실제 source 결정을 확정할 때 GPU-004 또는 GPU-005의 선택 파트너 자료 필요. 초안/지원표는 먼저 작성 가능.
- 근거: PIVOT §3, §10.
- 산출물: `docs/gpu/decisions/settlement-rails.md`, source/debt chain·token/decimals·escrow·RPC·explorer·finality manifest schema.
- 작업: Creditcoin Vault/원장 + 공식 Attestcoin source 검증 + source escrow를 기본 구조로 확정한다. GPU-075의 공식 지원과 실제 파트너의 EVM chain ID·chain key·사건 발행 권한을 대조한다. issuer 자산 지원·환전 유동성·bridge/정산 책임·fee·실패 복구를 구체화한다. 실제 선택 자료가 없으면 DRAFT/UNCONFIRMED로 남긴다.
- 완료 기준: read proof와 자금 이동을 구분하고 미지원 chain/자산은 disabled다. 확정채권 사건·지급 사건·destination 자금 경로와 각 신뢰 주체가 구분된다. 자체 서명이나 source-native 대출로 자동 전환하지 않으며 사용자 요구와 양립 불가하면 OPEN/NO_GO를 제시한다. 기술 기준선만으로 LIVE 준비 완료 금지.
- 검증: 샘플 자금 경로를 한 settlement ID로 그려 source receipt 이후 어느 시점에 debt/NAV를 바꾸는지 명세. 실제 이동은 GPU-009/056 권한 내에서만 수행.

### GPU-009 — 선택 파트너 E2 지급 통제 실증

- 상태: TODO
- 유형/우선순위: LIVE / P0
- 선행: GPU-006, GPU-008
- 선택 선행: GPU-004 또는 GPU-005 중 시험할 파트너 DONE.
- 근거: PIVOT §4.2~4.3, §5.2.
- 산출물: 승인 환경 전용 `script/gpu/control_probe.*` 또는 재현 가능한 수동 절차, `docs/gpu/partners/control-poc.md`.
- 작업: 실제 권한/API를 이용해 지정 receiver 입금·차주 서명 없는 claim/회수, receiver·stakeholder·owner/module 변경, unstake·탈퇴·재등록·support recovery·해제 race를 시험한다. 원천 지급 계약/계정 권한까지 확인한다.
- 완료 기준: 시험 범위와 결과를 증거로 판정하고 `observed_grade=E0/E1/E2`, `outcome=PASS/NO_GO`를 남긴다. E2/PASS에는 담보 채권의 차주 단독 지급 우회 불가·실제 지급·종료 후 채권 존속/상계 영향 확인이 필요하다. E0/E1 확인은 DONE+NO_GO로 기록할 수 있으나 G1 통과 불가다. 감지 후 draw freeze만 성공하면 E1이다.
- 외부 조건: 명시된 시험 권한·계정·자금 한도·실제 지급 대기. script/mock 작성만으로 DONE 금지; 부족하면 BLOCKED_EXTERNAL.
- 검증: 요청→ack→실제 효과→입금의 독립 증거, 관리자 override 잔여 위험, 종료/해제 결과. production 구현 의존성 없이 좁은 PoC로 실증 가능해야 한다.
- R2 필수 작업·완료/검증: 이 시험의 source 입금 관측은 E2 실증 자료이지 G-ASC 증거가 아니다. 공식 native 실제 검증은 GPU-080/056에서 독립 수행한다.

### GPU-010 — 첫 파트너·상품·자금의 실행 조건 확정(G1)

- 상태: TODO
- 유형/우선순위: DD / P0
- 선행: GPU-003, GPU-006, GPU-007, GPU-008, GPU-009, GPU-076
- 근거: PIVOT §14.3~14.4.
- 산출물: `docs/gpu/decisions/pilot-approval.md`; 선택 파트너와 ACCEPTED 약정/정책 버전.
- 작업: 첫 파트너 하나, 차주군·관할·대출 asset/chain, 법적 형태, 승인 금리/한도/만기/waterfall/reserve/LP 조건, E2 범위를 책임자에게 확정받는다. 이전 SPEC의 OPEN 항목과 영향을 검토한다.
- 완료 기준: 실제 자금 경로와 권리 근거가 일치한다. 보류/거절 이유도 정식 결과로 기록하되 go-live 통과와 구분한다. G1 승인에 이후 UI·감사·운영 완료를 허위 포함하지 않는다.
- 외부 조건: 사업/신용/법률/자금 책임자의 결정. 모델이 승인을 대필·조작하지 않는다.
- 검증: 조건별 근거 참조와 서명/승인자·시각. 정식 값이 TEST_ONLY와 다르면 영향 티켓 재검증 목록을 생성한다.
- R2 필수 작업·완료/검증: 선택 provider의 실제 source 지원 및 대출 전 증명 가능한 확정/양도·미지급채권 경로를 GPU-076과 함께 승인 대상으로 적는다. 자체 주장 anchor/완납 지급만 있으면 첫 상품 admission을 보류한다. G-ASC/G3는 별도 후속 gate다.

## 4. 공유 설계와 데이터 계약

### GPU-011 — 도메인·ID·단위·경로·API 계약

- 상태: DONE (2026-09-14, SPEC v1; docs/gpu/execution/GPU-011.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-003, GPU-074, GPU-075
- 근거: PIVOT §6.1~6.2, §7~9.
- 산출물: `docs/gpu/domain-model.md`, versioned schema/fixture, §0.5 경로표 확정.
- 작업: Borrower/LegalEntity/ProviderAccount/Asset/Assignment/Encumbrance/Receivable/Settlement/CashReceipt/ControlAgreement/Facility/Recovery를 정의한다. 각 금액의 asset·chain·decimals, 시각의 의미, 경제 ID와 기술 관측 ID, revision, 상태·에러 코드를 명세한다.
- 완료 기준: 물리 GPU/VM/MIG/container/group/NFT 구분; 같은 자산의 이동·RMA·여러 account 연결 이력; DB/API/Solidity 소유 필드와 개인정보 경계가 명확하다. monetary JSON은 정확한 정수 문자열/명시적 decimal 형식이다.
- 검증: 샘플 한 차주·두 facility·동일 GPU 이동·분할 정산을 스키마로 표현. upstream 데이터 부재는 필드 optional/provenance로 표현하고 임의 채움 금지.
- R2 필수 작업·완료/검증: SourceEvent/ProofRequest/ProofArtifact/NativeVerification/EvidenceConsumption을 분리한다. destination 환경·source chainKey·EVM chain ID·encoding, profile/method/nativeStatus/provenance/controlGrade/cashState를 정의한다. testnet 증거의 production 혼입, 같은 chainKey의 환경별 다른 source, 다중 log를 fixture로 표현한다.

### GPU-012 — 금융 회계 명세와 독립 reference model

- 상태: DONE (2026-09-14, 15 vectors pass; docs/gpu/execution/GPU-012.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-002, GPU-003, GPU-007, GPU-011
- 근거: PIVOT §2.2, §5~7, §12.
- 산출물: `docs/gpu/accounting.md`, `test/fixtures/gpu/accounting.json`, 정수/유리수 기반 독립 계산 모델.
- 작업: principal/미납이자/fee/일수 기준/rounding/자본화/연체/손상/상각/회수/LP share/현금 소유권을 정의한다. 초기 제안은 facility 고정 APR·미납이자 별도 보존이며 미수이자 자본화는 명시적 채택 전 비활성화한다. 정상·default waterfall과 reserve 소유권을 구분한다.
- 완료 기준: 법적 채무와 NAV 장부가가 별개다. source/in-flight/destination 이중 계상, 차주 매출채권의 LP NAV 가산, 환불 reserve의 LP 귀속을 금지하는 분개가 있다. rate 변경을 지원하면 정확한 구간별 정산 방식을 명시한다.
- 검증: $5,000·10%·1년·$250 상환→원금 $5,000/이자 $250; $10,000에 정확한 반년 10%+반년 20%→$1,500; 두 차주·초과입금·상각 후 회수·전액손실/새 LP 진입 벡터. TEST_ONLY 약정과 실제 승인 값을 구분.
- R2 필수 작업·완료/검증: reference model에 native 성공한 완납채권→borrowing base 0, proof만 제출→debt/NAV 불변, native 장애 중 직접 destination repayFor 정상 배분을 추가한다.

### GPU-013 — 권한·통제 약정·상태 전환 계약

- 상태: DONE (2026-09-14, SPEC v1; docs/gpu/execution/GPU-013.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-003, GPU-011
- 근거: PIVOT §4~5, §7~8.
- 산출물: `docs/gpu/permissions-and-states.md`, actor/action/state 표.
- 작업: borrower/registrar/underwriter/guardian/oracle/treasury/servicer/provider admin의 권한, auth challenge/domain/nonce, control version·expiry·revocation·release를 정의한다. facility 상태와 운영 계정 상태는 독립시킨다.
- 완료 기준: keeper가 payer/borrower를 바꾸거나 임의 beneficiary를 지정할 수 없다. draw pause와 collection 유지, cure/dispute/default 전환, debt=0 이후 미결 refund/정산 확인, 완제 후 역할 반환 조건이 명확하다.
- 검증: receiver 변경↔draw/release race, support override, stale observation, 권한 키 교체, borrowed asset과 다른 asset, 오래된 release assertion의 전이 표. 실제 upstream 권한 승인은 GPU-009/010에서 별도 확보.
- R2 필수 작업·완료/검증: 지갑/약정/심사/통제 승인 서명과 source 사실 검증은 별개다. relay gas payer는 매출 발급자/treasury가 아니다. admin·guardian·underwriter·verifier 교체로 native requirement를 해제하는 상태 전이를 허용하지 않는다.

### GPU-014 — 경제 사건·정정·정산 대사의 골든 fixture

- 상태: DONE (2026-09-14, 5 golden fixtures executed; docs/gpu/execution/GPU-014.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-011, GPU-012, GPU-013, GPU-076
- 근거: PIVOT §6.2, §8.2~8.3, §10.3.
- 산출물: `docs/gpu/evidence-and-reconciliation.md`, `test/fixtures/gpu/settlements/`.
- 작업: economic event ID와 provider observation ID, chain tx/log ID, conversion/bridge leg, repayment allocation ID를 연결한다. earned→settled→paid는 같은 매출 lifecycle로, 수정은 원본 참조 reversal/delta로 정의한다.
- 완료 기준: 한 채권의 여러 지급·한 지급의 여러 채권 배분, source와 destination 통화 차이, 부분 취소·refund·이미 사용한 채권 정정 처리가 있다. adapter/schema version 변경이 경제 ID를 새로 만들지 않는다.
- 검증: 중복 API+서명+chain 관측, 같은 provider event ID의 다른 account/chain, 역순/겹친 기간, 완납 채권 재담보, 출처 불명 입금, source만 수령한 경우의 기대 원장과 합계.
- R2 필수 작업·완료/검증: GPU-076의 query cache ID, artifact ID, proof-bound source event ID, economic ID를 구분한다. receipt 내부 log ordinal과 RPC block-global logIndex를 혼동하지 않는다. 한 tx의 log 2개 각각 1회·공개 verify 선점 방지·자체 hash anchor의 부적격·caller height/time/index 변조를 골든 fixture에 포함한다.

## 5. 공통 저장소·인증·데이터 파이프라인

### GPU-015 — 공통 Python package와 핵심 도메인 DB migration

- 상태: DONE (2026-09-14, PostgreSQL 16 실검증; docs/gpu/execution/GPU-015.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-000, GPU-011, GPU-013, GPU-075
- 근거/읽기: PIVOT §8; prover `watcher.py`, legacy relayer `db.py`, 서비스별 `pyproject.toml`.
- 범위: 제안 `offchain/gpu/pyproject.toml`, `hashcredit_gpu/{domain,db}/`, `migrations/`; API/prover가 같은 package를 참조하게 구성.
- 작업: borrower/legal entity/provider account/authorization, asset/assignment/encumbrance, control agreement, facility/decision/policy의 FK·unique·check constraints 구현. Python venv에서 editable/dev 설치 및 재현 가능한 migration CLI를 제공한다.
- 완료 기준: 빈 PostgreSQL→head, 이전 schema fixture→head, backup/restore의 ID·관계·합계 보존. `create_all()`로 production migration을 대체하지 않는다. 민감 자료는 문서/secret 참조만 저장.
- 검증: 신규 PY-GPU(`test_schema.py`), PY-GPU(`test_migrations.py`), PY-API/PY-PROVER import smoke. SQLite만 통과하면 미완료.
- R2 필수 작업·완료/검증: provider/facility/decision에 requiredVerification·policyVersion·source namespace·executionProfile을 저장한다. native testnet 데이터의 production 재사용을 제약·migration 테스트로 거부한다.

### GPU-016 — 이벤트·현금·상환·작업 원장과 audit DB

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-014, GPU-015
- 근거: PIVOT §8.2~8.3.
- 범위: 공통 DB/migrations; raw events, receivables, settlements, cash receipts, allocations, recovery/writeoffs, audit, cursors/jobs/outbox/tx/exceptions.
- 작업: raw hash·schema/revision·원천/수집 시각 보존, 경제 사건 unique, immutable audit/정정 연결, 통화별 amount constraints. job 상태·attempt·lease·semantic idempotency key·tx nonce 인덱스를 구현한다.
- 완료 기준: 동시 insert·중복 revision·배분 합계 초과를 거부하거나 명시적으로 대사한다. 차주 refund/reserve와 LP cash 귀속이 조회에서 분리된다. migration 순서는 GPU-015와 충돌하지 않는다.
- 검증: 신규 PY-GPU(`test_event_ledger.py`), PY-GPU(`test_migrations.py`); PostgreSQL concurrency·rollback·restore 후 원장 합계 검사.
- R2 필수 작업·완료/검증: proof_requests/artifacts/native_verifications/evidence_consumptions(내부 제안)에 canonical query/event locator, artifact hash/ref, SDK/ABI/decoder/manifest 버전, destination verification/acceptance block·tx, 상태/attempt/reason을 저장한다. API ready·eth_call 성공·실제 native 확정·경제 소비를 독립 상태로 검증한다.

### GPU-017 — 법인·계정·GPU 권리 연결 서비스

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-015
- 근거: PIVOT §6.1, §11.
- 범위: `hashcredit_gpu/assets/`, account/encumbrance 서비스, 승인된 자료 참조 저장.
- 작업: provider account와 borrower/legal entity 연결, 자산 parent/partition/assignment/RMA 이력, 선순위·중복 양도 플래그, 등록/검증/거절 상태를 구현한다. UUID와 실제 소유권 검토 결과를 분리한다.
- 완료 기준: 같은 physical asset의 여러 listing이 자동으로 여러 담보가치를 만들지 않는다. 미확인 소유권/리스/우선권은 eligible=false; 계정 연결만으로 차주 등록·대출 승인되지 않는다.
- 검증: 신규 PY-GPU(`test_assets.py`): MIG 분할, NIC 변경, RMA replacement, 두 provider 동시 배정, 다른 차주 재연결, 기존 담보와 중복채권.
- R2 필수 작업·완료/검증: NFT/hash anchor·token transfer의 native 성공만으로 GPU 소유권·무담보·E2를 승인하지 않는 회귀를 추가한다.

### GPU-018 — GPU API 인증·객체별 권한·credentials 보관

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-001, GPU-013, GPU-015
- 근거: PIVOT §2.2, §7~8; 기존 `main.py`, `config.py`, claim/auth 패턴.
- 범위: `hashcredit_api/gpu/{auth,permissions}/`, 공통 authorization/secret 참조.
- 작업: 일회성 challenge·nonce·expiry·chain/app domain·borrower/account 결합, EOA/계약 지갑의 명시적 지원, 세션/CSRF/CORS·rate/크기 제한, 객체별 접근 검사를 구현한다. provider OAuth/token은 실제 방식만 지원한다.
- 완료 기준: 타 법인·account·facility ID 조회/수정 차단. 심사·funding·통제 변경은 별도 역할; credential은 response/log/fixture에 없다. 공개 API에 owner key를 되돌리지 않는다.
- 검증: 신규 API `tests/test_gpu_auth.py`로 replay·다른 chain/caller·만료·권한 해제·EIP-1271 실패·IDOR·secret redaction 검사; PY-API.
- R2 필수 작업·완료/검증: proof query도 허용 source/contract/profile에 제한한다. 사용자 입력 RPC/URL·verifier 주소·mock mode·trusted/bypass flag·mark-verified mutation을 거부한다. endpoint allowlist와 secret redaction 및 SSRF 방어를 검사한다.

### GPU-019 — ProviderAdapter 계약·capability·mock harness

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-014, GPU-015
- 근거: PIVOT §3, §8.1.
- 범위: `hashcredit_gpu/providers/{base,mock}.py`, 비식별 fixture·공통 contract tests.
- 작업: `listAssets/fetchRevenue/fetchSettlements/getControlState/claimRevenue/requestControlChange`의 입력·출력·cursor·에러·지원 capability를 타입으로 정의한다. read/write 지원은 독립이고 unknown은 unsupported다.
- 완료 기준: mock는 명시적 LOCAL 태그·별도 provider namespace로만 동작하고 production admission/decision을 생성할 수 없다. malformed response·누락 단위·불명 chain은 성공 처리하지 않는다.
- 검증: 신규 PY-GPU(`test_provider_contract.py`): pagination, unsupported write, expired data, revision, mock→production 경로 거부. 파트너 계정 없이 완료 가능한 티켓.
- R2 필수 작업·완료/검증: ProviderAdapter 사업자료 capability와 GPU-079 공식 proof capability를 분리한다. API 정상/공식 source 미지원, genuine testnet proof/mock provider도 production 부적격인 계약 테스트를 추가한다.

### GPU-020 — Aethir 읽기 connector와 정산 lifecycle 매핑

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-019
- 입력 조건: GPU-004에서 출처가 검증된 기술 schema·비식별 샘플·endpoint/auth 명세. 금융 우선권/계약 실사의 미완료 자체는 이 로컬 CODE 작업을 막지 않는다.
- 근거: PIVOT §3.2, §8.
- 범위: `hashcredit_gpu/providers/aethir.py`, 승인된 비식별 Aethir fixture.
- 작업: 실제 Host API/원장으로 host/group/GPU·stakeholder·service fee/reward·gross/net/penalty·earned/vested/claimable/withdrawn을 매핑한다. 수수료·vesting은 적용 버전/자료로 관리한다.
- 완료 기준: 샘플 statement의 금액·단위·시각·상태를 잃지 않고 정규화. endpoint/ABI·auth scope의 출처가 기록되고 Checker API/portal scraping으로 대체하지 않는다.
- 검증: 신규 PY-GPU(`test_provider_aethir.py`)로 문서화된 응답/에러/페이지 계약을 검증한다. schema/샘플도 없으면 stub까지만 작성하고 BLOCKED_EXTERNAL; 이를 DONE으로 표시하지 않는다. read-only smoke·전체 DD·실제 E2/회수는 GPU-056의 외부 통과 조건이다.
- R2 필수 작업·완료/검증: statement 필드를 공식 source event locator 또는 OFFCHAIN_ASSERTION으로 매핑한다. 로컬 connector 완료는 native 검증 완료가 아니며 미지원 source는 읽기만 가능하다. proof/E2 외부 대기 때문에 확인된 schema의 LOCAL 구현을 막지 않는다.

### GPU-021 — GPU.net 읽기 connector와 supplier 수익 매핑

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-019
- 입력 조건: GPU-005에서 출처가 검증된 현행 supplier 기술 schema·샘플·endpoint/auth 명세. 로컬 구현과 전체 금융 실사 완료를 구분한다.
- 근거: PIVOT §3.3, §8.
- 범위: `hashcredit_gpu/providers/gpunet.py`, 비식별 현행 supplier fixture.
- 작업: 실제 supplier account/machine/statement/payer/payee/token/chain·상업 매출/emission 분류. 지원되지 않은 지급/통제 기능은 typed unsupported로 유지한다.
- 완료 기준: tenant credits·Queen/Validator 보상·RWA 재판매를 rental receivable로 섞지 않는다. 과거 provider guide의 key/chain/보상식이 현행 설정에 자동 반영되지 않는다.
- 검증: 신규 PY-GPU(`test_provider_gpunet.py`)로 확인된 현행 사양을 검증. 사양/샘플 부재면 BLOCKED_EXTERNAL; read-only smoke와 전체 DD는 GPU-056의 외부 조건. Aethir 첫 출시를 막는 공통 선행으로 연결하지 않는다.
- R2 필수 작업·완료/검증: 정산 자료의 source contract/event locator와 API-only 항목을 분리한다. 로컬 supplier connector 완료를 공식 source 지원으로 간주하지 않으며 native 미지원 시 금융 admission은 비활성이다.

### GPU-022 — 수집 cursor·backfill·webhook·원문 보존

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-016, GPU-019
- 근거/읽기: PIVOT §8.3; 기존 prover `watcher.py`, `relayer.py`, `cli.py`.
- 범위: `hashcredit_prover/gpu/ingestion.py`, 공통 cursor/outbox, API webhook ingress.
- 작업: account별 영속 high-water/page token, 중첩 backfill, 정정 재조회, raw 저장+cursor+outbox atomic commit. webhook 서명/timestamp/replay·payload 크기·polling fallback 구현. 재시작 시 최근 10블록으로 초기화하지 않는다.
- 완료 기준: 429/timeout/중간 페이지 실패 뒤 누락 없는 재개; cursor 전진으로 저장 실패를 건너뛰지 않음. out-of-order·duplicate 입력 허용, 경제적 반영 한 번.
- 검증: 신규 PY-GPU(`test_ingestion.py`): commit 전후 crash, 중복 webhook/worker, 과거 지급 backfill, 잘못된 signature, source retention gap. LOCAL mock로 완료 가능.
- R2 필수 작업·완료/검증: 원문·cursor와 같은 transaction의 outbox로 GPU-079 proof 후보를 발행한다. 검증 전 OBSERVED/PENDING만 기록한다. API polling fallback은 native fallback이 아니다. 공식 outage 동안 cursor 보존·catch-up 후 proof 재개·한도 미증가를 검증한다.

### GPU-023 — 매출 분류·매출채권 원장·적격 borrowing base

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-007, GPU-014, GPU-016, GPU-022
- 근거: PIVOT §6.2~6.3.
- 범위: `hashcredit_gpu/revenue/`, `receivables/`, policy version 적용.
- 작업: 영업매출/자기 송금/인센티브/환급/차입금 구분, 기간·만기·양도·분쟁·선순위 공제, 이미 지급된 채권 제거, 부분 지급 잔액, reversal/delta 처리. GPU 가동률만으로 매출 생성 금지.
- 완료 기준: 같은 경제 사건의 API/서명/chain 자료가 세 번 매출로 계산되지 않는다. claimable 전 금액을 즉시 현금으로 보지 않는다. 채권 정정은 기존 부채를 지우지 않고 borrowing base/심사에 반영한다.
- 검증: 신규 PY-GPU(`test_receivables.py`): 기간 중첩, 같은 event revision, paid 재담보, 수수료 이중 공제, own transfer, refund·SLA·token 환산 단위.
- R2 필수 작업·완료/검증: proof validity·issuer/매출 provenance·미지급 적격 잔액을 모두 검사한다. verified own-transfer/임의 hash 게시/인센티브로 채권 생성 금지. 지급 proof는 잔액 감소 또는 이력이며 완납금을 trailing revenue 공식으로 다시 담보화하지 않는다. 보조 서명만으로 eligible이 되지 않는 회귀를 추가한다.

### GPU-024 — 현금 수령·분할/합산 정산 대사 엔진

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-012, GPU-014, GPU-016, GPU-023
- 근거: PIVOT §6.2, §8, §10.3.
- 범위: `hashcredit_gpu/settlement/`, source/debt chain event readers, reconciliation exceptions.
- 작업: receivable→settlement→source receipt→conversion/bridge leg→destination receipt→allocation 연결. token/chain/payer/payee/finality 검증, 소유권·fee·in-flight·unmatched money를 구분한다.
- 완료 기준: source 입금/bridge ack만으로 debt 감소 명령을 만들지 않는다. 다른 차주 돈·wrong token·출처 불명 입금은 exception으로 격리. 실제 대출 통화 수령 범위 이상의 배분 불가.
- 검증: 신규 PY-GPU(`test_reconciliation.py`): 다대다 지급, 부분·초과입금, 중복 log, reorg, destination 지연, 환전 비용, refund reserve, raw→원장 추적. 실제 온체인 상환 연결은 GPU-039/045.
- R2 필수 작업·완료/검증: source observed/native accepted/destination cash received/allocated를 분리하고 native accepted는 GPU-031/073의 앱 상태와 대사한다. 직접 destination 허용 토큰 상환에는 무관한 외부 proof를 요구하지 않는 테스트를 추가한다.

### GPU-025 — durable jobs·outbox·동시 worker·재시도

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-016
- 근거: PIVOT §8.3; legacy relayer의 failed row 재처리 문제.
- 범위: `hashcredit_gpu/jobs/`, outbox dispatcher, worker lease/dead-letter CLI.
- 작업: 작업 claim/lease 갱신·attempt·backoff·terminal/transient 구분, 사유 있는 manual resume, semantic idempotency, DB transaction과 outbox 연계를 구현한다.
- 완료 기준: 전달 자체의 exactly-once를 약속하지 않고 경제적 효과의 중복 방지를 검증한다. failed row 존재만으로 영구 skip되지 않는다. lease 만료 후 중복 실행에도 안전하다.
- 검증: 신규 PY-GPU(`test_jobs.py`) PostgreSQL 두 worker 경쟁, commit 직전/직후 종료, 중복 outbox, terminal 재개 권한·감사.
- R2 필수 작업·완료/검증: proof 준비 대기·artifact 확보·제출·확정·소비에 durable 상태를 둔다. not-ready/통신 장애/unsupported/invalid를 구분한다. 실패 뒤 signer-fallback job이 없고 재시도와 경제 사건 재소비가 분리됨을 검증한다.

### GPU-026 — EVM 전용 dispatcher·nonce·finality 복구

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-008, GPU-013, GPU-025, GPU-075
- 근거/읽기: PIVOT §8.3; API/prover `evm.py`.
- 범위: `hashcredit_gpu/transactions/`, `hashcredit_prover/gpu/tx_dispatcher.py`; API의 직접 owner 송신 대체.
- 작업: chain/signer별 nonce lock, simulation, fee/gas bound, pending/replaced/mined/finalized/reverted 상태, 재시작 reconciliation. semantic action ID와 transaction hash를 구분한다.
- 완료 기준: send 후 timeout을 실패 확정으로 간주해 중복 송금하지 않는다. application reservation 취소/만료와 늦게 mined된 tx를 대사한다. 읽기/attestation/treasury credentials가 분리된다.
- 검증: 신규 PY-GPU(`test_dispatcher.py`) 및 Anvil: nonce race, replacement, tx 성공/DB 실패, reorg, signer 중단·회복, duplicate semantic job. 실제 partner write는 GPU-038.
- R2 필수 작업·완료/검증: 금융 증거 제출은 내부에서 GPU-078을 호출하는 GPU-031/업무 앱의 stateful record/consume 진입점을 대상으로 한다. GPU-078 직접 호출은 검증 probe일 뿐 앱 기록/소비가 아니다. gas relay와 treasury 키를 분리하고 submission receipt/native 결과/앱 accepted·consumed를 따로 확인한다. SDK verifySingle/eth_call만으로 업무 DONE 금지, 실패한 proof를 다른 verifier로 재송신해 우회 금지.

### GPU-073 — 전체 v2 온체인 이벤트 projector와 read model 대사

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-008, GPU-016, GPU-025, GPU-029
- 근거: PIVOT §8.2~8.3, §9, §12; 외부 지갑·제3자 상환·직접 LP 거래도 authoritative 원장에 반영해야 함.
- 범위: `hashcredit_prover/gpu/chain_indexer.py`, `hashcredit_gpu/projections/`, deployment/chain cursor·block hash·reorg journal.
- 작업: 각 deployment block부터 provider/control/facility/debt/repay/LP/queue/recovery/governance 이벤트를 수집한다. 자체 dispatcher를 거친 tx로 제한하지 않는다. 영속 cursor, chunk backfill, finality, duplicate log, rollback/replay, schema/deployment version을 처리한다.
- 완료 기준: 외부 지갑의 직접 repayFor·LP deposit/withdraw·관리 변경도 API/credit read model에 반영된다. pending/finalized를 구분하고 canonical contract 조회와 debt/share/cash/예약 합계를 대사한다. projection lag 중 오래된 승인 발급을 차단한다.
- 검증: 신규 PY-GPU(`test_chain_projector.py`), Anvil fixture: 외부 signer tx, 처음부터 replay, reorg block 교체, tx 성공/DB commit 실패, 이벤트 순서·중복, 관리자 cap 변경, 미납 이자 view와 event만의 값 차이.
- 통합 조건: LOCAL은 GPU-029 이벤트 fixture로 시작 가능. GPU-055/057에서 실제 v2 contract 이벤트와 view를 다시 대사한다. 이 티켓은 분해 검토에서 추가되어 ID가 뒤지만 실행 위치는 데이터 기반 단계다.
- R2 필수 작업·완료/검증: native acceptance/consumption 및 verifier·proof policy·source 변경도 투영한다. API ready가 아닌 authoritative 앱 이벤트/상태로 판정한다. 외부 submitter·다중 log·destination reorg·profile 혼입·API 성공/앱 revert 사례를 테스트한다.

### GPU-027 — 심사·한도·노출·override 서비스

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-007, GPU-012, GPU-013, GPU-017, GPU-023, GPU-073
- 근거: PIVOT §6.3, §11.
- 범위: `hashcredit_gpu/credit/`, policy/credit decision, 심사 API 내부 서비스.
- 작업: 적격 순미수채권, 승인한도, 실제 원리금, reservation, 차주/그룹/provider/customer/DC/region/SKU/global headroom을 산정한다. freshness·현금 가용일·만기·비용·token 가격 정책, 승인/만료/철회, reason-bound override 구현.
- 완료 기준: 그룹 cap $10k·관련 전체 노출 $8k이면 추가 총액 ≤$2k. 만료된 데이터/통제/override는 새 승인 불가. policy update와 decision invalidation을 연결한다. 최종 draw는 온체인 재검증 대상이다.
- 검증: 신규 PY-GPU(`test_credit_decisions.py`): 동시 신청, 모든 facility 합계, 채권 일부 지급, stale/risk version, 여러 통화의 단위, cap 축소 후 debt 보존. 테스트 신용조건으로 로컬 완료 가능.
- R2 필수 작업·완료/검증: decision을 필요한 native event ID 집합·source·정책/manifest 버전·freshness에 묶는다. pending/invalid/unsupported·verified own-transfer·fully-paid collateral을 거부한다. manual override가 native requirement를 해제하지 못함을 GPU-081에서 통합 검증한다.

### GPU-028 — 보조 사실·통제·신용 승인 서명 (native 증명 대체 금지)

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-013, GPU-014, GPU-027, GPU-029
- 근거/읽기: PIVOT §7~8; `offchain/relayer/hashcredit_relayer/signer.py`.
- 범위: `hashcredit_gpu/authorizations/`, 별도 typed-data fixtures·역할 제한 발급 서비스. 기존 signer는 서명 유틸만 참고하고 BTC PayoutClaim 발급 경로는 가져오지 않는다.
- 작업: 차주 동의·심사 결정·권리/통제 확인·API 관측 보조 주장만 목적별 타입으로 서명한다. borrower/account/facility/terms·필요 native event ID 집합·source/profile·controlVersion/policyVersion·nonce/expiry/domain·signer epoch/quorum을 귀속한다. 보조 주장과 신용 실행 승인도 다른 타입으로 둔다.
- 완료 기준: 중복 signer로 quorum 증가 불가, 자체 collector 서명을 파트너 서명으로 표시 금지, mock 자료로 production 승인 발급 금지. source 거래 포함/receipt/token 입금을 이 서명만으로 VERIFIED 또는 borrowing-base 적격으로 만들 수 없다. 공식 verifier 장애/미지원 source 대체 발급 경로가 없다.
- 검증: 신규 PY-GPU(`test_authorizations.py`), GPU-031 공통 golden vector: domain/필드 변조·old/revoked key·expiry·중복 signer·목적 간 signature 재사용·이미 소비한 event/revision·native ID 누락/변조. 실제 native 연결과 최종 draw 거부는 GPU-081에서 재검증한다. 지갑 인증/약정 동의 서명 자체는 제거하지 않는다.

## 6. 금융 컨트랙트

### GPU-029 — Solidity 공통 타입·인터페이스·이벤트

- 상태: DONE (2026-09-14, solc 0.8.28; docs/gpu/execution/GPU-029.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-011, GPU-012, GPU-013, GPU-014
- 근거: PIVOT §6~7; 기존 `contracts/interfaces/`는 구조 참고만 사용.
- 범위: `contracts/gpu/interfaces/`, `types/`, 구현 없는 fixture/stub.
- 작업: DebtLedger/Vault/Manager/Verifier/Risk/Control/Escrow/Settlement/Repayment 경계를 정의한다. typed ID·asset unit·version·expiry·권한·오류·event topic과 회계 소유권을 NatSpec에 명시한다.
- 완료 기준: BTC sats/txid/vout가 공통 매출 타입에 남지 않는다. `repayFor`의 requested/received/applied/principalPaid/interestPaid/feePaid/excess/newDebt를 명확히 구분한다. view 검증과 경제 사건 consume 책임이 분리된다.
- 검증: 신규 SOL(`GPU029InterfacesTest`), `forge build --sizes`, Python/Solidity 공용 ABI fixture. implementation을 요구하는 순환 의존성을 넣지 않는다.
- R2 필수 작업·완료/검증: NativeProofEnvelope/VerifiedSourceEvent와 SupplementaryAssertion/CreditAuthorization을 타입 분리한다. 공식 ABI는 GPU-075, event schema는 GPU-076, native 검증은 GPU-078, 소비/경제 dedup은 GPU-031 책임이다. BTC ABI 확장이나 SDK wrapper method를 Solidity ABI로 추측하지 않는다.

### GPU-030 — 역할·provider/account/asset 등록과 지갑 귀속

- 상태: DONE (2026-09-14, 15 tests; AuthorizationVerifier 포함; docs/gpu/execution/GPU-030.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-013, GPU-029
- 근거: PIVOT §7, §11.
- 범위: `contracts/gpu/{ProtocolRoles,ProviderRegistry,AccountRegistry}.sol`; asset/encumbrance onchain 참조.
- 작업: registrar/underwriter/guardian/oracle/treasury 역할, 승인 provider/contract/token/chain, borrower↔account canonical 연결·변경 이력. EOA/EIP-1271 challenge의 caller/domain/nonce/deadline과 중복 귀속을 검증한다.
- 완료 기준: proof 서명 복사로 다른 차주에 account를 붙일 수 없다. 등록되지 않은 source는 거부한다. registry 등록 자체를 GPU 소유권·E2 인증으로 취급하지 않는다.
- 검증: 신규 SOL(`GPU030RegistryTest`): 다른 chain/contract/caller, 동일 nonce·만료, 계약지갑 reject, key rotation, 중복 account, 역할 우회. backend GPU-017/018과 필드 계약 일치.
- R2 필수 작업·완료/검증: source chain·issuer/emitter·event schema·token·account·upgrade 관리자와 policy version을 등록한다. 사건 당시/현재 account 귀속 변경 정책을 명세한다. 같은 signature의 가짜 emitter·미승인 proxy upgrade·등록되지 않은 issuer의 주입을 거부한다.

### GPU-031 — 공식 검증 결과 수용·보조 승인 분리·경제 사건 소비 원장

- 상태: DONE (2026-09-14, LOCAL; 22 tests; envelope 기반 consume·경제 ID dedup; revision↔economicEventId 규칙은 GPU-081 OPEN; docs/gpu/execution/GPU-031.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-014, GPU-029, GPU-030, GPU-078
- 근거: PIVOT §6.2, §7.
- 범위: `contracts/gpu/{EvidenceBook,AuthorizationVerifier}.sol`; 공식 proof adapter 자체는 GPU-078 담당이다.
- 작업: 고정된 GPU-078의 검증 결과만 VerifiedSourceEvent로 수용한다. source/provider/account/asset/event/issuer/revision·proof-bound locator·정책/유효기간을 기록한다. 보조 승인 서명은 별도 AuthorizationVerifier에서 epoch/quorum/domain/expiry를 확인한다. query verification cache, event 소비, economic lifecycle dedup을 서로 분리한다.
- 완료 기준: 공식 proof 없이 보조 서명/관리자/API로 native 사건을 등록할 수 없다. 공개 verify/record는 적법한 consumer의 소비 권리를 선점하지 않는다. 소비는 허용 consumer의 업무 반영과 원자적이다. 한 tx의 각 log는 각각 소비 가능하며 verifier/ABI 변경·다른 proof bytes·API 중복이 경제 사건을 새로 만들지 않는다. native 검증된 자체 주장도 provenance=OFFCHAIN_ASSERTION을 유지한다.
- 검증: 신규 SOL(`GPU031EvidenceTest`): native 실패/누락, 보조 signature 목적·domain·old/revoked/duplicate signer, front-run verify, 같은 tx의 log 2개·같은 log 재소비·다른 account/chain/token, 역순 revision, consumer 업무 revert 후 재시도, verifier 교체 후 replay. GPU-028 golden vector와 GPU-081의 금융 통합을 연결한다.

### GPU-032 — 지급 통제 registry·유효성·해제 상태

- 상태: DONE (2026-09-14, LOCAL; 18 tests; 실제 upstream lock은 GPU-009/056 외부 gate; docs/gpu/execution/GPU-032.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-013, GPU-029, GPU-030
- 근거: PIVOT §4, §7.
- 범위: `contracts/gpu/ControlRegistry.sol`, agreement reference와 control observation.
- 작업: 통제 대상 채권/account·beneficiary·범위·계약 hash·효력/만료·version·확인 증거·철회/변경/해제 조건을 저장한다. stale/withdrawn/version mismatch를 fail closed 처리한다.
- 완료 기준: 계정 연결은 E2로 자동 승격되지 않는다. 완제 판단은 authoritative debt 및 미결 약정과 연결되고 오래된 release proof는 거부된다. upstream 실제 lock은 GPU-009/056 외부 gate로 유지한다.
- 검증: 신규 SOL(`GPU032ControlTest`): 만료·폐기·version 변경↔draw/release race, 권한 없는 receiver·beneficiary 변경, 완제 후 미결 refund, 이전 그룹/재등록 ID 재사용.
- R2 필수 작업·완료/검증: 과거 lock event의 native proof는 현재 E2가 아니다. 통제 유효기간·해제·권한 변경·실제 upstream 우회 가능성 확인을 계속 적용한다.

### GPU-033 — 단일 채무 원장과 정확한 이자 계산

- 상태: DONE (2026-09-14, LOCAL; 22 tests, GPU-012 AC-01~06 vectors; docs/gpu/execution/GPU-033.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-012, GPU-029
- 근거: PIVOT §2.2, §7, §12.
- 범위: `contracts/gpu/DebtLedger.sol`, `libraries/InterestMath.sol`, 독립 모델 fixture 연결.
- 작업: facility별 principal/미납이자/fee·accrual anchor·rate terms, 시간 경과·부분 상환·원금화 정책·합계 조회를 구현한다. Manager/Vault는 독자적인 이자 계산을 하지 않는다. 기존 BTC 원장은 소급 변경하지 않는다.
- 완료 기준: 미납 이자가 timestamp 초기화로 사라지지 않는다. rate 변경 미지원이면 명시적으로 거부; 지원 시 구간 checkpoint로 소급 적용 방지. rounding 정책과 캐리 잔액이 분할 실행에 일관된다.
- 검증: 신규 SOL(`GPU033DebtTest`): $5,000/$500/$250→$5,250, 다중 차주, exact half-year rate 변경, 0시간/미세 상환/반복 accrual/상한값/자본화 비활성. 장기 무활동 facility의 미납 이자도 합계 view에 반영. reference model과 값 비교.

### GPU-034 — Vault 현금·대출채권·NAV·보호된 share 코어

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-012, GPU-029, GPU-033
- 근거: PIVOT §2.2, §7.
- 범위: `contracts/gpu/LendingVaultV2.sol`; loss/queue 인터페이스는 GPU-041/042에서 통합.
- 작업: authoritative ledger 기반 대출채권, LP 소유 현금·손상·지급채무, share conversion·deposit/즉시 출금·preview/minShares/minAssets를 구현한다. ERC-4626 채택 여부와 실제 충족 범위를 명세한다.
- 완료 기준: collateral receivables·차주 residual/refundable reserve를 NAV에 더하지 않는다. donation이 차주 상환이 되지 않고 초기 share/rounding 방어가 있다. 지급액/원금·이자 분류를 Vault가 임의 재계산하지 않는다.
- 검증: 신규 SOL(`GPU034VaultTest`): 1 base-unit 입금→100 USDC donation→200 USDC 입금, non-return ERC20·unsupported token, preview slippage, LP 지분 합계, 현재 현금 부족. 전액손실 후 LP 처리의 최종 통합은 GPU-042.

### GPU-035 — 온체인 borrowing base·집중도·실행 예약

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-007, GPU-012, GPU-029, GPU-030, GPU-031, GPU-033
- 근거: PIVOT §6.3, §7.
- 범위: `contracts/gpu/{ReceivableBook,GpuRiskPolicy,ExposureController}.sol` 또는 동일 책임의 모듈. 권장 하위 작업: GPU-035.a 적격채권/정정, GPU-035.b 노출/예약.
- 작업: 검증된 채권 집계/정정/paid 상태와 decision expiry를 반영하고 범주별 모든 debt+reservation을 합산한다. reservationId/approval nonce/expiry/cancelled/consumed 상태, authority와 cap 변경 invalidation을 구현한다.
- 완료 기준: reserve→draw 시 reserved 감소와 debt 증가가 원자적이며 이중 차감되지 않는다. 취소/만료/재사용 거부, offchain timeout만으로 onchain 예약 해제 금지. 한도 하락은 기존 debt를 지우지 않는다. v2에서 cap=0은 신규 실행 금지이며 무제한 sentinel로 사용하지 않는다.
- 검증: 신규 SOL(`GPU035RiskTest`): 그룹 $10k/미결 $8k→최대 $2k, 두 동시 예약·consume, 지급 채권 제거·부분 정정, stale policy/control, 여러 범주 겹침, 큰 값·단위·만기 전 현금 가용성. global cap $11k에서 A가 $10k·10%·1년 무활동이면 B의 $1 draw도 거부. NAV 상각과 cap 노출 감소는 자동 연동하지 않고 승인 정책으로 분리.
- R2 필수 작업·완료/검증: GPU-031에 기록된 native 사건과 GPU-076의 미지급 적격 잔액만 반영한다. 증거/정책 version·freshness를 draw에 연결하고 직접 signed revenue 경로를 두지 않는다. 미지원 source·hash anchor·완납 지급·verifier 변경을 통한 base 증가를 거부한다.

### GPU-036 — facility 승인·신규 draw의 원자적 실행

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-030, GPU-031, GPU-032, GPU-033, GPU-034, GPU-035
- 근거: PIVOT §5, §7.
- 범위: `contracts/gpu/CreditFacilityManager.sol`, terms/decision acceptance.
- 작업: borrower/facility/vault/asset/termsHash/policyVersion/controlVersion/nonce/expiry에 승인 귀속. 최신 debt·미납·유효 통제·현재 headroom·현금을 검증한 뒤 예약 consume/채무 증가/실송금을 원자 처리한다.
- 완료 기준: approve된 수취인 외 자금 이동 불가, token transfer 실패 시 전부 rollback. control/policy 변경 후 오래된 승인을 사용할 수 없다. 계약 약정 없이 자동 갱신/증액되지 않는다.
- 검증: 신규 SOL(`GPU036DrawTest`): front-run, 중복 nonce·예약, cap race, 멈춘 draw·유동성 부족·wrong vault/asset/borrower, late-mined expired approval, 부분 token 실패.
- 출시 조건: 로컬 fixture의 control/정책은 테스트 전용; 일반 고객/LP funded draw 활성화는 GPU-010/063 승인 이후. GPU-056의 승인된 소액 시험 대출은 §0.4 제한 실험 규칙을 따른다.
- R2 필수 작업·완료/검증: 최종 온체인 draw도 GPU-081 native requirement를 적용한다. API 검사나 심사 signature만으로 실행할 수 없고 필수 공식 증거 누락/만료/version mismatch를 거부한다.

### GPU-037 — source escrow·waterfall·잔여금·완제 해제

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-012, GPU-013, GPU-029, GPU-030, GPU-032, GPU-077
- 근거: PIVOT §4~5, §7, §10.
- 범위: `contracts/gpu/{RevenueEscrow,EscrowFactory}.sol`, upstream/repayment 인터페이스용 mock.
- 작업: provider/group/agreement별 통제 계좌, 약정된 운영비/reserve/debt sweep/residual 분배, 제한된 claim 대상·selector·recipient, release 후 권한 반환을 구현한다. 생성을 위한 factory는 필요한 경우만 둔다.
- 완료 기준: admin의 arbitrary call/approve/module 변경이 active agreement의 beneficiary를 우회하지 않는다. 여러 facility 우선순위와 초과금 소유권 명확. debt=0만으로 미결 정산·환불 조건을 무시해 해제되지 않는다.
- 검증: 신규 SOL(`GPU037EscrowTest`): 두 facility·부분 지급·duplicate sweep·wrong recipient·claim 재진입·미결 refund·오래된 release·완제 후 잔액 반환. upstream mock 성공과 E2 검증 분리.
- R2 필수 작업·완료/검증: GPU-077의 실제 입금/출처 분류를 연결한다. 임의 notify(amount)·기존 잔액 재보고·sweep 후 재통지로 매출 event를 생성하지 않는다. donation·fee-on-transfer·다중 payout·반복 notify 회귀를 추가한다. 원격 실행에 미출시 Writability를 가정하지 않는다.

### GPU-038 — 파트너 통제/claim 실행 adapter와 효과 확인

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-013, GPU-019, GPU-025, GPU-026, GPU-032, GPU-037
- 입력 조건: 실제 partner binding에는 GPU-020 또는 GPU-021의 기술 명세·선택 connector가 필요. 공통 executor LOCAL 구현은 이 외부 입력 없이 진행 가능.
- 근거: PIVOT §4, §8.3.
- 범위: provider별 `control/claim` adapter, `hashcredit_prover/gpu/control_executor.py`.
- 작업: 실제 제공된 API/contract만으로 claim·수령 설정·약정상 release를 수행한다. 요청/ack/최종 적용 관측을 분리하고 nonce/idempotency·재시도·승인 사유·허용 대상·한도를 연결한다.
- 완료 기준: 공통 executor와 확인된 interface의 fail-closed 처리를 LOCAL로 검증하면 CODE 완료 가능하다. `partner_binding=UNCONFIGURED/SANDBOX_VERIFIED/LIVE_VERIFIED`를 별도 기록하고, 미지원 provider는 write 비활성이다. 200 응답만으로 lock/claim 완료가 되지 않고 읽기 credentials로 write하지 않는다.
- 검증: 신규 PY-GPU(`test_control_executor.py`): timeout 후 실제 적용, ack 후 미적용, 중복 claim, revoked scope, 권한 없는 release. 실제 binding·승인된 sandbox 효과 확인·실금 회수는 GPU-056의 필수 외부 검증에 포함한다.
- R2 필수 작업·완료/검증: 실제 source-chain tx/허용 API executor와 Attestcoin Readability 역할을 구분한다. Writability inbox/outbox가 이미 사용 가능하다고 가정한 구현을 금지한다.

### GPU-039 — repayFor·실수령금·원리금 배분 router

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-012, GPU-029, GPU-033, GPU-034, GPU-036, GPU-037
- 근거: PIVOT §5~7, §10.3.
- 범위: `contracts/gpu/RepaymentRouter.sol`, debt/Vault 제한된 상환 hook.
- 작업: payer와 debtor facility 분리, 실제 received amount 기반 allocation, 단일 원장의 interest/principal/fee 배분, requested/received/applied/excess 반환·event를 구현한다. 직접 상환의 cap-before-transfer와 이미 escrow에 들어온 초과금을 구분한다.
- 완료 기준: `received = principalPaid + interestPaid + feePaid + excess`를 같은 수령/귀속 경계에서 만족. 다른 차주의 원금 불변, source statement만으로 상환 불가. surplus 반환/credit 정책과 owner가 명확하다.
- 검증: 신규 SOL(`GPU039RepaymentTest`): 부분 이자·전액/초과·부채0·제3자·wrong facility/token·non-return ERC20·재진입·paused draw 중 상환·동일 receipt 재사용. SOL-FULL.
- R2 필수 작업·완료/검증: 공식 proof 서비스 down 중 직접 repayFor 성공, source native proof만 있고 destination 현금이 없으면 debt/NAV 불변을 추가 검증한다.

### GPU-040 — 환전·bridge/정산·destination 수령 adapter

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-008, GPU-024, GPU-026, GPU-037, GPU-039
- 근거: PIVOT §10.
- 범위: `contracts/gpu/SettlementReceiver.sol`, 승인된 `ISettlementAdapter` 구현, worker 결제 leg 추적.
- 작업: 허용 asset/chain/router·quote expiry·minOut·slippage/수수료 한도·refund 경로. source→conversion→in-flight→actual destination token receipt→repayFor를 연결한다. 같은 체인이면 bridge 없이 같은 수령 원칙을 적용한다.
- 완료 기준: proof/message/송금 tx hash만으로 debt 감소 불가. 외부 source 사건을 금융 상태에 반영하는 검증은 공식 Attestcoin 필수이며 보조 서명으로 대신하지 않는다. 중복 전달·재시도·부분 도착을 식별하고 양 체인에서 같은 금액을 이중 상환하지 않는다. 목적지 직접 실수령 상환은 별도 현금 경로다. 환전/bridge/정산은 실제 제공되는 승인 레일만 쓰고 Writability/무신뢰 bridge가 이미 출시됐다고 가정하지 않는다.
- 검증: 신규 SOL(`GPU040SettlementTest`), PY-GPU(`test_settlement_legs.py`): wrong chain/token/beneficiary, stale price, illiquidity, minOut 실패, bridge 지연·재조직·중복 message·refund.
- 출시 조건: 로컬 테스트 adapter만 있는 경우 LOCAL 완료로 한정하고 GPU-056에서 실제 route를 별도 검증한다.

### GPU-041 — 연체·default·reserve·손상·상각·후속 회수

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-012, GPU-013, GPU-033, GPU-034, GPU-036, GPU-039
- 근거: PIVOT §5.3, §7, §11~12.
- 범위: `contracts/gpu/RecoveryManager.sol`, ledger/Vault loss hook.
- 작업: due schedule/grace/cure/dispute/default, 미수이자 인식 중단/손상 정책, funded reserve의 소유권별 충당, write-off·상각 후 회수·계약 종료를 구현한다. 법적 채무와 NAV 손실을 따로 보존한다.
- 완료 기준: API 장애/가동률 하락만으로 자동 처분하지 않는다. write-off≠면제, 같은 손실 이중 인식 금지, 차주 환불 reserve를 LP 손실에 임의 사용하지 않음. 연체 중 자발적/자동 상환 유지.
- 검증: 신규 SOL(`GPU041RecoveryTest`): cure·부분손상·전액상각·late recovery·reserve 부족·중복 loss event·수익 sweep 확대 조건·동일 자산 이중 NAV 반영.

### GPU-042 — 출금 queue·손실 귀속·전액손실 후 LP 처리

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-007, GPU-012, GPU-034, GPU-041
- 근거: PIVOT §7, §9, §12.
- 범위: `contracts/gpu/WithdrawalQueue.sol` 또는 확정된 출금 정책 모듈, Vault 통합.
- 작업: 요청/취소/부분 이행/claim·순서·현금 제한·share 가격 확정 시점·출금 중 손실 귀속을 정의대로 구현한다. insolvency/재자본화/새 epoch 시 기존 LP의 회수 권리를 보존한다.
- 완료 기준: queue 참가가 과거 손실을 다른 LP에 떠넘기는 우회가 되지 않는다. GPU-034의 즉시 withdraw/redeem을 포함한 모든 출금 진입점이 같은 현금 예약·우선순위를 적용한다. 전액손실 후 신규 LP가 기존 회수권을 탈취하지 않음. facility 표시만으로 손실 격리 주장 금지.
- 검증: 신규 SOL(`GPU042WithdrawalsTest`): 동시 요청/취소, A의 queue 대기 중 B가 직접 withdraw/redeem으로 예약 현금 인출 시도, 부분 유동성, NAV 감소 전후, 전액손실→새 입금→late recovery, minAssets, duplicate claim, rounding.

### GPU-043 — governance·pause·wiring·키 교체 통제

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-030, GPU-031, GPU-032, GPU-036, GPU-037, GPU-039, GPU-041, GPU-042
- 근거: PIVOT §2.2, §7, §13.
- 범위: v2 관리자 권한, multisig/timelock 연결, emergency function 분리.
- 작업: draw/evidence/conversion/repayment pause 범위, guardian의 한계, verifier/signer/key rotation·policy 변경, 일회성 안전 wiring 또는 검증된 migration 경계를 구현한다.
- 완료 기준: 활성 부채 중 owner가 manager/vault/asset/beneficiary를 임의 교체할 수 없다. emergency draw freeze 중 허용 회수는 유지된다. 관리 변경은 event·대기/승인 경로가 있고 mock grants가 v2 ABI에 없다.
- 검증: 신규 SOL(`GPU043GovernanceTest`): 권한 상승, timelock 우회, debt 있는 wiring 변경, old signer 폐기, pause 조합과 repay, release backdoor. SOL-FULL.
- R2 필수 작업·완료/검증: production requiredVerification은 ATTESTCOIN_NATIVE다. owner/policy/emergency 변경으로 signed/mock로 downgrade하지 못한다. decoder/ABI/verifier 변경에는 호환성·replay 보존·영향 재검증이 필요하며 임의 mock 주소 활성화를 거부한다.

## 7. 운영 서비스·API·프런트엔드

### GPU-044 — 통제/약정 모니터와 회수 case workflow

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-013, GPU-024, GPU-025, GPU-027, GPU-032, GPU-041, GPU-079
- 근거: PIVOT §5.3, §8.3, §11.
- 범위: `hashcredit_prover/gpu/{control_monitor,covenants,recovery_worker}.py`, case/action/audit 서비스.
- 작업: stale observation·API 장애·실제 통제 위반·지급 연체를 구분한다. draw freeze 신호, grace/cure/dispute, 승인된 회수 요청·ack·효과 확인·미결 exception·write-off 업무를 연결한다.
- 완료 기준: 관측 실패로 자동 default/원격 shutdown하지 않는다. 모든 조치에 사유·약정/권한·승인자·대상·deadline·실제 효과가 있다. worker는 idempotent intent를 만들고 미지원 write를 실행 완료로 표시하지 않는다.
- 검증: 신규 PY-GPU(`test_monitoring.py`), PY-GPU(`test_recovery_workflow.py`): 지연→복구, 200 ack/미적용, 중복 action, 통제 만료, 미결 refund. 실제 조치는 GPU-038/056에서 통합.
- R2 필수 작업·완료/검증: proof 준비 지연·attestation lag·invalid·환경 drift를 차주 연체/통제 위반과 구분한다. outage로 자동 default 금지, 새 증거가 필요한 실행만 제한하고 직접 상환/회수를 유지한다. signer bypass를 복구 action으로 생성하지 않는다.

### GPU-045 — GPU 제품 API·read model·권한 있는 mutation

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-017, GPU-018, GPU-024, GPU-026, GPU-027, GPU-036, GPU-039, GPU-041, GPU-042, GPU-044, GPU-073, GPU-081
- 근거: PIVOT §8~9.
- 범위: `hashcredit_api/gpu/` router/service, `main.py` GPU mode, OpenAPI contract.
- 작업: `/v1/providers`, connections/assets/facilities/receivables/settlements/controls/repayments/recoveries/LP/operations API를 정의대로 구현한다. GPU-073의 전체 chain read model에 canonical block·freshness·evidence level·금액 단위를 포함한다. write는 검증된 payload 또는 role-bound queue intent로 제한한다. GPU app factory/entrypoint는 `main.py`의 BTC crypto/RPC/proof 최상위 import와 분리한다.
- 완료 기준: 조회 성공과 금융 승인·자금 실행을 구분한다. 객체별 RBAC·pagination·idempotency·상태 오류가 일관된다. 비밀정보/고객 workload 비노출. BTC crypto/RPC package·Bitcoin 환경변수 없는 GPU 이미지에서도 import/start/readiness가 성공하며 legacy app은 별도 유지한다.
- 검증: 신규 API `tests/test_gpu_api.py`: 다른 borrower/role, stale reads, amount precision, 중복 mutation, 취소/정정, backend tx pending·revert, old BTC write route 비활성. PY-API.
- R2 필수 작업·완료/검증: proof requested/ready/native accepted/business eligible/cash received/repayment applied를 독립 API 필드로 제공한다. verified boolean 하나로 축약하지 않는다. API/admin mutation의 mark-verified 및 검증수준 변경을 거부하는 테스트를 추가한다.

### GPU-046 — ABI·OpenAPI 타입 생성과 deployment manifest 연결

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-008, GPU-029, GPU-045, GPU-075, GPU-078
- 근거: PIVOT §9~10; web `lib/abis.ts`, `lib/env.ts`, `types/index.ts`, `use-contracts.ts`.
- 범위: `script/gpu/generate_types.*`, web generated ABI/DTO, shared manifest loader.
- 작업: 실제 Foundry artifact/OpenAPI로 ABI·DTO 생성/검사 명령을 추가한다. chain·token·decimals·explorer·contract·API version·deployment mode를 manifest에서 읽는다. 생성물은 수동 편집하지 않는다.
- 완료 기준: API/Solidity event/프런트엔드 amount와 enum이 drift하지 않는다. chain key와 EVM chain ID 혼동, zero/wrong-chain contract, 알 수 없는 token은 configuration error다. 명령·원본·생성물 위치가 문서화된다.
- 검증: 신규 generation drift 검사, manifest fixtures, WEB. 생성 명령 두 번 실행 시 변화 없음; release 주소는 실제 검증 전 fixture로만 존재.
- R2 필수 작업·완료/검증: requiredVerification/profile, 환경별 source ID↔chainKey/encoding, SDK/ABI/decoder provenance·manifest hash·실제 verifier binding·deployment block을 생성물에 포함한다. 앱/source/외부 decoder는 code/권한 검증, native precompile은 공식 ABI capability 검사로 구분한다. native/prod mock binding은 실패다.

### GPU-047 — GPU 앱 shell·wallet·state·legacy namespace

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-046
- 근거/읽기: PIVOT §9; `app-shell.tsx`, stores, `hooks/use-api-client.ts`, `lib/constants.ts`.
- 범위: 앱 route/tab 구성, chain guard, versioned localStorage, query/state invalidation.
- 작업: 연결 wallet/account/chain 변경 시 이전 요청을 취소하거나 무효화한다. 조회 차주와 서명자가 다르면 write를 제한한다. 기존 BTC localStorage는 GPU 계정/한도로 해석하지 않고 legacy namespace로 보존한다.
- 완료 기준: tx helper의 invalid address early return이 성공 처리되지 않는다. unsupported chain·missing manifest·pending tx가 명확하다. BTC onboarding/proof 화면은 GPU route에서 제외하되 legacy 조회 계획을 보존한다.
- 검증: WEB, state 전이 fixture/수동 재현 기록. GPU-052 도입 후 wallet switch·stale response·storage migration 자동 회귀를 연결한다.
- R2 필수 작업·완료/검증: profile/source/verifier policy 변경 시 이전 proof/승인/cache/localStorage를 무효화한다. mock/public testnet/production을 명시하고 서명으로 대신 진행 UI는 없다. legacy read fallback은 native downgrade가 아니다.

### GPU-048 — 공급자 연결·권리 자료·통제·심사 onboarding

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-018, GPU-045, GPU-047
- 근거: PIVOT §9; `features/dashboard/claim-section.tsx` 대체.
- 범위: provider selection/connection, account/asset 증거 제출 참조, control/underwriting/terms 동의 화면.
- 작업: 연결·권리 확인·통제 검증·신용 승인·실행 가능을 별개 상태로 구현한다. 필요한 파트너 인증 방식과 지원 capability만 노출한다. 동의할 만기·회수 비율·지급 제한·연체·완제 후 해제를 보여준다.
- 완료 기준: E0/E1·미심사·만료·unsupported provider에는 borrow CTA가 활성화되지 않는다. 사유/다음 단계가 보이고 secret/실물 자료 원문이 브라우저 저장소에 남지 않는다.
- 검증: WEB, 승인/거절/철회/외부 대기/법인 권한 없음 시각 검토. GPU-052에서 fixture 기반 전이 E2E 추가.
- R2 필수 작업·완료/검증: 공식 지원·필요 사건의 native 상태·매출 출처를 연결/권리/E2/심사와 별도 표시한다. 필수 공식 증거 없음/미지원이면 borrow CTA 차단, native 배지를 GPU 소유권/E2로 표시 금지.

### GPU-049 — facility dashboard·차입·상환·완제 UX

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-036, GPU-039, GPU-045, GPU-047
- 근거: PIVOT §5, §9; borrower card/hooks.
- 범위: facility별 원금·미납이자·만기/납기·유효 한도·reservation·회수 내역·borrow/repay.
- 작업: 미수·claimable·source/in-flight·실제 상환을 구분한다. quote/decision 만료, updated debt, 승인/송신/pending/finalized/revert 상태를 처리한다. frozen/delinquent에도 허용 상환을 제공한다.
- 완료 기준: 다른 facility/payer로 상환 오배분하지 않는다. 초과금·원리금 배분·남은 debt가 이벤트/원장과 일치한다. debt=0과 control released를 별개로 표시한다.
- 검증: WEB, 금액 경계·지갑 교체·동시 draw/repay·pending replacement·재시도 시각 확인. GPU-052 E2E에서 source receipt만 있는 상태의 debt 불변 검사.
- R2 필수 작업·완료/검증: proof 준비/확정과 실수령/상환을 별도 단계로 보여준다. proof 성공만으로 debt 감소/한도 증가 표시 금지. source/destination tx·event 링크와 proof 장애 중 직접 상환 UX를 검증한다.

### GPU-050 — LP 자산·실현 수익·노출·출금 화면

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-034, GPU-041, GPU-042, GPU-045, GPU-047
- 근거: PIVOT §9; `features/pool/*`, `use-vault-info.ts`.
- 범위: deposit/withdraw/queue/cancel/claim, NAV·cash·debt·impairment·reserve·provider exposure.
- 작업: borrower APR와 LP realized/estimated yield를 구분하고 기간/수수료 기준을 표시한다. token decimals·minShares/minAssets·미결 queue·유동성 제한·손실 귀속을 확정 계약대로 연결한다.
- 완료 기준: 원금보장·고정 LP 수익으로 표현하지 않는다. borrower-owned reserve와 in-flight를 가용 LP 현금으로 보여주지 않는다. 전액손실·late recovery·새 epoch 권리를 올바르게 표시한다.
- 검증: WEB, GPU-052의 LP E2E: donation slippage, 충분하지 않은 현금, 일부 출금 이행, NAV 감소, queue 취소·중복 claim·wrong chain.
- R2 필수 작업·완료/검증: proof count/verified amount 합계를 NAV·현금에 가산하지 않는다. 검증 지연에 따른 신규 실행 제한과 실제 회수 손실을 구분하는 UI 테스트를 추가한다.

### GPU-051 — 심사·대사 exception·회수 operator console

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-044, GPU-045, GPU-047
- 근거: PIVOT §8.3, §9, §11; 기존 `features/admin`, `operations`, `proof` 참고.
- 범위: 권한 있는 별도 운영 route, case 목록·상세·감사 이력.
- 작업: 심사 memo/정책/override 승인, raw→settlement→cash trace, unmatched money, dead-letter·pending tx, 통제·연체·회수 요청/효과 확인을 제공한다. 각 mutation에 reason·현재 version·권한 검사를 연결한다.
- 완료 기준: receipt/ack/실효 상태를 구분하고 alert owner·기한·runbook이 있다. 고객 workload·secret은 미노출. UI 숨김만으로 권한을 구현하지 않는다.
- 검증: WEB, GPU-052 역할별 E2E: 타 차주·무권한, 동시 승인·expired override, 중복 manual retry, 효과 미확인, stale ledger warning.
- R2 필수 작업·완료/검증: query→artifact hash/version→native acceptance→economic mapping→cash trace와 proof 장애 queue를 추가한다. retry는 가능하나 mark-verified/mock 전환/자체 signer 강제 통과 버튼은 없다.

### GPU-052 — 프런트엔드 unit·접근성·통합 E2E 기반

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-047, GPU-048, GPU-049, GPU-050, GPU-051
- 근거: PIVOT §9, §12; `apps/web/package.json`에는 기존 test script 없음.
- 범위: web unit runner/Playwright 등 필요한 도구, `test`/`test:e2e` scripts, 비식별 UI fixtures.
- 작업: §0.6 명령을 실제 생성하고 local API/Anvil 또는 명시적 fixture server를 사용한다. mock UI 테스트와 실제 contract E2E 결과를 구분한다. keyboard·focus·오류/진행 상태·모바일 금액 표시를 검증한다.
- 완료 기준: onboarding→승인→borrow→source receipt→실제 repay→release/LP withdrawal의 주요 전이, role/chain/account 변경과 실패 경로가 자동화된다. screenshot만으로 금융 흐름 성공을 판단하지 않는다.
- 검증: WEB, WEB-TEST, WEB-E2E. 테스트 개수·브라우저 설치·서버 포트·실행 방법을 기록하며 live wallet/credential을 CI에서 요구하지 않는다.
- R2 필수 작업·완료/검증: native pending/invalid/unsupported→draw 거부, accepted/cash 미수령→debt 불변, 장애 중 direct repay, profile 혼입·잘못된 매출 provenance를 테스트한다. LOCAL UI E2E는 GPU-080 NATIVE_TESTNET 증거가 아니다.

## 8. 운영 기반·종합 검증

### GPU-053 — 로컬/배포 서비스 구성·의존성·키 분리

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-015, GPU-016, GPU-025, GPU-026, GPU-028, GPU-045, GPU-079
- 근거/읽기: PIVOT §8, §13; Compose/Railway/Dockerfile/start-worker, `.env.example` 계열.
- 범위: 공통 package 포함 build, GPU API/ingestion/공식 proof client·relay/심사 authorization/treasury dispatcher 역할, Postgres, GPU fixture 환경.
- 작업: 고정 BTC 주소 JSON 주입을 승인된 DB connection으로 대체한다. public API/read collector/proof relay/심사 승인/funds signer 권한을 분리하고 secret reference·rotation·로그 redaction·리소스 한도를 구성한다. GPU active profile에서 불필요 BTC 의존성을 제외하되 legacy profile 보존.
- 완료 기준: fixture env만으로 재현 가능한 local stack, BTC crypto/RPC 없는 GPU app과 `coincurve` 등 필요한 legacy profile의 import/start 분리 확인. Node/Python/Foundry·lockfile 전략이 일관되고 실제 key/URL secret을 config 출력에 포함하지 않는다.
- 검증: 이 티켓에서 생성한 가짜 값 전용 `test/fixtures/gpu/local.env`를 사용해 `docker compose --env-file test/fixtures/gpu/local.env config`, image build·local startup·health/readiness·직접 권한 접근 거부. 실제 credentials가 없는 격리 환경에서 실행하며 Railway 배포는 GPU-063.
- R2 필수 작업·완료/검증: 공식 SDK proof client/relay와 underwriting authorization을 분리하고 TS package의 lock/build/JSON 경계를 포함한다. native/prod 시작점에서 mock verifier/precompile/RPC·강제 VERIFIED 및 signer-fallback 설정을 거부한다. NATIVE_TESTNET의 실제 배포 TEST_ONLY source는 §0.2에 따라 허용하지만 production admission은 금지한다. ASC-CHECK/ASC-TEST와 profile별 readiness·권한·secret redaction을 검사한다.

### GPU-054 — CI의 금융·DB·웹·보안 gate

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-000, GPU-015, GPU-016, GPU-029, GPU-052, GPU-053, GPU-082
- 근거: PIVOT §12~13; `.github/workflows/test.yml`.
- 범위: Foundry/Python/Postgres/web build/lint/unit/E2E, 생성물 drift, dependency/secret scan.
- 작업: 무조건 허용인 Slither `continue-on-error`를 제거하고 필요한 예외만 사유·범위·만료로 기록한다. fixture 기반 CI에는 live credentials가 필요 없어야 한다. 실제 파트너 테스트는 별도 명시적 실행 gate로 둔다.
- 완료 기준: 보안/회계/타입 테스트 실패가 release gate 실패로 이어진다. 테스트 0개·전부 skip·missing tool을 성공으로 보고하지 않는다. 후속 GPU-055/057 script도 존재하는 시점에 등록한다.
- 검증: local CI-equivalent 명령과 승인된 CI 실행 결과. 고의 실패 fixture가 pipeline을 실패시키는지 확인하고 정상 복구; 비밀정보가 fork PR 로그에 노출되지 않음.
- R2 필수 작업·완료/검증: LOCAL deterministic, GPU-082 공식 artifact/encoding 호환성, GPU-080 실제 native-testnet job을 구분한다. LOCAL은 네트워크와 독립이다. network BLOCKED/SKIPPED는 G-ASC PASS가 아니다. ASC-CHECK/ASC-TEST와 mock binding/downgrade 거부를 CI에 연결한다.

### GPU-055 — 전체 금융 상태 머신 differential·invariant 검증(G2 일부)

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-012, GPU-031, GPU-032, GPU-033, GPU-034, GPU-035, GPU-036, GPU-037, GPU-039, GPU-040, GPU-041, GPU-042, GPU-043, GPU-081, GPU-082
- 근거: PIVOT §12; 기존 invariant handler의 borrow/repay/시간 경과 누락.
- 범위: `test/gpu/invariant/`, independent reference model·golden fixtures.
- 작업: handlers에 borrow/repay/warp/policy/control/reservation/withdraw/loss/recovery를 실제 포함한다. unit test를 이 단계까지 미루지 않으며 조합 상태·장기간·다중 actor를 검증한다.
- 완료 기준: 채무/현금/NAV/귀속 보존, 최신 한도 내 신규 draw, 실제 수령 전 debt 감소 금지, 중복 경제 반영 금지. “언제나 debt≤limit”을 불변식으로 사용하지 않는다. handler별 호출 분포를 확인한다.
- 검증: 신규 SOL(`GPU055.*`), 명시한 invariant runs/depth/seed와 SOL-FULL. 발견 실패를 expectation 완화/skip으로 숨기지 않고 해당 구현 티켓으로 환류한다.
- R2 필수 작업·완료/검증: native invalid/unsupported·검증 지연·보조 서명·verifier/governance 변경을 handlers에 추가한다. proof requirement 우회 없음·proof만으로 debt/NAV 변화 없음·paid 재담보 불가·장애 중 direct repay 유지를 검증한다.

### GPU-056 — 선택 파트너의 실제 통제·자금·상환 E2E(G3)

- 상태: TODO
- 유형/우선순위: LIVE / P0
- 선행: GPU-009, GPU-010, GPU-024, GPU-028, GPU-038, GPU-039, GPU-040, GPU-043, GPU-055, GPU-062, GPU-080, GPU-081, GPU-082
- 선택 선행: GPU-020 또는 GPU-021 중 실제 시험 파트너 DONE.
- 근거: PIVOT §4.3, §10, §12.2.
- 산출물: `docs/gpu/verification/<provider>/`, 승인된 integration harness·증거 참조.
- 작업: 확정 manifest와 승인된 소액·계정으로 statement→source claim/withdraw→환전/전송→destination 실제 수령→원리금 차감→완제/권한 해제를 대사한다. 최종 구현으로 receiver 변경·복구·재등록·release race도 재검증한다.
- 완료 기준: 실제 돈·event·DB·차주/Vault 잔액 일치. 기발생 담보채권의 차주 단독 지급 우회 불가. vesting/claim/withdraw의 실제 calendar를 기다리고 결과를 기록한다.
- 외부 조건: G1=APPROVED, 선택 파트너 DD의 필요한 capability PASS, read-only smoke 및 GPU-038 실제 write binding/SANDBOX 효과 검증, 시험 배포/거래 권한·예산·기간·실제 지급/접근. mock나 sandbox 수치만 있으면 LIVE 완료 금지. 이는 제한된 검증이며 일반 사용자 자금 모집 허가가 아니다.
- 검증: contract/chain/block/tx/amount/unit/소유권·request/effect·실패 복구 증거; confidential raw 대신 안전한 참조. 금액 합계를 독립 계산.
- R2 필수 작업·완료/검증: 선택 provider 원천 사건이 공식 SDK→native→앱 소비를 실제 통과한 증거를 권리/E2/현금과 연결한다. 개발자 test payout, 우리 API hash anchor, 미지원 원천은 실제 파트너 native/E2 증거를 대체하지 못한다. G-ASC와 실제 source/환경 차이를 재검증한다.

### GPU-057 — 정상·연체·회수·손실·LP 출금 로컬 E2E(G2)

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-022, GPU-023, GPU-024, GPU-025, GPU-026, GPU-028, GPU-031, GPU-038, GPU-040, GPU-041, GPU-042, GPU-044, GPU-045, GPU-053, GPU-055, GPU-073, GPU-079, GPU-081, GPU-082
- 근거: PIVOT §5.3, §8.3, §12.
- 범위: 신규 `script/gpu/e2e_local.sh`, isolated Postgres/Anvil/mock provider scenarios.
- 작업: 생성→연결/심사→통제→draw→정산/repay→grace/cure/default→reserve/write-off→late recovery→LP 출금/완제해제를 실행한다. 수집/tx/DB의 crash point, partial payment와 refund를 삽입한다.
- 완료 기준: 각 경계의 현금·법적 채무·NAV·차주 residual이 reference model과 맞는다. source/receipt와 승인 nonce의 중복이 효과를 두 번 만들지 않는다. mock 환경 표시와 live broadcast 차단이 확실하다.
- 검증: V2-E2E, PY-API/PY-PROVER/PY-GPU 관련 suite, SOL-FULL. 매 실행 독립 DB/체인과 결정적 fixture를 사용; 사용자 workspace/DB를 초기화하지 않는다.
- R2 필수 작업·완료/검증: LOCAL_MOCK만 precompile substitute를 허용하되 production과 같은 envelope/status/no-downgrade 계약을 쓴다. invalid/unavailable/tampered·다중 log·SDK process crash를 테스트한다. 이 완료는 G-ASC를 충족하지 않는다.

### GPU-058 — 위협 모델·독립 보안/회계 검토·감사 대응

- 상태: TODO
- 유형/우선순위: DD / P1
- 선행: GPU-043, GPU-054, GPU-055, GPU-057, GPU-080, GPU-082
- 근거: PIVOT §7, §11~12.
- 산출물: `docs/gpu/security-review.md`, audit scope/evidence/remediation tracker.
- 작업: owner/admin·signer·oracle·파트너·bridge·DB·worker·UI trust boundary, 수익 우회, forged revenue, reservations, 회계/share·손실 귀속을 독립 리뷰한다. 외부 감사자에게 고정 commit/약정/테스트/실패 사례를 제공한다.
- 완료 기준: 중대 발견 해결 또는 실제 책임자의 명시된 수용/출시 보류, 수정 후 재검증·version 추적. 자체 리뷰를 외부 감사로 표기하지 않는다. 선택 live adapter 수정은 다시 검토한다.
- 외부 조건: 외부 감사 요구 범위·일정·책임자의 검토. 도구 검사·자료 패키지만 완료되면 DD 전체는 미완료로 기록.
- 검증: 공격/오류 재현→수정→회귀 증거, 실제 audit report 참조, 미해결 항목과 출시 영향.
- R2 필수 작업·완료/검증: query→검증 bytes→event→borrower/receivable 의미 결합, source provenance·보조 승인 경계·prover/relay 변조/DoS·다중 log replay·downgrade를 감사한다. GPU-080/082 결과와 commit/manifest를 대조한다. native 외부 대기 중 LOCAL 리뷰는 준비하되 DD 전체 완료를 조작하지 않는다.

### GPU-059 — 관측·성능 한도·백업/복구·운영 drill

- 상태: TODO
- 유형/우선순위: CODE / P1
- 선행: GPU-022, GPU-024, GPU-025, GPU-026, GPU-044, GPU-053, GPU-057, GPU-079, GPU-082
- 근거: PIVOT §8.3, §11, §13.
- 범위: metric/alert·runbook·load fixtures·Postgres/queue/tx 복구 절차.
- 작업: API/settlement lag, last cash, control change/expiry, debt due/overdue, DSCR, exposure, unmatched cash, in-flight, ledger mismatch, queue/nonce health에 담당·대응기한·draw freeze 조건을 연결한다. 보관/삭제·audit 요구와 RPO/RTO를 문서화한다. 첫 E2 파일럿에도 전력/호스팅비·tenant SLA·정산 중단·파트너/호스팅 연락 책임·허용 조치·고객 workload 접근 금지 runbook을 포함한다.
- 완료 기준: backup restore 뒤 ID·원문 hash·금액 합계와 pending 작업/tx 상태가 일치. worker 재시작·signer 중단·provider outage·가격 stale 상태에서 안전하게 신규 draw를 제한하고 회수는 복구 가능. 빈번한 GPU event를 100-record 온체인 배열로 처리하지 않는다.
- 검증: 새 DB에 restore drill, 정량 목표가 있는 부하/가스·batch-size 테스트, alert 주입→담당자 대응 기록. 목표 수치는 승인/측정 근거를 남기고 실서비스 부하 실험은 별도 권한 범위.
- R2 필수 작업·완료/검증: proof queue age·attestation/cache lag·native reject/verification age·source/encoding/decoder drift 경보와 artifact/acceptance/consumption 백업을 추가한다. outage→catch-up 후 중복 소비 없음·신규 사실 우회 없음·direct repay/회수 유지 drill을 수행한다.

## 9. 마이그레이션·배포·파일럿

### GPU-060 — 기존 배포·부채·LP 권리의 읽기 전용 inventory

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-000
- 근거: PIVOT §13.1; README/배포 스크립트·현재 ABI.
- 범위: 신규 `script/gpu/inventory_legacy.*`, `docs/gpu/legacy-inventory.md`, 기준 블록 snapshot schema.
- 작업: 실제 chain/address/bytecode/owner/token/borrower principal·미납이자/LP shares/금고 잔액/processed evidence를 조회한다. 주소 후보와 live 확인 결과를 구분하고 source aggregate/event log로 누락 차주를 점검한다.
- 완료 기준: 실자금/미결 권리 존재 여부를 근거로 판정; 코드 README가 testnet이라는 이유만으로 부재를 가정하지 않는다. 현재 이자 오류 영향은 정정안과 분리하고 snapshot 값을 조용히 고치지 않는다.
- 검증: fixture·Anvil inventory, 가능하면 공개 RPC read-only 조회의 block/hash·합계 대사. 외부 RPC 접근 실패 시 LOCAL tool 완료와 미확인 live inventory를 구분; 실제 cutover는 live 확인 필요.
- R2 필수 작업·완료/검증: 과거 BTC/SPV/자체 relayer 증거를 native VERIFIED로 재분류하지 않고 legacy provenance를 보존한다.

### GPU-061 — legacy 회수·오류 조정·전환/복구 절차

- 상태: TODO
- 유형/우선순위: SPEC / P0
- 선행: GPU-012, GPU-036, GPU-060
- 근거: PIVOT §13.1.
- 산출물: `docs/gpu/legacy-transition.md`, 영향 계산표, local migration/cutover drill.
- 작업: 기존 debt·LP share·현금·계산 오류의 차주/LP 영향과 조정 결정을 분리한다. legacy manager/vault pairing 보존, borrower freeze 등 지원되는 신규 차입 중단, repay/read 유지, 신규 v2 별도 배포, 사용자 안내·fallback을 설계한다.
- 완료 기준: “global pause 후 상환 유지” 절차가 없다. BTC history/credit을 GPU 담보로 복사하지 않는다. 자금 이전/채무 변경이 필요하면 대상·이유·권리/동의·별도 구현 범위를 구체화한다.
- 검증: Anvil snapshot→freeze→repay와 v2 신규 실행의 분리, old/new UI fallback, 합계 비교. 실제 freeze/manager 교체/자금 이동은 이 티켓에서 자동 수행하지 않는다.
- R2 필수 작업·완료/검증: legacy 조회/상환 fallback과 GPU native proof downgrade를 구분한다. 과거 BTC 증거/서명을 새 native evidence ID로 migration하지 않는다.

### GPU-062 — v2 배포 스크립트·manifest·dry-run

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-008, GPU-043, GPU-053, GPU-060, GPU-075, GPU-078, GPU-081
- 근거: PIVOT §7, §13.
- 범위: 신규 `script/DeployGpu.s.sol`, `script/gpu/verify_deployment.*`, fixture/deployment manifest.
- 작업: source/debt chain별 배포·안전 wiring·role/owner 설정·caps·검증된 token/decimals·provider admission 순서를 구현한다. demo/testnet과 production 구성을 명확히 분리하고 schema version·build commit을 저장한다.
- 완료 기준: production에 mock token/auto credit/permissive admission/잘못된 owner·chain·승인 한도 초과가 들어가면 명시적 실패. cap=0/admission off의 안전한 비활성 배포는 허용하고 이를 무제한으로 해석하지 않는다. 일반 파일럿 활성화는 GPU-063, 소액 시험 활성화는 §0.4/GPU-056의 별도 승인 범위다. legacy 연결은 불변이며 실제 source의 bytecode/ABI/admin/finality 확인 가능해야 한다.
- 검증: 신규 SOL(`GPU062DeploymentTest`), Anvil dry-run/배포 후 assertion·재실행 안전성·wrong-chain manifest. 로컬 이외 broadcast는 GPU-056 시험 범위 또는 GPU-063 승인 범위에서만 실행.
- R2 필수 작업·완료/검증: 선택 runtime·source mapping·고정 ABI/decoder·앱 verifier·requiredVerification을 assertion에 넣는다. 앱/source/decoder는 code/권한 검사, precompile은 공식 positive/negative 호출 검사다. 임의 mock binding 거부. GPU-080의 소형 technical harness는 이 full-stack 티켓을 선행으로 요구하지 않는다.

### GPU-063 — 첫 실자금 파일럿 배포·운영 승인(G4)

- 상태: TODO
- 유형/우선순위: RELEASE / P0
- 선행: GPU-010, GPU-052, GPU-054, GPU-055, GPU-056, GPU-057, GPU-058, GPU-059, GPU-060, GPU-061, GPU-062, GPU-065, GPU-066, GPU-080, GPU-081, GPU-082
- 근거: PIVOT §14.3~14.4.
- 산출물: `docs/gpu/releases/pilot-release.md`, 승인된 commit/manifest·차주·cap·운영 담당·rollback 범위.
- 작업: G1 승인, G2/G3 증거, 감사 결과, 실제 자본·자산·개별 차주 심사/약정·권리·가격/정산 정책, custody/secret/권한, legacy 보존, 사용자 조건·운영 준비를 검토한다. 승인할 배포/자금 대상을 구체적인 proposal로 준비한다.
- 완료 기준: missing/NO_GO gate·중대 미해결·TEST_ONLY 정책·live inventory 미확인 상태에서 실행 불가. 기존 승인 범위가 충분하면 그 안에서 진행하고 새 외부 권한만 요청한다. 승인 후 실제 배포·wiring·smoke·제한 cap를 확인한다.
- 검증: deploy 전 simulation, 배포 bytecode/owner/asset/roles/caps/readiness 확인, 허용 차주 외 draw 거부, 실제 배포 후 회수 경로 점검. 자금 이동/외부 연락/서비스 변경 결과는 대상과 함께 기록.
- R2 필수 작업·완료/검증: G-ASC PASS와 GPU-081/082, 실제 source의 GPU-056 결과가 필수다. testnet 성공을 mainnet 호환성으로 간주하지 않는다. 출시 환경 read-only/proof smoke를 재확인하며 chain/source/ABI/decoder/코드/중요 설정 변경 시 영향 재검증한다. BLOCKED/SKIPPED/LOCAL만 있으면 출시 불가.
- 출시 환경 positive 검증: 실제 source의 유효 proof를 **출시 대상 chain·앱 verifier·decoder·manifest 조합**에서 native+엄격한 event/업무 검증까지 성공시킨다. 권한 범위 내 eth_call/simulation 또는 승인된 제한 tx를 사용하고 결과·block·artifact/manifest hash를 저장한 뒤 활성화한다. ChainInfo 조회·wrong proof의 revert·다른 testnet의 PASS만으로 대체하지 않는다. 상태 기록/상환 실제 성공은 별도 GPU-056 증거가 필요하다.

### GPU-064 — 실제 정산 주기 관찰·월말 마감·파일럿 평가(G5)

- 상태: TODO
- 유형/우선순위: LIVE / P1
- 선행: GPU-063
- 근거: PIVOT §11~12, §14.
- 산출물: `docs/gpu/pilot-review.md`, 실제 credit memo·collection history·월말 reconciliation/손익·issue tracker의 안전한 참조.
- 작업: 승인된 차주의 연결/자료/심사→대출→실제 정산→자동 상환을 운영한다. statement/source/bridge/destination/debt/NAV/수수료/reserve를 정산별·월말별 독립 대사한다. 가동률·토큰·정산 지연/회수 비용·LP 수익을 예상과 비교한다.
- 완료 기준: 실제 지급 calendar를 거친 현금 회수와 예외 처리가 있다. 좋은 결과만 선택하지 않고 미지급/연체·회수 실패·비용·잔여 위험을 포함한다. 확대/유지/축소/종료 결정과 근거가 있다.
- 외부 조건: 실제 지급·시간 경과·운영 승인 범위. 코드 merge/시간 warp로 운영 기간을 충족하지 않는다. 관찰 중 무단 cap 증액 금지.
- 검증: 현금/권리/장부·월말 tax/accounting 증빙 참조, 약정 vs 실제 DSCR·loss·collection 지표, 장애/cure/default 대응 기록.
- R2 필수 작업·완료/검증: proof 비용·attestation/검증 지연·실패/재시도와 실제 현금 회수 지연을 따로 측정한다. 지원/runtime/artifact 변경과 재검증 이력을 월말 기록에 포함한다.

### GPU-065 — 제품·기술·보안·파트너·운영 문서 정합성

- 상태: IN_PROGRESS (2026-09-14, docs/gpu/execution/GPU-065.md — 체크포인트 GPU-065.a 완료: README/TECH/TECH_DISCORD/docs/hackathon/deck·pitch·submission을 R2 GPU 매출채권 제품으로 재작성, R2-O08 결정 반영, v1 문서 legacy 표시; 코드·API·manifest 대조 정합화(GPU-065.b)는 선행 CODE 티켓 완료 후)
- 유형/우선순위: SPEC / P1
- 선행: GPU-008, GPU-011, GPU-012, GPU-013, GPU-043, GPU-045, GPU-059, GPU-074, GPU-078, GPU-079, GPU-081
- 근거: PIVOT §13.2.
- 범위: `README.md`, `TECH.md`, `TECH_DISCORD.md`, `docs/specs/PROJECT.md`, `USC_ADAPTER.md`, provenance/threat-model/audit-checklist/배포·가스 문서.
- 작업: 실제 권한·증거·회계·chain 지원·funds route·API write boundary·운영 절차를 코드와 일치시킨다. BTC identity/SPV ADR은 legacy 표시하고 기존 `docs/process/TICKET.md`의 과거 DONE을 GPU 완료로 오해하지 않게 연결 안내를 둔다.
- 완료 기준: “adapter만 교체”, “read-only API”와 실제 owner writes, 고정 LP 수익·원금보장·GPU 자동 청산 같은 불일치가 제거되었다. 각 기능의 LOCAL/SANDBOX/LIVE 상태와 신뢰 주체·미확인 기능이 표시된다.
- 검증: 코드/API/manifest와 문서 field·명령·URL 비교, 링크/명령 smoke·DIFF. 생성된 ABI를 설명과 대조. 기존 local-only/미추적 자료를 임의 덮어쓰지 않는다.
- R2 필수 작업·완료/검증: PIVOT §10/TECH §3/README/해커톤 scope의 optional Attestcoin·자체 signer fallback·source-native 기본안·미구현 현재형을 R2와 실제 결과로 정합화한다. 공식 proof가 GPU 실매출/채권/소유권/강제 회수를 모두 보장한다는 과장도 금지다. BTC RelayerSigVerifier를 GPU fallback으로 그대로 쓸 수 있다고 쓰지 않는다.

### GPU-066 — 브랜드·카피·demo·사용자 전환 안내

- 상태: IN_PROGRESS (2026-09-14, docs/gpu/execution/GPU-066.md — 체크포인트 GPU-066.a 완료: 사용자 결정으로 GitHub repo `inchyangv/rackline`로 개명·remote 갱신, 배포/서비스 식별자 `rackline-*`로 통일, 죽은 도메인 기본값 제거, 도메인·재배포 체크리스트(`docs/deploy/RAILWAY.md` §9); 실제 도메인 등록·Vercel/Railway 재배포·DNS는 사용자 로그인/승인 후)
- 유형/우선순위: CODE / P1
- 선행: GPU-003, GPU-047, GPU-048, GPU-049, GPU-050
- 근거: PIVOT §9, §13.2.
- 범위: web metadata/OG/favicon/브랜드 자산·제품 카피, demo 시나리오, package 표시명·도메인 이전 계획.
- 작업: 이름 유지/변경 결정을 기록하고 BTC 중심 카피를 실제 GPU 상품과 일치시킨다. demo는 정상 자동 상환과 만료/회수 제한을 보여주되 mock 여부 표시. 기존 링크/bookmark·legacy read 접근·사용자 안내를 준비한다.
- 완료 기준: 새 logo/도메인/브랜드를 사용자 결정 없이 확정하지 않는다. 미결정이면 명시적인 임시 내부 이름으로만 준비한다. 과거 해커톤 실적과 현재 파트너/금융 지원을 구분한다.
- 검증: WEB, 시각/메타데이터/링크·모바일 점검, BTC/HashCredit/checkpoint/mUSDT 잔존 검색 후 active/legacy/의도된 항목 분류. 실제 도메인/DNS 변경은 별도 승인된 rollout 범위.
- R2 필수 작업·완료/검증: genuine native testnet, mock provider/settlement, 실제 파트너 통합을 demo 카피에서 각각 표시한다. Writability·실물 자동 청산·파트너 실매출을 demo proof 성공으로 홍보하지 않는다.

### GPU-067 — legacy 종료 조건 확인과 active runtime 정리

- 상태: TODO
- 유형/우선순위: RELEASE / P1
- 선행: GPU-061, GPU-064, GPU-065
- 근거: PIVOT §13.
- 범위: BTC worker/endpoint/deploy profile·더 이상 필요 없는 deps·문서 링크·runtime config.
- 작업: 미결 BTC debt·LP 청구·실제 자금·기록 보존 기간을 확인한다. 정리 후보 파일/서비스/키·복구 방법을 먼저 목록화하고 active GPU profile에서 BTC 경로를 분리한다. 종료 가능한 범위만 중단/아카이브한다.
- 완료 기준: 권리가 남으면 종료를 BLOCKED_EXTERNAL 또는 부분 보류하고 read/repay 경로 유지. 소스 이력·snapshot·증거/회계 보존. keys/미추적 문서/광범위 디렉터리 일괄 삭제 없음.
- 검증: GPU 전체 관련 suite, legacy 필수 read/repay smoke, package/lockfile·배포 profile에서 obsolete dependency 제거 검증. 제거한 서비스/파일과 복구 가능성을 실행 기록에 남긴다.
- R2 필수 작업·완료/검증: GPU active 경로의 legacy fact-signing verifier/키/env/endpoint fallback을 제거·차단하되 미결 legacy 회수에 필요한 기능은 별도 profile로 보존한다.

## 10. 첫 파일럿 이후 확장

### GPU-068 — 두 번째 파트너의 독립 승인·위험 격리·활성화

- 상태: DEFERRED
- 유형/우선순위: LIVE / P2
- 선행: GPU-064
- 선택 선행: 아직 출시하지 않은 파트너의 GPU-004/020 또는 GPU-005/021 경로, GPU-038 해당 partner binding.
- 근거: PIVOT §3, §14.
- 작업/산출물: 첫 파트너의 code/schema를 재사용하되 두 번째 provider의 권리·정산·asset/chain·E2·가격·cap·loss attribution을 별도 결정한다. GPU-009/010/056의 절차를 새 provider별 증거팩으로 반복하고 release proposal 작성.
- 완료 기준: 첫 파트너 성공을 두 번째 E2/계약 증거로 대체하지 않는다. 필요하면 별도 Vault/자본으로 LP 손실을 격리한다. 같은 실물/채권이 플랫폼 이동/동시 등록 시 중복 금융되지 않는다.
- 검증: cross-provider ID·schema 차이·중복 자산·cap·disable 한 파트너 후 다른 파트너 회수 정상, 실제 소액 정산·자동 상환. 승인 전 provider admission off.
- R2 필수 작업·완료/검증: 두 번째 파트너의 실제 source에 GPU-075/076/078/080/082 검증 조합을 재적용한다. 첫 native 성공을 다른 chain/issuer에 복사하거나 낮은 advance rate 서명 경로로 활성화하지 않는다.

### GPU-069 — E3 실물 담보·구매금융 사업/권리 설계

- 상태: DEFERRED
- 유형/우선순위: DD / P2
- 선행: GPU-064, GPU-006, GPU-007
- 근거: PIVOT §4, §5.1, §6.3, §11.
- 산출물: `docs/gpu/asset-finance/term-sheet.md`, title/lease/lien/custody/insurance·권리·가격 실사.
- 작업: SKU/serial·소유권·선순위·소재 관할, 담보 등록/대항·우선순위, 보관자 동의·반출 제한·보험·현장 회수·매각 partner를 확인한다. 순처분가치에서 철거/운송/보관/수리/판매/시간 비용을 차감한다.
- 완료 기준: GPU 가치와 동일 GPU 미래 매출을 단순 합산하지 않는다. 자기자본·vendor 직접 지급·인도/설치/검수별 tranche와 default step-in 조건의 책임자 승인이 있다.
- 외부 조건/검증: 법률·호스팅·보험·vendor·회수 주체의 실제 자료/동의. NFT나 agent 설치만으로 E3 판정 금지.

### GPU-070 — 구매처 직접 지급·인도/검수별 실행 모듈

- 상태: DEFERRED
- 유형/우선순위: CODE / P2
- 선행: GPU-069, GPU-035, GPU-036, GPU-039, GPU-045
- 근거: PIVOT §5.1, §14.
- 범위: asset-finance facility terms·purchase order·vendor allowlist·tranche·검수 evidence·UI.
- 작업: 승인된 장비/공급처·자기자본·invoice·인도/검수/가동 조건에 따라 분할 실행한다. 미인도/불량/RMA/취소·환불·납기 지연·가격 변경을 상태로 처리한다.
- 완료 기준: 차주 임의 지갑으로 구매자금 우회 불가, 동일 invoice/milestone 중복 실행 없음, 여러 tranche의 총노출 cap 준수. evidence 발급자/expiry/충돌·manual override 이력 보존.
- 검증: 신규 SOL(`GPU070AssetFinanceTest`), API/UI fixture: 위조·중복 invoice, 부분 인도, 검사 실패, vendor 변경, refund, 자기자본 부족·stale 조건. 실제 구매는 별도 승인.

### GPU-071 — 운영 인수·실물 회수·처분·보험 청구 drill

- 상태: DEFERRED
- 유형/우선순위: LIVE / P2
- 선행: GPU-069, GPU-070, GPU-041, GPU-044
- 근거: PIVOT §4~5, §11.
- 산출물: host/custodian/vendor/회수 주체의 승인 runbook과 실제/승인된 모의훈련 증거.
- 작업: 전력/호스팅비·tenant SLA·데이터 접근 경계, 운영자 교체, 반출/인수·운송·보관·검수·매각·보험 청구·순회수 배분 절차를 수행한다.
- 완료 기준: 원격 GPU 중단을 회수 성공으로 처리하지 않는다. 실제 집행 주체·법적 권한·현장 접근·장비 일치·비용/기한·회수금 destination이 입증된다. customer workload를 대주 담보로 취급하지 않는다.
- 검증: 양도/인수 증거와 inventory, 예상 vs 실제 비용/처분가치, 회수 후 debt/NAV/LP 배분, 실패 시 대안. 권한이 없으면 준비 문서 이후 BLOCKED_EXTERNAL.

### GPU-072 — 미래 GPU 현금흐름 기반 상품 확장

- 상태: DEFERRED
- 유형/우선순위: SPEC / P2
- 선행: GPU-064, GPU-007, GPU-012
- 근거: PIVOT §5.1, §6.3, §14.
- 산출물: `docs/gpu/cashflow-finance/`, underwriting 모델·새 상품 ADR·차이 테스트 계획.
- 작업: 실제 유료 사용량·실현 단가·OPEX·플랫폼 공제·순현금·vesting을 이용해 DSCR/상환 schedule/원금을 산정한다. 미발생 매출과 확정채권을 구분하고 운영 유지/네트워크 이탈·고객집중·토큰 유동성 위험을 추가한다.
- 완료 기준: 기존 확정채권의 E2 통제만으로 장래 매출을 보장한다고 표현하지 않는다. 반복 갱신/신규 자금으로만 만기가 성립하는 모델을 거부한다. 새 약정·cap·정책·검증 범위를 승인 가능한 자료로 제시한다.
- 검증: pilot 실자료 backtest, 가격/가동률/지연/OPEX 복합 stress·민감도, 확정채권과 중복 인정 방지. 이 SPEC 완료만으로 새 상품 자동 활성화 금지; 채택 시 필요한 차이 구현 티켓을 추가한다.

## 11. 공식 Attestcoin 필수 통합 — R2 추가 티켓

이 구간은 후속 확장이 아니라 첫 제품 P0다. GPU-074/075는 GPU-000 직후, 나머지는 각 선행 완료 시 실행한다. 모든 외부 사실은 확인 근거를 남기며 기술 시험은 실제 파트너 매출/회수 가능성의 증거를 대신하지 않는다.

### GPU-074 — R2 결정 원장·현재 구현 inventory·문서 충돌 정리

- 상태: DONE (2026-09-14, docs/gpu/execution/GPU-074.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-000
- 근거/읽기: 사용자 공식 Attestcoin 요구, 이 문서 §0.9; PIVOT §1/10, TECH §3, README, `docs/specs/USC_ADAPTER.md`, `docs/hackathon/HACKATHON_MVP_SCOPE.md`, 실제 contracts/offchain/deploy scripts.
- 산출물: `docs/gpu/decisions/attestcoin-first.md`, `docs/gpu/execution/ATTESTCOIN_GAP.md`, 짧은 CLAUDE.md의 R2 진입 안내. 기존 문서는 작성 중 변경을 먼저 확인하고 관련 주장만 정합화한다.
- 작업: 공식 검증 필수·Creditcoin execution·자체 source 서명 fallback 금지·보조 승인 존속을 확정 결정으로 기록한다. 구현/예정/LOCAL/native-testnet/partner LIVE를 파일·artifact·tx 증거로 분류한다. 미구현인데 배포/실행 중이라고 쓴 문장은 planned/unverified로 바로잡되 확인되지 않은 외부 배포 부재도 단정하지 않는다.
- 충돌 처리: PIVOT의 선택적 signer/source-native 안, TECH의 낮은 advance rate fallback, NFT lock/foreclose=실물 집행이라는 오해, 과거 payout=미지급채권, `notify(balance)` 임의 매출, transaction 단위 replay, 오래된 ABI/endpoint를 목록화하고 담당 티켓에 연결한다. demo NFT를 production 필수 담보로 승격하지 않는다.
- 완료 기준: 확정 R2와 사용자 추가 결정이 필요한 상품 변경이 분리된다. 기존 금융/권리/레거시 요구를 삭제하지 않았고 기능 존재를 문서만으로 DONE 처리하지 않는다. 사용자/동시 실행자의 변경을 덮어쓰지 않는다.
- 검증: DIFF, 문서↔실제 코드/배포 산출물 교차표, R2 충돌 검색과 담당 GPU ID 확인. 전 범위 문서 마감 검토는 GPU-065에서 재수행한다.

### GPU-075 — 공식 SDK·native ABI·decoder·환경 manifest와 read-only probe

- 상태: DONE (2026-09-14, docs/gpu/execution/GPU-075.md; environmentStatus=PROBED for CC3 testnet, LOCAL tool completion; native proof PASS remains GPU-080)
- 유형/우선순위: CODE / P0
- 선행: GPU-000
- 근거/읽기: §0.9 공식 문서와 공식 Gluwa 예제/선택 package의 소스·license·release/commit. 기존 USC_ADAPTER.md는 참조일 뿐 공식 ABI 원장이 아니다.
- 범위: `offchain/attestcoin/` package/lock/tsconfig·검사 명령, `config/attestcoin/` manifest schema·TEST_ONLY fixture, `docs/gpu/attestcoin/environment.md`; 신규 ASC-CHECK/ASC-TEST/ASC-PROBE.
- 작업: `@gluwa/usc-sdk`와 호환 ethers·공식 contract/decoder artifact를 출처·버전/commit·integrity로 고정한다. 현행 `asc-contracts`/과거 `usc-contracts` 명칭 차이와 공식 예제 drift를 확인하고 임의 package/method를 만들지 않는다. 선택 공식 Solidity interface의 mutability·return/revert·encoding을 실제 파일로 확인한다. SDK `verifySingle` 이름을 native Solidity 함수명으로 복사하지 않는다.
- manifest: destination chain ID/RPC 식별·runtime 확인 근거, source EVM chain ID/genesis 식별·환경별 chainKey·encoding·지원 확인 시각, BlockProver/ChainInfo, decoder 주소 또는 링크 artifact/code hash, SDK/ABI 버전/hash, proof endpoint/schema, source emitter/token 등록 참조, requiredVerification/profile·deployment block·manifest hash. secret은 참조만 저장한다.
- probe: 허용 URL의 source/destination chain ID·공식 ChainInfo 지원표·attestation 높이와 endpoint 응답 계약을 읽기 전용으로 확인한다. testnet의 두 prover hostname이 같다고 가정하지 않는다. 일반 앱/외부 decoder의 code 확인과 native precompile의 문서화된 호출 검사를 분리한다. native 주소의 빈 bytecode만으로 미배포 판정 금지.
- 완료 기준: package build/typecheck, 문서화된 schema·공식 artifact fixture, 잘못된 환경/chainKey/encoding/주소/mock profile 거부가 재현된다. 예시 주소를 live-verified로 표시하지 않는다. tool의 LOCAL 완료와 `environmentStatus=UNCONFIRMED/PROBED/UNSUPPORTED`를 따로 기록하며 실제 native proof PASS는 GPU-080이다.
- 검증: ASC-CHECK, ASC-TEST, 가능한 환경의 ASC-PROBE와 명령/시각/안전한 결과. 없는 RPC/권한/자료는 미확인으로 기록한다. 임의 proof를 공식 golden fixture로 만들거나 probe 출력의 키/토큰을 노출하지 않는다.

### GPU-076 — native 증명 범위·source 금융 사건·매출채권 의미 계약

- 상태: DONE (2026-09-14, SPEC v1; 파트너 의존 EC-O01~O03 OPEN; docs/gpu/execution/GPU-076.md)
- 유형/우선순위: SPEC / P0
- 선행: GPU-011, GPU-012, GPU-013, GPU-075
- 근거: §0.9, PIVOT §5/6/10; 공식 source-contract/decoder 구조. 실제 파트너 선택은 GPU-004/005 자료와 GPU-008을 참조하되 없으면 DRAFT/OPEN으로 명시한다.
- 산출물: `docs/gpu/attestcoin/evidence-contract.md`, source event ABI/typed fixture, `proof-to-business-mapping.md`, 언어 간 canonical ID/금액 벡터. 외부 ABI와 내부 제안 event를 분리한다.
- 작업: `ProofEnvelope → VerifiedSourceEvent → BusinessEvidence → EligibleUnpaidReceivable`의 필드를 정의한다. provider가 실제 인정한 채무/양도·정정과 payout event를 구분한다. 발행 권한·contract state change·payer/payee·provider/account/receivable binding·단위·순액/공제·revision·중복 정책을 명세한다. 과거 payout만 있으면 history/채권 감소에만 쓰고 첫 상품에 필요한 확정 미지급채권 경로를 OPEN으로 남긴다.
- 검증 경계: proof-bound height/tx position/receipt 내부 log ordinal/검증 bytes와 RPC/worker가 주장한 txHash·timestamp·invoice metadata를 구분한다. 입증되지 않은 시간으로 freshness를 늘릴 수 없다. 공식 encoding에 source timestamp가 없으면 필드를 꾸미지 않고 acceptance time·입증 가능한 높이·별도 provenance 및 보수적 유효성 정책을 명세한다.
- 최신성/누락 방어: acceptance time은 최초 기록 시각일 뿐 오래된 source 채권을 새것으로 만들지 않는다. issuer가 관리하는 잔액/revision·최종 지급/취소/정정 cutoff·decision challenge에 귀속된 source checkpoint 등 채택 경로를 정의하고 official proof와 결합한다. 누락 revision·catch-up gap·stale checkpoint·후속 지급 선택적 은닉 시 draw를 차단한다. source 상태 고정/예약 또는 승인된 bounded-lag·buffer·대사 정책 없이 즉시 최신성을 가정하지 않는다. 이 정책과 한도/위험은 GPU-007/010 승인 대상이다.
- 재조직/분쟁: destination canonical reorg의 read-model rollback과, 실제 draw/repay 이후 source 증거 분쟁을 구분한다. 후자는 collateral/evidence를 disputed로 표시해 신규 실행을 제한하고 대사/약정 절차로 처리하되, 이미 확정된 destination 채무·송금·실수령 상환을 지우지 않는다.
- ID 계약: proof query/cache key와 event consumption key를 분리한다. event는 canonical source identity + 증명에 귀속된 transaction 위치 + receipt log ordinal로 유일화하고 env/체인 재조직 정책을 명시한다. 경제 ID는 verifier 주소·SDK 버전·proof bytes·재제출 txHash 변경으로 새로 생기지 않는다. 한 tx의 여러 log 처리는 별도 event 단위이며 다른 observer/API 중복도 대사한다.
- 완료 기준: 실제 지원 source event의 의미, 우리 서버 주장 게시, 파트너 권리 확인, E2, 실제 cash를 구분한다. native로 증명 가능한 채무자 사건과 남은 채권의 관계가 없으면 production 적격화 불가다. 현금흐름 상품/NFT 담보로의 무단 변경이나 보조 서명만으로 source 사실을 대체하는 설계가 없다.
- 검증: 2개 log/1개 tx, 1채권 여러 지급·1지급 여러 채권, own transfer, arbitrary anchor, paid 재담보, 다른 차주/토큰/체인, source 확정과 destination cash 미도착을 fixture로 리뷰. GPU-014/029에 이 계약을 전달한다.

### GPU-077 — source 금융 이벤트·입금 출처·중복 방지 구현

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-029, GPU-030, GPU-076
- 근거: GPU-076 event 계약; PIVOT §4/6/10. GPU-037 escrow/waterfall과 순환하지 않도록 여기서는 최소 source 상태/수령/event 모듈을 구현한다.
- 범위: `contracts/gpu/source/` 최소 receipt/issuer binding 모듈, source adapter 인터페이스, `test/gpu/source/`, 별도 `MockDePINPayout` TEST_ONLY fixture. 기존 provider contract를 쓸 경우 확인된 ABI용 decoder/fixture를 추가하며 임의 provider API를 만들지 않는다.
- 작업: 등록된 지급자/issuer·account/receivable·asset을 연결하고 실제 토큰 수령과 event 금액을 원자적으로 결합한다. 지원 ERC20의 before/after 차액·nonce/settlement ID를 검사한다. arbitrary `notify(amount)`/기존 balance 재보고를 금지한다. 직접 donation/자기 송금/출처 불명 입금은 별도 unclassified 상태이며 매출로 emit하지 않는다. rebase/fee-on-transfer/nonstandard 자산은 승인된 정책 없으면 거부한다.
- 채권 사건: provider가 인정한 obligation/assignment/정정은 실제 발행 권한/상태 전이가 확인된 경우만 업무상 인정한다. 로컬 테스트 issuer는 실제 파트너 서명을 대체하지 않는다. statement hash를 우리 emitter에 게시해도 명시적 assertion 유형을 유지한다.
- 현재 상태: GPU-076에서 채택한 source 잔액/revision checkpoint·challenge/예약·지급/취소 상태를 원자적 source ledger 전이에 귀속한다. permissionless stale snapshot이나 독립 notify로 최신 채권이라고 재발행하지 못한다. 실제 provider 상태와 연결할 수 없으면 production binding을 UNCONFIGURED로 남긴다.
- 완료 기준: source event가 임의 금액 부풀리기·반복 통지·수취인 변경으로 매출을 만들지 못한다. 역할/upgrade 관리자·해제·등록 변경 이력이 있고 실제 출처 검증 상태가 보존된다. GPU-037은 이 모듈을 조합하되 미구현 upstream lock을 구현됐다고 주장하지 않는다.
- 검증: SOL(`GPU077SourceTest`): 동일 입금 반복 통지, sweep 후 재통지, own-transfer/donation, 가짜 issuer·동일 signature emitter·wrong token/recipient, 실제 차액 불일치·재진입, 다중 log·settlement 중복·정정. SOL-FULL.
- 외부 경계: 공통 코드/TEST_ONLY source는 LOCAL 완료 가능. `partnerSourceBinding=UNCONFIGURED/VERIFIED`는 별도이며 GPU-004/005/009/056 없이 실제 파트너나 E2 완료로 표시하지 않는다. 공개 testnet 배포는 GPU-080 승인 범위다.

### GPU-078 — 공식 AttestcoinRevenueVerifier·native 검증·엄격한 event 추출

- 상태: DONE (2026-09-14, LOCAL; 41 tests, mock BlockProver만 — native PASS는 GPU-080; docs/gpu/execution/GPU-078.md)
- 유형/우선순위: CODE / P0
- 선행: GPU-029, GPU-030, GPU-075, GPU-076
- 근거: §0.9 및 GPU-075에서 고정한 공식 BlockProver interface/decoder. GPU-077 구현 자체는 선행이 아니며 확정 ABI fixture로 독립 개발한다.
- 범위: `contracts/gpu/AttestcoinRevenueVerifier.sol`, 공식 ABI/decoder 의존 연결, versioned proof envelope, 명확히 LOCAL인 native test double. 앱 adapter는 필요하지만 검증 엔진을 자체 BtcSpvVerifier/서명 oracle로 재구현하지 않는다.
- 작업: manifest/등록 source와 일치하는 proof를 공식 native precompile에 검증 요청하고 성공한 정확한 txBytes에서만 receipt/log를 추출한다. 공식 ABI에 맞는 false/revert/empty·malformed 응답을 fail closed 처리한다. receiptStatus=1, 허용 transaction/encoding, source/issuer/emitter, event signature/topic/data 길이, token·payer/payee·account/receivable 귀속·amount·단위를 검사한다.
- 메타데이터: worker가 따로 보낸 amount/recipient/timestamp/txIndex를 proven 값으로 사용하지 않는다. 필요한 위치는 검증된 proof/encoding에서 유도하고 log 선택 범위·proof bytes·siblings/continuity 길이·gas 상한을 명세한다. 시간/txHash의 입증 범위는 GPU-076을 따른다. 일반 RPC receipt와 다른 bytes를 혼합하지 않는다.
- 완료 기준: native 실패/미지원/manifest mismatch에는 서명 fallback이 없다. 검증 함수가 타인의 경제 사건 소비 권리를 선점하지 않으며 소비는 GPU-031이 맡는다. official success는 source event 유효성이지 GPU 매출 적격성/현금/법적 권리가 아니다. LOCAL mock 주소/etch를 native/prod manifest로 사용할 수 없다.
- 검증: SOL(`GPU078AttestcoinVerifierTest`): 공식 wire fixture positive, receipt 실패, wrong chainKey/encoding/emitter/token/recipient, 금액·log ordinal·proof 변조, oversized/malformed bytes, native false/revert/empty, 다중 log, 공개 verify front-run. LOCAL 성공은 명시적으로 mock 검증이며 G-ASC는 GPU-080이 담당한다.

### GPU-079 — 공식 SDK proof worker·durable lifecycle·Python 연결

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-016, GPU-022, GPU-025, GPU-026, GPU-029, GPU-031, GPU-073, GPU-075, GPU-076, GPU-078
- 근거: 공식 SDK/Offchain Workers와 GPU-075 채택 artifact. 기존 Bitcoin proof builder의 유효성 로직을 가져오지 않는다.
- 범위: `offchain/attestcoin/src/` proof client/JSON CLI·tests, `hashcredit_prover/gpu/attestcoin_worker.py`, DB job/artifact 연결. API/server/prover core 전체 TS 전환은 범위 밖이다.
- 작업: 허용 source 지원 확인→tx/height 후보 확인→공식 attestation 및 builder cache 준비 대기→공식 SDK proof 획득→형식/범위 점검→GPU-026으로 GPU-031/업무 앱의 stateful 기록 진입점 제출→native/앱 확정 상태 대사를 연결한다. 그 진입점이 GPU-078을 호출하며 raw verifier probe 성공은 NATIVE_ACCEPTED/CONSUMED가 아니다. HTTP 결과의 proof는 비신뢰 입력이며 온체인 검증을 생략하지 않는다.
- 내구성: query ID·manifest/version·source locator·artifact hash/원문 참조·submission tx·확정 block·event ID를 유지한다. polling/timeout/backoff/jitter/429, service cache lag, attestation 지연, process crash, source/destination reorg, replacement와 idempotent 재개를 구현한다. 상태 전이는 OBSERVED→WAITING_ATTESTATION→PROOF_READY→SUBMITTED→NATIVE_ACCEPTED→CONSUMED를 구분하며 invalid/unsupported는 별도 terminal 원인이다.
- 보안: 프로세스 인자는 임의 shell 문자열이 아닌 고정 실행 파일+인자 배열/검증된 JSON으로 전달한다. payload/출력/시간/동시성 제한, stderr redaction, endpoint allowlist를 둔다. 공식 proof 생성기를 바꾸더라도 native 최종 검증과 증명 수준은 동일해야 하며 자체 서명 대체는 금지다.
- 완료 기준: proof API 200/SDK 사전검사만으로 DB VERIFIED/한도 변경 불가. 직접 외부 submitter도 GPU-073이 대사한다. source log 수집/정산 대사·treasury 송금과 proof relay의 역할이 분리되고 legacy SPV 모듈 없이 시작한다.
- 검증: ASC-CHECK/ASC-TEST, PY-GPU(`test_attestcoin_worker.py`): 공식 fixture·형식 변경·불명 chain·JSON 정수 정밀도·cache 지연·crash/restart·timeout 후 mined·duplicate job·wrong artifact·검증 실패 후 signer 우회 없음. LOCAL 통과와 실제 source proof는 GPU-080에서 분리 기록한다.

### GPU-080 — 실제 공개 testnet 공식 proof·native·앱 소비 E2E (G-ASC)

- 상태: TODO
- 유형/우선순위: LIVE / P0 (기술 시험, 요구 증거 수준 NATIVE_TESTNET)
- 선행: GPU-031, GPU-075, GPU-077, GPU-078, GPU-079
- 근거: §0.4/0.9; 이 티켓은 파트너 DD/G1/GPU-062/063와 독립이다.
- 산출물: `script/gpu/attestcoin_native_e2e.sh`, 필요한 최소 `DeployAttestcoinProbe.s.sol`, `docs/gpu/verification/attestcoin-native.md`, 비밀정보 없는 versioned proof fixtures·manifest/tx 참조. full lending 배포 전에 source/adapter/EvidenceBook/제한 consumer만으로 시험 가능하다.
- 작업: 명시 승인된 Sepolia→CC3 testnet 등 공식 지원 test 환경에 제한된 source/검증 앱을 배포하거나 검증된 시험 배포를 재사용한다. 실제 성공 거래를 생성/관측하고 공식 attestation/cache를 기다려 proof를 얻은 뒤 실제 앱에서 native 검증·event 기록/권한 있는 소비를 수행한다. 재시작/재제출과 동일 tx의 2개 log 각각 1회 처리를 재현한다.
- 실패 검증: tampered proof는 native에서 거부, 실제 실패 receipt는 앱에서 거부, 포함 증명 자체는 유효하나 wrong emitter/token/recipient인 사건은 업무 검증에서 거부, 같은 log 재소비 거부를 확인한다. 상태 변경이 필요 없는 부정 벡터는 실제 public RPC의 eth_call로 검사 가능하나 positive acceptance/consumption은 실제 tx/receipt가 필요하다.
- 완료 기준: 공식 source/destination chain·runtime 지원, 고정 SDK/ABI/decoder·앱 build/manifest hash, source tx/block/event locator, proof artifact hash, destination app verification/consumption tx·receipt/event, 거부 벡터와 상태 불변이 재현된다. deployed code/source와 고정 native binding을 확인해 Anvil etch·항상 true mock·순수 SDK eth_call 성공만으로 PASS 처리하지 않는다.
- 외부 조건: 대상 testnet·시험 계약·전용 지갑·가스/테스트 토큰 예산·기간의 승인과 실제 endpoint 접근. 없으면 harness/로컬 검증 후 BLOCKED_EXTERNAL; mainnet/실고객 자금·파트너 연락은 금지다. testnet 송금에도 임의 키/자금 사용 금지.
- 검증: ASC-PROBE 후 ASC-NATIVE, source/destination explorer 및 RPC의 결과 대조, 각 positive/negative case 수·exit code·artifact 참조. source가 MockDePIN이면 `partnerRevenue=SIMULATED`, settlement 미시험이면 `settlement=NOT_TESTED`다. NATIVE_TESTNET 성공을 실제 파트너 매출/E2/실자금 회수로 표시하지 않는다.
- 유지 조건: G-ASC PASS는 시험 조합에 귀속한다. runtime/ABI/decoder/verifier/중요 설정 변경 시 GPU-082로 영향 분석 후 필요한 실제 시험을 재수행한다. 기술 E2E 준비 완료와 PASS를 구분한다.

### GPU-081 — 공식 증거 요구와 심사·한도·draw·정산의 전 구간 연결

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-023, GPU-024, GPU-027, GPU-028, GPU-031, GPU-035, GPU-036, GPU-039, GPU-040, GPU-079
- 근거: §0.9의 필수 경로. 개별 구현 완료로 남은 틈을 없애는 통합 티켓이며 API/UI는 GPU-045 이후 담당한다.
- 범위: credit/receivables/settlement 서비스와 EvidenceBook/RiskPolicy/Manager/RepaymentRouter 연결, 통합 fixture·검증정책 resolver. 로컬 native substitute와 production manifest의 경계를 유지한다.
- 작업: 승인할 사실·필요 source event 집합·native acceptance·issuer/매출 provenance·미지급 잔액·정정·E2·policy/terms/expiry를 하나의 추적 가능한 decision으로 연결하고 최종 onchain draw에서 같은 요구를 확인한다. 외부 사건 직접 등록·관리자 grant·보조 서명·다른 verifier 경로로 한도가 생기지 않게 한다.
- 회계 경계: 지급 완료 evidence는 채권의 paid 잔액/이력에 반영하고 재담보화하지 않는다. proof만으로 debt/NAV를 바꾸지 않는다. actual destination cash→facility allocation→repayFor만 상환하며 제3자 직접 상환에는 무관한 proof를 요구하지 않는다. proof 서비스 outage에서 유효 증거의 정책상 사용 범위와 새 사실 인정 중단을 구분한다.
- 완료 기준: SDK/DB/온체인의 event/economic ID·revision·policy가 일치한다. native-required 조건을 API나 UI에만 두지 않는다. 검증된 임의 송금/우리 hash anchor·paid history·미지원 source로 새 borrowing base를 만들 수 없다. proof 장애가 자동 default나 전체 repayment pause가 되지 않는다.
- 현재성 gate: GPU-076의 source 잔액/revision·challenge·상태보호 또는 승인된 제한 지연 조건을 실제 decision/draw에 적용한다. 지급/취소가 나중에 있었는데 과거 obligation proof만 먼저 제출한 경우, indexer catch-up 전에도 freshness를 새로 부여하지 않는다. 누락/오래된 checkpoint는 차단 사유이며 이미 존재하는 채무를 삭제하지 않는다.
- 검증: SOL(`GPU081AdmissionTest`), PY-GPU(`test_native_credit_integration.py`), ASC-TEST: 정상 적격 미지급채권→승인/draw, missing/invalid/expired proof·직접 manager 호출·signer/admin override·profile mismatch 거부, paid 정정 후 headroom 감소/기존 debt 보존, proof만 도착→debt 불변, 실제 cash 도착→정확한 부분이자 상환. G-ASC/G3를 mock로 충족했다고 기록하지 않는다.

### GPU-082 — 공식 encoding 호환성·공격 벡터·변경 시 재검증 패키지

- 상태: TODO
- 유형/우선순위: CODE / P0
- 선행: GPU-031, GPU-077, GPU-078, GPU-079, GPU-081
- 근거: GPU-075 고정 공식 artifact, GPU-076 의미/ID 계약, GPU-078~081 통합 경계. G-ASC와 상호 의존하지 않도록 LOCAL conformance부터 완성한다.
- 범위: `test/fixtures/gpu/attestcoin/`, SOL(`GPU082ConformanceTest`), TS/Python conformance tests, `docs/gpu/attestcoin/compatibility.md`, manifest/schema/ABI drift 검사 명령.
- 작업: 같은 공식 wire fixture를 SDK→JSON→Python dispatcher→Solidity decoder에 넣어 금액/체인/위치/ID가 일치하는지 비교한다. fixture의 출처/버전/hash·실제 capture 여부를 남기고 LOCAL 합성 벡터를 genuine proof라고 이름 붙이지 않는다. proof/tx bytes·siblings·continuity·event length 변조와 대용량 입력의 자원 한도를 fuzz한다.
- 필수 사례: query cache 재사용과 event 소비 분리, 같은 tx 2 logs, 같은 event 다른 proof bytes/verification tx, 다른 API observation/settlement tx의 동일 경제 사건, receipt 실패/가짜 emitter/own-transfer/hash anchor, signed fallback/role escalation, stale source/time 주장, chainKey 재매핑·decoder/runtime 변경·재조직, consume 업무 revert 후 재시도.
- 누락/비가역 회귀: 유효한 과거 obligation proof만 선택 제출한 뒤 후속 paid/cancel proof를 숨김, 오래된 proof 재제출로 시간 갱신, 최신 revision 누락/ingestion gap, 실제 draw/repay 후 source reorg·증거 분쟁을 추가한다. collateral 제한과 대사만 수행하고 실제 destination 채무/자금/상환을 source rollback으로 삭제하지 않는지 검사한다.
- 완료 기준: 새 SDK/ABI/decoder/verifier 버전으로 증거를 중복 인정하거나 testnet/mock를 production으로 승격하지 못한다. fail-closed와 현금/채무 불변식이 cross-language로 일치한다. 호환성 변경의 영향표에 schema/fixture 재생성·old evidence 보존·GPU-080 native 재시험·필요한 GPU-056 파트너 재검증·release 보류 조건이 있다.
- 검증: ASC-CHECK/ASC-TEST, PY-GPU(`test_attestcoin_conformance.py`), SOL(`GPU082ConformanceTest`), SOL-FULL; seed·case 수·0 tests 여부·실패 fixture를 기록한다. GPU-054 CI와 GPU-058 감사에 연결하며 GPU-080의 실제 capture가 생기면 해당 조합 회귀를 다시 실행한다.

## 12. PIVOT·R2 요구사항 추적표

### 12.1 PIVOT §14.2 원래 백로그 → 실행 티켓

| PIVOT ID | 이 문서의 담당 티켓 |
| --- | --- |
| P-01 | GPU-003, GPU-007, GPU-010 |
| P-02 | GPU-004, GPU-009, GPU-020, GPU-038, GPU-056 |
| P-03 | GPU-005, GPU-009, GPU-021, GPU-038, GPU-056 |
| P-04 | GPU-006, GPU-009, GPU-010, GPU-013, GPU-032, GPU-037, GPU-056 |
| P-05 | GPU-008, GPU-010, GPU-024, GPU-040, GPU-056, GPU-075, GPU-076, GPU-080 |
| D-01 | GPU-011, GPU-015, GPU-016, GPU-017, GPU-029, GPU-046 |
| D-02 | GPU-012, GPU-014, GPU-023, GPU-024, GPU-039, GPU-073 |
| C-01 | GPU-002, GPU-012, GPU-033, GPU-034, GPU-039, GPU-055 |
| C-02 | GPU-001, GPU-013, GPU-018, GPU-030, GPU-043 |
| C-03 | GPU-009, GPU-032, GPU-037, GPU-038, GPU-056 |
| C-04 | GPU-024, GPU-039, GPU-040 |
| C-05 | GPU-027, GPU-035, GPU-036, GPU-043, GPU-044 |
| C-06 | GPU-041, GPU-044, GPU-057, GPU-064 |
| C-07 | GPU-034, GPU-042, GPU-050 |
| B-01 | GPU-019, GPU-020, GPU-021, GPU-022 |
| B-02 | GPU-014, GPU-023, GPU-024, GPU-028, GPU-031, GPU-076~079, GPU-081, GPU-082 |
| B-03 | GPU-016, GPU-025, GPU-026, GPU-073 |
| B-04 | GPU-032, GPU-038, GPU-044, GPU-051 |
| F-01 | GPU-018, GPU-047, GPU-048 |
| F-02 | GPU-046, GPU-049, GPU-050, GPU-052 |
| F-03 | GPU-044, GPU-045, GPU-051, GPU-052 |
| O-01 | GPU-000, GPU-060, GPU-061, GPU-062, GPU-067 |
| O-02 | GPU-053, GPU-054, GPU-059 |
| T-01 | GPU-002, GPU-055 |
| T-02 | GPU-009, GPU-056, GPU-057, GPU-080~082 |
| T-03 | GPU-054, GPU-058, GPU-059, GPU-063 |
| G-01 | GPU-065, GPU-066, GPU-074 |
| G-02 | GPU-068, GPU-069, GPU-070, GPU-071, GPU-072 |

### 12.2 원래 백로그 외 상세 요구의 소유자

| PIVOT 요구 | 티켓 |
| --- | --- |
| 전체 코드 결함과 잘못된 기존 테스트 기대값 | GPU-001, GPU-002, GPU-012, GPU-030~043, GPU-055 |
| Aethir receiver/계정 변경·claim/unstake·vesting·slashing | GPU-004, GPU-009, GPU-020, GPU-032, GPU-038, GPU-056 |
| GPU.net 상품/체인 혼동·미확인 supplier 권한 | GPU-005, GPU-008, GPU-021, GPU-068 |
| 경쟁/제휴·기존 금융 우선권·단위 경제성 | GPU-004~007, GPU-010, GPU-064 |
| 법인/대표권·실물/리스·중복 양도·데이터 권리 | GPU-006, GPU-017, GPU-018, GPU-063, GPU-069 |
| 발생/정산/수집/수령 시각·정정·분할/합산 | GPU-011, GPU-014, GPU-016, GPU-022~024 |
| 이자·부실·NAV·차주 reserve·late recovery·월말 마감 | GPU-012, GPU-033, GPU-034, GPU-039, GPU-041, GPU-042, GPU-064 |
| 모든 facility 노출·reservation·late-mined tx | GPU-026, GPU-027, GPU-035, GPU-036, GPU-055, GPU-073 |
| 주소 귀속·nonce·EIP-1271·quorum·signer 변경 | GPU-013, GPU-018, GPU-028~032, GPU-043 |
| 실제 source/debt 자산·공식 Attestcoin·환전·bridge | GPU-008, GPU-024, GPU-040, GPU-046, GPU-056, GPU-062, GPU-074~082 |
| DB migration·outbox·retry·webhook·복구 | GPU-015, GPU-016, GPU-022, GPU-025, GPU-026, GPU-053, GPU-059 |
| 외부 지갑 포함 전체 이벤트·canonical read model·reorg | GPU-073, GPU-024, GPU-027, GPU-045, GPU-055, GPU-057 |
| 사용자/운영 UI·LP 수익/출금·타입·localStorage | GPU-045~052 |
| 배포·키 분리·보안 CI·가스/성능·외부 감사 | GPU-053~059, GPU-062, GPU-063 |
| legacy debt·LP 권리·pause 제한·오류 조정 | GPU-060, GPU-061, GPU-063, GPU-067 |
| README·USC 문서·브랜드·도메인·dependency 정리 | GPU-053, GPU-065~067 |
| 실물 회수·vendor 직접 지급·인도·보험·SLA | GPU-069~071 |

### 12.3 R2 공식 검증 요구 → 담당 티켓·완료 증거

| R2 요구 | 구현/결정 담당 | 필수 확인 |
| --- | --- | --- |
| 자체 시스템 대신 공식 native 필수·문서 충돌 해소 | GPU-074, GPU-008, GPU-065 | R2 ADR·planned/implemented/live 분리 |
| 최신 공식 package/ABI/decoder·환경별 지원 | GPU-075, GPU-046, GPU-062 | pinned artifact/lock·manifest hash·read-only probe |
| source 지원 확인·미지원 원천 우회 금지 | GPU-004, GPU-005, GPU-008, GPU-076, GPU-068 | 실제 provider 지급/채권 event mapping, unsupported admission off |
| proof validity ≠ 매출 출처 ≠ 미지급채권 ≠ E2 | GPU-011~014, GPU-023, GPU-076, GPU-081 | 독립 필드/정책·paid 재담보/자체 anchor 거부 |
| 보조 서명 목적 제한·native fallback 없음 | GPU-013, GPU-028, GPU-031, GPU-043, GPU-081 | signature 목적 분리·admin/underwriter 우회 거부 |
| source 실제 수령·issuer·event 의미 | GPU-030, GPU-037, GPU-077 | 실제 차액·donation/반복 notify·가짜 issuer 거부 |
| 공식 native/decoder·검증 bytes의 엄격한 해석 | GPU-078, GPU-080, GPU-082 | receipt 실패·변조·wrong emitter/token/account 거부 |
| query/event/economic ID·다중 log·replay | GPU-014, GPU-016, GPU-031, GPU-073, GPU-076, GPU-082 | 두 logs 각각 1회·공개 verify 선점 방지·교체 후 dedup |
| SDK worker·attestation/cache 대기·재시도 | GPU-022, GPU-025, GPU-026, GPU-075, GPU-079 | process/DB/tx crash 복구·API ready와 앱 acceptance 분리 |
| 공식 증거→심사→온체인 draw 강제 | GPU-027, GPU-035, GPU-036, GPU-081 | 직접 contract/API/admin 모든 경로의 native requirement |
| proof ≠ 자금 이동·직접 repay 유지 | GPU-024, GPU-039, GPU-040, GPU-055, GPU-081 | source만 도착 시 debt 불변·장애 중 실제 수령 상환 |
| profile/native/provenance/control/cash UI·API | GPU-045~052, GPU-066 | mock/genuine native/partner LIVE 혼동 없음 |
| 실제 공개 testnet 공식 검증 G-ASC | GPU-080 | source tx/proof hash/실제 앱 tx·receipt·소비·거부 사례 |
| 실제 파트너 source/E2/현금 검증 G3 | GPU-009, GPU-010, GPU-056 | native 시험과 독립인 실제 provider·권리·상환 증거 |
| CI·보안·운영·SDK/runtime 변경 대응 | GPU-054, GPU-058, GPU-059, GPU-062, GPU-063, GPU-082 | LOCAL/실제 network gate 분리·drift/DoS·재검증·복구 |
| BTC proof/서명 migration·레거시 권리 보존 | GPU-060, GPU-061, GPU-067 | 과거 증거를 native VERIFIED로 재분류하지 않음 |

### 12.4 최종 제출물 체크리스트

- [ ] GPU-000~067 및 GPU-073~082의 첫 파트너 적용 티켓과 모든 출시 gate의 결과가 명시되어 있다. 비선택 파트너/실제 미결 legacy 종료는 사유와 상태를 남긴다.
- [ ] 각 DONE에 실제 파일·명령·테스트 개수·결과·증거 수준이 있고 존재하지 않는 API/주소/명령/승인이 없다.
- [ ] G1~G4 및 G-ASC의 PASS/승인 상태가 명시되고 NO_GO/불명/BLOCKED/SKIPPED 결과를 DONE이나 LOCAL 통과만 보고 승격시키지 않았다.
- [ ] PIVOT의 모든 기존 ID와 상세 요구가 담당 티켓에 연결되었다. 새로 드러난 요구는 무단 scope 확대 대신 후속 ID/결정으로 추적한다.
- [ ] LOCAL mock·genuine NATIVE_TESTNET·파트너 sandbox·실제 지급·법률/사업 승인·외부 감사의 범위를 구분했다.
- [ ] 공식 SDK/ABI/decoder·source 지원·환경 mapping·manifest hash와 실제 native 증거가 있고, verifier 주소/업그레이드/profile 변경으로 검증 조건을 우회할 수 없다.
- [ ] 필수 외부 source 사실에 공식 증명 없는 신규 신용 실행이 없고, 자체 API anchor·보조 서명·과거 완납 지급이 새 담보가 되지 않는다.
- [ ] 공개 verify 선점·동일 tx 다중 log·경제 사건 replay·source/destination reorg·native 장애 복구를 검증했다.
- [ ] proof 장애 중 신규 사실은 우회 없이 제한되고, destination 직접 실수령 상환·허용 회수는 유지된다.
- [ ] 실제 지급 source가 미지원이면 admission off/차단 이유를 유지했다. 미출시 Writability나 무신뢰 bridge를 완료된 기능으로 가정하지 않았다.
- [ ] 레거시 권리·기록을 보존했고 source→실제 수령→부채/NAV/LP의 보존 관계를 검증했다.
- [ ] 파일럿 이후 GPU-068~072는 별도 선택·권한·실증 없이 자동 실행하지 않는다.

실행 시작점은 GPU-000이다. 이후 GPU-074/075를 우선하여 공식 검증 결정을 고정하고, 선행이 충족된 작업만 READY로 바꾼다. 티켓 ID/참조/AND 의존성의 순환 여부를 상태 갱신 때 다시 검사한다. 이 문서 개정 완료는 83개 구현 티켓이나 G-ASC가 완료됐다는 뜻이 아니다.
