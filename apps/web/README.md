# Rackline Web Frontend

React app for Rackline (formerly HashCredit) on Creditcoin EVM — stablecoin working capital for GPU operators, funded by liquidity providers.
This is the v2 visual system running on the v1 (Bitcoin-payout) testnet contracts; every number shown is a live
on-chain read and every step that is not available in this deployment is labelled as such.

## Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 19 + TypeScript |
| Build | Vite 7 |
| Styling | Tailwind CSS v4 + shadcn/ui (Radix) |
| Fonts | Archivo Variable + Chivo Mono Variable, self-hosted via `@fontsource-variable` |
| State | Zustand 5 |
| Chain | ethers.js v6 (public RPC reads, injected wallet for writes) |
| History | Blockscout logs API (`Borrowed` / `Repaid` events → Statement) |

## Pages

- **Borrow** — facility header (viewed address, status tag), one hero number (drawable now), terms ledger,
  on-chain statement, Draw / Repay action block, facility setup stepper, repayment disclosure.
- **Lend** — pool header, cash in pool, utilization meter, pool ledger, connected-wallet position,
  Deposit / Withdraw action block (withdraw is denominated in mUSDT), funding disclosure.

## Design system

Tokens live in `src/index.css` (`--ink-*`, `--bone*`, `--signal`, `--ok/--warn/--err`, `--rule*`) and are aliased
onto the shadcn variables so Radix primitives inherit them. Utilities: `num` (mono + tabular), `wordmark`,
`eyebrow`, `condensed`. Rules: one hero number per page, hairlines instead of boxed cards, signal orange only for
the mark rule / active underline / focus / gauge, no shadows or gradients, every disabled action shows a prose
reason, all money via `<Money/>` (truncated, grouped, kerned, exact value in the tooltip).

Brand strings (name, wordmark, descriptor, legal line) are in `src/lib/brand.ts`; contract, env and API identifiers
keep their legacy `HashCredit*` names.

## Setup

```bash
npm install
npm run dev            # http://localhost:5173
```

## Build

```bash
npm run lint
npm run build          # tsc -b && vite build → dist/
npm run preview
```

## Environment variables

All optional; defaults target Creditcoin Testnet (chainId `102031`).

- `VITE_RPC_URL`, `VITE_CHAIN_ID`
- `VITE_HASH_CREDIT_MANAGER`, `VITE_VAULT_ADDRESS`, `VITE_STABLECOIN_ADDRESS`, `VITE_BTC_SPV_VERIFIER`
- `VITE_API_URL` — backend API (payout-address verification)
- `VITE_EXPLORER_BASE` — Blockscout UI base (address / tx links)
- `VITE_EXPLORER_API_BASE` — Blockscout API base (statement events)

The footer shows the build commit (`__APP_COMMIT__`, injected in `vite.config.ts`; Vercel's
`VERCEL_GIT_COMMIT_SHA` is used when present).

## Deployment

Deployed to Vercel from `apps/web`.
