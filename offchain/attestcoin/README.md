# @rackline/attestcoin-tools

TypeScript tooling for the GPU lending evidence path. It pins the **official**
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
The package fails closed on unpinned artifacts, mismatched manifests, unsupported profiles, and malformed proof responses.

Layout: `src/artifacts.ts` (pins), `src/abi.ts` (ABI loading/signature sets), `src/manifest.ts`
(schema + fail-closed validation + canonical hash), `src/probe.ts` (read-only checks, injectable transport),
`src/cli.ts`. Paths passed to the CLI resolve against the directory `npm` was invoked from.
