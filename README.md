# HashCredit

**Revenue-Based Financing for Bitcoin Miners on Creditcoin**

HashCredit enables Bitcoin miners to borrow stablecoins against their future mining revenue. Instead of traditional collateral, credit limits are determined by verifiable on-chain payout events from mining pools.

## Overview

```
Mining Pool → BTC Payout → Relayer Detects → EVM Proof → Credit Limit ↑ → Borrow USDC
```

### Key Features

- **Revenue-Based Credit**: Credit limits based on trailing mining revenue, not locked collateral
- **Verifiable Payouts**: EIP-712 signed proofs from trusted relayer (MVP) or Bitcoin SPV (production)
- **Replay Protection**: Each payout can only be credited once
- **Risk Management**: Configurable advance rates, caps, and freeze controls

## Quick Start

```bash
# Install dependencies
forge install
cd offchain/relayer && pip install -e . && cd ../..

# Run tests
forge test

# Deploy (local)
anvil &
forge script script/Deploy.s.sol --rpc-url http://localhost:8545 --broadcast

# Run relayer
hashcredit-relayer run --btc-address <BTC_ADDR> --evm-address <EVM_ADDR>
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Bitcoin        │────►│  Python         │────►│  Creditcoin     │
│  Network        │     │  Relayer        │     │  EVM            │
│                 │     │                 │     │                 │
│  • Pool Payouts │     │  • Watch Addrs  │     │  • Manager      │
│  • Confirmations│     │  • EIP-712 Sign │     │  • Vault        │
│                 │     │  • Submit Proof │     │  • Verifier     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Contracts

| Contract | Description |
|----------|-------------|
| `HashCreditManager` | Core contract: borrower registry, payout recording, credit limits, borrow/repay |
| `LendingVault` | Stablecoin liquidity pool with LP shares and interest accrual |
| `RelayerSigVerifier` | EIP-712 signature verification for payout proofs (MVP) |
| `RiskConfig` | Risk parameters: advance rate, caps, confirmation requirements |
| `PoolRegistry` | Mining pool allowlist for payout source verification |

## Protocol Flow

1. **Register Borrower**: Admin registers miner with their BTC payout address hash
2. **Detect Payout**: Relayer watches Bitcoin for payouts to registered addresses
3. **Submit Proof**: Relayer signs and submits payout evidence to Manager
4. **Update Credit**: Manager calculates new credit limit based on trailing revenue
5. **Borrow**: Miner borrows stablecoin up to their credit limit
6. **Repay**: Miner repays debt with interest

## Credit Calculation

```
creditLimit = trailingRevenue(BTC) × btcPrice(USD) × advanceRate(%)
```

Example:
- Trailing Revenue: 1 BTC
- BTC Price: $50,000
- Advance Rate: 50%
- Credit Limit: **$25,000 USDC**

## Security

- **Replay Protection**: txid/vout uniqueness check prevents double-counting
- **Signature Verification**: Only authorized relayer can submit proofs
- **Time Limits**: Signatures have deadlines to prevent stale submissions
- **New Borrower Caps**: Lower limits for unproven borrowers
- **Admin Controls**: Freeze capability for emergency situations

## Development

```bash
# Build contracts
forge build

# Run tests with verbosity
forge test -vvv

# Gas report
forge test --gas-report

# Format code
forge fmt
```

## Documentation

- [DEMO.md](./DEMO.md) - Step-by-step demo walkthrough
- [PROJECT.md](./PROJECT.md) - Full project specification
- [TICKET.md](./TICKET.md) - Implementation tickets

## Tech Stack

- **Smart Contracts**: Solidity 0.8.24, Foundry
- **Off-chain**: Python 3.11+, web3.py, httpx
- **Bitcoin Data**: mempool.space API (MVP), Bitcoin Core RPC (production)
- **Target Chain**: Creditcoin EVM (testnet: chain ID 102031)

## License

MIT

---

Built for CTC Hackathon 2024
