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
2) **One-click operation (API)**: Checkpoint registration → Borrower pubkeyHash registration → Borrower registration → Proof creation/submission
3) **Proof/Submission**: proofHex is automatically filled, and the submission result/tx status is displayed.
4) **Borrower Action (Wallet)**: Sign Borrow / Repay transactions directly and show “User Action”

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
- **Creditcoin testnet gas (CTC)**
- Administrator (owner) key: `PRIVATE_KEY` of Railway (API service) must be the owner account
- Demo signing wallet (borrower): Planned to import and sign in MetaMask

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

### 4.2 Demonstrate “One-Click Automation” with Operations (API) (1-2 minutes)
Tab: `Operations (API)`

#### A) Check API connection
1) `API URL`: `https://api-hashcredit.studioliq.com`
2) `API Token`: `API_TOKEN` value entered in Railway
3) Click ‘Health Check’ → Confirm OK

#### B) Checkpoint registration
1) Enter `checkpoint height`
- Principle: Choose a reasonable value near or below `target_height` to use in your proof.
2) Click ‘Checkpoint Registration (API)’

#### C) Register Borrower pubkeyHash
1) `Borrower (EVM)`
- It is recommended to match the borrower input value at the top of the FE.
2) `Borrower BTC Address`: `tb1...`
3) Click ‘pubkeyHash registration (API)’

#### D) Register Borrower (Manager.registerBorrower)
1) Same EVM address as `registerBorrower: borrower`
2) Click `registerBorrower(API)`

Comment example
- "For SPV verification, the BTC payout key hash corresponding to the borrower is required, and these values ​​are registered on-chain."

#### E) Proof creation/submission (one click)
1) `txid`: Bitcoin testnet txid (display format)
2) `vout`: output index
3) `checkpoint_height`: Checkpoint height registered above
4) `target_height`: Header height the proof should reach
5) Click ‘One Click (Create + Submit)’

result
- The build/submit result JSON is output in `API results` below.
- If successful, the on-chain transaction may be displayed in the FE's `Tx status` (depending on service implementation)
- `proofHex` in the `Proof/Submission` tab is automatically filled

In case of failure (order to revive the demo)
- Click ‘Create proof (API)’ first to check the build results
- After checking `dry_run`, click `proof submission (API)` to show the “submission flow” itself.
- If it still fails, quickly show only `health check`, `checkpoint registration`, `pubkeyHash registration`, and `registerBorrower` and move on to the next part.

### 4.3 Show “proof data” on proof/submission screen (30 seconds)
Tab: `Certify/Submit`

- Show whether `proofHex` is auto-filled
- If necessary, click `submitPayout (wallet)` to demonstrate “submit to user wallet”

caution
- `submitPayout (wallet)` is signed by the currently connected wallet.
- Since revert is possible depending on permissions/conditions, API submission is recommended as the main method for live demos.

### 4.4 Show “product feel” through borrower actions (Borrow/Repay) (1 minute)
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
- MetaMask chainId 102031 can be converted
- 3 contract addresses are correct
- Prepare API token
- Prepare txid/vout/checkpoint_height/target_height (for live proof)

## 6. Troubleshooting (only things that occur frequently)
- Wallet connection not possible: Check installation/activation of browser extension wallet (MetaMask)
- Chain mismatch: Resolved with ‘Chain Conversion (102031)’ above.
- API 4xx/5xx: Check token (X-API-Key), check Railway log
- CORS error: FE domain must be included in `ALLOWED_ORIGINS` of API
- Proof failure: Check if the txid/vout/height combination is correct and target_height is not too small.
