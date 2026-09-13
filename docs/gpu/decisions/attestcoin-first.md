# R2 Decision Ledger — Attestcoin-first (official native verification required)

Status: ACCEPTED for FIXED items (user decision 2026-09-14, recorded by GPU-074) · OPEN items need a separate,
explicit user decision. Source of authority: user's R2 requirement + `TICKET.md` §0.9. This ledger governs
where `PIVOT.md`, `TECH.md`, `README.md`, `docs/specs/USC_ADAPTER.md` and `docs/hackathon/*` disagree.
Conflicts and their owner tickets are listed in `docs/gpu/execution/ATTESTCOIN_GAP.md`.

Decision IDs are stable references for execution records (`적용한 결정 ID`). Version: **R2-v1 (2026-09-14)**.
Changing a FIXED item requires a new ledger version and re-verification of dependent tickets (§0.4).

## 1. FIXED decisions

| ID | Decision | What it excludes | Applies to |
| --- | --- | --- | --- |
| R2-D01 | **Loan ledger and execution chain are Creditcoin.** CTC gas/network, the Attestcoin protocol, and the loan stablecoin are three separate configuration items. | Reading "Creditcoin" as CTC/ATC collateral, CTC/ATC loan currency, or a token-purchase decision. PIVOT §10.2's second configuration (vault on another settlement chain) is *not* adopted; adopting it is R2-O05. | GPU-006, 010, 029~043, 062 |
| R2-D02 | **External source-chain facts are verified only through the official Attestcoin native path**: official BlockProver precompile call + official decoder over the *exact verified bytes*, with the official SDK/proof service as the proof source, all pinned by version/commit/hash (GPU-075). | Any other verifier as the source of `nativeStatus=VERIFIED`. HTTP 200 / SDK local success / keeper signature ≠ VERIFIED. | GPU-075, 078, 079, 080, 082 |
| R2-D03 | **No substitute and no automatic fallback.** Self-signed EIP-712 oracle/relayer attestation, admin approval, BTC SPV, or mock/etched verifiers cannot stand in for native verification in any production or NATIVE_TESTNET profile. There is **no "attested" evidence class with a lower advance rate**. | TECH §2.1/§3 and README "attested adapter, lower advance rate"; PIVOT §10.3 "EIP-712 signer quorum initial integration" option; USC_ADAPTER "SPV is a valid instantiation" as a production argument. | GPU-029, 035, 078, 081, 082 |
| R2-D04 | **Auxiliary signature paths persist for their own purposes**: wallet authentication, covenant/agreement consent, underwriting approval, partner rights attestations. They are `OFFCHAIN_ASSERTION` inputs and never create source facts or borrowing base. | Laundering an OFFCHAIN_ASSERTION (including our own statement-hash anchor emitted on a supported chain) into native GPU revenue. | GPU-013, 017, 024, 076, 081 |
| R2-D05 | **Five judgments stay separate**: (a) official proof → *this event occurred on this source*; (b) GPU operating-revenue provenance; (c) current unpaid eligible receivable; (d) E2 payment control; (e) actual destination cash receipt. Each is verified and recorded on its own (`nativeStatus`, `earningsProvenance`, `controlGrade`, `cashState`). | Treating (a) as any of (b)–(e). | GPU-011, 076, 077, 081 |
| R2-D06 | **History is not a receivable; old proofs cannot refresh freshness.** Past payout events reduce/record history only. Inclusion of a past event does not prove current unpaid status or the absence of later paid/cancel/correction. Freshness is bound to a source-authority checkpoint/revision or an approved bounded-lag/buffer/reservation policy, never to acceptance time or an API watermark alone. | "no paid event seen ⇒ unpaid"; re-submitting an old proof to extend validity; trailing-payout sums as borrowing base for the first product. | GPU-076, 077, 081, 082 |
| R2-D07 | **Debt is reduced only by actual loan-currency receipt at the designated destination account/Vault, allocated to the facility (`repayFor`).** Source receipt, claimable amount, oracle assertion, cross-chain message, or proof are not repayment. Proof-service outage does not block permitted direct `repayFor`, recovery, or existing rights. | Double-reduction across source and destination; auto-default or global repayment pause on proof outage. | GPU-037, 039, 040, 081 |
| R2-D08 | **Unsupported source ⇒ `UNSUPPORTED_SOURCE`, admission off.** If the chosen partner's real payout chain is outside official support, that path is not launched; deploying our own emitter on a supported chain or proving only a post-bridge arrival does not prove the original chain's payment. | Auto-enabling unsupported chains; lower-advance-rate workaround. | GPU-008, 075, 076, 020/021 |
| R2-D09 | **Writability is not assumed available.** Remote payment control uses real partner authority (GPU-009/038); fund movement uses verified settlement rails (GPU-040). Any future Writability adoption needs a new support check, threat model, and approval ticket. | Designing cross-chain claim/receiver changes or a trustless bridge into the current scope. | GPU-009, 038, 040 |
| R2-D10 | **First product = financing of confirmed, assignable, currently unpaid GPU receivables** with E2 control. GPU rental marketplace, node-NFT collateral loans, future-cash-flow products, equipment finance, token loans are separate DEFERRED decisions (GPU-068~072). | Promoting the hackathon NFT/trailing-payout demo to production collateral. | GPU-003, 008, 010, 072 |
| R2-D11 | **Pinning**: official SDK (`@gluwa/usc-sdk` per docs), compatible ethers peer, official contract/decoder artifacts, supported-chain table, chainKey/encoding, endpoints — all resolved from latest official material *and* actual artifacts, recorded with version/commit/integrity in a manifest (GPU-075). No `latest`, no invented package/method/address. SDK method names (e.g. `verifySingle`) are not copied as native Solidity function names. | Trusting TECH/README/USC_ADAPTER names (`INativeQueryVerifier.verifyAndEmit`, `EvmV1Decoder`, `prover.cc3-testnet…`) as the official ledger before GPU-075 confirms them. | GPU-075, 078, 082 |
| R2-D12 | **Evidence levels are not promoted.** LOCAL (fixture/mock) ≠ SANDBOX ≠ NATIVE_TESTNET (real public source tx + official native verification on a public Creditcoin testnet) ≠ LIVE ≠ ACCEPTED. `PRODUCTION` profile config ≠ launch approval. G-ASC (GPU-080) needs real testnet native verification *and* app record/consume evidence; it does not satisfy G3. | Anvil precompile mocks, always-true doubles, pure SDK `eth_call` success, or skipped tests recorded as native PASS. | all CODE/LIVE tickets |
| R2-D13 | **Legacy preservation.** v1 contracts, deployed addresses, debts, LP rights, keys, dirty worktree, and untracked docs are preserved. Global renames and unrelated cleanups are not bundled. Legacy global pause is not reused for recovery. | Retiring or editing v1 on-chain state; bulk doc rewrites outside the owning ticket. | GPU-060, 061, 065, 067 |
| R2-D14 | **Hackathon/demo materials are not production decisions.** `docs/hackathon/*`, deck/scripts, and the NFT/trailing-payout narrative remain demo-labeled. TEST_ONLY MockDePIN sources may be used on a real public testnet for G-ASC with `partnerRevenue=SIMULATED`. | Treating demo scope as the product spec; treating mock partner E2 as a real right. | GPU-065, 080 |

## 2. Fixed interpretation rules

1. Precedence: applicable repo instructions and the user's latest requirement → this ledger / `TICKET.md` §0.9 →
   remaining PIVOT product/financial conditions → approved detailed ADRs → TECH/README/hackathon docs.
2. A ticket "exists" ≠ permission to deploy, broadcast, move funds, contact partners, or change products.
3. `DONE` requires the ticket's completion criteria and required evidence level, with regression/permission/
   failure-path tests actually run (0 tests ≠ pass).
4. Documentation present tense about unimplemented components is `planned/unverified`; absence of an external
   deployment is not asserted without a chain check.

## 3. OPEN — requires explicit user/business decision (not decided here)

| ID | Question | Why it is open | Owner |
| --- | --- | --- | --- |
| R2-O01 | Which partner is first (Aethir or GPU.net)? | Needs DD outputs; only one path is required to launch. | GPU-004/005/008/010 |
| R2-O02 | Is the chosen partner's real payout/obligation source on an officially supported chain, and which event(s) are natively provable? | Official support table (doc-confirmed 2026-09-14, runtime-unverified) vs partner reality. | GPU-008, 075, 076 |
| R2-O03 | If only past payouts (or API-only facts) are provable, does first-product admission wait, or is the product changed? | R2-D06/D10 forbid silently switching to trailing-payout/future-cash-flow. | GPU-076, 008, 010 (change → GPU-072) |
| R2-O04 | Freshness policy: source checkpoint/reservation vs approved bounded-lag/buffer, and the limits/haircuts attached. | Risk parameters are an approval item. | GPU-076, 007, 010 |
| R2-O05 | Settlement rail source escrow → conversion → destination receipt; and whether PIVOT §10.2's alternate vault-chain configuration is ever adopted. | Partner/liquidity facts; product/capital-structure change. | GPU-006, 040, 010 |
| R2-O06 | Loan stablecoin on Creditcoin (issuer support, real contract, liquidity). | External confirmation. | GPU-006, 010 |
| R2-O07 | Retirement or repurpose of `RelayerSigVerifier`/`offchain/relayer` (legacy EIP-712) — keep as legacy only, or reuse for OFFCHAIN_ASSERTION signing with a new domain. | Either is compatible with R2-D03/D04; code choice pending design. | GPU-013, 029, 060 |
| R2-O08 | Fate of hackathon-facing docs (README/TECH NFT narrative): keep demo-labeled alongside R2 or rewrite. | Brand/communication choice. | GPU-065 |
| R2-O09 | Whether an approved, scoped public-testnet budget (wallet, gas, test tokens, contracts, period) exists for GPU-080. | External approval. | GPU-080 |

## 4. What this ledger does not do

- It does not verify official SDK/ABI/endpoint/chain support (GPU-075), nor any partner fact (GPU-004/005/009).
- It does not delete existing financial, rights, or legacy requirements from PIVOT/TICKET.
- It does not mark any component as implemented; implementation status is `ATTESTCOIN_GAP.md` §1.
