/**
 * Pinned official Attestcoin (ex-USC) artifacts.
 *
 * Every entry below was taken from the actual npm tarballs on 2026-09-13/14 (see
 * docs/gpu/attestcoin/environment.md for provenance). `check` recomputes the hashes of the
 * installed files and fails if anything drifted, so a dependency bump can never silently change
 * the ABI, decoder, or interface the on-chain verifier is built against.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const req = createRequire(__filename);

export const PINNED_PACKAGES = {
  "@gluwa/usc-sdk": {
    version: "0.18.0",
    integrity:
      "sha512-iUEXPAp1gB/HDYkXad+StVJvs0Yz2ZIbzijc8SaBflGJ95hPnVahyY+tsP2PApswSQaX2uIBM7Cb0jpZ+KBzTQ==",
    tarballSha256: "b1f7ef611eb5658864686a7028907ed3d12e089091128e6c266281615a03d875",
    repository: "https://github.com/gluwa/cc-next-query-builder",
    license: "MIT",
  },
  "@gluwa/asc-contracts": {
    version: "0.2.1",
    tarballSha256: "b45fffaf30fe94a1b050800dfd8a67e6e5e9564afbb12ce0422f2c3cb4289dee",
    repository: "https://github.com/gluwa/asc-contracts",
    license: "MIT",
  },
  ethers: { version: "6.15.0" },
} as const;

/** Official files whose exact bytes are part of the verification contract. */
export const PINNED_FILES: ReadonlyArray<{ id: string; pkg: string; file: string; sha256: string; role: string }> = [
  {
    id: "blockProverAbi",
    pkg: "@gluwa/usc-sdk",
    file: "dist/block-prover/block_prover.json",
    sha256: "cf796a38fa5b2ebfab7d25755256139652755c71eed935675d88458244e0cd5c",
    role: "BlockProver precompile ABI (verify/verifyAndEmit single+batch, calculateTxIndex, TransactionVerified)",
  },
  {
    id: "chainInfoAbi",
    pkg: "@gluwa/usc-sdk",
    file: "dist/chain-info/chain_info.json",
    sha256: "1c93aab8f029bd0b25594753729e61c70dfa8f5d99b203745b77d6e7baa14f77",
    role: "ChainInfo precompile ABI (get_supported_chains, attestation queries)",
  },
  {
    id: "evmV1DecoderAbi",
    pkg: "@gluwa/usc-sdk",
    file: "dist/utils/evmV1DecoderAbi.json",
    sha256: "bd07dc76f8ab1505d6eec373da990de7fab624e878a206ed1a2618c4667c829a",
    role: "EvmV1Decoder ABI as shipped by the SDK",
  },
  {
    id: "evmV1DecoderSol",
    pkg: "@gluwa/asc-contracts",
    file: "contracts/common/EvmV1Decoder.sol",
    sha256: "2de1a8faf7b203c33a08db73e7a79e0523c4a84580c9c75ce209df0d5bf2e692",
    role: "Official decoder library source (pragma ^0.8.28)",
  },
  {
    id: "nativeQueryVerifierSol",
    pkg: "@gluwa/asc-contracts",
    file: "contracts/write-ability/common/INativeQueryVerifier.sol",
    sha256: "bc81982eb4070d3a5519346c868c73eff177b7c514ef2befae6cadfe9cddd1ed",
    role: "Full BlockProver interface + NativeQueryVerifierLib (pragma ^0.8.28)",
  },
  {
    id: "nativeQueryVerifierLeanSol",
    pkg: "@gluwa/asc-contracts",
    file: "contracts/write-ability/INativeQueryVerifier.sol",
    sha256: "330e2039911731e2bfede78c28b498f51bda5704a8634abb26325487fe0ba3e2",
    role: "Lean vendored interface: structs + view verify only (pragma ^0.8.20)",
  },
  {
    id: "ascBaseSol",
    pkg: "@gluwa/asc-contracts",
    file: "contracts/readability/ASCBase.sol",
    sha256: "ff24791a29b1b5477088ec2e36a4960768ec79178817458c6e77c2a4ce3b9f3c",
    role: "Official readability base contract (reference pattern, not deployed by us)",
  },
  {
    id: "blockProverTypesSol",
    pkg: "@gluwa/asc-contracts",
    file: "contracts/write-ability/common/BlockProverTypes.sol",
    sha256: "7f2f5aecf619566a154341c75481fc2a6b3e749e021070d59bc26112c8a47b43",
    role: "Proof struct semantics (isLeft = sibling on the left; continuity digest formula)",
  },
];

/** Function/event signatures the BlockProver ABI must expose (from the pinned JSON). */
export const EXPECTED_BLOCK_PROVER_SIGNATURES = [
  "calculateTxIndex((bytes32,(bytes32,bool)[]))",
  "verify(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))",
  "verify(uint64,uint64[],bytes[],(bytes32,(bytes32,bool)[])[],(bytes32,bytes32[]))",
  "verifyAndEmit(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))",
  "verifyAndEmit(uint64,uint64[],bytes[],(bytes32,(bytes32,bool)[])[],(bytes32,bytes32[]))",
  "event TransactionVerified(uint64,uint64,uint64)",
] as const;

export const EXPECTED_CHAIN_INFO_SIGNATURES = [
  "get_supported_chains()",
  "get_chain_by_key(uint64)",
  "get_latest_attestation_height_and_hash(uint64)",
  "get_attestation_genesis_height(uint64)",
  "get_attestation_bounds(uint64,uint64)",
  "is_height_attested(uint64,uint64)",
] as const;

/** Mutability facts confirmed from the pinned ABI; GPU-078 must not assume otherwise. */
export const BLOCK_PROVER_MUTABILITY = {
  verify: "view",
  verifyAndEmit: "nonpayable",
  calculateTxIndex: "view",
} as const;

export function sha256Hex(bytes: Buffer | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

export function resolvePackageRoot(pkg: string): string {
  // Resolve via a file every package ships instead of package.json (ethers restricts exports).
  const probeFile: Record<string, string> = {
    "@gluwa/usc-sdk": "@gluwa/usc-sdk/dist/index.js",
    "@gluwa/asc-contracts": "@gluwa/asc-contracts/contracts/readability/ASCBase.sol",
  };
  const entry = probeFile[pkg];
  if (!entry) throw new Error(`no resolver for package ${pkg}`);
  const resolved = req.resolve(entry, { paths: [path.resolve(__dirname, "..")] });
  const idx = resolved.lastIndexOf(`node_modules${path.sep}${pkg.replace("/", path.sep)}`);
  if (idx < 0) throw new Error(`cannot locate package root for ${pkg} from ${resolved}`);
  return resolved.slice(0, idx + `node_modules${path.sep}${pkg.replace("/", path.sep)}`.length);
}

export function pinnedFilePath(id: string): string {
  const f = PINNED_FILES.find((p) => p.id === id);
  if (!f) throw new Error(`unknown pinned file id ${id}`);
  return path.join(resolvePackageRoot(f.pkg), f.file);
}

export interface ArtifactCheckResult {
  ok: boolean;
  installedVersions: Record<string, string>;
  files: Array<{ id: string; file: string; expected: string; actual: string | null; ok: boolean }>;
  errors: string[];
}

export function installedVersion(pkg: string): string {
  if (pkg === "ethers") {
    return (req("ethers") as { version: string }).version.replace(/^v?/, "");
  }
  const root = resolvePackageRoot(pkg);
  return (JSON.parse(readFileSync(path.join(root, "package.json"), "utf8")) as { version: string }).version;
}

/** Recompute hashes of every pinned file and compare with the registry. Pure local check. */
export function checkArtifacts(): ArtifactCheckResult {
  const errors: string[] = [];
  const installedVersions: Record<string, string> = {};
  for (const [pkg, pin] of Object.entries(PINNED_PACKAGES)) {
    try {
      const v = installedVersion(pkg);
      installedVersions[pkg] = v;
      if (!v.startsWith(pin.version)) errors.push(`${pkg}: installed ${v} != pinned ${pin.version}`);
    } catch (e) {
      errors.push(`${pkg}: cannot read installed version: ${(e as Error).message}`);
    }
  }
  const files = PINNED_FILES.map((f) => {
    let actual: string | null = null;
    try {
      actual = sha256Hex(readFileSync(pinnedFilePath(f.id)));
    } catch (e) {
      errors.push(`${f.id}: cannot read ${f.file}: ${(e as Error).message}`);
    }
    const ok = actual === f.sha256;
    if (actual && !ok) errors.push(`${f.id}: sha256 drift ${f.file}: expected ${f.sha256} got ${actual}`);
    return { id: f.id, file: f.file, expected: f.sha256, actual, ok };
  });
  return { ok: errors.length === 0, installedVersions, files, errors };
}
