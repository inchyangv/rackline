# Attestcoin gap inventory and document-conflict register (R2)

Recorded by GPU-074 on 2026-09-14 at commit `aea2405` + working tree. Evidence basis: file presence, test
runs in `BASELINE.md`, and grep of the repository. **No chain query, RPC call, or partner contact was made.**
Governing decisions: `docs/gpu/decisions/attestcoin-first.md` (R2-D01…D14). Re-run this inventory whenever a
GPU-075+ ticket lands; do not treat this file as a status ledger (that is each ticket's `상태` in `TICKET.md`).

Classification legend — `IMPLEMENTED` (code + tests exist in repo), `PLANNED` (docs/tickets only),
`LOCAL` (fixture/mock evidence exists), `NATIVE_TESTNET` (real public-testnet native verification recorded),
`PARTNER_LIVE` (confirmed real partner account/transaction), `UNVERIFIED_EXTERNAL` (docs claim an external
deployment; not checked here, neither asserted nor denied).

## 1. Implementation inventory (docs claim → actual evidence)

| Component (as named in docs) | Claimed in | Actual evidence in repo (2026-09-14) | Class | Owner ticket |
| --- | --- | --- | --- | --- |
| `AttestcoinRevenueVerifier` over BlockProver precompile | README §Solution/§Architecture, TECH §2.1/§3, MVP_SCOPE §1.1 | `contracts/gpu/` absent; grep `attestcoin|blockprover|0x…0fd2|gluwa` in `*.sol` = 0 hits | PLANNED | GPU-078 |
| `IRevenueVerifier` / `RevenueEvidence` | TECH §2.1/§3/§7, README | Only `contracts/interfaces/IVerifierAdapter.sol` (BTC `PayoutEvidence`) exists | PLANNED | GPU-029 |
| `GpuNodeNFT` (ERC-721 lien/foreclose) | README, TECH §2.1, MVP_SCOPE | absent | PLANNED — and **not a production collateral decision** (R2-D10/D14) | GPU-072 (DEFERRED product) / GPU-065 (docs) |
| `GpuCreditManager`, `LendingVault` v2, `RiskConfig` v2 | README, TECH §2.1/§6 | absent; v1 `HashCreditManager.sol`, `LendingVault.sol`, `RiskConfig.sol` only (defects PIVOT §2.2) | PLANNED | GPU-029~043 |
| Source chain `NodeAccount`/registry, `MockDePINPayout` | README, TECH §2.2, MVP_SCOPE §1.2 | `contracts/gpu/source/` absent | PLANNED | GPU-077 (+GPU-080 for TEST_ONLY testnet deploy) |
| Official SDK proof client (`@gluwa/usc-sdk`) / keeper `GET proof-by-tx` | README §Attestcoin, TECH §2.3/§3, MVP_SCOPE §1.3 | `offchain/attestcoin/` now pins `@gluwa/usc-sdk@0.18.0` + `@gluwa/asc-contracts@0.2.1` (lockfile integrity) and ships check/probe tools only; **no proof client/worker** and no `offchain/keeper/` | SDK pinned (LOCAL); worker PLANNED | GPU-079 |
| Environment manifest / official ABI fixtures | TICKET §0.5 paths | `config/attestcoin/{cc3-testnet.sepolia,local-mock}.json` + `manifest.schema.json`; `test/fixtures/gpu/attestcoin/official/*.abi.json` (OFFICIAL_ARTIFACT_COPY) + `probe/cc3-testnet.sepolia.probe.json` | IMPLEMENTED; CC3 testnet `environmentStatus=PROBED` (2026-09-13T22:14Z, read-only) — not a native proof | GPU-082 (conformance) |
| Bitcoin SPV proof builder + `BtcSpvVerifier`/`CheckpointManager` | README/TECH "legacy" | `offchain/prover/hashcredit_prover/proof_builder.py`, `contracts/BtcSpvVerifier.sol`, `contracts/CheckpointManager.sol`; 14+22+22+8 forge tests, 61 pytest | IMPLEMENTED (legacy; **not** an R2 evidence path, R2-D03) | GPU-060 |
| `RelayerSigVerifier` (EIP-712) + `offchain/relayer` | TECH §2.1/§7, README: "retained as attested adapter" | `contracts/RelayerSigVerifier.sol` (15 tests), `offchain/relayer/` (9 tests) | IMPLEMENTED (legacy). **Not a v2 evidence adapter** (R2-D03); repurpose/retire is R2-O07 | GPU-013, 029, 060 |
| Public `/claim/register-and-grant` with admin key; `grantTestnetCredit` | PIVOT §2.2 P0; README "no owner-key API" (v2) | `offchain/api/hashcredit_api/evm.py:74-119`, `main.py`; `contracts/HashCreditManager.sol:197` — **still present in v1 code** | IMPLEMENTED (defect) | GPU-001 |
| Web Operator/Node/Pool tabs for v2 | README §Status | `apps/web` is the rebranded v1 UI (Dashboard/Pool, BTC flows); no GPU screens | PLANNED | GPU-047~052 |
| v1 contracts "live on testnet" at listed addresses (chain 102031) | README §Status/§Addresses, TECH §9 | Addresses appear in `README.md`, `TECH.md`, `.env.example`, `apps/web/src/lib/env.ts`; local `broadcast/` artifacts exist (gitignored). No chain check performed | UNVERIFIED_EXTERNAL | GPU-060 (legacy state check), GPU-062 |
| v2 contracts on CC3 testnet / Sepolia (`<TODO>` addresses) | README, TECH §9 | All `<TODO>`; nothing to verify | PLANNED (no deployment claimed with an address) | GPU-062, 080 |
| Live demo / API URLs (`hashcredit.studioliq.com`) | README | v1 service; not checked | UNVERIFIED_EXTERNAL | GPU-060/063 |

Summary (updated by GPU-075): official artifacts are pinned and the CC3 testnet environment is read-only
PROBED; **every verifier/source-contract/worker/GPU-credit component is still PLANNED; zero NATIVE_TESTNET
proof or PARTNER_LIVE evidence exists.** The only implemented proof path is Bitcoin SPV (legacy). Nothing here
changes by editing docs; it changes only when GPU-077/078/079/080 produce artifacts.

## 2. Document-conflict register (R2 vs existing docs)

Each row: where the conflicting claim lives, the R2 decision that prevails, what was done in GPU-074, and the
ticket that owns the durable fix. "Edited" means a targeted wording fix was applied in this ticket; the
underlying design/code fix belongs to the owner ticket.

| # | Conflicting claim | Location | R2 rule | GPU-074 action | Owner |
| --- | --- | --- | --- | --- | --- |
| C01 | "`RelayerSigVerifier` retained as attested adapter for chains Attestcoin does not cover, lower advance rate"; "Fallback: … at a lower advance rate"; `evidenceClass 1 = relayer-attested` | TECH §2.1, §3 (last para), §7; README §Attestcoin integration, §What v2 reuses, project structure (`relayer/ … v2 attested adapter`) | R2-D03, R2-D08 | **Edited**: fallback removed, unsupported source = `UNSUPPORTED_SOURCE`; relayer labeled legacy | GPU-029/078 (code), GPU-065 (full doc pass) |
| C02 | PIVOT §10.3: "If an EIP-712 signer-quorum initial integration is chosen, state trust parties…" (optional self-signed path) | `PIVOT.md` §10.3 | R2-D03 | Not edited (PIVOT is the product-basis record; R2 supersedes via TICKET §0.9) — registered here | GPU-065 |
| C03 | PIVOT §10.2 second configuration (vault/escrow on another settlement chain, Creditcoin as evidence ledger) | `PIVOT.md` §10.2 | R2-D01 (Creditcoin ledger); alternate = R2-O05 | Registered; remains a documented alternative needing explicit decision | GPU-006/010 |
| C04 | "Mint, Attestcoin verification, limit computation, draw, lien, sweep, `repayFor` and LP accounting run as real contracts on Creditcoin CC3 testnet" | README §Testnet substitutions; TECH §8 | Interpretation rule 4 (planned/unverified) | **Edited** to "designed to run … not implemented/deployed from this repository as of 2026-09-14" | GPU-062 (real deploy), GPU-065 |
| C05 | Status table lists v2 contracts/keeper/UI as existing ("hackathon vertical slice") | README §Status | rule 4 | **Edited** to planned + pointer to this file | GPU-065 |
| C06 | Project structure lists `contracts/gpu/`, `test/gpu/`, `offchain/keeper/` | README §Project structure | rule 4 | **Edited** (marked planned) | GPU-011 (path table), GPU-065 |
| C07 | NFT lock = "on-chain payment control"; NFT foreclosure = recovery of "revenue rights and the hardware claim"; NFT "locked as collateral" | TECH §1, §5; README §Solution steps 6/8; WHY_WE_PIVOTED §Lien/§Foreclosure | R2-D05, R2-D10, PIVOT §4 (E2 is a partner/legal control; `isLocked=true` alone ≠ E2) | Registered; WHY_WE_PIVOTED line 76 already disclaims. TECH header note added | GPU-009/038 (real E2), GPU-072 (NFT product, DEFERRED), GPU-065 |
| C08 | Credit model = "Σ verified net payouts in trailingWindow" (past payouts as borrowing base) | TECH §3 rules, §4; README §Credit model; MVP_SCOPE §1.1 `limitOf` | R2-D06, R2-D10 (first product = confirmed unpaid receivables) | Registered; TECH header note. Formula not rewritten here (product spec is GPU-003/076) | GPU-035, 076, 081 |
| C09 | `NodeAccount.notify(token, amount)` "called by the payer or by anyone after balance check"; `PayoutReceived` from arbitrary notify | MVP_SCOPE §1.2; TECH §2.2 | GPU-077 spec (no arbitrary `notify(amount)`/balance re-report; atomic receipt+event) | Registered; MVP_SCOPE header note | GPU-077 |
| C10 | Replay key = `keccak256(chainKey, blockHeight, txIndex)` (transaction-level) | TECH §3, README §Attestcoin, USC_ADAPTER §1/§3.3, MVP_SCOPE | TICKET §0.9 / GPU-076 ID contract: canonical source identity + proof-bound tx position + **receipt log ordinal**; query-cache key ≠ consumption key | Registered | GPU-076, 031, 078 |
| C11 | ABI/endpoint names: `INativeQueryVerifier.verifyAndEmit(...)` at `0x0FD2`, `EvmV1Decoder.decodeReceiptFields`, `getLogsByEventSignature`, `GET prover.cc3-testnet.creditcoin.network/proof-by-tx/{chainKey}/{txHash}` | USC_ADAPTER §1/§6, TECH §3, README §Attestcoin, WHY_WE_PIVOTED §59, memory notes | R2-D11 | **Resolved by GPU-075** (`docs/gpu/attestcoin/environment.md`): interface/decoder names confirmed from pinned `@gluwa/asc-contracts@0.2.1`; `verify` is `view`, `verifyAndEmit` nonpayable; SDK path is `/api/v1/proof-by-tx/{chainKey}/{txHash}` (the `/api/v1` prefix was missing in TECH/README); both testnet hostnames answer, recorded as primary/alternate, not aliases. USC_ADAPTER's `verifyAndEmit … returns (bool)` view signature is outdated. | GPU-065 (doc wording) |
| C12 | USC_ADAPTER: "BTC SPV is a valid instantiation of the same pattern"; Path B/C swap adapters; checklist "deploy adapter, `setVerifier`" | `docs/specs/USC_ADAPTER.md` §2–§8 | R2-D03 (no SPV/adapter-swap substitute); v1 `setVerifier` hot-swap is a PIVOT §2.2 P1 finding | Header note added; body kept as legacy reference | GPU-060, 029 |
| C13 | Local mocking: "`MockNativeQueryVerifier` … returns `true`"; fixtures "captured from a real Sepolia tx via the prover API" | MVP_SCOPE §1.1 | R2-D12 (LOCAL only; never in native/prod manifest; captured fixtures need provenance) | MVP_SCOPE header note | GPU-078, 082 |
| C14 | Settlement: keeper "executes the leg with a mock bridge" → `repayFor` | TECH §2.3/§8, README §Testnet substitutions | R2-D07/D09; real rail = GPU-040 | Registered (already labeled demo) | GPU-040 |
| C15 | "Partner receiver lock (E2) enforced at the `NodeAccount` controller only" | TECH §8, README | TICKET §0.3 (controller lock alone ≠ E2) | Registered (already labeled demo) | GPU-009, 038 |
| C16 | "Testnet auto-grant credit does not exist in v2" while v1 code/API still exposes `grantTestnetCredit` and `/claim/register-and-grant` | TECH §4, README §Credit model vs `offchain/api/hashcredit_api/evm.py`, `contracts/HashCreditManager.sol:197` | TICKET §0.3 (no testnet grant / public owner-key API in production GPU path) | Registered | GPU-001 |
| C17 | Environment facts "Sepolia = chainkey 1, Ethereum mainnet = 3 on CC3 testnet; mainnet source chainkey 1; precompiles `0x…0FD2`/`0x…0FD3`" | TECH §3, README, TICKET §0.9 table | R2-D11 | **CC3 testnet confirmed by read-only probe (GPU-075)**: chainKey 1 = 11155111 enc 1, chainKey 3 = 1 enc 1, genesis 0. Mainnet remains doc-only (no RPC probed). | GPU-062 (mainnet probe) |
| C18 | "Legacy v1 (still live)" / "live on testnet" / live demo URLs | TECH §9, README §Status/§Addresses | rule 4 (external deployment not verified here; not denied) | Not edited | GPU-060, 063 |
| C19 | Hackathon build order, "Day 3: real precompile on testnet", tags `v1-spring-2026`/`v2-fall-2026` | MVP_SCOPE §1.5/§2 | R2-D14 (demo scope; any public testnet broadcast needs GPU-080 approval scope) | MVP_SCOPE header note | GPU-080, 065 |
| C20 | `docs/process/TICKET.md` "Current Baseline" title | `docs/process/TICKET.md` | TICKET.md preamble: legacy BTC/SPV record, not GPU progress | Not edited (legacy record preserved, R2-D13) | GPU-060 |

**GPU-065.a (2026-09-14, user decision R2-O08 → rewrite):** the communication documents were rewritten to the R2 product rather than patched. Resolved in docs (code fixes still with the owner tickets): C01 (README/TECH/DORAHACKS no longer mention an attested adapter or lower advance rate), C02 (PIVOT §10.3 bullet struck through with an R2-D03/D04 note; R2 note added under the PIVOT header), C04/C05/C06 (README/TECH status tables dated, every v2 component marked planned with its owner ticket; project structure lists only paths that exist), C07 (NFT lien/foreclosure removed from README/TECH/WHY_WE_PIVOTED/deck/scripts; `WHY_WE_PIVOTED.md` §3 records why the NFT draft was retired), C08 (credit model rewritten to PIVOT §6.3 eligible unpaid receivables; trailing-payout formula removed), C09/C10/C13 (`HACKATHON_MVP_SCOPE.md` rewritten: atomic receipt event, log-level consumption key, etched double only from `local-mock.json`), C11 (README/TECH/DORAHACKS now cite the GPU-075 pinned names and versions from `docs/gpu/attestcoin/environment.md`), C14/C15 (demo substitutions restated as G-ASC TEST_ONLY with `partnerRevenue=SIMULATED`, E2 not demonstrable with a mock payer), C16 (README/TECH reflect GPU-001's `testnet_demo` isolation), C19 (build order re-keyed to ticket prerequisites and GPU-080 approval scope). v1 docs (`docs/specs/PROJECT.md`, `BTC_IDENTITY_BINDING.md`, `threat-model.md`, `audit-checklist.md`, `provenance.md`, `gas-limits.md`, `adr/0001-btc-spv.md`) carry a legacy header; `docs/hackathon/ADDITIONAL_QUESTION.md` is marked v1 history; `CEIP.md` product-fit sections updated. Still open: C03 (R2-O05), C12 body (legacy reference kept), C17 (runtime facts now from GPU-075), C18 (v1 live URLs not verified), C20 (`docs/process/TICKET.md` preserved).

Not conflicts (kept as-is): README pivot notice framing (v1 winner, rename, legacy identifiers); WHY_WE_PIVOTED
narrative with its explicit enforcement disclaimer (line 76); PIVOT §1/§4–§6 product, E-level and accounting
conditions (these *are* R2's financial basis); TECH §6 accounting invariants (consistent with R2-D07).

## 3. Cross-table: docs ↔ code/artifacts checked in this ticket

| Check | Command / method | Result |
| --- | --- | --- |
| Attestcoin/USC identifiers in code | `grep -rniE "attestcoin\|usc[-_ ]?sdk\|blockprover\|0x…0fd2\|gluwa"` over `*.sol *.py *.ts *.tsx *.json *.toml *.sh *.yml` (excl. deps/build) | 0 files |
| Proposed R2 paths | `ls contracts/gpu test/gpu offchain/gpu offchain/attestcoin config/attestcoin test/fixtures/gpu docs/gpu/attestcoin` | all absent except `docs/gpu/` (created by GPU-000/074) |
| Node workspaces / lockfiles | root `package.json` workspaces; `apps/web/package-lock.json` grep `gluwa` | web only; no `@gluwa/*` |
| Legacy auto-grant path | grep `grantTestnetCredit`, `register-and-grant` | present in `HashCreditManager.sol:197`, `hashcredit_api/evm.py`, `models.py` |
| v1 addresses | grep `0x593e14…2055` | README, TECH, `.env.example`, `apps/web/src/lib/env.ts` (default) — consistent among themselves; chain not queried |
| Owner ticket IDs referenced above | grep `^### GPU-NNN` in `TICKET.md` | all exist |

## 4. Change log

- 2026-09-14 GPU-074: initial inventory and register; targeted edits to `README.md`, `TECH.md`,
  `docs/specs/USC_ADAPTER.md`, `docs/hackathon/HACKATHON_MVP_SCOPE.md` (see the ticket record for diffs).
- 2026-09-14 GPU-075: SDK/ABI/manifest rows updated; C11/C17 resolved for CC3 testnet with pinned artifacts and probe.
- 2026-09-14 GPU-065.a: communication-document rewrite to the R2 product (see §2 note); inventory §1 unchanged (no new code); `docs/gpu/decisions/attestcoin-first.md` R2-O08 marked DECIDED.
