# HashCredit Web Frontend

React-based dashboard for the HashCredit protocol on Creditcoin EVM.

## Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 19 + TypeScript |
| Build | Vite 7 |
| Styling | Tailwind CSS v4 + shadcn/ui (Radix) |
| State | Zustand 5 |
| Chain | ethers.js v6 |

## Tabs

- **Dashboard** — Read on-chain state (credit limit, debt, payout history) + collapsible Admin section
- **Operations** — Build checkpoint payload via API, then submit `setCheckpoint` with wallet
- **Proof/Submit** — Build proof via API, then submit `submitPayout` with wallet

Admin functions (`registerBorrower`, `setBorrowerPubkeyHash`, `setVerifier`) are in the Dashboard's collapsible "Admin (Owner-only)" section. RPC and contract configuration is read from environment variables (no Settings tab).

## Setup

```bash
cp .env.example .env   # Configure RPC URL, contract addresses
npm install
npm run dev            # http://localhost:5173
```

## Build

```bash
npm run build          # Output in dist/
npm run preview        # Preview production build
```

## Environment Variables

See `.env.example` for the full list. Key variables:

- `VITE_API_URL` — Backend API URL
- `VITE_RPC_URL` — Creditcoin EVM RPC endpoint
- `VITE_CHAIN_ID` — Chain ID (default: `102031` for testnet)

## Deployment

Deployed to Vercel. On push to `main`, Vercel auto-builds from `apps/web`.

Live: https://hashcredit.studioliq.com
