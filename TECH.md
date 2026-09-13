# Rackline — Technical Note

> Rackline, formerly HashCredit. GPU NFT credit on Creditcoin: Attestcoin-proven revenue, on-chain payment control, self-repaying facilities.
> v1 (Bitcoin SPV) technical note is archived in git history and under `archive/v1-btc/` (local).

---

## 1. The core idea

A lender needs three things from an asset: to identify it, to route its cash, and to reclaim it. Bitcoin hashrate offered none of these without a mining pool's cooperation. A GPU deployment on a DePIN network offers all three:

- **Identify** — hardware UUID / serial, host and group ids, SKU and count.
- **Route** — the network pays a receiver address it records on-chain.
- **Reclaim** — revenue rights are assignable; hardware is a serialized machine with a resale market.

Rackline wraps those three properties in one on-chain object, the **GPU NFT**, and lends against the revenue that flows through it.

```
Register deployment → mint GpuNodeNFT (Creditcoin)
Network pays the NFT's NodeAccount (source chain: Ethereum / Sepolia)
Attestcoin proves the payout on Creditcoin → RevenueEvidence → credit limit
Operator draws stablecoin → NFT locked (lien)
Next payout → NodeAccount.sweep() → repayFor(tokenId) → debt falls
Sustained default → GpuNodeNFT forecloses to the vault
```

---

## 2. Components

### 2.1 Creditcoin CC3 (credit layer)

| Contract | Responsibility |
|---|---|
| `GpuNodeNFT` (ERC-721) | One token per registered deployment. Stores `provider`, `sku`, `unitCount`, `hardwareHash`, `sourceChainKey`, `nodeAccount`, `status`. `lock(tokenId)` / `unlock(tokenId)` callable only by the credit manager; transfers revert while locked; `foreclose(tokenId, to)` moves a defaulted token to the vault. Duplicate `hardwareHash` mints revert. |
| `IRevenueVerifier` | `verifyRevenue(bytes proof) returns (RevenueEvidence)`. Successor of v1's `IVerifierAdapter`; provider- and chain-neutral. |
| `AttestcoinRevenueVerifier` | Implements `IRevenueVerifier` over the BlockProver precompile. See §3. |
| `RelayerSigVerifier` (v1, retained) | EIP-712 attested evidence for chains Attestcoin does not cover yet. Evidence from this adapter is labeled *attested*, never *proven*, and gets a lower advance rate in `RiskConfig`. |
| `GpuCreditManager` | Facilities keyed by `tokenId`. Records evidence (replay-protected), maintains trailing net revenue, computes the limit, executes `borrow`, `repay`, `repayFor`, draw freeze, default and foreclosure. Separate `pauseDraws()` and `pauseRepayments()`; the latter is never used in normal incidents. |
| `LendingVault` (v2) | Stablecoin LP pool. Single ledger for principal / accrued interest / fees per facility; partial interest payments preserve the unpaid balance; APR changes never apply retroactively; first-loss `reserve`; `recognizeLoss` / `recordRecovery`; withdrawals limited to available cash. |
| `RiskConfig` (v2) | `advanceRateBps` (per evidence class), `trailingWindow`, `evidenceMaxAge`, `perNodeCap`, `perProviderCap`, `globalCap`, `reserveBps`, `sweepBps`, `defaultGraceSeconds`. |

### 2.2 Source chain (Ethereum / Sepolia)

| Contract | Responsibility |
|---|---|
| `NodeAccount` | Per-NFT escrow deployed through a registry (ERC-6551-style: `(chainId, GpuNodeNFT, tokenId)` → deterministic address). Accepts ERC-20 / native payouts, emits `PayoutReceived(uint256 indexed tokenId, address indexed token, uint256 amount)`. `sweep()` splits by `policy` (repayment share → settlement route, remainder → operator). `setPolicy` / `setReceiver` are callable only by the protocol `controller`; while the Creditcoin lien is active the controller refuses operator-initiated changes. |
| `MockDePINPayout` | Testnet stand-in for the network's payout contract. Not deployed on mainnet. |

Following Attestcoin's source-chain guidance, the source contracts stay minimal: hold funds and emit events; business logic lives on Creditcoin.

### 2.3 Off-chain

| Service | Responsibility |
|---|---|
| `keeper` | Watches `PayoutReceived` on the source chain → `GET {prover}/proof-by-tx/{chainKey}/{txHash}` → `GpuCreditManager.recordRevenue(proof)` → schedules `sweep()` → executes the settlement leg → `repayFor(tokenId)`. Durable job queue, idempotency keys, nonce dispatcher. |
| `api` | Provider connectors (Aethir Cloud Host statements, GPU.net supplier statements) for underwriting, receivable reconciliation, and control-state monitoring. Read-only credentials; never holds owner keys. |
| `web` | React 19 / Vite / ethers v6. Operator (register, mint, credit, draw), Node (evidence, sweeps, lien state), Pool (LP). |

---

## 3. Attestcoin integration

Attestcoin proves that a transaction is included in a finalized block of a supported source chain, then lets a Creditcoin contract decode it synchronously.

```
Source chain               Keeper                              Creditcoin
────────────────────────   ─────────────────────────────────   ────────────────────────────────────────
NodeAccount emits          GET prover.cc3-testnet              AttestcoinRevenueVerifier.verifyRevenue
PayoutReceived(...)   →    .creditcoin.network/          →       INativeQueryVerifier(0x0FD2)
in tx T, block B           proof-by-tx/{chainKey}/{T}            .verifyAndEmit(chainKey, B, encodedTx,
                           → encodedTx, merkleProof,                            merkleProof, continuityProof)
                             continuityProof                     EvmV1Decoder.decodeReceiptFields(encodedTx)
                                                                 require(receipt.receiptStatus == 1)
                                                                 logs = getLogsByEventSignature(receipt, PAYOUT_RECEIVED)
                                                                 require(log.emitter == nodeAccount[tokenId])
                                                                 evidence = RevenueEvidence{...}
                                                                 processedQueries[keccak(chainKey, B, txIndex)] = true
```

```solidity
struct RevenueEvidence {
    uint256 tokenId;        // GpuNodeNFT
    address token;          // payout asset on the source chain
    uint256 amount;         // base units
    uint64  chainKey;       // Attestcoin chain key (Sepolia = 1 on CC3 testnet)
    uint64  blockHeight;
    uint32  txIndex;
    uint64  timestamp;      // source block timestamp
    uint8   evidenceClass;  // 0 = Attestcoin-proven, 1 = relayer-attested
}
```

Rules enforced in the verifier:
- The precompile does not check transaction success; `receiptStatus == 1` is mandatory.
- The `PayoutReceived` log must be emitted by the `NodeAccount` registered for that `tokenId` on that `chainKey`. Logs from other emitters are ignored.
- Replay key = `keccak256(chainKey, blockHeight, txIndex)` at the verifier; the manager additionally keys on `(tokenId, chainKey, blockHeight, txIndex)`.
- Token allow-list per provider (`RiskConfig`); unknown payout tokens are recorded but excluded from the borrowing base.

Environments (from Attestcoin docs, 2026-09): CC3 testnet sources are Ethereum Sepolia (chainkey 1) and Ethereum mainnet (chainkey 3); CC3 mainnet source is Ethereum mainnet (chainkey 1). Precompiles: BlockProver `0x...0FD2`, ChainInfo `0x...0FD3`. SDK: `@gluwa/usc-sdk`. Chains not yet supported (e.g. Arbitrum) fall back to the attested adapter with a lower advance rate.

---

## 4. Credit model

```
EligibleRevenue   = Σ verified net payouts in trailingWindow, per evidence class
                  − provider deductions / disputes / refunds known to the connector
                  − staleness / concentration / token-liquidity haircuts
ReceivableLimit   = EligibleRevenue × advanceRateBps[class] / 10_000
FacilityLimit     = min(ReceivableLimit, approvedCap[tokenId])
FacilityRoom      = FacilityLimit − principal − accruedInterest − reservedDraws
AvailableDraw     = max(0, min(FacilityRoom, perProviderHeadroom, globalHeadroom, vault.availableCash()))
```

Every `borrow` re-evaluates the formula with current evidence (must be younger than `evidenceMaxAge`) and current control state (`NodeAccount` policy version matches the one recorded at facility open). A stale "locked" observation does not authorize a draw.

Credit is never derived from nominal GPU count, FLOPS, advertised utilization, or token price appreciation. Testnet auto-grant credit does not exist in v2.

---

## 5. Payment control and default

| Level | State | Lending |
|---|---|---|
| E0 | Read-only API, signatures, payout history | Observe |
| E1 | `NodeAccount` set as receiver, operator can still change it at the network | Observe + control experiments |
| E2 | Network / contract recognizes the assignment; operator cannot change the receiver alone while debt is open | Funded facilities |
| E3 | E2 + physical lien, custodian consent, removal restrictions | Equipment purchase financing |

State machine per facility: `Draft → UnderReview → ControlPending → Active → Repaid → Released`, with the recovery branch `Active → DrawFrozen → Delinquent → Defaulted → Recovery → ClosedWithLoss`.

On default: draws freeze immediately; sweeps continue and `sweepBps` rises to the default ratio; after `defaultGraceSeconds` the manager calls `GpuNodeNFT.foreclose(tokenId, vault)`. Loss is recognized against `reserve` first, then LP NAV. Write-off keeps the recovery record open.

What is not on-chain: legal assignment of receivables, the operator agreement, and any hardware lien. These are prerequisites tracked per facility (`controlAgreementHash`, `agreementVersion`) and verified off-chain before `ControlPending → Active`.

---

## 6. Accounting invariants (v2 ledger)

- `principal + accruedInterest + fees` per facility reconciles to the vault's per-facility ledger at every state change.
- Partial interest payment reduces `accruedInterest` only; it never resets the accrual timestamp.
- Rate changes create a new accrual segment; prior segments are frozen at their rate.
- Source-chain receipt, in-flight settlement, and vault receipt are three states; only the last reduces debt.
- `Σ LP claims + reserve + protocol fees = vault cash + outstanding principal − recognized losses`.
- Draw pause never blocks `repay` / `repayFor`.

Regression vectors from the v1 review (e.g. $5,000 at 10% for one year, $250 partial interest → remaining $5,250, not $5,000) are fixtures in the v2 test suite.

---

## 7. What is reused from v1

| v1 | v2 |
|---|---|
| `IVerifierAdapter` / `PayoutEvidence` | `IRevenueVerifier` / `RevenueEvidence` (same seam, new ABI) |
| `HashCreditManager` | `GpuCreditManager` (facility-per-NFT, `repayFor`, lien, separate pauses) |
| `LendingVault` | `LendingVault` v2 (corrected accounting, reserve, loss recognition) |
| `RiskConfig` | `RiskConfig` v2 (GPU policy, evidence classes, freshness) |
| `RelayerSigVerifier` | retained as the attested adapter |
| `BtcSpvVerifier`, `CheckpointManager`, `BitcoinLib`, prover worker | legacy; not deployed on the v2 path |
| Wallet UX, Zustand stores, shared UI, Foundry invariants, Railway / Vercel | reused |

---

## 8. Testnet substitutions (stated for judges)

| Real system | Demo |
|---|---|
| Aethir / GPU.net payout contract | `MockDePINPayout` on Sepolia |
| Sepolia → Creditcoin settlement (bridge / partner) | Keeper executes the leg with a mock bridge |
| Partner receiver lock (E2) | Enforced at the `NodeAccount` controller only; partner-level lock is the Phase 1 PoC |
| Provider statements | Fixture data in the API |

Everything else — mint, Attestcoin verification, limit computation, draw, lien, sweep, `repayFor`, LP accounting — runs as real contracts on Creditcoin CC3 testnet.

---

## 9. Contracts (Creditcoin CC3 testnet, chainId 102031)

| Contract | Address |
|---|---|
| GpuNodeNFT | `<TODO>` |
| AttestcoinRevenueVerifier | `<TODO>` |
| GpuCreditManager | `<TODO>` |
| LendingVault v2 | `<TODO>` |
| RiskConfig v2 | `<TODO>` |
| Stablecoin (mUSDT) | `0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A` |

Sepolia: NodeAccount registry `<TODO>`, MockDePINPayout `<TODO>`.

Legacy v1 (still live): HashCreditManager `0x593e140982cDC040d69B7E7623A045C6d6Ca2055`, LendingVault `0x4d74126369BacB67085a1E70d535cA15515d1AFa`, BtcSpvVerifier `0x16DEd6a617a911471cd4549C24Ed8C281f096fd2`, CheckpointManager `0x4Ae5418242073cd37CCc69C908957E413a04f6f9`.
