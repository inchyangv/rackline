# Why We Pivoted: From Bitcoin Hashrate to GPU NFTs

> Rackline v1 (then HashCredit) won BUIDL CTC Spring 2026 and issued stablecoin credit against SPV-proven Bitcoin mining payouts.
> Rackline (v2, formerly HashCredit) issues stablecoin credit against **GPU NFTs** — tokenized GPU deployments on DePIN compute networks whose revenue is routed through a protocol-controlled Node Account and proven on Creditcoin via the Attestcoin Protocol.
>
> Same mission: turn verifiable machine revenue into on-chain credit. Different asset, because the asset is what decides whether the lender ever gets paid.

---

## 1. The short version

| | v1 — Bitcoin hashrate | v2 — GPU NFT |
|---|---|---|
| Borrower | Bitcoin miner paid by a mining pool | GPU operator (Cloud Host / provider) paid by a DePIN compute network |
| Revenue evidence | Bitcoin SPV proof of pool payout (144-header chain, Merkle, output script) | Attestcoin-proven EVM payout event into the node's escrow account |
| Repayment control | Depended on mining pools agreeing to withhold payouts. No pool ever integrated. | Revenue is paid into a **Node Account** the operator cannot redirect while debt is outstanding |
| Collateral | None. Hashrate is a rate, not an asset. | The **GPU NFT**: revenue rights on-chain, hardware claim via operator agreement |
| Default remedy | "Pool redirects hashrate" — not implementable without the pool | Draw freeze → escrow sweep → NFT foreclosure to the vault |
| Creditcoin fit | Custom SPV verifier we built ourselves | Native Attestcoin Protocol (`0x0FD2` BlockProver precompile) |

---

## 2. The five reasons

### 2.1 We could prove the revenue, but we could not control the cash

v1 proved payouts beautifully — PoW header chains, Merkle inclusion, on-chain BTC address binding with EVM precompiles. The judges' three follow-up questions after Demo Day all converged on one thing: *what happens when the miner does not repay?*

Our honest answer was that enforcement lived in a contract with the mining pool that did not exist. A miner can switch pools or payout addresses in minutes. The repayment path was entirely voluntary (`repay()` pulls tokens from the caller). The "pool withholds X%" and "pool redirects hashrate" story required pools to build lender-specific infrastructure with no economic reason to do so.

A credit product where the borrower alone decides whether cash reaches the lender is not a credit product. This became the design rule for v2: **no loan unless the contracted repayment can be collected without the borrower's further consent.**

### 2.2 Our customers pivoted before we did

The mid-market miner we targeted is disappearing into GPU hosting:

- Hashprice fell to roughly $28–35 per PH/s/day in Q1 2026 and 15–20% of miners now operate at a cash loss; weighted cash cost per BTC for listed miners is near $90K against ~$67K spot (CoinShares Q1 2026 Mining Report).
- Bitcoin's hashrate posted its first Q1 decline since 2020 (about −4%) as miners convert megawatts to AI/HPC.
- Listed miners signed more than $70B of GPU/AI hosting deals; HPC is now ~70% of revenue for TeraWulf, IREN and Core Scientific (Visible Alpha consensus via S&P Global / CoinDesk).

The machines our borrowers run are becoming GPUs. Following the revenue means following the GPU.

### 2.3 GPUs are financeable. Hashrate is not.

Traditional finance already lends against GPUs at scale: CoreWeave's $2.3B (2023) and $7.5B (2024) facilities led by Blackstone and Magnetar, Lambda's $500M Macquarie facility (the first GPU asset-backed structure, 2024) and its $1B facility in 2026, Fluidstack's up-to-$10B capacity, Crusoe's $425M. Neoclouds hold more than $20B of GPU-collateralized debt.

That market only serves companies with hundreds of millions in hardware and audited financials. The long tail — the operators supplying 440,000+ GPU containers across 94 countries to Aethir alone, plus GPU.net, io.net, Render and Akash providers — has the same asset and the same cash-flow gap, and no lender.

We are not inventing a collateral thesis. We are bringing a proven one to a segment nobody serves, with on-chain verification replacing the audit.

### 2.4 The working-capital gap is structural, not cyclical

DePIN compute networks pay operators in tokens with vesting and claim delays. On Aethir, Cloud Host service fees become claimable after 45 days, rewards vest 30% immediately / 30% at 90 days / 40% at 180 days, with a 5% protocol fee and one claim per day per type. Electricity, hosting and hardware leases are due monthly in fiat or stablecoins.

Revenue is earned today and cashable in 45–180 days. That mismatch is the product. It does not depend on token prices going up.

### 2.5 DePIN revenue is EVM-native — exactly what Creditcoin proves

v1 had to build Bitcoin inside the EVM: checkpoints, bounded header chains, BIP-137 signature recovery. DePIN payouts are ordinary EVM transactions and events on Ethereum-family chains. Creditcoin's Attestcoin Protocol verifies finalized Ethereum transactions synchronously through the BlockProver precompile at `0x0FD2`, decodes receipts and logs with `EvmV1Decoder`, and returns the data to our credit contract in a single block.

v2 replaces our bespoke verifier with the chain's native one. Less cryptography we have to defend, more of Creditcoin's core capability in the product.

---

## 3. Why an NFT, specifically

"GPU-backed" only means something if the lender holds rights that survive the borrower changing their mind. The NFT is the container for those rights:

1. **Identity.** One token per registered GPU deployment (provider, SKU, hardware hash, host/group id). The same physical machine cannot be financed twice.
2. **Escrow.** Each GPU NFT has a **Node Account** on the payout chain (an ERC-6551-style bound account). The operator sets the network's reward / service-fee receiver to it. Payouts land there — not in the operator's wallet.
3. **Lien.** While a facility is open, the NFT is locked in the credit manager. The operator cannot transfer it, and cannot change the Node Account's sweep policy or receiver. That is on-chain payment control.
4. **Auto-repayment.** Every payout is swept by policy: agreed share → repayment, remainder → operator. No repay button.
5. **Foreclosure.** On sustained default the NFT — the revenue rights and, under the operator agreement, the hardware claim — moves to the vault for recovery or resale.
6. **Composability.** A standard, transferable GPU NFT with an income-bearing account is a primitive other Creditcoin builders can use: insurance, fractionalization, secondary markets for GPU revenue rights.

What the NFT does not do by itself: it does not make Aethir or GPU.net honor our escrow, and it does not give us legal title to a server in a data center. Those come from partner-level receiver locks and signed operator agreements. We say so on every slide that touches enforcement. Control levels are graded (E0 read-only → E1 escrow set but revocable → E2 payment path locked → E3 physical lien), and only E2+ qualifies for funded loans.

---

## 4. What we kept, what we retired

**Kept from v1**
- The proof ↔ credit ↔ vault separation (`IVerifierAdapter` → `IRevenueVerifier`), which is why swapping Bitcoin SPV for Attestcoin does not touch credit logic.
- `LendingVault` and `RiskConfig` as patterns, with the accounting corrected (partial interest preserved, single principal/interest ledger, no retroactive APR).
- Wallet UX, the EIP-712 relayer, invariant/fuzz test discipline, Railway/Vercel deployment.

**Retired to legacy**
- `BtcSpvVerifier`, `CheckpointManager`, `BitcoinLib`, BTC address binding, the SPV prover worker. They remain in the repo and on testnet as v1.

**Fixed before any real money**
- Testnet auto-grant credit and the public owner-key API are excluded from the v2 path.
- Interest accounting bugs found in review are reproduced as regression vectors and corrected in the v2 ledger.

---

## 5. What changes for the pitch

- We no longer say "trustless" about enforcement. Evidence is trustless (Attestcoin); enforcement is contractual plus on-chain control, and we grade it.
- We no longer quote a fixed LP yield. LP return = borrower interest − losses − reserve − costs.
- We renamed the protocol. HashCredit named the hashrate; Rackline names racks of GPUs and a credit line. Contract and repository identifiers keep the legacy `HashCredit*` names.
- We no longer claim a partner integration we do not have. Aethir and GPU.net are the first two targets; the first funded loan starts with the one whose payment control passes our tests.

---

## 6. 한국어 요약

- **v1의 한계**: 페이아웃 증명은 됐지만 회수를 통제할 수 없었다. 마이닝 풀의 원천징수 계약이 실제로 존재하지 않았고, 마이너는 풀/주소를 언제든 바꿀 수 있었다. 심사위원의 추가 질문 3개가 전부 이 지점이었다.
- **고객이 먼저 피벗**: 2026년 1분기 해시프라이스 $28–35/PH/s/day, 마이너 15–20%가 현금 손실, 상장 마이너 매출의 ~70%가 HPC. 우리가 노리던 중형 마이너가 GPU 호스팅으로 이동 중이다.
- **GPU는 금융 가능한 자산**: CoreWeave $9.8B, Lambda $1.5B 등 전통 금융이 이미 $20B+ GPU 담보 대출을 실행. 롱테일 DePIN 운영자에게는 아무도 빌려주지 않는다.
- **구조적 운전자본 갭**: Aethir 서비스 수수료는 45일 후 청구, 보상은 30/90/180일 베스팅. 비용은 매달 나간다.
- **Creditcoin 네이티브**: DePIN 지급은 EVM 이벤트 → Attestcoin(0x0FD2)으로 바로 검증. 자체 SPV 검증기를 버리고 체인 고유 기능을 쓴다.
- **NFT의 역할**: 식별(중복 금융 방지) · 에스크로(Node Account 수령) · 담보 잠금(대출 중 이전/수령자 변경 불가) · 자동 상환(스윕) · 부실 시 회수(NFT 이전) · 조합 가능성.
- **이름 변경**: HashCredit(해시레이트) → Rackline(GPU 랙 + 크레딧 라인). 컨트랙트·레포 식별자는 레거시 이름 유지.
- **말하지 않는 것**: enforcement에 "trustless", 고정 LP 수익률, 확보하지 않은 파트너십.
