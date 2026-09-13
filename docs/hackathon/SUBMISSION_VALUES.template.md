# Submission Values (Template) — Rackline

Copy to `docs/hackathon/SUBMISSION_VALUES.md` and fill in. Leave `TODO — not deployed` where nothing exists; never invent an address or a tx.

## Project

| Field | Value |
|-------|-------|
| Project name | Rackline (formerly HashCredit) |
| Logo URL | https://raw.githubusercontent.com/inchyangv/rackline/main/logo/rackline-avatar.png |
| Track | RWA (also DePIN, DeFi) |
| One-liner | Working capital for GPU operators, secured by revenue they have already earned. |
| Description | Paste from `DORAHACKS.md` (One-liner → Why Creditcoin) |
| GitHub repo URL | https://github.com/inchyangv/rackline |
| Deck PDF URL | TODO |
| Demo video URL | TODO |
| Attestcoin usage | Official native verification only: `AttestcoinRevenueVerifier` → `INativeQueryVerifier` precompile `0x…0FD2` (`verifyAndEmit`) + `EvmV1Decoder`; SDK `@gluwa/usc-sdk` 0.18.0, `@gluwa/asc-contracts` 0.2.1 pinned by hash (`config/attestcoin/cc3-testnet.sepolia.json`); source Sepolia chainKey 1; proof service `GET /api/v1/proof-by-tx/{chainKey}/{txHash}` (primary `proof-gen-api.cc3-testnet.creditcoin.network`) |

## Testnet deployment

| Field | Value |
|-------|-------|
| Credit chain | Creditcoin CC3 Testnet, chainId `102031`, RPC `https://rpc.cc3-testnet.creditcoin.network` |
| Source chain | Ethereum Sepolia (Attestcoin chainKey `1`, chainId `11155111`) |
| Environment status | `PROBED` (read-only, 2026-09-13; `docs/gpu/attestcoin/environment.md`) — native proof: TODO (G-ASC / GPU-080) |

### Creditcoin contracts (v2)

| Contract | Address | Blockscout |
|----------|---------|------------|
| AttestcoinRevenueVerifier | TODO — not deployed | |
| EvidenceBook | TODO — not deployed | |
| Facility manager / debt ledger | TODO — not deployed | |
| LendingVault v2 | TODO — not deployed | |
| RiskConfig v2 | TODO — not deployed | |
| Test stablecoin (GPU-080 scope) | TODO | |

Legacy v1 (Spring 2026): HashCreditManager `0x593e140982cDC040d69B7E7623A045C6d6Ca2055`, LendingVault `0x4d74126369BacB67085a1E70d535cA15515d1AFa`, mUSDT `0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A`.

### Sepolia contracts

| Contract | Address | Etherscan |
|----------|---------|-----------|
| Controlled escrow (facility #1) | TODO — not deployed | |
| MockDePINSettlement (TEST_ONLY) | TODO — not deployed | |

### Evidence links
- `ASC-PROBE` report: `test/fixtures/gpu/attestcoin/probe/cc3-testnet.sepolia.probe.json` (read-only environment check, not a proof)
- First `SettlementReceived` tx (Sepolia): TODO
- Matching `EventRecorded` tx (Creditcoin, native verification): TODO
- First `repayFor` tx (destination cash receipt): TODO

## Demo

Demo highlights (up to 3):
- A settlement into a controlled escrow on Sepolia is natively verified on Creditcoin through the official Attestcoin precompile — the only evidence path
- Eligible unpaid receivables (not past payouts) set the facility room; a stale checkpoint blocks new draws
- A second settlement reaches the vault through a (mock) rail and `repayFor` reduces the debt with no operator signature

Demo flow: see `SCRIPT.md` (Part A = today; Part B = after the demo slice is built). Simulated parts: `Simulated payer`, `Mock settlement`, `partnerRevenue=SIMULATED`.
