# HashCredit

**Bitcoin Mining Profit Based (RBF) Lending Protocol on Creditcoin (SPV Mode)**

HashCredit verifies Bitcoin miners’ “full payout” transactions with SPVs, allowing Creditcoin EVM to calculate loan limits and borrow stablecoins without collateral.

## Demo link

- Frontend: `https://hashcredit.studioliq.com`
- API: `https://api-hashcredit.studioliq.com`

## Overview (one line)

`Bitcoin payout(tx)` -> `SPV proof` -> `Creditcoin on-chain credit limit` -> `Borrow/Repay`

## Core features

- Revenue-based credit limit: Convert trailing BTC profits to USD to calculate credit limit
- SPV verification: Verify Bitcoin transaction inclusion with checkpoint + header chain + Merkle inclusion proof
- Prevent replay: Same payout is reflected only once
- Risk parameters: advance rate, new borrower cap, window, etc.

## Architecture

```text
Bitcoin(testnet/main)  ->  Railway(API/Worker/DB)  ->  Creditcoin EVM(contracts)
```

## Component

- On-chain (Creditcoin EVM)
- `HashCreditManager`: Borrower registration, payout reflection, credit limit calculation, borrow/repay
- `LendingVault`: Stablecoin deposit/loan vault
- `CheckpointManager`: Stores Bitcoin block header checkpoints
- `BtcSpvVerifier`: SPV proof verification
- `RiskConfig`, `PoolRegistry`: Risk/Pool settings
- Off-chain (Railway)
- `offchain/api`: proof creation + checkpoint/borrower registration + proof submission (operation key)
- `offchain/prover`: Monitoring address polling and automatic proof submission (worker)
- Postgres: worker status/duplicate submission prevention
- Frontend (Vercel)
- `apps/web`: On-chain inquiry + demo operation button + demo wallet creation (local storage)

## Demo/Operation Flow (Summary)

1. Register checkpoint on-chain (`CheckpointManager`)
2. Borrower(EVM) <-> Register BTC address (pubkeyHash) (`BtcSpvVerifier`)
3. Borrower registration (`HashCreditManager.registerBorrower`)
4. Create and submit proof (`HashCreditManager.submitPayout`)
5. Borrower executes ‘Borrow/Repay’

## Important security note (mainnet)

In the testnet demo, the operator registers a borrower (EVM) <-> BTC address.

To prevent random mapping attacks on the mainnet, **claim based on proof of ownership (two-sided signature)** is required.
- Server issues nonce
- Borrower signs EVM + BTC signature (based on wallet `signmessage`. BIP-322 method is recommended in the long term)
- Execute pubkeyHash/borrower registration transaction on-chain only after verification

Current implementation:
- If you turn on `BORROWER_MAPPING_MODE=claim` in `offchain/api`, you can perform the above flow with `/claim/start` and `/claim/complete`.

## Local Development (Summary)

```bash
# contracts
forge build
forge test

# API
cd offchain/api
cp .env.example .env
pip install -e .
hashcredit-api

# Prover/Worker
cd ../prover
cp .env.example .env
pip install -e .
hashcredit-prover --help

# Frontend
cd ../../apps/web
cp .env.example .env
npm install
npm run dev
```

## document

- `docs/hackathon/SUBMISSION_CHECKLIST.md`: Submission checklist
- Distribution/demo operation documents are managed locally only (they are not uploaded to the repo).

## License

MIT
