# HashCredit Demo Guide

This guide walks through the complete HashCredit demo flow for the CTC Hackathon.

## Prerequisites

- Node.js 18+ (for Foundry/Forge)
- Python 3.11+
- Foundry installed (`curl -L https://foundry.paradigm.xyz | bash && foundryup`)
- Access to Creditcoin testnet RPC

## Quick Start (5 minutes)

### 1. Setup Environment

```bash
# Clone and enter the repository
cd ctc-btc-miner

# Install Foundry dependencies
forge install

# Install Python relayer
cd offchain/relayer
pip install -e .
cd ../..

# Copy environment template
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` with your values:

```bash
# Required for deployment
RPC_URL=https://rpc.cc3-testnet.creditcoin.network
CHAIN_ID=102031
PRIVATE_KEY=your_deployer_private_key

# Required for relayer
RELAYER_PRIVATE_KEY=your_relayer_signing_key
```

### 3. Deploy Contracts

```bash
# Deploy to local Anvil (for testing)
make anvil &  # In another terminal
make deploy-local

# Or deploy to Creditcoin testnet
forge script script/Deploy.s.sol --rpc-url $RPC_URL --broadcast
```

### 4. Register a Borrower

```bash
# Using cast (Foundry CLI)
cast send $HASH_CREDIT_MANAGER "registerBorrower(address,bytes32)" \
  0xBorrowerAddress \
  0xBtcPayoutKeyHash \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY
```

### 5. Run the Relayer

```bash
# Check payouts to a Bitcoin address
hashcredit-relayer check bc1qexampleaddress

# Run relayer in single-shot mode
hashcredit-relayer run --once \
  --btc-address bc1qexampleaddress \
  --evm-address 0xBorrowerAddress

# Run relayer continuously
hashcredit-relayer run \
  --btc-address bc1qexampleaddress \
  --evm-address 0xBorrowerAddress
```

### 6. Borrow Against Credit

```bash
# Check available credit
cast call $HASH_CREDIT_MANAGER "getAvailableCredit(address)" \
  0xBorrowerAddress \
  --rpc-url $RPC_URL

# Borrow (as borrower)
cast send $HASH_CREDIT_MANAGER "borrow(uint256)" \
  1000000000 \  # $1000 (6 decimals)
  --rpc-url $RPC_URL \
  --private-key $BORROWER_PRIVATE_KEY
```

## Demo Scenario

### Scenario: Mining Pool Payout → Credit Line → Stablecoin Loan

1. **Setup**: Alice is a Bitcoin miner receiving payouts to `bc1q...alice`

2. **Registration**: Protocol admin registers Alice:
   - EVM Address: `0xAlice...`
   - BTC Payout Key Hash: `keccak256("bc1q...alice")`

3. **Payout Detection**: Relayer watches `bc1q...alice`:
   - Detects incoming payout: 0.5 BTC from mining pool
   - Waits for 6 confirmations
   - Creates EIP-712 signed proof

4. **Proof Submission**: Relayer submits to HashCreditManager:
   - Signature verified against authorized relayer
   - Payout recorded (replay protected)
   - Credit limit updated: 0.5 BTC × $50,000 × 50% = $12,500

5. **Borrowing**: Alice borrows against her credit:
   - Requests $5,000 USDC
   - Manager verifies credit limit
   - Vault transfers USDC to Alice

6. **Repayment**: Alice repays with interest:
   - Approves Manager to spend USDC
   - Calls `repay($5,050)`
   - Debt reduced, credit available again

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Bitcoin Network                          │
│                                                                 │
│  Mining Pool ──────────────► Miner BTC Address                  │
│               (payout)       bc1q...                            │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Python Relayer                              │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐        │
│  │   Bitcoin   │───►│   EIP-712   │───►│     EVM      │        │
│  │   Watcher   │    │   Signer    │    │   Submitter  │        │
│  └─────────────┘    └─────────────┘    └──────────────┘        │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Creditcoin EVM                               │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   HashCreditManager                      │   │
│  │   ┌────────────┐  ┌────────────┐  ┌────────────┐        │   │
│  │   │  Borrower  │  │   Payout   │  │   Credit   │        │   │
│  │   │  Registry  │  │  Recording │  │   Limit    │        │   │
│  │   └────────────┘  └────────────┘  └────────────┘        │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             │                                   │
│              ┌──────────────┼──────────────┐                   │
│              ▼              ▼              ▼                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │RelayerSig    │  │ LendingVault │  │  RiskConfig  │         │
│  │Verifier      │  │  (USDC)      │  │              │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Contract Addresses (Testnet)

| Contract | Address |
|----------|---------|
| HashCreditManager | (deployed) |
| LendingVault | (deployed) |
| RelayerSigVerifier | (deployed) |
| RiskConfig | (deployed) |
| PoolRegistry | (deployed) |
| MockUSDC | (deployed) |

## Security Considerations

1. **Replay Protection**: Each payout (txid/vout) can only be credited once
2. **Signature Verification**: Only authorized relayer can submit payouts
3. **Deadline Enforcement**: Signatures expire to prevent stale submissions
4. **Credit Caps**: New borrowers have limited credit until track record established
5. **Freeze Capability**: Admin can freeze borrowers in case of suspicious activity

## Testing

```bash
# Run all Solidity tests
forge test -vvv

# Run specific test
forge test --match-test test_borrow -vvv

# Gas report
forge test --gas-report
```

## Troubleshooting

### "Payout already processed"
The same Bitcoin transaction output has already been submitted. Each txid/vout pair can only be used once.

### "Deadline expired"
The relayer signature has expired. Relayer needs to generate a fresh signature.

### "Invalid signature"
Either the wrong relayer key was used, or the chain ID doesn't match.

### "Exceeds credit limit"
The borrower is trying to borrow more than their credit limit allows. More payouts needed or partial repayment required.
