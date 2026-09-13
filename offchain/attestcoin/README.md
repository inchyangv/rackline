# @rackline/attestcoin-tools

Narrow TypeScript package for the GPU lending pivot (TICKET.md GPU-075). It pins the **official**
Attestcoin (ex-USC) SDK, ABIs and Solidity artifacts by version and hash, validates environment manifests
under `config/attestcoin/`, and runs a **read-only** environment probe. It never signs, broadcasts, or
holds keys. It is not a proof worker (GPU-079) and not a verifier (GPU-078).

```
npm ci --prefix offchain/attestcoin
npm --prefix offchain/attestcoin run check                      # ASC-CHECK: pins, ABI signature sets, manifests
npm --prefix offchain/attestcoin run test -- --run              # ASC-TEST: offline unit tests (fake transport)
npm --prefix offchain/attestcoin run probe -- --manifest config/attestcoin/cc3-testnet.sepolia.json --out <report.json>
```

Facts, versions, hashes and probe results: `docs/gpu/attestcoin/environment.md`.
Decisions this package enforces: `docs/gpu/decisions/attestcoin-first.md` (R2-D02, R2-D03, R2-D11, R2-D12).

Layout: `src/artifacts.ts` (pins), `src/abi.ts` (ABI loading/signature sets), `src/manifest.ts`
(schema + fail-closed validation + canonical hash), `src/probe.ts` (read-only checks, injectable transport),
`src/cli.ts`. Paths passed to the CLI resolve against the directory `npm` was invoked from.
