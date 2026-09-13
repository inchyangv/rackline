# Attestcoin environment and artifact ledger

Pinned on 2026-09-13/14 from the official docs and the actual npm artifacts. This is the artifact/version/
environment source of truth. "Probed" means a read-only RPC/HTTP check succeeded at the stated time; it is
**not** a native proof result and not partner, payment-control, or cash evidence.

## 1. Official artifacts (pinned, hashed)

| Artifact | Version | Integrity / hash | Source |
| --- | --- | --- | --- |
| `@gluwa/usc-sdk` (TS/JS SDK) | **0.18.0** (published 2026-06-22) | npm `sha512-iUEXPAp1gB/HDYkXad+StVJvs0Yz2ZIbzijc8SaBflGJ95hPnVahyY+tsP2PApswSQaX2uIBM7Cb0jpZ+KBzTQ==`; tarball sha256 `b1f7ef61…03d875` | registry.npmjs.org; repo `gluwa/cc-next-query-builder`; MIT |
| `@gluwa/asc-contracts` (Solidity sources) | **0.2.1** | tarball sha256 `b45fffaf…289dee` | npm; repo `gluwa/asc-contracts`; MIT; depends on `@openzeppelin/contracts 5.1.0` |
| `@gluwa/usc-contracts` (older name) | 0.2.0 | tarball sha256 `68dc21d3…f710e1` | **not used** — superseded naming (`USC*` → `ASC*`); listed to document the drift |
| `ethers` | 6.15.0 (SDK declares `^6.15.0`) | lockfile | peer/runtime for the SDK |

Pinned files (sha256; enforced by `ASC-CHECK` and `artifacts.test.ts`):

| Role | File | sha256 |
| --- | --- | --- |
| BlockProver precompile ABI | `usc-sdk/dist/block-prover/block_prover.json` | `cf796a38fa5b2ebfab7d25755256139652755c71eed935675d88458244e0cd5c` |
| ChainInfo precompile ABI | `usc-sdk/dist/chain-info/chain_info.json` | `1c93aab8f029bd0b25594753729e61c70dfa8f5d99b203745b77d6e7baa14f77` |
| EvmV1Decoder ABI (SDK copy) | `usc-sdk/dist/utils/evmV1DecoderAbi.json` | `bd07dc76f8ab1505d6eec373da990de7fab624e878a206ed1a2618c4667c829a` |
| EvmV1Decoder library source | `asc-contracts/contracts/common/EvmV1Decoder.sol` | `2de1a8faf7b203c33a08db73e7a79e0523c4a84580c9c75ce209df0d5bf2e692` |
| Full `INativeQueryVerifier` + `NativeQueryVerifierLib` | `asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol` | `bc81982eb4070d3a5519346c868c73eff177b7c514ef2befae6cadfe9cddd1ed` |
| Lean `INativeQueryVerifier` (view `verify` only) | `asc-contracts/contracts/write-ability/INativeQueryVerifier.sol` | `330e2039911731e2bfede78c28b498f51bda5704a8634abb26325487fe0ba3e2` |
| `ASCBase` reference pattern | `asc-contracts/contracts/readability/ASCBase.sol` | `ff24791a29b1b5477088ec2e36a4960768ec79178817458c6e77c2a4ce3b9f3c` |
| `BlockProverTypes` (proof semantics) | `asc-contracts/contracts/write-ability/common/BlockProverTypes.sol` | `7f2f5aecf619566a154341c75481fc2a6b3e749e021070d59bc26112c8a47b43` |

Byte-identical copies of the three ABI JSONs live in `test/fixtures/gpu/attestcoin/official/` with
`PROVENANCE.json` (kind `OFFICIAL_ARTIFACT_COPY`); `fixtures.test.ts` fails if they drift from `node_modules`.

## 2. Native interface facts (from the pinned files — not from TECH/README)

`INativeQueryVerifier` at `0x0000000000000000000000000000000000000FD2` (the "Block Prover precompile";
docs note it was previously called *Native Query Verifier*, which is why the Solidity name survives):

| Function | Mutability | Notes |
| --- | --- | --- |
| `verify(uint64 chainKey, uint64 height, bytes encodedTransaction, MerkleProof, ContinuityProof) → bool` | `view` | SDK `verifySingle` = `staticCall` of this. **Reverts** on invalid proof (observed: `Error("Merkle proof validation failed")`). |
| `verify(uint64, uint64[] heights, bytes[] txs, MerkleProof[], ContinuityProof shared) → bool` | `view` | batch, shared continuity proof (SDK `MAX_BATCH_SIZE` 10, range 1000 blocks) |
| `verifyAndEmit(...)` single / batch | `nonpayable` | same checks + emits `TransactionVerified(uint64 indexed chainKey, uint64 indexed height, uint64 transactionIndex)` |
| `calculateTxIndex(MerkleProof) → uint64` | `view` | `isLeft=true` ⇒ sibling on the left ⇒ current node is the right child ⇒ bit set at that level (probed: `[]→0`, `[L,R]→1`, `[R,L]→2`, `[L,L,L]→7`) |

Structs: `MerkleProofEntry{bytes32 hash; bool isLeft}`, `MerkleProof{bytes32 root; MerkleProofEntry[] siblings}`,
`ContinuityProof{bytes32 lowerEndpointDigest; bytes32[] roots}`. Continuity digest formula (BlockProverTypes):
`digest[i] = keccak256(abi.encodePacked(blockHeight + i, roots[i], digest[i-1]))`, `digest[-1] = lowerEndpointDigest`.

`NativeQueryVerifierLib`: `PRECOMPILE = 0x…0FD2`; `isCreditcoinChainId` ∈ {102030, 102031, 102032};
`hasPrecompile()` returns true on those chain ids **without** checking bytecode (native precompiles have
`extcodesize == 0`). Therefore: **empty bytecode at 0xFD2/0xFD3 is not evidence of absence**; the probe uses
documented calls instead.

`EvmV1Decoder` (library, all `pure`): `getTransactionType`, `isValidTransactionType`, `decodeCommonTxFields`,
`decodeReceiptFields` (→ `receiptStatus`, `receiptGasUsed`, `receiptLogs[]{address_, topics[], data}`,
`receiptLogsBloom`), `getLogsByEventSignature(ReceiptFields|LogEntry[], bytes32)`. Transaction types 0–4
(legacy, 2930, 1559, 4844, 7702). Encoding = SDK `EncodingVersion.V1` (`abiEncode(tx, receipt)` → `bytes[]` chunks).

ChainInfo precompile at `0x0000000000000000000000000000000000000fd3` (all `view`): `get_supported_chains()
→ (uint64 chainKey, uint64 chainId, bytes chainName, uint8 chainEncoding)[]`, `get_chain_by_key`,
`get_latest_attestation_height_and_hash(chainKey) → (height, hash, isAttestation, exists)`,
`get_attestation_genesis_height`, `get_attestation_bounds`, `is_height_attested`, checkpoint/digest lookups.

**Do not copy SDK method names into Solidity**: there is no `verifySingle`/`verifyBatch` in the native ABI.

## 3. Proof service contract (SDK 0.18.0 `proof-provider/service`)

| Item | Value |
| --- | --- |
| Paths | `GET /api/v1/proof-by-tx/{chainKey}/{txHash}`, `POST /api/v1/proof-batch-by-tx/{chainKey}` (body: `string[]`), `GET /api/v1/attested-height/{chainKey}` → `{ "attestedHeight": number }` |
| Single response | `ProofResult{success, data?: ContinuityResponse{chainKey, headerNumber, txIndex, txHash, txBytes, continuityProof{lowerEndpointDigest, roots[]}, merkleProof{root, siblings[{hash,isLeft}]}, cached, generatedAt}, error?}` |
| Timeouts | axios timeout default 10 s (SDK ctor arg); `waitUntilHeightAttested` polls attested-height every 15 s, 15 min timeout, + extra delay for load-balanced caches |
| Trust | The proof is **untrusted input**; only the native precompile result counts (R2-D02). `cached`/`generatedAt`/`txHash`/`txIndex` from the service are worker hints, not proven values (GPU-076 §proof-bound fields). |

Hostnames (CC3 testnet): environments table lists `proof-gen-api.cc3-testnet.creditcoin.network`; SDK docs
and README use `prover.cc3-testnet.creditcoin.network`. Both answered `/api/v1/attested-height/1` with the
same value at probe time. They are recorded as **primary + alternate** and probed separately; the manifest
does not declare them aliases.

## 4. Environments

### CC3 Testnet — `config/attestcoin/cc3-testnet.sepolia.json` — `environmentStatus=PROBED`

| Item | Docs (2026-09-13) | Probe (2026-09-13T22:14:25Z, finalized block 5,483,080) |
| --- | --- | --- |
| Destination chainId | — | `eth_chainId` = **102031** |
| Destination RPC (read-only allowlist) | `https://rpc.cc3-testnet.creditcoin.network` (SDK docs) | reachable |
| BlockProver / ChainInfo | `0x…0FD2` / `0x…0fd3` | `calculateTxIndex` vectors PASS; `verify(bogus)` reverts `Merkle proof validation failed`; bytecode 0 bytes (expected) |
| Decoder contract | `0x731c345d79Fb8BbDC541f9DF3b6317585F849F9f` | 9,598 bytes of code; keccak256 `0xb549c9d8eaf7d361192f8e363fe98717464441e2dd26e2b3bd1e0725df73a065` (pinned in manifest). Source equivalence to `EvmV1Decoder.sol` **not** verified (no verified-source link; GPU-082 may compile-and-compare) |
| Supported sources | Sepolia chainKey 1 (genesis 0), Ethereum mainnet chainKey 3 (genesis 0) | `get_supported_chains()` = `[(3, 1, "Ethereum", enc 1), (1, 11155111, "Sepolia ethereum", enc 1)]` |
| Latest attestation (chainKey 1) | — | height 11,698,710, `isAttestation=true`; proof service primary and alternate both `attestedHeight=11698710` (lag 0) |
| Source RPC (read-only allowlist) | — | `https://ethereum-sepolia-rpc.publicnode.com` → `eth_chainId` 11155111 |
| ASC dashboard | `https://dashboard.cc3-testnet.creditcoin.network/` | not probed |

Manifest hash: `sha256:2b0162d0c206f421138269a721c6338d8cf294d67dc644bb8b35ebb9bfbff6bb`. Probe report:
`test/fixtures/gpu/attestcoin/probe/cc3-testnet.sepolia.probe.json`.

### CC3 Mainnet — **no manifest yet** — `UNCONFIRMED`

Docs values (2026-09-13): Proof Builder API `https://proofbuilder.cc3-mainnet-usc.creditcoin.network/`,
decoder `0x9D094C9f22B10FCf842c2fC6A0981630A4F94B5C`, same precompile addresses, supported source Ethereum
Mainnet chainKey 1 (genesis 0), dashboard `https://dashboard.cc3-mainnet-usc.creditcoin.network/`. The
mainnet RPC URL is not stated on the environments page and was not invented; the official lib lists chain id
102030 as a Creditcoin chain id. A `PRODUCTION` manifest is created by GPU-062 only after a read-only probe
with a confirmed RPC (validator requires `supportConfirmedBy=PROBE` and a pinned decoder code hash).

### LOCAL_MOCK — `config/attestcoin/local-mock.json` — `UNCONFIRMED` by construction

Anvil chain ids 31337/31338, local URLs allowed **only** because `executionProfile=LOCAL_MOCK`,
`mock=true`, `verificationMethod=LOCAL_MOCK`. It can never be PROBED, never NATIVE_TESTNET/PRODUCTION, and
GPU-078's etched precompile double must be wired from this manifest only.

## 5. Compatibility items for downstream tickets

| # | Item | Owner |
| --- | --- | --- |
| E1 | Official Solidity files use `pragma ^0.8.28` (`EvmV1Decoder.sol`, full `INativeQueryVerifier.sol`, `ASCBase.sol`); repo `foundry.toml` pins `solc = 0.8.24` / `evm_version = london`. `contracts/gpu/` needs a Foundry profile with solc ≥ 0.8.28 (and an EVM version the Creditcoin runtime supports — confirm before choosing `cancun`+) or a compatible vendored copy; do not downgrade the official file. | GPU-029 / GPU-078 |
| E2 | Two `INativeQueryVerifier.sol` copies exist in the package (full vs lean). GPU-078 must import the **full** one (`write-ability/common/`) for `verifyAndEmit`/`calculateTxIndex`; the lean one only has view `verify`. | GPU-078 |
| E3 | Decoder can be linked as a library or inlined; the on-chain decoder address is informational for the app (the app should decode from the verified bytes with the pinned library, not `delegatecall` an external address it does not control) — decision recorded at GPU-078. | GPU-078 |
| E4 | `chainName` bytes decoding: SDK comment says name decoding "seems to be failing" in some versions; probe decodes UTF-8 bytes directly (`"Sepolia ethereum"`). Names are informational; identity is `(chainKey, chainId, encoding)`. | GPU-079 |
| E5 | Proof service `generatedAt`, `cached`, `txHash`, `txIndex` are unproven hints; proof-bound values are `chainKey`, `headerNumber`, `txBytes`, `merkleProof`, `continuityProof` and the on-chain `calculateTxIndex`. | GPU-076 / 079 |
| E6 | `ProofBuilder.getProof` swallows HTTP errors into `{success:false,error}`; worker must not treat `success:true` as verification. | GPU-079 |
| E7 | Writability contracts in `asc-contracts` (Outbox/Inbox/…) are out of scope (R2-D09). | — |

## 6. Commands (added by this ticket)

| Alias | Command | Network |
| --- | --- | --- |
| ASC-CHECK | `npm --prefix offchain/attestcoin run check` | none |
| ASC-TEST | `npm --prefix offchain/attestcoin run test -- --run` | none |
| ASC-PROBE | `npm --prefix offchain/attestcoin run probe -- --manifest <path> [--out <path>]` | read-only RPC/HTTP to the manifest's allowlisted hosts; refuses `mock` manifests without `--allow-mock`; exit 3 on FAIL/UNSUPPORTED |
| hash | `npm --prefix offchain/attestcoin run hash -- --manifest <path>` | none |

Install: `npm ci --prefix offchain/attestcoin` (Node ≥ 22; `package-lock.json` carries integrity for every dependency).
