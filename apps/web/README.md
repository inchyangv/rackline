# Rackline GPU web

React/Vite application with two entry modes:

- `/app`: the connected application. It reads deployment identity from the GPU API and signs financial transactions in the user's wallet.
- `/demo`: a browser-only preview with synthetic balances. It makes no wallet, API, or RPC calls.

Legacy BTC components and storage stay isolated from the GPU routes.

## Run and configure

```sh
npm ci --prefix apps/web
VITE_GPU_API_URL=http://127.0.0.1:8000 npm --prefix apps/web run dev
```

`VITE_GPU_API_URL` is the only GPU deployment setting in the browser build. Everything else (chain ID, loan token and decimals, contract addresses, explorer, execution profile, manifest identity) comes from `GET /v1/config`. With the variable set, `/` opens the connected application; without it, `/` keeps the preview. `/app` and `/demo` always open their own mode.

The API must allow the exact frontend origin through CORS. A missing or invalid deployment fails closed. Production refuses a test-only loan token; native profiles require official Attestcoin verification. A native profile setting is not proof that any native event has been accepted.

## User flows

| Area | What the user can do |
| --- | --- |
| Wallet | EIP-712 login bound to API domain, chain, wallet, purpose, and expiry. Sessions stay in memory; account or network changes invalidate pending reads and login state. |
| Providers | Submit a borrower profile and document reference, reconnect for borrower scope, submit a provider connection for review, inspect account/control status, request an official source proof for a linked account. Submission is not approval, E2, or native acceptance. |
| Borrow | Read recorded accounting separately from current chain debt. Each borrow or repayment binds a fresh authoritative facility ID. `repayExact` keeps direct repayment available during proof outages and caps transfers at current debt. |
| Earn | Faucet (test-only native-testnet assets), deposit, immediate withdrawal, queued withdrawal, cancellation, permissionless queue processing, funded claim, prior-epoch recovery. Available shares exclude locked requests; reserves and in-flight cash do not inflate liquidity. |
| Operations | Role-gated cases with version-checked, reasoned assignment, acknowledgment, retry, resolution, and audit history. The API enforces authority independently of visible controls. |

Before submitting, every wallet transaction verifies chain and account, deployed code, vault asset and decimals, then simulates the call. Token approvals are for the entered amount. Deposit and withdrawal review freezes a two-minute quote with a 0.5% minimum-output bound. The UI reports success only after two confirmations; rejection, revert, and cancellation keep the error state; a replacement with a changed call is not accepted as the original action.

## Generated code and checks

```sh
npm --prefix apps/web run generate:gpu
npm --prefix apps/web run check:generated
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test -- --run
npm --prefix apps/web run test:e2e
```

`scripts/generate-gpu.mjs` reads `forge inspect` ABIs and the GPU API's OpenAPI schema (Solidity interfaces plus `GpuTestToken`, and `hashcredit_api.gpu.app:create_app`) and writes only `src/features/gpu/generated/`. Never edit generated files by hand. The shared GPU and API Python packages must be installed first; locally the generator uses `.venv-py313/bin/python`, CI sets `GPU_TYPES_PYTHON=python`.

## Deployment

The static build is `apps/web/dist`. `vercel.json` rewrites `/app/*` and `/demo/*` to `index.html`; API and asset paths are untouched. The root `.vercelignore` allowlists only frontend build inputs, so keys, environments, native artifacts, and backend files are never uploaded. Build provenance appears in the footer.

Verification and evidence boundaries: [tests/README.md](tests/README.md).
