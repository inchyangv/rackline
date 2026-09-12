# HashCredit — Pitch Deck

> 15 slides. Copy-paste ready. One idea per slide.
> For **HashKey Chain On-Chain Horizon Hackathon 2026** — DeFi Track.
> Demo Showcase: Apr 22 (AWS Office) | Final Pitch & Awards: Apr 23 (Web3 Festival)

---

## Design Direction: Swiss International (Style #07)

> Clean, restrained, information-dense. One accent color. Strict grid.
> PPTX 생성 시 아래 스펙을 반드시 따를 것.

### Background

All slides: **Pure White** `#FFFFFF`

### Colors

| Role | Color | HEX |
|------|-------|-----|
| Primary Accent | Bitcoin Orange | `#F7931A` |
| Headings | Near-black | `#111111` |
| Dark text | Dark grey | `#333333` |
| Body text | Mid grey | `#555555` |
| Muted / captions | Light grey | `#999999` |
| Rules / dividers | Pale grey | `#DDDDDD` |
| Card fill | Off-white | `#F5F5F5` |
| Dark card bg | Navy | `#1A1A2E` |
| Positive | Green | `#228855` |
| Negative | Soft red | `#CC3333` |

### Fonts

| Element | Font | Size | Style |
|---------|------|------|-------|
| Slide title | **Arial Bold** | 32–36pt | Bold |
| Section label | **Arial Bold** | 9pt | Uppercase, accent color |
| Body text | **Arial** | 12–14pt | Regular |
| Caption | **Arial** | 9–11pt | Muted color |
| Table header | **Arial Bold** | 11pt | Muted color |
| Table body | **Arial** | 12pt | Regular |
| Big numbers | **Arial Bold** | 36pt | Accent or black |

### Layout Rules

1. **Left vertical accent bar** — 0.08" wide, full-height, Bitcoin Orange `#F7931A` on every content slide
2. **Horizontal divider rules** — 1pt `#DDDDDD` to separate sections within a slide
3. **Max 3 content blocks per slide** — clean, not crowded
4. **Section label** top-left — `"01 — PROBLEM"` format, 9pt uppercase accent
5. **Slide number** bottom-right — 10pt muted
6. **Off-white cards** `#F5F5F5` for grouped content
7. **No rounded corners, no gradients, no stock photos**
8. **Single accent color only** — Bitcoin Orange for emphasis, everything else is greyscale

### Signature Elements

- Left vertical accent bar on every slide (except cover & thank you which use thicker bar)
- Horizontal rules as section separators
- Orange bullet markers (small squares) for list items
- Orange step numbers for sequential content
- `"HASHCREDIT"` section labels top-left

---

## Slide 1: Cover

**HashCredit**

Working capital for Bitcoin miners, via mining pools.

_Pool-enforced repayment. SPV-proven revenue. USDT on demand._

Built on HashKey Chain · DeFi Track · Live on Testnet

---

## Slide 2: Problem

**$17B in annual mining revenue. Zero ways to borrow against it on-chain.**

Miners pay for electricity, hardware, and facilities in fiat — but earn in BTC. Post-halving full cost per BTC has surged to ~$137K (Apex Mining). Hardware ROI now exceeds 1,200 days. Miners have raised **$11B+ in convertible debt since 2023** (AInvest) just to keep operations running. Public miners sold 5,359 BTC in December 2025 alone to stay liquid. The cash crunch is structural, not cyclical.

Today's financing options all suck:

- **Lock up your BTC?** Freezes the asset miners need for operations. (Ledn, SALT — 7–12% APR)
- **Pledge your ASICs?** Over-collateralized, slow, institutional only. (Luxor — 5–18% APR)
- **Off-chain revenue lending?** No pool-native enforcement — manually underwritten, zero on-chain verifiability. And the trust-based lenders already failed: BlockFi bankrupt, Celsius bankrupt, Genesis bankrupt.
- **Raise equity?** Dilutive, takes months, only works for public miners.

The result: miners sit on the most provable income stream in crypto, and nobody lets them use it.

**Hashrate — a miner's core productive asset — is invisible on-chain.** No trustless verification exists. Existing on-chain lending (Aave, Compound) requires overcollateralized liquid assets — doesn't model a miner's revenue stream.

---

## Slide 3: Market

**TAM: $17.2B** in annual BTC miner revenue (2025, The Block)

**SAM: $5.2–6.9B** — Mid-market miners running 30–40% of global hashrate. Non-public, mid-scale operators: too small for capital markets, too big for personal credit. They need this the most — and have no good options today.

**Distribution insight:** The top 10 mining pools control 90%+ of global hashrate. Each pool is a single point of integration that unlocks thousands of miners. HashCredit doesn't need to acquire miners one by one — **one pool partnership = thousands of borrowers.**

- 10% revenue penetration → **$1.7B** in lending volume
- At 8% average APR → **$136M** annual protocol revenue opportunity
- Crypto mining market growing at **12.7% CAGR** through 2035 (Precedence Research)

**Comparable:** Stripe Capital has advanced **$9B+** to merchants using the same revenue-based model. We apply it to a more verifiable revenue stream — Bitcoin mining payouts proven by PoW, not self-reported payment volume.

**LP opportunity**: USDT depositors earn 8% APR — 2–3× standard DeFi rates (Aave USDT ~3–4%) — backed by SPV-proven revenue and pool-level enforcement. Real yield from real economic activity, not token incentives.

---

## Slide 4: Key Insight

**You can't prove hashrate directly — it's a physical rate. But you can prove its output.**

Every pool payout is a Bitcoin transaction distributed proportional to contributed hash power. It's timestamped, immutable, and verifiable by anyone who has the block headers. **Payout history is the hashrate record** — and it's already on a public ledger.

This is *better* data than what Stripe Capital uses to underwrite merchants. Stripe relies on self-reported revenue through their own platform. Bitcoin payouts are verified by proof-of-work — the strongest commitment mechanism ever built.

Revenue-based financing works for SaaS (Stripe Capital, Clearco, Pipe).
It works even better for mining — because the revenue is **math, not trust**.

SPV turns Bitcoin payout records into trustless on-chain evidence. No oracle. No custodian. No bridge. Pure cryptography.

---

## Slide 5: Solution

**HashCredit turns verified Bitcoin payouts into a revolving stablecoin credit line on HashKey Chain.**

```
Pool payout (BTC tx) → SPV proof → On-chain verification → Credit limit update → Draw stablecoins → Pool auto-withholds repayment
```

- **No BTC lockup** — mine through your registered pool
- **SPV-proven revenue** — no oracle, no bridge, pure cryptography
- **Pool-enforced repayment** — automatic withholding at source
- **Modular verifier** — `IVerifierAdapter` decouples proof from credit logic
- **Default enforcement** — pool redirects miner's hashrate. No courts. No trust.

One sentence: **"Stripe Capital for Bitcoin miners, but trustless — and pool-enforced."**

---

## Slide 6: How It Works

```
1. Mining pool registers with HashCredit (agrees to withhold)
2. Miner gets paid by pool                          (Bitcoin tx)
3. Off-chain worker detects payout, waits for confirmations
4. Builds SPV proof — headers, Merkle, tx output    (off-chain)
5. Verifier checks PoW + Merkle + output script     (trustless, on-chain)
6. Credit limit updates automatically               (on-chain)
7. Miner draws stablecoins / Pool withholds repayment
```

Enforcement: pool withholds X% of each payout as automatic repayment.
Sustained default → pool redirects miner's hashrate to protocol. No courts. No trust. Pure economic enforcement.

---

## Slide 7: Business Model

| Stream | How it works |
|--------|-------------|
| Interest spread | Borrowers pay 10% APR → LPs earn 8% → protocol keeps 2% spread |
| Origination fee | 0.5% per drawdown |
| Pool withholding | Automatic repayment via pool — zero collection cost |

**LP yield comparison:**
| Platform | APR | Security |
|----------|-----|----------|
| Aave USDT | 3–4% | Overcollateral |
| Curve stables | 5–7% | Overcollateral + slippage |
| **HashCredit LP** | **8%** | **SPV-proven revenue + pool withholding** |

Flywheel: more miners → more proven revenue → more LP confidence → more USDT liquidity → lower rates → more miners.

---

## Slide 8: Traction

**It works today.** End-to-end, on HashKey Chain Testnet.

- 7 production smart contracts deployed (chainId `133`)
- SPV proofs generated from real Bitcoin testnet transactions
- Full borrow/repay lifecycle operational
- On-chain BTC identity binding (BIP-137 sig verification via EVM precompiles)
- 24/7 automated prover worker
- Frontend live: https://hashcredit.studioliq.com
- API live: https://api-hashcredit.studioliq.com
- Test suite: unit, integration, invariant fuzzing, gas profiling
- Modular `IVerifierAdapter` — plug-and-prove architecture

**Testnet Contract Addresses (HashKey Chain Testnet, chainId=133):**

| Contract | Address |
|----------|---------|
| HashCreditManager | `0x2716cCD5E6ee2845D79cF30657C215e536Ba0F74` |
| LendingVault | `0x3517D3a0dDd4455091d89CaB9Be5df3439bd15fb` |
| CheckpointManager | `0xa27281FDFf89A34e842F251224380FC92F4Eb338` |
| BtcSpvVerifier | `0xa7506A5c1C03EE38EdDE1572c55DB339f5FD05c4` |
| Stablecoin (mUSDT) | `0x73840B35612eA8B13825288F0955A3F552645675` |

---

## Slide 9: Why Now

| Signal | What it means |
|--------|--------------|
| **Halving (2024)** | Block reward → 3.125 BTC. Revenue per hash cut 50%. Working capital matters more than ever. |
| **$11B in mining debt** | Miners raised $11B+ in convertible debt since 2023. Demand for financing is proven and growing. |
| **Hashrate at 1 ZH/s** | Hardware ROI exceeds 1,200 days. Mining is more capital-intensive than ever. |
| **Treasury drawdowns** | Public miners sold 5,359 BTC in Dec 2025 alone just to stay liquid. |
| **Trust crisis** | BlockFi, Celsius, Genesis — all bankrupt. Industry needs trustless alternatives. |
| **No incumbent** | Trustless BTC proof + pool-enforced repayment + on-chain credit — nobody else is building this. |

---

## Slide 10: Competitive Edge

**The only protocol that uses cryptographic proof instead of trust — with pool-level enforcement.**

| | HashCredit | Everyone Else |
|---|---|---|
| Collateral | **None** — revenue-proven | BTC, ASICs, or self-reported financials |
| Verification | **SPV proof** — pure math | Oracle, custodian, or manual review |
| Repayment | **Automatic** — pool withholds | Manual, trust-dependent |
| Speed | **Instant** — auto-updating credit | Days to weeks |
| Access | **Permissionless** — via registered pool | KYC, minimums, institutional gatekeeping |

Our SPV verifier runs entirely on-chain — the same trust model Bitcoin itself uses since 2009.
No oracle to bribe. No custodian to trust. No underwriter to convince.

---

## Slide 11: Roadmap

| Phase | When | What |
|-------|------|------|
| **Complete** | Q1 2026 | 7 contracts, SPV verifier, full lifecycle, frontend on HashKey Chain Testnet |
| **In Progress** | Q2 2026 | Audit, HashKey Chain mainnet deployment, 10 pilot miners |
| **Target** | Q3 2026 | 50 miners, $500K TVL, mining pool API partnerships |
| **Vision** | Q4 2026 | $5M TVL, 200+ miners, cross-chain oracle adapter |

---

## Slide 12: Team

**Built by engineers who understand both Bitcoin and DeFi.**

- **Incheol Yang (CEO)** — KAIST CS. Co-founded a DeFi system trading house, managed $20M at 40%+ APR. Previously at KRAFTON PUBG Studio (in-game trading/payment systems) and Coinone Exchange (smart order routing, institutional WebSocket API).
- **Juhyeong Park (CTO)** — Yonsei CS. CTO of Onther — led a mainnet to $750M market cap, designed Plasma EVM. Previously at Chainpartners designing DEX aggregators and perpetual DEXs.

Two founders built the entire protocol — contracts, SPV prover, worker, frontend.

---

## Slide 13: Why HashKey Chain

**Mining-revenue lending needs more than an EVM chain.**

**1. Compliance infrastructure enables institutional partnerships.**
Mining pools must contractually agree to withhold repayment from payouts. On default, KYC-verified identities enable legal recourse. HashKey Chain is operated by HashKey Group — an SFC-licensed financial institution in Hong Kong — and built compliance-first: identity tooling, policy controls, and auditability at the protocol level. This makes the pool partnership model legally viable.

**2. HashKey ecosystem is the distribution channel.**
HashCredit needs two sides: miners who borrow and LPs who provide USDT. HashKey Exchange provides fiat on/off-ramps and USDT liquidity. HashKey Capital provides strategic investment and introductions to mining operators. Hong Kong — where ~30% of global hashrate operates nearby — is the natural hub.

**3. Full EVM precompile support enables trustless BTC verification.**
Our core innovation — on-chain BTC address ownership proof via `claimBtcAddress()` — requires `ecrecover` (0x01), `sha256` (0x02), and `ripemd160` (0x03). HashKey Chain (OP Stack) supports all standard Ethereum precompiles natively. No oracle, no bridge, no custom precompile needed.

**4. Modular architecture for ecosystem evolution.**
Proof verification is decoupled from credit logic via `IVerifierAdapter`. As HashKey Chain's ecosystem matures (cross-chain messaging, ZK bridges, oracle networks), new proof sources plug in without touching credit logic, vault, or risk config.

---

## Slide 14: The Ask

_[HashKey Chain On-Chain Horizon Hackathon 2026 — DeFi Track]_

**Raising $250K Seed.** Revenue-based financing for Bitcoin miners — trustless, pool-enforced, production-ready.

**Use of funds:**
- 40% Engineering + mainnet deploy ($100K)
- 20% Security audit ($50K)
- 20% Initial vault USDT liquidity ($50K)
- 20% Mining pool partnerships + GTM ($50K)

**From HashKey ecosystem:**
- **Technical partnership** — infrastructure support from HashKey Chain engineering team
- **HashKey Capital** — investment + mining operator introductions
- **HashKey Exchange** — USDT liquidity integration + fiat on/off-ramp
- **Compliance guidance** — cross-jurisdictional pool withholding agreement support
- **Post-hackathon incubation** — continued ecosystem and institutional resource support

---

## Slide 15: Thank You

Thank you.

| Resource | URL |
|----------|-----|
| Live Demo | https://hashcredit.studioliq.com |
| API | https://api-hashcredit.studioliq.com |
| GitHub | https://github.com/inchyangv/ctc-hashcredit |
| Contact | inch@studioliq.com |

HashKey Chain Testnet · chainId 133 · DeFi Track

---

## Appendix (backup slides — use if asked)

### A: Risk Model

- **Trailing-window credit** — limit based on recent revenue, not lifetime total
- **Advance rate < 100%** — borrowers access a fraction of verified revenue (default 50%)
- **New borrower caps** — limited initial credit until track record builds
- **Replay protection** — each `(txid, vout)` processed exactly once
- **Large payout discount** — dampens unusually large single payouts
- **Pool withholding** — automatic repayment from each subsequent payout
- **Hashrate redirect** — on sustained default, pool redirects mining power
- **Pausability** — emergency circuit breaker

All parameters on-chain via `RiskConfig`. No black box.

### B: SPV Verification Detail

We verify Bitcoin transactions directly on HashKey Chain:
1. Trusted checkpoint (block header anchor on-chain)
2. Header chain — each header PoW-validated
3. Merkle inclusion — tx in block's Merkle tree
4. Output script — payout goes to borrower's registered address

No oracle. No bridge. No multisig. Same model Bitcoin SPV wallets have used since 2009.

### C: Borrower Mapping Security Model

BTC and ETH both use secp256k1 — so a BTC wallet signature can be verified on-chain using EVM precompiles.

`BtcSpvVerifier.claimBtcAddress()` implements fully on-chain BTC address ownership verification:
1. User signs a BIP-137 message with their BTC wallet
2. Off-chain API extracts signature parameters (pubKeyX, pubKeyY, btcMsgHash, v, r, s)
3. On-chain: `ecrecover(btcMsgHash, v, r, s)` recovers the signer
4. On-chain: compress the public key → `ripemd160(sha256(compressed))` = BTC pubkeyHash
5. Stores `borrowerPubkeyHash[msg.sender]`

### D: Modular Verifier Architecture

```
HashCreditManager ──→ IVerifierAdapter.verifyPayout(proof)
                              │
                  ┌───────────┼───────────┐
                  │           │           │
            BtcSpvVerifier  Relayer   FutureAdapter
            (current)       (bridge)  (ZK, oracle, etc.)
```

### E: Testnet vs Mainnet — Credit Limit

On **mainnet**, credit is driven by real mining revenue via SPV proofs.
On **testnet**, `autoGrantCredit` gives linked borrowers 1,000 mUSDT credit for demo purposes. The full SPV pipeline is deployed and functional but checkpoint registration and proof submission are operator functions.

### F: Key Numbers

| Metric | Value | Source |
|--------|-------|--------|
| BTC miner revenue (2025) | $17.2B | The Block |
| Hashrate ATH | 1.15 ZH/s | CoinWarz |
| Hardware ROI | 1,200+ days | Industry |
| Full cost per BTC | ~$137K | Apex Mining |
| Mining convertible debt (since 2023) | $11B+ | AInvest |
| Mining market CAGR | 12.7% | Precedence Research |
| Top 10 pools hashrate share | 90%+ | BTC.com |
| Stripe Capital merchant advances | $9B+ | Stripe |
| Aave USDT APR | 3–4% | DeFi Llama |
| HashCredit target LP APR | 8% | Protocol design |

### G: FAQ

**vs Aave/Compound?** — They're collateral-based (deposit to borrow). We're revenue-based (prove income to borrow). Completely different primitive.

**Why mining pools, not individual miners?** — Pool = institutional counterparty. Pool can withhold payouts and redirect hashrate on default. Individual miners have no equivalent enforcement lever.

**What if mining stops?** — Trailing window. Credit declines to zero naturally. Debt remains and accrues interest.

**What if pool defaults?** — Multi-pool diversification in roadmap. Initially, partner pools are screened. Pool's own reputation is at stake.

**Gaming / self-transfers?** — Bounded by advance rate, min thresholds, large payout discount, pool registry.

**BTC price drops?** — Credit is USD-denominated. Price drop = lower credit limit. Advance rate provides buffer.

**Why not oracles?** — Single point of failure. SPV is pure math. Can't be bribed or go offline.

**Why HashKey Chain?** — Compliance infrastructure for pool partnerships (SFC-licensed operator). HashKey Exchange for USDT liquidity. Full EVM precompile support for trustless BTC verification. Hong Kong as Asia-Pacific hashrate hub. OP Stack with standard precompiles — zero custom requirements.

**BTC wallet binding without an oracle?** — BTC and ETH share secp256k1. We verify BTC signatures with EVM's `ecrecover`, then hash the pubkey with `sha256` → `ripemd160` to derive the BTC address. All EVM precompiles, zero external dependencies.

**How are credit limits determined on mainnet?** — 30-day trailing window of SPV-verified mining payouts, converted to USD at on-chain BTC price, multiplied by 50% advance rate. Anti-gaming: large-payout discount, new-borrower cap, min payout threshold. More mining = higher credit.

### H: One-liners

**Formal:**
> HashCredit is a revenue-based financing protocol for Bitcoin miners on HashKey Chain. Mining pools act as institutional counterparties: payouts are proven via SPV, stablecoin credit lines are issued, and repayment is automatically withheld from subsequent pool payouts — no collateral, no manual repayment, no trust required.

**DeFi-focused:**
> HashCredit brings Bitcoin mining infrastructure — the world's most provable productive asset — into on-chain DeFi. SPV-verified hashrate revenue becomes a trustless credit primitive on HashKey Chain.

**Punchy:**
> Miners earn billions. They can't borrow against it. We fix that — pool-enforced, SPV-proven, on-chain.

**30-second pitch:**
> Bitcoin miners earned $17 billion last year. They've raised $11 billion in debt just to stay operational. But there's no on-chain way to borrow against mining revenue — and the centralized lenders who tried all went bankrupt. HashCredit fixes this. We contract with mining pools as institutional counterparties. Miners prove their payouts via Bitcoin SPV on HashKey Chain, draw USDT instantly, and the pool automatically withholds repayment. On default, the pool redirects hashrate. No courts. No trust. Just math. It's live on HashKey Chain Testnet today — 7 contracts, full borrow/repay lifecycle, automated SPV prover.

**Elevator pitch (10 sec):**
> Stripe Capital for Bitcoin miners — but trustless. Pool-enforced repayment, SPV-proven revenue, built on HashKey Chain.
