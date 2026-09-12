We're HashCredit. We turn Bitcoin mining payouts into on-chain USDT credit lines — using mining pools as the institutional counterparty, Bitcoin SPV as the proof, and HashKey Chain as the settlement layer. The full pipeline is live on testnet today.

Bitcoin miners generate $17 billion a year. There's no on-chain way to borrow against it.

Post-halving, the full cost to mine one Bitcoin has reached $137K. Miners raised $11 billion in debt since 2023 just to stay operational. Public miners sold over 5,000 BTC in a single month to cover costs. The working capital crunch is structural and accelerating.

Existing options have all failed. BTC lockup freezes the asset miners need. Trust-based lenders like BlockFi and Celsius went bankrupt. Existing on-chain lending requires overcollateralized liquid assets — it doesn't model a miner's revenue stream. Hashrate, the miner's core productive asset, is invisible on-chain. No trustless verification exists. Until now.

---

TAM is $17.2 billion in annual miner revenue. We target mid-market miners — 30 to 40% of global hashrate, underserved by capital markets. Top 10 pools control 90% of hashrate — one pool partnership unlocks thousands of borrowers. Stripe Capital advanced $9 billion+ with the same revenue-based model. Mining payouts are even more verifiable — proven by proof-of-work. At 10% penetration, that's $1.7 billion in lending volume and $136 million in annual protocol revenue. LP yield: 8% APR backed by real mining activity, not token emissions — two to three times typical DeFi rates.

You can't prove hashrate directly — it's a physical rate. But you can prove its output. Every pool payout is a Bitcoin transaction committed to by proof-of-work, verifiable by anyone with block headers. Payout history is the hashrate record. SPV turns that into trustless on-chain evidence. No oracle. No custodian. Just math.

---

We contract with mining pools. The pool agrees to withhold a repayment percentage from each subsequent payout — automatic enforcement at the source. When a payout occurs, we generate an SPV proof on-chain, the credit limit updates, and the miner can draw USDT immediately.

On default: the pool redirects the miner's hashrate. That's our collateral. Not a physical asset — hashrate.

Our IVerifierAdapter uses a modular verifier architecture. Any new proof source — bridges, oracles, ZK proofs — is a single contract swap. No rewrite needed.

Pool registers once — agrees to withholding. Miner keeps mining. Worker detects the payout, builds the SPV proof off-chain, submits to HashKey Chain. On-chain verifier checks PoW and Merkle inclusion — fully trustless. Credit limit updates. Miner draws USDT. Pool withholds repayment from the next payout.

Seven steps. Fully automated. Miners touch nothing after setup.

---

Three participants: miners borrow USDT at 10% APR through their pool. LPs deposit USDT and earn 8% — that's two to three times Aave's rate, protected by SPV proofs and pool-level enforcement. Protocol keeps the 2% spread plus a 0.5% origination fee per draw.

Seven production smart contracts live on HashKey Chain Testnet. SPV proofs generated from real Bitcoin testnet transactions. Full borrow/repay lifecycle operational. 24/7 automated prover worker. On-chain BTC identity binding using BIP-137 signature verification through EVM precompiles. Frontend live at hashcredit.studioliq.com. Full test suite including invariant fuzzing.

Contract addresses are deployed on HashKey Chain Testnet — chain ID 133. Verifiable right now.

---

The 2024 halving cut revenue per hash by 50%. Hardware ROI now exceeds 1,200 days. Public miners sold 5,359 BTC in a single month just to stay liquid. The demand is structural and accelerating. No one else is building this.

Every alternative requires either locking collateral or trusting a centralized underwriter. We use cryptographic proof and pool-enforced repayment — instant, permissionless, fully on-chain. Same trust model Bitcoin has used since 2009.

Q1 is done — everything you've seen is live. Q2: audit, HashKey Chain mainnet deployment, first 10 pilots. Q3: 50 miners, $500K TVL. Q4: $5M TVL, 200+ miners, cross-chain oracle adapter.

Two founders. We built the entire stack ourselves.

Incheol Yang: Co-founded a DeFi system trading house, managed $20M at 40%+ APR. Previously at KRAFTON PUBG and Coinone Exchange building trading infrastructure.

Juhyeong Park: CTO of Onther, led a mainnet to $750M market cap, designed Plasma EVM. Smart contract audits and full-stack Solidity architecture.

---

This is the most important slide for this room.

Mining-revenue lending needs more than just an EVM chain. It needs compliance infrastructure that makes pool partnerships legally viable.

HashKey Chain is operated by HashKey Group — an SFC-licensed financial institution in Hong Kong. The chain is built compliance-first: identity tooling, policy controls, and auditability at the protocol level. Pool withholding requires contractual and legal frameworks. HashKey Chain makes that possible — most DeFi-native chains cannot.

HashKey ecosystem is our distribution channel. HashKey Exchange provides fiat on/off-ramps and USDT liquidity. HashKey Capital provides strategic investment and introductions to mining operators. Hong Kong, where roughly 30% of global hashrate operates nearby, is the natural hub.

On the technical side, our core innovation — on-chain BTC address ownership proof — requires ecrecover, sha256, and ripemd160 precompiles. HashKey Chain, built on OP Stack, supports all standard Ethereum precompiles natively. No oracle, no bridge, no custom precompile needed.

And our modular IVerifierAdapter architecture means any new proof type is one contract swap away. As HashKey Chain's ecosystem matures with cross-chain messaging and ZK bridges, new proof sources plug in without touching credit logic.

---

We're raising $250K seed.

40% goes to engineering and mainnet deployment — the critical path. 20% to security audit — non-negotiable before mainnet. 20% to LP seed liquidity. 20% to mining pool partnerships.

This round delivers: audit, HashKey Chain mainnet deployment, 50 pilot miners, $500K TVL.

From the HashKey ecosystem: technical partnership and infrastructure support from the HashKey Chain engineering team. HashKey Capital for investment and mining operator introductions. HashKey Exchange for USDT liquidity integration and fiat on-ramp. Compliance guidance for cross-jurisdictional pool withholding agreements. And post-hackathon incubation with continued ecosystem and institutional resource support.

Thanks. Happy to go deeper on anything — the SPV mechanics, the pool enforcement model, or the HashKey Chain integration path.
