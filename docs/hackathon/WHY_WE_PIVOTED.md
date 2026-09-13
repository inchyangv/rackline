# Why We Pivoted: From Bitcoin Hashrate to GPU Receivables

> Rackline v1 (then HashCredit) won BUIDL CTC Spring 2026 and issued stablecoin credit against SPV-proven Bitcoin mining payouts.
> Rackline (v2, formerly HashCredit) lends stablecoin working capital to GPU operators on DePIN compute networks, secured by **confirmed, unpaid receivables** assigned to a **controlled payment path**, with source-chain settlement events verified on Creditcoin through the official Attestcoin Protocol.
>
> Same mission: turn verifiable machine revenue into on-chain credit. Different asset, because the asset is what decides whether the lender ever gets paid.
>
> Revision note (2026-09-14): the first v2 draft of this document described "GPU NFT credit" (tokenized deployments, NFT lien / foreclosure, trailing-payout limits). That draft was retired by the R2 decisions (`docs/gpu/decisions/attestcoin-first.md`, R2-D06/D10/D14); §3 explains why. Nothing described here is implemented as of 2026-09-14.

---

## 1. The short version

| | v1 — Bitcoin hashrate | v2 — GPU receivables |
|---|---|---|
| Borrower | Bitcoin miner paid by a mining pool | GPU operator (Cloud Host / provider) paid by a DePIN compute network |
| What is financed | Nothing identifiable — a rate | Confirmed, unpaid settlements owed by a named payer for delivered work |
| Revenue evidence | Bitcoin SPV proof of pool payout (144-header chain, Merkle, output script), built by us | Settlement event on the source chain, verified natively on Creditcoin by the official Attestcoin Protocol |
| Repayment control | Depended on mining pools agreeing to withhold payouts. No pool ever integrated. | Payer settles into a controlled escrow; the payer recognizes the assignment and the operator cannot redirect it alone (E2), proven by a real test before funding |
| What reduces debt | `repay()` pulled tokens from the borrower — voluntary | Only actual loan-currency receipt at the vault, allocated to the facility (`repayFor`) |
| Default remedy | "Pool redirects hashrate" — not implementable without the pool | Draws freeze, escrow collection continues, cure, reserve, agreed recovery; hardware only under E3 |
| Creditcoin fit | Custom SPV verifier we built ourselves | Native Attestcoin verification (`INativeQueryVerifier` precompile `0x…0FD2`, `EvmV1Decoder`), pinned by version |

---

## 2. The five reasons

### 2.1 We could prove the revenue, but we could not control the cash

v1 proved payouts beautifully — PoW header chains, Merkle inclusion, on-chain BTC address binding with EVM precompiles. The judges' three follow-up questions after Demo Day all converged on one thing: *what happens when the miner does not repay?*

Our honest answer was that enforcement lived in a contract with the mining pool that did not exist. A miner can switch pools or payout addresses in minutes. The repayment path was entirely voluntary (`repay()` pulls tokens from the caller). The "pool withholds X%" and "pool redirects hashrate" story required pools to build lender-specific infrastructure with no economic reason to do so.

A credit product where the borrower alone decides whether cash reaches the lender is not a credit product. This became the first design rule for v2: **no loan unless the contracted repayment can be collected without the borrower's further consent.** The second rule followed from the same post-mortem: **no borrowing base on a source-chain fact we cannot verify natively on Creditcoin.**

### 2.2 Our customers pivoted before we did

The mid-market miner we targeted is disappearing into GPU hosting:

- Hashprice fell to roughly $28–35 per PH/s/day in Q1 2026 and 15–20% of miners now operate at a cash loss; weighted cash cost per BTC for listed miners is near $90K against ~$67K spot (CoinShares Q1 2026 Mining Report).
- Bitcoin's hashrate posted its first Q1 decline since 2020 (about −4%) as miners convert megawatts to AI/HPC.
- Listed miners signed more than $70B of GPU/AI hosting deals; HPC is now ~70% of revenue for TeraWulf, IREN and Core Scientific (Visible Alpha consensus via S&P Global / CoinDesk).

The machines our borrowers run are becoming GPUs. Following the revenue means following the GPU.

### 2.3 GPU receivables are financeable. Hashrate is not.

Traditional finance already lends against GPUs at scale: CoreWeave's $2.3B (2023) and $7.5B (2024) facilities led by Blackstone and Magnetar, Lambda's $500M Macquarie facility (the first GPU asset-backed structure, 2024) and its $1B facility in 2026, Fluidstack's up-to-$10B capacity, Crusoe's $425M. Neoclouds hold more than $20B of GPU-collateralized debt.

That market only serves companies with hundreds of millions in hardware and audited financials. The long tail — the operators supplying 440,000+ GPU containers across 94 countries to Aethir alone, plus GPU.net, io.net, Render and Akash providers — has the same cash-flow gap and no lender.

We are not inventing a collateral thesis. We are bringing the oldest one in working-capital finance — receivables with a controlled payment path — to a segment nobody serves, with native on-chain verification of the settlement events replacing part of the audit.

### 2.4 The working-capital gap is structural, not cyclical

DePIN compute networks pay operators in tokens with vesting and claim delays. On Aethir, Cloud Host service fees become claimable after 45 days, rewards vest 30% immediately / 30% at 90 days / 40% at 180 days, with a 5% protocol fee and one claim per day per type. Electricity, hosting and hardware leases are due monthly in fiat or stablecoins.

Revenue is earned today and cashable in 45–180 days. That mismatch is the product. It does not depend on token prices going up.

### 2.5 DePIN settlements are EVM-native — exactly what Creditcoin proves

v1 had to build Bitcoin inside the EVM: checkpoints, bounded header chains, BIP-137 signature recovery. DePIN settlements on supported chains are ordinary EVM transactions and events. Creditcoin's Attestcoin Protocol verifies finalized transactions synchronously through the BlockProver precompile at `0x…0FD2`, and the official `EvmV1Decoder` reads receipts and logs from the verified bytes in the same block.

v2 replaces our bespoke verifier with the chain's official one, pinned by version and hash (`docs/gpu/attestcoin/environment.md`). Less cryptography we have to defend, more of Creditcoin's core capability in the product — and no substitute path: if a partner's settlement chain is not officially supported, that path is `UNSUPPORTED_SOURCE` and does not launch.

---

## 3. Why receivables and payment control — not an NFT

Our first v2 draft tokenized each GPU deployment as an NFT with a bound "Node Account", locked the NFT while debt was open, computed limits from trailing verified payouts, and called foreclosure of the NFT the remedy. We retired that design for four reasons, now fixed in the R2 ledger:

1. **An NFT lock is not payment control.** The payer (Aethir, GPU.net) does not know about our token. Whether the operator can redirect the receiver is decided by the payer's rules and the control agreement, not by `isLocked=true` in our contract. E2 is a partner-recognized, tested right (R2-D05; PIVOT §4).
2. **Past payouts are not a receivable.** "Σ verified payouts in a trailing window" is history. It does not prove that anything is owed today, and re-submitting an old proof cannot make it fresh. The first product finances confirmed, currently unpaid receivables against a source-authority checkpoint (R2-D06).
3. **Foreclosing an NFT does not recover anything the escrow was not already collecting.** The transferable rights we actually hold are the assigned receivables and the controlled payment path; hardware claims exist only under E3 with a real lien and custodian consent.
4. **A demo primitive must not become production collateral by default.** NFT-collateral loans, future-cash-flow products and equipment finance are separate decisions with their own tickets (R2-D10, GPU-068~072).

What v2 records on Creditcoin instead: the registered deployment / provider account, the control agreement (grade, validity, hash), the canonical verified settlement events (`EvidenceBook`), the facility and debt ledger, and every destination cash receipt. That is the RWA: a financed receivable with an on-chain credit record.

Control levels are graded (E0 read-only → E1 escrow set but revocable → E2 payer-recognized, non-bypassable → E3 physical lien), and only E2+ qualifies for funded loans. We say so on every slide that touches enforcement.

---

## 4. What we kept, what we retired

**Kept from v1**
- The proof ↔ credit ↔ vault separation, which is why replacing Bitcoin SPV with official Attestcoin verification does not change the shape of the credit layer.
- `LendingVault` and `RiskConfig` as patterns, with the accounting rebuilt (partial interest preserved, single principal / interest ledger, no retroactive APR, reserve, loss recognition).
- Wallet UX and design system, invariant / fuzz test discipline, Railway / Vercel deployment.

**Retired to legacy**
- `BtcSpvVerifier`, `CheckpointManager`, `BitcoinLib`, BTC address binding, the SPV prover worker. They remain in the repo and on testnet as v1.
- `RelayerSigVerifier` and the EIP-712 relayer as an *evidence* path. Auxiliary signatures (wallet auth, agreement consent, underwriting approval) persist for their own purposes and never create borrowing base (R2-D03/D04).

**Retired from the v2 draft**
- GPU NFT lien / foreclosure as enforcement, trailing-payout borrowing base, "attested" evidence class at a lower advance rate, arbitrary `notify(amount)` payout reporting, transaction-level replay keys.

**Fixed before any real money**
- Testnet auto-grant credit and the public owner-key API are excluded from the v2 path. GPU-001 (done 2026-09-14) isolated the v1 API's register-and-grant route behind a `testnet_demo` profile; the production profile holds no admin key.
- Interest accounting bugs found in review are reproduced as regression vectors and corrected in the v2 ledger.

---

## 5. What changes for the pitch

- We no longer say "trustless" about enforcement. Evidence is natively verified (Attestcoin); enforcement is contractual plus payment control, and we grade it.
- We no longer quote a fixed LP yield. LP return = borrower interest − losses − reserve − costs.
- We no longer present a proof as revenue, a past payout as a receivable, or an in-flight transfer as repayment. Five judgments, five states.
- We renamed the protocol. HashCredit named the hashrate; Rackline names racks of GPUs and a credit line. Contract and repository identifiers keep the legacy `HashCredit*` names.
- We no longer claim a partner integration we do not have. Aethir and GPU.net are the first two targets; the first funded loan starts with the one whose payment control passes our tests.
- We state status plainly: as of 2026-09-14 the official Attestcoin artifacts are pinned and the testnet is probed; no v2 contract, worker or UI exists; no native proof has been submitted.

---

## 6. 한국어 요약

- **v1의 한계**: 페이아웃 증명은 됐지만 회수를 통제할 수 없었다. 마이닝 풀의 원천징수 계약이 실제로 존재하지 않았고, 마이너는 풀/주소를 언제든 바꿀 수 있었다. 심사위원의 추가 질문 3개가 전부 이 지점이었다.
- **두 가지 설계 원칙**: 차주의 추가 동의 없이 회수할 수 없으면 대출하지 않는다. Creditcoin에서 네이티브로 검증할 수 없는 소스 체인 사실로 borrowing base를 만들지 않는다.
- **고객이 먼저 피벗**: 2026년 1분기 해시프라이스 $28–35/PH/s/day, 마이너 15–20%가 현금 손실, 상장 마이너 매출의 ~70%가 HPC. 우리가 노리던 중형 마이너가 GPU 호스팅으로 이동 중이다.
- **GPU 매출채권은 금융 가능한 자산**: CoreWeave $9.8B, Lambda $1.5B 등 전통 금융이 이미 $20B+ GPU 담보 대출을 실행. 롱테일 DePIN 운영자에게는 아무도 빌려주지 않는다.
- **구조적 운전자본 갭**: Aethir 서비스 수수료는 45일 후 청구, 보상은 30/90/180일 베스팅. 비용은 매달 나간다.
- **Creditcoin 네이티브**: DePIN 정산은 EVM 이벤트 → 공식 Attestcoin(0x0FD2 + EvmV1Decoder)으로 검증. 자체 SPV 검증기를 버리고 체인의 공식 기능만 쓴다. 미지원 체인은 `UNSUPPORTED_SOURCE`로 출시하지 않는다.
- **NFT가 아닌 이유**: NFT 잠금은 지급 통제가 아니다(지급 주체는 우리 토큰을 모른다). 과거 payout 합계는 채권이 아니다. 담보는 양도된 확정 미지급 채권과 통제된 지급 경로(E2)이며, 장비는 E3에서만 담보다. NFT 담보 상품은 별도 보류 결정.
- **다섯 가지 판단 분리**: 소스 이벤트(native proof) · 매출 출처 · 현재 미지급 채권 · E2 통제 · 실제 목적지 현금 수령. 증명은 매출이 아니고, 과거 payout은 채권이 아니며, 이동 중 자금은 상환이 아니다.
- **이름 변경**: HashCredit(해시레이트) → Rackline(GPU 랙 + 크레딧 라인). 컨트랙트·레포 식별자는 레거시 이름 유지.
- **말하지 않는 것**: enforcement에 "trustless", 고정 LP 수익률, 확보하지 않은 파트너십, 구현되지 않은 컨트랙트의 "배포됨".
