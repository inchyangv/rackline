# @rackline/attestcoin-tools

TypeScript tooling for the GPU lending evidence path. It pins the **official** Attestcoin (ex-USC) SDK, ABIs, and Solidity artifacts by version and hash, validates environment manifests under `config/attestcoin/`, builds the proof CLI used by the worker, and runs a read-only environment probe. It never signs, broadcasts, or holds keys; the proof worker and the on-chain verifier are separate components.

```bash
npm ci --prefix offchain/attestcoin
npm --prefix offchain/attestcoin run check          # ASC-CHECK: pins, ABI signature sets, manifests
npm --prefix offchain/attestcoin run test -- --run  # ASC-TEST: offline unit tests (fake transport)
npm --prefix offchain/attestcoin run build          # dist/src/cli.js for the proof worker
npm --prefix offchain/attestcoin run probe -- --manifest config/attestcoin/cc3-testnet.sepolia.json --out <report.json>
```

The package fails closed on unpinned artifacts, mismatched manifests, unsupported profiles, and malformed proof responses. Versions, hashes, and probe results: `docs/gpu/attestcoin/environment.md`.

Layout: `src/artifacts.ts` (pins), `src/abi.ts` (ABI loading and signature sets), `src/manifest.ts` (schema, fail-closed validation, canonical hash), `src/probe.ts` (read-only checks, injectable transport), `src/cli.ts`. CLI paths resolve against the directory `npm` was invoked from.
