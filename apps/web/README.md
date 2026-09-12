# HashCredit Web Frontend

React-based dashboard for the HashCredit protocol on HashKey Chain.

## Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 19 + TypeScript |
| Build | Vite 7 |
| Styling | Tailwind CSS v4 + shadcn/ui (Radix) |
| State | Zustand 5 |
| Chain | ethers.js v6 |

## Tabs

- **Dashboard** — Credit overview, borrow/repay, protocol status, BTC wallet claim, and collapsible Settings section
- **Checkpoint** — Register a Bitcoin block header checkpoint on-chain
- **Proof** — Build an SPV proof and submit payout

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
- `VITE_RPC_URL` — HashKey Chain RPC endpoint
- `VITE_CHAIN_ID` — Chain ID (default: `133` for testnet)

## Deployment

Deployed to Vercel. On push to `main`, Vercel auto-builds from `apps/web`.

Live: https://hashcredit.studioliq.com
