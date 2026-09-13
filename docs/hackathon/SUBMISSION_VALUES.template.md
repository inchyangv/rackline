# Submission Values (Template) — Rackline

Copy to `docs/hackathon/SUBMISSION_VALUES.md` and fill in.

## Project

| Field | Value |
|-------|-------|
| Project name | Rackline (formerly HashCredit) |
| Logo URL | TODO (host `logo/logo.png`) |
| Track | RWA (also DePIN, DeFi) |
| One-liner | GPU NFTs that borrow against their own revenue. |
| Description | Paste from `DORAHACKS.md` (One-liner → Why Creditcoin) |
| GitHub repo URL | https://github.com/inchyangv/ctc-hashcredit |
| Deck PDF URL | TODO |
| Demo video URL | TODO |
| Attestcoin usage | `AttestcoinRevenueVerifier` → `0x0FD2` BlockProver; source chain Sepolia (chainkey 1); prover API `https://prover.cc3-testnet.creditcoin.network/proof-by-tx/{chainKey}/{txHash}` |

## Testnet deployment

| Field | Value |
|-------|-------|
| Credit chain | Creditcoin CC3 Testnet, chainId `102031`, RPC `https://rpc.cc3-testnet.creditcoin.network` |
| Source chain | Ethereum Sepolia (Attestcoin chainkey `1`) |

### Creditcoin contracts (v2)

| Contract | Address | Blockscout |
|----------|---------|------------|
| GpuNodeNFT | TODO | TODO |
| AttestcoinRevenueVerifier | TODO | TODO |
| GpuCreditManager | TODO | TODO |
| LendingVault v2 | TODO | TODO |
| RiskConfig v2 | TODO | TODO |
| Stablecoin (mUSDT) | 0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A | |

### Sepolia contracts

| Contract | Address | Etherscan |
|----------|---------|-----------|
| NodeAccountRegistry | TODO | TODO |
| NodeAccount (token #1) | TODO | TODO |
| MockDePINPayout | TODO | TODO |

### Evidence links
- First `PayoutReceived` tx (Sepolia): TODO
- Matching `RevenueRecorded` tx (Creditcoin): TODO
- First `repayFor` tx: TODO

## Demo

Demo highlights (up to 3):
- Mint a GPU NFT and see its Node Account become the payout receiver
- Attestcoin-proven payout raises the credit limit on Creditcoin
- Second payout sweeps and repays the facility with no operator signature

Demo flow: see `SCRIPT.md`.
