# HashCredit Demo Guide

This guide walks through the complete HashCredit demo flow for the CTC Hackathon.

## Prerequisites

- Foundry installed (`curl -L https://foundry.paradigm.xyz | bash && foundryup`)
- Python 3.11+
- Access to an EVM RPC (local Anvil or Creditcoin testnet)
- (Optional) Node.js 18+ (only if you want to run `apps/web`)

## Quick Start (5 minutes)

### 1. Setup Environment

```bash
# Clone and enter the repository
cd ctc-btc-miner

# Install Foundry dependencies
forge install

# Install Python relayer (recommended: venv)
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e "offchain/relayer[dev]"

# Copy environment template
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` with your values:

```bash
# Required (deploy + relayer submitter)
RPC_URL=https://rpc.cc3-testnet.creditcoin.network
CHAIN_ID=102031
PRIVATE_KEY=your_deployer_private_key

# Required (EIP-712 signer)
RELAYER_PRIVATE_KEY=your_relayer_signing_key

# Optional: if RELAYER_PRIVATE_KEY is different from PRIVATE_KEY
# RELAYER_SIGNER=0xYourRelayerSignerAddress
```

### 3. Deploy Contracts

```bash
# Load .env into your current shell (for `make` / `cast` commands below)
set -a
source .env
set +a

# Deploy to local Anvil (for testing)
# Terminal A:
make anvil

# Terminal B:
make deploy-local

# Or deploy to Creditcoin testnet
make deploy-testnet
```

After deployment, copy the printed addresses into your `.env` (`HASH_CREDIT_MANAGER`, `VERIFIER`, `LENDING_VAULT`).

### 4. Register a Borrower

```bash
# Choose a borrower EVM address and a BTC address to watch
export BORROWER_EVM=0xBorrowerAddress
export BTC_ADDR=bc1qexampleaddress
export BTC_KEY_HASH=$(cast keccak "$BTC_ADDR")

# Using cast (Foundry CLI)
cast send $HASH_CREDIT_MANAGER "registerBorrower(address,bytes32)" \
  $BORROWER_EVM \
  $BTC_KEY_HASH \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY
```

### 5. Run the Relayer

```bash
# Check payouts to a Bitcoin address
hashcredit-relayer check "$BTC_ADDR"

# Run relayer in single-shot mode
hashcredit-relayer run --once \
  --btc-address "$BTC_ADDR" \
  --evm-address "$BORROWER_EVM"

# Run relayer continuously
hashcredit-relayer run \
  --btc-address "$BTC_ADDR" \
  --evm-address "$BORROWER_EVM"
```

### 6. Borrow Against Credit

```bash
# Check available credit
cast call $HASH_CREDIT_MANAGER "getAvailableCredit(address)" \
  $BORROWER_EVM \
  --rpc-url $RPC_URL

# Borrow (as borrower)
# BORROWER_PRIVATE_KEY must match the borrower EVM address.
cast send $HASH_CREDIT_MANAGER "borrow(uint256)" \
  1000000000 \
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

## Contract Addresses

The deployment script prints all deployed addresses. Copy them into your `.env`:

- `HASH_CREDIT_MANAGER`
- `VERIFIER`
- `LENDING_VAULT`

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
