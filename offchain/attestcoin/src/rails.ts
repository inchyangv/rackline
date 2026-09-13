/**
 * Settlement rail manifest validation (GPU-008, `config/gpu/schema/settlement-rails-v1.schema.json`).
 *
 * A rail says where facts are proven (an Attestcoin manifest) and where money moves (source escrow →
 * conversion → settlement → Creditcoin destination). Rules enforced here, beyond the JSON shape:
 *   - the referenced Attestcoin manifest must exist, hash-match, and list the rail's source chain
 *     (chainKey/chainId/encoding) — otherwise the source is UNSUPPORTED (R2-D08);
 *   - PRODUCTION rails: no UNCONFIRMED/DISABLED legs or assets, no null addresses, no TEST_ONLY status,
 *     partnerSourceBinding=VERIFIED, and the Attestcoin manifest must itself be PRODUCTION and non-mock;
 *   - NATIVE_TESTNET rails may carry nulls/UNCONFIRMED but must be TEST_ONLY or DISABLED and never claim VERIFIED
 *     partner binding without a partner (that is GPU-004/005/009 evidence, not a config flag);
 *   - executionProfile must match the Attestcoin manifest's profile.
 * The validator never fills in values: `null` is the only honest unknown.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { type Manifest, type ValidationResult, computeManifestHash } from "./manifest";

export const RAIL_STATUSES = ["TEST_ONLY", "DISABLED", "PILOT_APPROVED"] as const;
export const LEG_STATUSES = ["UNCONFIRMED", "PROBED", "APPROVED", "DISABLED"] as const;
type LegStatus = (typeof LEG_STATUSES)[number];

export interface RailLeg {
  kind: string;
  status: LegStatus;
  counterparty: string | null;
  contract: string | null;
  feeModel: string | null;
  failureOwner: string | null;
  recoveryProcedure: string | null;
  limits?: Record<string, number | string | null>;
}

export interface RailAsset {
  symbol: string;
  address: string | null;
  decimals: number | null;
  issuerRef: string | null;
  status: LegStatus;
}

export interface RailManifest {
  schemaVersion: 1;
  railId: string;
  executionProfile: "LOCAL_MOCK" | "NATIVE_TESTNET" | "PRODUCTION";
  railStatus: (typeof RAIL_STATUSES)[number];
  partnerSourceBinding: "UNCONFIGURED" | "VERIFIED";
  providerSlug: string;
  evidence: { attestcoinManifestId: string; attestcoinManifestHash: string; requiredVerification: "ATTESTCOIN_NATIVE" };
  debtChain: { name: string; chainId: number; rpcUrls: string[]; explorerUrls: string[]; finality: "finalized" };
  sourceChain: {
    name: string;
    chainId: number;
    chainKey: number;
    encoding: 1;
    attestationGenesis: number | null;
    rpcUrls: string[];
    explorerUrls: string[];
    finality: "attestation";
    supportStatus: LegStatus;
  };
  assets: { sourceToken: RailAsset; loanToken: RailAsset };
  escrow: { contract: string; address: string | null; deploymentTx: string | null; codeHash: string | null; status: LegStatus };
  conversion: RailLeg;
  settlement: RailLeg;
  notes: string[];
}

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;
const HASH32 = /^0x[0-9a-fA-F]{64}$/;

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function checkLeg(name: string, leg: unknown, errors: string[]): void {
  if (!isObj(leg)) {
    errors.push(`${name}: must be an object`);
    return;
  }
  for (const k of ["kind", "status", "counterparty", "contract", "feeModel", "failureOwner", "recoveryProcedure"]) {
    if (!(k in leg)) errors.push(`${name}.${k}: missing`);
  }
  if (!LEG_STATUSES.includes(leg.status as LegStatus)) errors.push(`${name}.status: invalid`);
  if (leg.contract !== null && !(typeof leg.contract === "string" && ADDRESS.test(leg.contract))) {
    errors.push(`${name}.contract: must be an address or null`);
  }
}

function checkAsset(name: string, a: unknown, errors: string[]): void {
  if (!isObj(a)) {
    errors.push(`${name}: must be an object`);
    return;
  }
  if (typeof a.symbol !== "string" || a.symbol.length === 0) errors.push(`${name}.symbol: missing`);
  if (a.address !== null && !(typeof a.address === "string" && ADDRESS.test(a.address))) errors.push(`${name}.address: must be an address or null`);
  if (a.decimals !== null && !(Number.isInteger(a.decimals) && (a.decimals as number) >= 0 && (a.decimals as number) <= 36)) {
    errors.push(`${name}.decimals: 0..36 or null`);
  }
  if (!LEG_STATUSES.includes(a.status as LegStatus)) errors.push(`${name}.status: invalid`);
}

/** Structural + cross-manifest validation. `attestcoin` is the referenced Attestcoin manifest (already loaded). */
export function validateRail(rail: RailManifest, attestcoin: Manifest | null): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const r = rail as unknown as Record<string, unknown>;

  if (r.schemaVersion !== 1) errors.push("schemaVersion must be 1");
  if (typeof r.railId !== "string" || !/^[a-z0-9.-]+$/.test(r.railId)) errors.push("railId: invalid");
  if (!["LOCAL_MOCK", "NATIVE_TESTNET", "PRODUCTION"].includes(String(r.executionProfile))) errors.push("executionProfile: invalid");
  if (!RAIL_STATUSES.includes(r.railStatus as never)) errors.push("railStatus: invalid");
  if (!["UNCONFIGURED", "VERIFIED"].includes(String(r.partnerSourceBinding))) errors.push("partnerSourceBinding: invalid");
  if (!isObj(r.evidence) || r.evidence.requiredVerification !== "ATTESTCOIN_NATIVE") {
    errors.push("evidence.requiredVerification must be ATTESTCOIN_NATIVE");
  }
  if (!isObj(r.debtChain) || ![31337, 102030, 102031, 102032].includes(Number(r.debtChain.chainId))) {
    errors.push("debtChain.chainId must be a Creditcoin chain id (or 31337 for LOCAL_MOCK)");
  } else if (r.debtChain.finality !== "finalized") errors.push("debtChain.finality must be 'finalized'");
  if (!isObj(r.sourceChain)) errors.push("sourceChain: missing");
  else {
    if (r.sourceChain.encoding !== 1) errors.push("sourceChain.encoding must be 1");
    if (r.sourceChain.finality !== "attestation") errors.push("sourceChain.finality must be 'attestation'");
    if (!LEG_STATUSES.includes(r.sourceChain.supportStatus as LegStatus)) errors.push("sourceChain.supportStatus: invalid");
  }
  if (!isObj(r.assets)) errors.push("assets: missing");
  else {
    checkAsset("assets.sourceToken", r.assets.sourceToken, errors);
    checkAsset("assets.loanToken", r.assets.loanToken, errors);
  }
  if (!isObj(r.escrow)) errors.push("escrow: missing");
  else {
    if (r.escrow.address !== null && !(typeof r.escrow.address === "string" && ADDRESS.test(r.escrow.address))) errors.push("escrow.address: address or null");
    for (const k of ["deploymentTx", "codeHash"]) {
      const v = r.escrow[k];
      if (v !== null && !(typeof v === "string" && HASH32.test(v))) errors.push(`escrow.${k}: 32-byte hash or null`);
    }
    if (!LEG_STATUSES.includes(r.escrow.status as LegStatus)) errors.push("escrow.status: invalid");
  }
  checkLeg("conversion", r.conversion, errors);
  checkLeg("settlement", r.settlement, errors);
  if (!Array.isArray(r.notes)) errors.push("notes: must be an array");

  // ---- cross-check with the Attestcoin manifest (facts rail)
  if (!attestcoin) {
    errors.push(`evidence.attestcoinManifestId: manifest '${rail.evidence?.attestcoinManifestId}' not found under config/attestcoin`);
  } else {
    const expected = computeManifestHash(attestcoin);
    if (rail.evidence.attestcoinManifestHash !== expected) {
      errors.push(`evidence.attestcoinManifestHash mismatch: rail=${rail.evidence.attestcoinManifestHash} manifest=${expected}`);
    }
    if (attestcoin.executionProfile !== rail.executionProfile) {
      errors.push(`executionProfile ${rail.executionProfile} != attestcoin manifest ${attestcoin.executionProfile}`);
    }
    if (attestcoin.destination.chainId !== rail.debtChain.chainId) {
      errors.push(`debtChain.chainId ${rail.debtChain.chainId} != attestcoin destination ${attestcoin.destination.chainId}`);
    }
    const src = attestcoin.source;
    if (src.chainId !== rail.sourceChain.chainId || src.chainKey !== rail.sourceChain.chainKey || src.encoding !== rail.sourceChain.encoding) {
      errors.push(
        `UNSUPPORTED_SOURCE: rail source (chainId ${rail.sourceChain.chainId}, chainKey ${rail.sourceChain.chainKey}) is not the attestcoin manifest's supported source (chainId ${src.chainId}, chainKey ${src.chainKey})`,
      );
    }
    if (rail.executionProfile === "PRODUCTION" && (attestcoin.mock || attestcoin.environmentStatus !== "PROBED")) {
      errors.push("PRODUCTION rail requires a non-mock, PROBED attestcoin manifest");
    }
  }

  // ---- profile rules
  if (rail.executionProfile === "PRODUCTION") {
    if (rail.railStatus === "TEST_ONLY") errors.push("PRODUCTION rail cannot be TEST_ONLY");
    if (rail.partnerSourceBinding !== "VERIFIED") errors.push("PRODUCTION rail requires partnerSourceBinding=VERIFIED (GPU-004/005/009 evidence)");
    const legs: Array<[string, LegStatus]> = [
      ["sourceChain.supportStatus", rail.sourceChain.supportStatus],
      ["assets.sourceToken.status", rail.assets.sourceToken.status],
      ["assets.loanToken.status", rail.assets.loanToken.status],
      ["escrow.status", rail.escrow.status],
      ["conversion.status", rail.conversion.status],
      ["settlement.status", rail.settlement.status],
    ];
    for (const [name, st] of legs) {
      if (st === "UNCONFIRMED") errors.push(`${name}: UNCONFIRMED is not allowed on a PRODUCTION rail`);
    }
    for (const [name, v] of [
      ["assets.sourceToken.address", rail.assets.sourceToken.address],
      ["assets.loanToken.address", rail.assets.loanToken.address],
      ["escrow.address", rail.escrow.address],
      ["escrow.codeHash", rail.escrow.codeHash],
    ] as const) {
      if (v === null) errors.push(`${name}: null is not allowed on a PRODUCTION rail`);
    }
    if (rail.settlement.status === "DISABLED") errors.push("settlement: a PRODUCTION rail needs an enabled settlement leg");
  } else {
    if (rail.railStatus === "PILOT_APPROVED") errors.push("only PRODUCTION rails can be PILOT_APPROVED");
    if (rail.partnerSourceBinding === "VERIFIED") errors.push("partnerSourceBinding=VERIFIED needs real partner evidence; not a test-profile flag");
    if (rail.escrow.address === null) warnings.push("escrow.address null: deploy under GPU-080 approval");
  }
  for (const u of [...rail.debtChain.rpcUrls, ...rail.sourceChain.rpcUrls]) {
    if (rail.executionProfile !== "LOCAL_MOCK" && !u.startsWith("https://")) errors.push(`rpc url must be https in ${rail.executionProfile}: ${u}`);
  }
  return { ok: errors.length === 0, errors, warnings };
}

export function loadRail(p: string): RailManifest {
  return JSON.parse(readFileSync(p, "utf8")) as RailManifest;
}

export function railManifestDir(repoRoot: string): string {
  return path.join(repoRoot, "config", "gpu", "rails");
}
