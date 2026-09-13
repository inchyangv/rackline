# Demo Slice — Rackline (GPU Receivables Credit, R2-aligned)

> Purpose: the **thinnest vertical slice** that makes every claim in `DORAHACKS.md` and `DECK.md` demonstrable on Creditcoin CC3 testnet + Sepolia **without contradicting the R2 production rules**. It is the demo-facing view of tickets GPU-077 (source event contract), GPU-078 (native verifier), GPU-079 (proof worker), GPU-080 (public-testnet native E2E, G-ASC) and the minimal facility flow; it does not replace their specs and adds no production decision.
> This is a demo scope with TEST_ONLY parameters. The production path (partner due diligence, E2 control PoC, financial core, audit) stays in `TICKET.md` / `PIVOT.md`.
>
> **Status (2026-09-14):** official artifacts pinned and CC3 testnet probed read-only (GPU-075). Nothing else in this document is implemented. Any public-testnet deployment or broadcast requires the GPU-080 approval scope (dedicated wallet, gas / test tokens, contracts, period). The earlier NFT-based slice (`GpuNodeNFT`, `NodeAccount.notify(amount)`, trailing-payout `limitOf`, transaction-level replay key, always-true `MockNativeQueryVerifier` in a testnet profile) is retired — see `docs/gpu/execution/ATTESTCOIN_GAP.md` §2 C07–C10, C13.

## 0. Non-negotiables (R2)
- Only official Attestcoin native verification produces `nativeStatus=VERIFIED`. No self-signed / relayer attestation, no admin approval, no mock verifier in a native or production profile. HTTP 200 / SDK `success:true` ≠ verified.
- No testnet auto-grant credit and no owner-key API on the GPU path. Base comes only from the receivable ledger fed by verified events; admin actions are Foundry scripts with a limited key.
- Debt decreases only when the vault receives loan currency and `repayFor` allocates it — never on source receipt, proof, or cross-chain message.
- Draw pause and repayment pause are separate; the demo never pauses repayments.
- A past payment event is history; it reduces the receivable and never creates new base. Freshness is bound to a checkpoint field the demo source publishes, not to acceptance time.
- Five judgments are shown separately in the UI: source event · provenance · unpaid receivable · control · cash.
- Every simulated component is labelled: `Simulated payer`, `Mock settlement`, `partnerRevenue=SIMULATED`, `controlGrade=E1 (mock)`.

## 1. Deliverables

### 1.1 Contracts — Creditcoin CC3 testnet (`contracts/gpu/`; specs GPU-029/031/033~036/039/078)
| Contract | Minimum behavior for the demo |
|---|---|
| `AttestcoinRevenueVerifier` | `recordEvent(bytes proof)`: decode `(chainKey, height, encodedTransaction, merkleProof, continuityProof)` from the manifest-pinned ABI; call `INativeQueryVerifier(0x…0FD2).verifyAndEmit(...)`; `EvmV1Decoder.decodeReceiptFields` on the verified bytes; `receiptStatus == 1`; the settlement event must come from the registered escrow for that facility on that `chainKey`; `txIndex` from `calculateTxIndex(merkleProof)`; hand the canonical event to `EvidenceBook`. Refuses a manifest whose `executionProfile=LOCAL_MOCK` or unpinned hash. |
| `EvidenceBook` | Records the canonical event once: consumption key = (chainKey, height, txIndex, receipt log ordinal) + canonical source identity; emits `EventRecorded`; reversals reference the original. |
| Control registry (minimal) | Records the demo escrow's control agreement hash, grade (`E1`, mock) and validity; the facility manager reads it and refuses funded draws above the demo's TEST_ONLY cap without `E2` — the demo shows the refusal path once. |
| Facility manager + debt ledger (minimal) | `openFacility`, `updateReceivables(...)` from the reconciled ledger (worker-authorized, versioned), `availableDraw(facility)`, `draw(facility, amount)`, `repay`, `repayFor(facility, amount)` (anyone), `pauseDraws / unpauseDraws`; single principal / unpaid-interest ledger; partial interest preserved. |
| `LendingVault` v2 (minimal) | per-facility ledger `(principal, accruedInterest)`, `repayFor` routing, `reserveBps` skim, `availableCash()`, deposit / withdraw limited to available cash. |
| `RiskConfig` v2 (minimal) | `advanceRateBps`, `freshnessMaxAge`, `perFacilityCap`, `globalCap`, eligible token list, `haircutBps`. |

Tests (Foundry, `test/gpu/`): verifier rejects wrong emitter / wrong event / `receiptStatus == 0` / replayed log / second log in the same tx consumed once / unpinned manifest; `EvidenceBook` reversal; base math with fresh vs stale checkpoint (stale ⇒ draw blocked); `draw` re-checks control validity; `repayFor` by a third party reduces debt; partial-interest regression ($5,000 / 10% / 1y / $250 → $5,250 remaining); draw pause does not block `repayFor`; proof-outage flag blocks new draws but not `repayFor`.

Local mocking (GPU-078, R2-D12): an etched precompile double wired **only** from `config/attestcoin/local-mock.json` (`executionProfile=LOCAL_MOCK`, `mock=true`); it replays captured official proof vectors, never returns unconditional `true`, and cannot be selected by a native / production manifest. Captured fixtures carry provenance (`test/fixtures/gpu/attestcoin/`).

### 1.2 Contracts — Sepolia (`contracts/gpu/source/`; spec GPU-077)
| Contract | Minimum behavior |
|---|---|
| Controlled escrow (per facility) | Receives ERC-20 settlements; emits the receipt event **in the same transaction as the transfer** (`SettlementReceived(facilityId, payer, token, amount, settlementRef)`) — no arbitrary `notify(amount)`, no balance re-reporting; `setReceiver` / policy only by the controller under the recorded agreement; `sweep()` sends the agreed share to the settlement route and the remainder to the operator. |
| `MockDePINSettlement` (TEST_ONLY) | `settle(escrow, token, amount, settlementRef, checkpoint)` mints / transfers a test token and pays the escrow; publishes a `checkpoint` (statement revision) the worker uses for freshness. Marked `partnerRevenue=SIMULATED`; never deployed with a production manifest. |

### 1.3 Proof worker (`offchain/attestcoin/`, TypeScript; spec GPU-079) + Python ledger glue
1. Poll Sepolia logs for `SettlementReceived` from registered escrows (persistent cursor).
2. Wait until the height is attested (`/api/v1/attested-height/{chainKey}`); fetch `GET /api/v1/proof-by-tx/{chainKey}/{txHash}` through the pinned SDK 0.18.0. Treat the response as untrusted input; `success:true` is not verification.
3. Encode and submit `AttestcoinRevenueVerifier.recordEvent(proof)` on Creditcoin (idempotent; skip if the consumption key exists). Record `nativeStatus` only from the on-chain result / `EventRecorded`.
4. Reconcile the verified event with the demo receivable ledger (checkpoint from the mock source): update eligible unpaid receivables and freshness; a `paid` event reduces the receivable.
5. If facility debt > 0 after a settlement: call `escrow.sweep()` on Sepolia; execute the **mock settlement leg** (worker transfers test stablecoin it holds on Creditcoin) → `repayFor(facility, amount)`; record one `settlementId` linking both txs; `cashState` moves `IN_FLIGHT → RECEIVED` only on the Creditcoin receipt.
6. Structured logs shown in the demo video.

### 1.4 Web (`apps/web/`; GPU-047~050 minimal)
- **Facility** — onboarding state, control grade with `mock` label, receivable ledger (eligible / unpaid / stale), available draw, Draw / Repay, statement of draws and `repayFor` receipts.
- **Evidence** — verified events table (source tx, block, log ordinal, amount, `nativeStatus`, Blockscout / Etherscan links); settlement history with `settlementId` and `cashState`; `Simulated payer` / `Mock settlement` badges.
- **Lend** — reuse the v1 pool screen (deposit / withdraw, metrics) + reserve and withdrawal-queue display; no fixed-APR wording.
- Keep the v1 flow reachable under a legacy namespace or build flag (GPU-047).

### 1.5 Docs / submission
- Fill addresses in `DORAHACKS.md`, `TECH.md` §10, `README.md` **only after** they exist; keep `<TODO — not deployed>` otherwise.
- Record the demo video with `SCRIPT.md` (Part A today; Part B after this slice); export the deck PDF from `Rackline_GPU_Deck.pptx`.
- Tag v1 as `v1-spring-2026`; tag the submission as `v2-fall-2026`.

## 2. Suggested build order (2 engineers; follows ticket prerequisites)
| Step | Work | Ticket |
|---|---|---|
| 1 | Interfaces, evidence types, consumption-key contract, `EvidenceBook` | GPU-029, 031, 076 |
| 2 | Source escrow + `MockDePINSettlement`; capture a real Sepolia settlement tx; fetch the official proof; save fixture with provenance | GPU-077, 080 (approval scope) |
| 3 | `AttestcoinRevenueVerifier` against the fixture (etched double from `local-mock.json` locally; real precompile on CC3 testnet) | GPU-078 |
| 4 | Minimal facility manager / debt ledger / vault / risk config; `repayFor`; regression tests | GPU-033~036, 039, 034 |
| 5 | Proof worker end to end; ledger glue; deploy scripts (no auto-grant; test token only under TEST_ONLY flag) | GPU-079, 062 |
| 6 | Web: Facility / Evidence screens; Lend cleanup; labels | GPU-047~050 |
| 7 | Dry run of `SCRIPT.md` Part B; video; fill addresses; submit | — |

## 3. Out of scope for the demo (explicitly)
- Real Aethir / GPU.net API connectors and partner receiver locks (real E2 is GPU-009/038; the demo's control grade is `E1 (mock)`).
- Real bridge / settlement partner (mock leg only; real rail is GPU-040).
- Default → recovery UI (contract functions + tests only).
- NFT collateral, secondary markets, insurance, fractionalization (DEFERRED products, GPU-068~072).
- Legal documents (operator agreement, receivable assignment) — templates only.
- Any claim that a testnet native proof pass is partner, E2, cash or business approval evidence.

## 4. Verification commands
```bash
npm --prefix offchain/attestcoin run check && npm --prefix offchain/attestcoin run test -- --run   # exists today
forge build --sizes && forge test --match-path 'test/gpu/*' -vvv                                  # after step 1
python -m pytest offchain/gpu/tests -q                                                             # after GPU-015
npm --prefix apps/web run lint && npm --prefix apps/web run build
bash script/gpu/attestcoin_native_e2e.sh --manifest config/attestcoin/cc3-testnet.sepolia.json --approval <ref>   # GPU-080, approved scope only
```
