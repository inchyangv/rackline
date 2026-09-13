# Hackathon MVP Scope — Rackline (GPU NFT Credit)

> Purpose: the **thinnest vertical slice** that makes every claim in `DORAHACKS.md` and `DECK.md` demonstrable on Creditcoin CC3 testnet + Sepolia.
> This is a demo scope with TEST_ONLY parameters. The production path (partner due diligence, E2 control PoC, accounting core, audit) stays in `TICKET.md` / `PIVOT.md` and is not replaced by this document.
>
> **R2 note (2026-09-14).** Several demo constructs below do **not** satisfy R2 production rules (`docs/gpu/decisions/attestcoin-first.md`; conflict register in `docs/gpu/execution/ATTESTCOIN_GAP.md` §2): `notify(token, amount)` callable by anyone after a balance check (C09), the transaction-level replay key (C10), a `MockNativeQueryVerifier` that returns `true` (LOCAL-only test double, never a native/testnet profile, C13), NFT lien as collateral/enforcement (C07), and trailing-payout limits (C08). Any public-testnet deployment or broadcast requires the GPU-080 approval scope. Nothing in this scope is implemented in the repository as of 2026-09-14.

## 0. Non-negotiables (from the v1 post-mortem)
- No testnet auto-grant credit in the v2 path. Credit comes only from recorded `RevenueEvidence`.
- No owner-key API endpoint. The keeper signs with its own limited key; admin actions are Foundry scripts.
- Draw pause and repayment pause are separate functions; the demo never pauses repayments.
- Debt decreases only when `LendingVault` receives stablecoin (`repayFor`), never on source-chain receipt alone.
- The UI labels simulated components ("Simulated network", "Mock settlement").

## 1. Deliverables

### 1.1 Contracts — Creditcoin CC3 testnet (`contracts/gpu/`)
| Contract | Minimum behavior for the demo |
|---|---|
| `GpuNodeNFT` | `mint(provider, sku, unitCount, hardwareHash, sourceChainKey, nodeAccount)`; unique `hardwareHash`; `lock/unlock` by manager; transfer reverts while locked; `foreclose(tokenId, to)` by manager |
| `IRevenueVerifier` + `RevenueEvidence` | as specified in `TECH.md` §3 |
| `AttestcoinRevenueVerifier` | `verifyRevenue(bytes proof)`: decode `(chainKey, blockHeight, encodedTx, merkleProof, continuityProof)`; call `INativeQueryVerifier(0x0FD2).verifyAndEmit`; `EvmV1Decoder` receipt + `PayoutReceived` log; `receiptStatus == 1`; emitter must equal `nodeAccount[tokenId]`; replay map |
| `GpuCreditManager` | `recordRevenue(proof)`, `limitOf(tokenId)`, `borrow(tokenId, amount)` (locks NFT), `repay(tokenId, amount)`, `repayFor(tokenId, amount)` (anyone), `pauseDraws/unpauseDraws`, `markDefault(tokenId)` → `foreclose` (owner-only for demo) |
| `LendingVault` v2 | reuse v1 vault with: per-facility ledger `(principal, accruedInterest)`, partial-interest preservation, `repayFor` routing, `reserveBps` skim, `availableCash()` |
| `RiskConfig` v2 | `advanceRateBps[class]`, `trailingWindow`, `evidenceMaxAge`, `perNodeCap`, `globalCap`, `sweepBps` |

Tests (Foundry, `test/gpu/`): mint uniqueness; lock/transfer revert; verifier replay; emitter mismatch revert; receipt status 0 revert (mock precompile); limit math with fresh/stale evidence; borrow → lock; `repayFor` by third party reduces debt; partial interest regression ($5,000 / 10% / 1y / $250 → $5,250 remaining); draw pause does not block `repayFor`.

Mocking the precompile locally: a `MockNativeQueryVerifier` at a configurable address that returns `true` and lets tests inject `encodedTx` fixtures (captured from a real Sepolia tx via the prover API).

### 1.2 Contracts — Sepolia (`contracts/gpu/source/`)
| Contract | Minimum behavior |
|---|---|
| `NodeAccountRegistry` | `account(tokenId)` deterministic (CREATE2) → `NodeAccount` |
| `NodeAccount` | receive ERC-20 (and native); `PayoutReceived(tokenId, token, amount)` emitted by `notify(token, amount)` called by the payer or by anyone after balance check; `sweep()` sends `sweepBps` to `settlementReceiver` and remainder to `operator`; `setPolicy` only by `controller`; `locked` flag set by controller |
| `MockDePINPayout` | `pay(nodeAccount, token, amount)` mints/transfers a mock reward token and calls `notify` |

### 1.3 Keeper (`offchain/keeper/`, Python, reuse prover/relayer scaffolding)
1. Poll Sepolia logs for `PayoutReceived` (persistent cursor).
2. Wait for finality/attestation; `GET {PROVER_URL}/proof-by-tx/{chainKey}/{txHash}`.
3. Encode proof → `GpuCreditManager.recordRevenue(proof)` on Creditcoin (idempotent; skip if replay key exists).
4. If facility debt > 0: call `NodeAccount.sweep()` on Sepolia; then execute the mock settlement leg (keeper transfers mUSDT it holds on Creditcoin) → `repayFor(tokenId, amount)`; record `settlementId` linking both txs.
5. Structured logs shown in the demo video.

### 1.4 Web (`apps/web/`)
- **Operator tab**: register form → mint; NFT card (tokenId, provider, SKU, hardware hash, Node Account address with Etherscan link, lock state); credit card (limit, drawn, available); Borrow / Repay.
- **Node tab**: evidence table (source tx, block, amount, class, Blockscout link); sweep history with `settlementId`; "Simulated" badges.
- **Pool tab**: reuse v1 (deposit / withdraw, metrics) + reserve display; remove fixed-APR wording.
- Remove BTC claim flow from the v2 route; keep v1 reachable under `/legacy` or a separate build flag.

### 1.5 Docs / submission
- Fill `<TODO>` addresses in `DORAHACKS.md`, `TECH.md`, `README.md`.
- Record the demo video with `SCRIPT.md`; upload deck PDF (export from `Rackline_GPU_Deck.pptx`).
- Tag v1 as `v1-spring-2026`; tag submission as `v2-fall-2026`.

## 2. Suggested build order (2 engineers)
| Day | Work |
|---|---|
| 1 | Interfaces (`IRevenueVerifier`, `RevenueEvidence`), `GpuNodeNFT`, `RiskConfig` v2, Foundry skeleton |
| 2 | `NodeAccount` + registry + `MockDePINPayout` on Sepolia; capture a real `PayoutReceived` tx; fetch proof via prover API; save fixture |
| 3 | `AttestcoinRevenueVerifier` against the fixture (mock precompile locally, real precompile on testnet); `GpuCreditManager.recordRevenue` |
| 4 | `LendingVault` v2 ledger fixes + `repayFor`; `borrow` lock; tests incl. partial-interest regression |
| 5 | Keeper end to end; deploy scripts (no auto-grant, no mock token unless flagged TEST_ONLY) |
| 6 | Web: Operator / Node tabs; Pool cleanup; labels |
| 7 | Dry run of `SCRIPT.md`; video; fill addresses; submit |

## 3. Out of scope for the demo (explicitly)
- Real Aethir / GPU.net API connectors and partner receiver locks (Phase 1 PoC).
- Real bridge / settlement partner (mock leg only).
- Default → foreclosure UI (contract function + test only).
- Secondary market for GPU NFTs, insurance, fractionalization.
- Legal documents (operator agreement, receivable assignment) — templates only.

## 4. Verification commands
```bash
forge build --sizes && forge test --match-path 'test/gpu/*' -vvv
python -m pytest offchain/keeper/tests -q
npm --prefix apps/web run lint && npm --prefix apps/web run build
```
