# Rackline GPU web

The application connects to the GPU API and deployment manifest. The separate `/demo` route is a browser-only interactive preview with synthetic balances and no wallet/API/RPC calls. Legacy BTC components and storage remain isolated from GPU routes.

## Run and configure

```sh
npm ci --prefix apps/web
VITE_GPU_API_URL=http://127.0.0.1:8000 npm --prefix apps/web run dev
```

`VITE_GPU_API_URL` is the only GPU deployment setting in the browser build. `/v1/config` supplies chain ID, loan token/decimals, contract addresses, explorer, execution profile, and manifest identity. `/` opens the connected application when this variable is configured. `/app` explicitly opens connected mode; `/demo` always opens the local preview. Without an API setting, `/` preserves the preview.

The API must allow the exact frontend origin through CORS. A missing or invalid deployment fails closed. Production refuses a test-only loan token; native profiles require official Attestcoin verification. A native profile setting is not proof that any native event has been accepted.

## User flows

- Wallet: EIP-712 login is bound to the API domain, chain, wallet, purpose, and expiration. Sessions stay in memory and account/network changes invalidate pending reads and login state.
- Providers: submit a borrower profile and document reference, reconnect for borrower scope, submit a durable provider connection review, inspect actual account/control status, and request an official source proof for a linked account. Submission is not approval, E2, or native acceptance.
- Borrow: read recorded accounting separately from current chain debt. Each borrow/repayment uses a fresh authoritative facility ID binding. The router's `repayExact` keeps direct repayment available during proof outages and caps transfers at current debt.
- Earn: faucet for explicitly test-only native-testnet assets, deposit, immediate withdrawal, queued withdrawal, cancellation, permissionless queue processing, funded claim, and prior epoch recovery. Available shares exclude locked requests; reserves and in-flight cash do not inflate liquidity.
- Operations: role-gated cases, version-checked reasoned assignment/acknowledgment/retry/resolution and audit history. The API enforces authority independently of visible controls.

Wallet transactions verify chain/account, deployed code, vault asset and decimals, then simulate before submission. Token approvals are for the entered amount. Deposit/withdrawal review freezes a two-minute quote with a 0.5% minimum-output bound. A transaction succeeds in the UI only after two confirmations; rejection, revert, and cancellation preserve the error state. A changed-call replacement is not accepted as the original action.

## Generation and checks

```sh
npm --prefix apps/web run generate:gpu
npm --prefix apps/web run check:generated
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test -- --run
npm --prefix apps/web run test:e2e
```

`scripts/generate-gpu.mjs` reads actual `forge inspect` ABIs and the GPU app's OpenAPI schema. It writes only `src/features/gpu/generated/`; never edit generated files manually. Install the shared GPU/API Python packages first. Locally the generator uses `.venv-py313/bin/python`; CI sets `GPU_TYPES_PYTHON=python`. Sources are Solidity interfaces plus `GpuTestToken` and `hashcredit_api.gpu.app:create_app`.

The static build is `apps/web/dist`. `vercel.json` provides scoped `index.html` fallbacks for `/app` and `/demo`; API and asset paths are untouched. The root `.vercelignore` allowlists only frontend build inputs, excluding keys, environments, native artifacts and backend files from CLI uploads. Build provenance appears in the footer. See [tests/README.md](tests/README.md) for evidence boundaries and real API interoperability checks.
