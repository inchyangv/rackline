# HashCredit (Creditcoin SPV) demo scenario

This document is a local-only guide to showing your “best”** at a hackathon **demo day.

- Distribution type: **Contract is separate**, FE is Vercel, the rest (API + SPV worker + DB) is Railway
- Chain: **Creditcoin EVM Testnet (chainId=102031)**
- Bitcoin: **testnet**
- FE domain: `https://hashcredit.studioliq.com`
- API domain: `https://api-hashcredit.studioliq.com`

## 0. Demo objectives (one sentence)
“If you enter an actual transaction on the Bitcoin testnet, the on-chain settlement/loan flow is executed through SPV proof verification on the Creditcoin testnet” within 3 to 5 minutes.

## 1. Demo setup (recommended 4 minute flow)
1) **Dashboard (Inquiry)**: Creditcoin testnet contract status/borrower status is visible in real time
2) **Admin (Wallet)**: setBorrowerPubkeyHash → registerBorrower (owner wallet signs)
3) **Operations (Wallet + API)**: Build checkpoint via API → setCheckpoint via wallet
4) **Proof/Submit**: Build proof via API → submitPayout via wallet
5) **Borrower Action (Wallet)**: Sign Borrow / Repay transactions directly and show “User Action”

## 2. Preparation before demo (required)
### A. Deployment/Domain
- FE: Distributed on Vercel and accessible through `hashcredit.studioliq.com`
- API: Distributed on Railway and accessible through `api-hashcredit.studioliq.com`
- API `/health` is 200 OK

### A-1. (Current distribution address note, 2026-02-26)
```txt
DEPLOYER=0x8B05D473158913a034376D749ECdEbd48040d6Aa
STABLECOIN_ADDRESS=0x9e00a3a453704e6948689eb68a4f65649af30a97
CHECKPOINT_MANAGER=0xe792383beb2f78076e644e7361ed7057a1f4cd88
BTC_SPV_VERIFIER=0x98b9ddafe0c49d73cb1cf878c8febad22c357f33
LENDING_VAULT=0x60cd9c0e8b828c65c494e0f4274753e6968df0c1
HASH_CREDIT_MANAGER=0x3cfb7fcf0647c78c3f932763e033b6184d79a936
```

### B. Wallet/Gas
- Install MetaMask (or injection wallet)
- **Creditcoin testnet gas (CTC)** for both owner and borrower wallets
- Owner wallet: the DEPLOYER account that deployed the contracts (for Admin/Operations tab)
- Borrower wallet: a separate account imported into MetaMask (for Borrow/Repay)

### C. Contract address (required)
The three items below must be correctly entered in the settings tab of FE.
- `HashCreditManager`
- `BtcSpvVerifier`
- `CheckpointManager`

### D. Bitcoin testnet transaction (required)
To show the proof “in real life” we need:
- Borrower’s **Bitcoin testnet address** (e.g. `tb1...`)
- 1 **Bitcoin testnet transaction** deposited to that address
- `txid` and `vout` (output index) of the transaction
- (Recommended) Proceed after securing at least a few confirmations

NOTE: This project uses Bitcoin RPC by default: `https://bitcoin-testnet-rpc.publicnode.com` (no authentication).

## 3. Prepare demo wallets (MetaMask)

Two wallets are needed: **owner** (admin operations) and **borrower** (loan actions).

### Add Creditcoin Testnet to MetaMask
1) MetaMask → Settings → Networks → Add Network
2) Enter:
   - Network Name: `Creditcoin Testnet`
   - RPC URL: (use the RPC from Settings tab or `https://rpc.cc3-testnet.creditcoin.network`)
   - Chain ID: `102031`
   - Currency Symbol: `CTC`
3) Save

### Owner wallet
- The account that deployed the contracts (DEPLOYER address above)
- Must have CTC testnet gas for Admin tab operations (registerBorrower, setBorrowerPubkeyHash, setCheckpoint)
- Import private key into MetaMask if not already added

### Borrower wallet
1) MetaMask → Account Menu → ‘Create Account’ (or ‘Import Account’)
2) Fund with CTC testnet gas for Borrow/Repay transactions
3) Click ‘Connect Wallet’ at the top right of FE to connect

Recommended
- Use a **dedicated demo account**, not your main wallet
- After demo, the account can be removed from MetaMask

## 4. (The coolest) live demo flow
Below is a good “click as you explain” sequence.

### 4.1 Show status on dashboard (30 seconds)
1) FE top right ‘Connect wallet’
2) Click the ‘Chain Switch (102031)’ button
3) In the top card
- Network: `Chain 102031`
- Available Credit/Balance
- Transaction status (real-time)
4) Check whether the `Manager (Inquiry)`, `Checkpoint (Inquiry)`, and `SPV Verifier (Inquiry)` cards appear normally.

Comment example
- "This screen reads and displays the on-chain status directly, and automation for operation is attached to the API."

### 4.2 Register borrower on-chain (Admin tab, ~30 seconds)
Tab: `Admin`

> **Must be connected with the owner wallet** (DEPLOYER account). Non-owner wallets will revert.

#### A) setBorrowerPubkeyHash (SPV Verifier)
1) Enter `borrower` EVM address (e.g. `0x...`)
2) Enter `pubkeyHash` (bytes20, `0x` + 40 hex chars) — the HASH160 of the borrower’s BTC pubkey
3) Click `setBorrowerPubkeyHash` → confirm in MetaMask

#### B) registerBorrower (Manager)
1) Enter `registerBorrower: borrower` — same EVM address as above
2) Enter `BTC address` (e.g. `tb1...`) — `btcPayoutKeyHash` is auto-computed via keccak256
3) Click `registerBorrower` → confirm in MetaMask

Comment example
- “For SPV verification, the BTC payout key hash corresponding to the borrower is required, and these values are registered on-chain.”

### 4.3 Build and set checkpoint (Operations tab, ~30 seconds)
Tab: `Operations`

1) `API URL`: `https://api-hashcredit.studioliq.com`
2) Enter `Checkpoint height` — choose a value near or below the block height of the BTC transaction
3) (Optional) Check `dry_run` to skip the wallet tx and just see the API build result
4) Click `Build + setCheckpoint (Wallet)` → API builds the checkpoint payload → MetaMask signs the on-chain transaction
5) Result JSON is shown in `API Result` below

Comment example
- “The API fetches the Bitcoin block header, and the wallet submits it on-chain as a checkpoint.”

### 4.4 Build SPV proof and submit payout (Proof/Submit tab, ~1 minute)
Tab: `Proof/Submit`

#### Step 1: Build proof (API)
1) `API URL`: confirm it matches `https://api-hashcredit.studioliq.com`
2) Enter `txid` — the Bitcoin testnet txid (display format, not reversed)
3) Enter `vout` — the output index (usually `0`)
4) Enter `checkpoint_height` — the checkpoint height registered in step 4.3
5) Enter `target_height` — a block height ≥ the tx confirmation height
6) Click `Build proof (API)` → result JSON shown in `API Result`
7) On success, `proofHex` is **auto-filled** in the section below

#### Step 2: submitPayout (Wallet)
1) Verify `proofHex` is filled (starts with `0x`)
2) Click `submitPayout` → confirm in MetaMask
3) Check `Tx Status` pill at the bottom for confirmation

Note
- `submitPayout` is signed by the currently connected wallet.
- The connected wallet must have been registered as borrower in step 4.2, or the call will revert.

### 4.5 Show “product feel” through borrower actions (Borrow/Repay) (1 minute)
Tab: `Dashboard`

1) In `Borrow`, example: Enter `1000` → Click `Loan`
2) ‘Approve (stablecoin approval)’ only when necessary (approval before redemption/depending on token structure)
3) In `Repay`, example: Enter `100` → Click `Repayment`
4) Show that the top card ‘transaction status’ changes to ‘waiting for signature → sent → confirmed’

Comment example
- "Once the proof is submitted, actual financial action is connected on-chain based on the data."

## 5. Checklist just before demo (30 second check)
- FE opens with `hashcredit.studioliq.com`
- API is `api-hashcredit.studioliq.com/health` OK
- MetaMask chainId 102031 connected
- Owner wallet and borrower wallet both have CTC gas
- 3 contract addresses are correct in Settings tab
- Prepare txid/vout/checkpoint_height/target_height (for live proof)

## 6. Troubleshooting (only things that occur frequently)
- Wallet connection not possible: Check installation/activation of browser extension wallet (MetaMask)
- Chain mismatch: Resolved with ‘Chain Conversion (102031)’ above.
- API 4xx/5xx: Check token (X-API-Key), check Railway log
- CORS error: FE domain must be included in `ALLOWED_ORIGINS` of API
- Proof failure: Check if the txid/vout/height combination is correct and target_height is not too small.
