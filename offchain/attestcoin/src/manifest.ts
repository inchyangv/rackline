/**
 * Environment manifest: the single source of truth for "which official Attestcoin deployment,
 * which source chain/chainKey/encoding, which pinned SDK/ABI/decoder" a verifier build and a
 * proof worker are bound to. Validation is fail-closed: any unknown, mock, or mismatching value
 * in a native/production profile is rejected with an explicit reason.
 *
 * Nothing in a manifest is "live-verified" by itself. `environmentStatus` records what the
 * read-only probe (probe.ts) confirmed; `nativeStatus` for actual proofs is owned by GPU-078/080.
 */
import { createHash } from "node:crypto";
import { getAddress, isAddress } from "ethers";

export const EXECUTION_PROFILES = ["LOCAL_MOCK", "NATIVE_TESTNET", "PRODUCTION"] as const;
export type ExecutionProfile = (typeof EXECUTION_PROFILES)[number];

export const VERIFICATION_METHODS = ["ATTESTCOIN_NATIVE", "LOCAL_MOCK"] as const;
export type VerificationMethod = (typeof VERIFICATION_METHODS)[number];

export const ENVIRONMENT_STATUSES = ["UNCONFIRMED", "PROBED", "UNSUPPORTED"] as const;
export type EnvironmentStatus = (typeof ENVIRONMENT_STATUSES)[number];

/** Official constants (from @gluwa/usc-sdk 0.18.0 and @gluwa/asc-contracts 0.2.1). */
export const OFFICIAL = {
  BLOCK_PROVER_PRECOMPILE: "0x0000000000000000000000000000000000000FD2",
  CHAIN_INFO_PRECOMPILE: "0x0000000000000000000000000000000000000fd3",
  /** NativeQueryVerifierLib.isCreditcoinChainId: 102030 (mainnet), 102031 (testnet), 102032 (devnet). */
  CREDITCOIN_CHAIN_IDS: { CC3_MAINNET: 102030, CC3_TESTNET: 102031, CC3_DEVNET: 102032 },
  /** SDK EncodingVersion.V1 — the only encoding the pinned SDK/decoder implement. */
  ENCODING_V1: 1,
  PROOF_PATHS: {
    proofByTx: "/api/v1/proof-by-tx",
    proofBatchByTx: "/api/v1/proof-batch-by-tx",
    attestedHeight: "/api/v1/attested-height",
  },
} as const;

export interface DestinationSpec {
  name: string;
  chainId: number;
  /** Allowlisted read-only RPC URLs (no credentials; a URL with a query string is rejected). */
  rpcUrls: string[];
  blockProver: { address: string };
  chainInfo: { address: string };
  decoder: {
    /** Official on-chain decoder address from the environments table, or null when unknown. */
    address: string | null;
    /** keccak256 of deployed runtime code observed by the probe; null until probed. */
    codeKeccak256: string | null;
    sourcePackage: string;
    sourceFile: string;
    sourceSha256: string;
  };
}

export interface SourceSpec {
  name: string;
  chainId: number;
  chainKey: number;
  encoding: number;
  genesisBlock: number;
  /** ISO timestamp of the last time official support was confirmed (docs or probe). */
  supportConfirmedAt: string | null;
  supportConfirmedBy: "DOCS" | "PROBE" | null;
  /** Allowlisted read-only RPC URLs for the source chain. */
  rpcUrls: string[];
  /** Registered emitters/tokens are owned by GPU-077/080; empty until then. */
  emitters: Array<{ address: string; kind: string; deploymentBlock: number | null; note: string }>;
  tokens: Array<{ address: string; symbol: string; decimals: number }>;
}

export interface ProofServiceSpec {
  baseUrl: string;
  /** Other hostnames documented for the same environment; probed separately, never assumed aliases. */
  alternateBaseUrls: string[];
  paths: { proofByTx: string; proofBatchByTx: string; attestedHeight: string };
  responseSchema: string;
}

export interface Manifest {
  manifestVersion: 1;
  manifestId: string;
  executionProfile: ExecutionProfile;
  requiredVerification: "ATTESTCOIN_NATIVE";
  verificationMethod: VerificationMethod;
  environmentStatus: EnvironmentStatus;
  mock: boolean;
  destination: DestinationSpec;
  source: SourceSpec;
  proofService: ProofServiceSpec;
  sdk: { package: string; version: string; integrity: string; abiSha256: Record<string, string> };
  contracts: { package: string; version: string; files: Record<string, string> };
  /** Our own app deployment block on the destination; null until GPU-080/062. */
  deploymentBlock: number | null;
  /** Secret references only (env var names). Values must never appear in a manifest. */
  secretRefs: Record<string, string>;
  notes: string[];
  manifestHash: string | null;
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

function canonicalize(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalize(obj[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** sha256 over canonical JSON of the manifest without `manifestHash`. */
export function computeManifestHash(m: Manifest): string {
  const { manifestHash: _omit, ...rest } = m;
  void _omit;
  return "sha256:" + createHash("sha256").update(canonicalize(rest)).digest("hex");
}

function isHttpsUrl(u: string): boolean {
  try {
    const p = new URL(u);
    return p.protocol === "https:" && p.search === "" && p.username === "" && p.password === "";
  } catch {
    return false;
  }
}

function isLocalUrl(u: string): boolean {
  try {
    const h = new URL(u).hostname;
    return h === "localhost" || h === "127.0.0.1" || h === "::1" || h.endsWith(".local");
  } catch {
    return true;
  }
}

function sameAddress(a: string, b: string): boolean {
  return isAddress(a) && isAddress(b) && getAddress(a) === getAddress(b);
}

const SHA256_RE = /^[0-9a-f]{64}$/;

/**
 * Validate a manifest. Native/production profiles reject: mock flags, non-official precompile
 * addresses, local RPCs, unsupported encoding, wrong destination chain id, missing pins, and a
 * stale manifestHash. LOCAL_MOCK must declare itself as mock and can never claim PROBED status.
 */
export function validateManifest(m: Manifest): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const native = m.executionProfile === "NATIVE_TESTNET" || m.executionProfile === "PRODUCTION";

  if (m.manifestVersion !== 1) errors.push(`manifestVersion must be 1, got ${String(m.manifestVersion)}`);
  if (!m.manifestId || !/^[a-z0-9][a-z0-9.-]*$/.test(m.manifestId)) errors.push("manifestId must be kebab/dot-case");
  if (!EXECUTION_PROFILES.includes(m.executionProfile)) errors.push(`unknown executionProfile ${String(m.executionProfile)}`);
  if (m.requiredVerification !== "ATTESTCOIN_NATIVE") errors.push("requiredVerification must be ATTESTCOIN_NATIVE (R2-D02)");
  if (!VERIFICATION_METHODS.includes(m.verificationMethod)) errors.push(`unknown verificationMethod ${String(m.verificationMethod)}`);
  if (!ENVIRONMENT_STATUSES.includes(m.environmentStatus)) errors.push(`unknown environmentStatus ${String(m.environmentStatus)}`);

  // Profile ↔ mock ↔ method coupling (R2-D03/D12).
  if (native) {
    if (m.mock) errors.push(`${m.executionProfile} manifest cannot set mock=true`);
    if (m.verificationMethod !== "ATTESTCOIN_NATIVE") errors.push(`${m.executionProfile} requires verificationMethod=ATTESTCOIN_NATIVE, got ${m.verificationMethod}`);
  } else {
    if (!m.mock) errors.push("LOCAL_MOCK manifest must set mock=true explicitly");
    if (m.verificationMethod !== "LOCAL_MOCK") errors.push("LOCAL_MOCK manifest must set verificationMethod=LOCAL_MOCK");
    if (m.environmentStatus === "PROBED") errors.push("LOCAL_MOCK manifest cannot claim environmentStatus=PROBED");
  }

  // Destination.
  const d = m.destination;
  if (!d) {
    errors.push("destination missing");
  } else {
    if (!Number.isInteger(d.chainId) || d.chainId <= 0) errors.push("destination.chainId must be a positive integer");
    if (m.executionProfile === "NATIVE_TESTNET" && d.chainId !== OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_TESTNET)
      errors.push(`NATIVE_TESTNET destination.chainId must be ${OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_TESTNET} (CC3 testnet), got ${d.chainId}`);
    if (m.executionProfile === "PRODUCTION" && d.chainId !== OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_MAINNET)
      errors.push(`PRODUCTION destination.chainId must be ${OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_MAINNET} (CC3 mainnet), got ${d.chainId}`);
    if (!Array.isArray(d.rpcUrls) || d.rpcUrls.length === 0) errors.push("destination.rpcUrls must list at least one URL");
    for (const u of d.rpcUrls ?? []) {
      if (native && !isHttpsUrl(u)) errors.push(`destination rpc must be https without credentials/query: ${redactUrl(u)}`);
      if (native && isLocalUrl(u)) errors.push(`destination rpc must not be local in ${m.executionProfile}: ${redactUrl(u)}`);
    }
    if (!isAddress(d.blockProver?.address ?? "")) errors.push("destination.blockProver.address invalid");
    else if (native && !sameAddress(d.blockProver.address, OFFICIAL.BLOCK_PROVER_PRECOMPILE))
      errors.push(`blockProver must be the official precompile ${OFFICIAL.BLOCK_PROVER_PRECOMPILE} in ${m.executionProfile} (no alternative verifier, R2-D03)`);
    if (!isAddress(d.chainInfo?.address ?? "")) errors.push("destination.chainInfo.address invalid");
    else if (native && !sameAddress(d.chainInfo.address, OFFICIAL.CHAIN_INFO_PRECOMPILE))
      errors.push(`chainInfo must be the official precompile ${OFFICIAL.CHAIN_INFO_PRECOMPILE} in ${m.executionProfile}`);
    if (d.decoder) {
      if (d.decoder.address !== null && !isAddress(d.decoder.address)) errors.push("destination.decoder.address invalid");
      if (native && d.decoder.address === null) errors.push("native profile requires the official decoder address");
      if (d.decoder.codeKeccak256 !== null && !/^0x[0-9a-f]{64}$/.test(d.decoder.codeKeccak256))
        errors.push("destination.decoder.codeKeccak256 must be 0x-prefixed 32-byte hex or null");
      if (!SHA256_RE.test(d.decoder.sourceSha256 ?? "")) errors.push("destination.decoder.sourceSha256 must be a sha256 hex");
      if (m.executionProfile === "PRODUCTION" && d.decoder.codeKeccak256 === null)
        errors.push("PRODUCTION requires a probed decoder codeKeccak256");
    } else {
      errors.push("destination.decoder missing");
    }
  }

  // Source.
  const s = m.source;
  if (!s) {
    errors.push("source missing");
  } else {
    if (!Number.isInteger(s.chainId) || s.chainId <= 0) errors.push("source.chainId must be a positive integer");
    if (!Number.isInteger(s.chainKey) || s.chainKey <= 0) errors.push("source.chainKey must be a positive integer (Creditcoin-internal key, not the EVM chainId)");
    if (s.encoding !== OFFICIAL.ENCODING_V1) errors.push(`source.encoding must be ${OFFICIAL.ENCODING_V1} (SDK EncodingVersion.V1); got ${String(s.encoding)}`);
    if (!Number.isInteger(s.genesisBlock) || s.genesisBlock < 0) errors.push("source.genesisBlock must be a non-negative integer");
    if (native && (!s.supportConfirmedAt || !s.supportConfirmedBy)) errors.push("native profile requires source.supportConfirmedAt/By (DOCS or PROBE)");
    if (m.executionProfile === "PRODUCTION" && s.supportConfirmedBy !== "PROBE") errors.push("PRODUCTION requires source support confirmed by PROBE");
    if (m.environmentStatus === "PROBED" && s.supportConfirmedBy !== "PROBE") errors.push("environmentStatus=PROBED requires source.supportConfirmedBy=PROBE");
    for (const u of s.rpcUrls ?? []) {
      if (native && !isHttpsUrl(u)) errors.push(`source rpc must be https without credentials/query: ${redactUrl(u)}`);
      if (native && isLocalUrl(u)) errors.push(`source rpc must not be local in ${m.executionProfile}: ${redactUrl(u)}`);
    }
    for (const e of s.emitters ?? []) {
      if (!isAddress(e.address)) errors.push(`source.emitters: invalid address ${e.address}`);
    }
    for (const t of s.tokens ?? []) {
      if (!isAddress(t.address)) errors.push(`source.tokens: invalid address ${t.address}`);
      if (!Number.isInteger(t.decimals) || t.decimals < 0 || t.decimals > 36) errors.push(`source.tokens: bad decimals for ${t.symbol}`);
    }
    if (native && s.chainId === d?.chainId) errors.push("source and destination chain ids must differ");
  }

  // Proof service.
  const p = m.proofService;
  if (!p) {
    errors.push("proofService missing");
  } else {
    if (native && !isHttpsUrl(p.baseUrl)) errors.push(`proofService.baseUrl must be https without credentials/query: ${redactUrl(p.baseUrl)}`);
    if (native && isLocalUrl(p.baseUrl)) errors.push("proofService.baseUrl must not be local in native profiles");
    for (const [k, v] of Object.entries(OFFICIAL.PROOF_PATHS)) {
      if (p.paths?.[k as keyof typeof OFFICIAL.PROOF_PATHS] !== v) errors.push(`proofService.paths.${k} must be ${v} (pinned SDK contract)`);
    }
    for (const alt of p.alternateBaseUrls ?? []) {
      if (native && !isHttpsUrl(alt)) errors.push(`proofService.alternateBaseUrls entry must be https: ${redactUrl(alt)}`);
    }
  }

  // Pins.
  if (!m.sdk || m.sdk.package !== "@gluwa/usc-sdk") errors.push("sdk.package must be @gluwa/usc-sdk");
  if (!m.sdk?.version) errors.push("sdk.version missing");
  if (!m.sdk?.integrity?.startsWith("sha512-")) errors.push("sdk.integrity must be the npm sha512 integrity string");
  for (const [k, v] of Object.entries(m.sdk?.abiSha256 ?? {})) if (!SHA256_RE.test(v)) errors.push(`sdk.abiSha256.${k} not a sha256`);
  if (!m.contracts || m.contracts.package !== "@gluwa/asc-contracts") errors.push("contracts.package must be @gluwa/asc-contracts");
  for (const [k, v] of Object.entries(m.contracts?.files ?? {})) if (!SHA256_RE.test(v)) errors.push(`contracts.files.${k} not a sha256`);

  // Secrets: reference names only.
  for (const [k, v] of Object.entries(m.secretRefs ?? {})) {
    if (!/^[A-Z][A-Z0-9_]*$/.test(v)) errors.push(`secretRefs.${k} must be an ENV VAR NAME, not a value`);
  }
  const serialized = JSON.stringify(m);
  if (/0x[0-9a-fA-F]{64}/.test(serialized.replace(/"codeKeccak256":"0x[0-9a-f]{64}"/g, "").replace(/"manifestHash":"sha256:[0-9a-f]{64}"/g, "")))
    errors.push("manifest contains a 32-byte hex value outside codeKeccak256/manifestHash (possible private key)");

  // Hash.
  if (m.manifestHash !== null) {
    const expected = computeManifestHash(m);
    if (m.manifestHash !== expected) errors.push(`manifestHash stale: expected ${expected}`);
  } else if (native) {
    warnings.push("manifestHash is null; compute and store it before use");
  }

  if (m.deploymentBlock !== null && (!Number.isInteger(m.deploymentBlock) || m.deploymentBlock < 0)) errors.push("deploymentBlock must be null or a non-negative integer");

  return { ok: errors.length === 0, errors, warnings };
}

/** Print only scheme+host so logs never carry API keys embedded in URL paths or queries. */
export function redactUrl(u: string): string {
  try {
    const p = new URL(u);
    return `${p.protocol}//${p.host}`;
  } catch {
    return "<invalid-url>";
  }
}
