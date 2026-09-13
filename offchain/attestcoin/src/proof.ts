/** Official SDK boundary: proof service output remains untrusted until app native consumption. */
import { proofProvider } from "@gluwa/usc-sdk";
import { JsonRpcProvider } from "ethers";
import { checkArtifacts } from "./artifacts";
import { Manifest, validateManifest } from "./manifest";

export interface ProofRequest {
  version: 1;
  txHash: string;
  manifestHash: string;
}

export interface ProofTransport {
  chainId(): Promise<number>;
  receipt(txHash: string): Promise<{ blockNumber: number; status: number | null } | null>;
  wait(height: number): Promise<void>;
  proof(txHash: string): Promise<proofProvider.ProofResult>;
}

/** The pinned SDK logs cache-wait messages to console.log; reserve stdout for the JSON protocol. */
export async function proofJson(m: Manifest, request: ProofRequest, injected?: ProofTransport): Promise<string> {
  const originalLog = console.log;
  const originalInfo = console.info;
  const originalDebug = console.debug;
  console.log = () => undefined;
  console.info = () => undefined;
  console.debug = () => undefined;
  try {
    return JSON.stringify(await fetchProof(m, request, injected));
  } finally {
    console.log = originalLog;
    console.info = originalInfo;
    console.debug = originalDebug;
  }
}

function transport(m: Manifest): ProofTransport {
  const rpc = new JsonRpcProvider(m.source.rpcUrls[0]);
  const builder = new proofProvider.service.ProofBuilder(m.source.chainKey, m.proofService.baseUrl, 15_000);
  return {
    chainId: async () => Number((await rpc.getNetwork()).chainId),
    receipt: (tx) => rpc.getTransactionReceipt(tx),
    wait: (height) => builder.waitUntilHeightAttested(m.source.chainKey, height, 1000, 5000, 0),
    proof: (tx) => builder.getProof(tx),
  };
}

export async function fetchProof(m: Manifest, request: ProofRequest, injected?: ProofTransport): Promise<Record<string, unknown>> {
  const base = { version: 1, manifestHash: m.manifestHash, txHash: request.txHash,
    executionProfile: m.executionProfile, verificationMethod: "ATTESTCOIN_NATIVE", nativeAccepted: false };
  const failure = (status: string, code: string) => ({ ...base, status, code });
  if (!validateManifest(m).ok || !checkArtifacts().ok || request.version !== 1 || request.manifestHash !== m.manifestHash) {
    return failure("INVALID", "MANIFEST_OR_ARTIFACT_BINDING");
  }
  if (m.mock || m.executionProfile === "LOCAL_MOCK" || m.environmentStatus === "UNSUPPORTED" || !m.source.rpcUrls.length) {
    return failure("UNSUPPORTED", "NATIVE_SOURCE_REQUIRED");
  }
  if (!/^0x[0-9a-f]{64}$/.test(request.txHash)) return failure("INVALID", "TRANSACTION_HASH");
  const t = injected ?? transport(m);
  try {
    if (await t.chainId() !== m.source.chainId) return failure("INVALID", "SOURCE_CHAIN_MISMATCH");
    const receipt = await t.receipt(request.txHash);
    if (!receipt) return failure("NOT_READY", "SOURCE_RECEIPT_PENDING");
    if (receipt.status !== 1) return failure("INVALID", "SOURCE_TRANSACTION_REVERTED");
    try { await t.wait(receipt.blockNumber); }
    catch { return failure("NOT_READY", "ATTESTATION_NOT_READY"); }
    const result = await t.proof(request.txHash);
    if (!result.success || !result.data) return failure("NOT_READY", "PROOF_NOT_READY");
    const p = result.data;
    const hash = (v: unknown) => typeof v === "string" && /^0x[0-9a-fA-F]{64}$/.test(v);
    if (!p.merkleProof || !p.continuityProof || !Array.isArray(p.merkleProof.siblings) ||
        !Array.isArray(p.continuityProof.roots) || !hash(p.txHash) ||
        typeof p.txBytes !== "string" || p.txBytes.length > 2_097_152 ||
        p.merkleProof.siblings.length > 64 || p.continuityProof.roots.length > 10_000 ||
        p.chainKey !== m.source.chainKey || p.txHash.toLowerCase() !== request.txHash || p.headerNumber !== receipt.blockNumber ||
        !Number.isSafeInteger(p.headerNumber) || p.headerNumber < 0 ||
        !Number.isSafeInteger(p.txIndex) || p.txIndex < 0 || !/^0x(?:[0-9a-fA-F]{2})+$/.test(p.txBytes) ||
        !hash(p.merkleProof.root) || !hash(p.continuityProof.lowerEndpointDigest) ||
        !p.continuityProof.roots.every(hash) || !p.merkleProof.siblings.every(s => s && hash(s.hash) && typeof s.isLeft === "boolean")) {
      return failure("INVALID", "PROOF_RESPONSE_BINDING");
    }
    return { ...base, status: "PROOF_READY", sdkVersion: m.sdk.version, encodingVersion: m.source.encoding,
      chainKey: p.chainKey, height: String(p.headerNumber), txIndex: p.txIndex, proof: {
        chainKey: String(p.chainKey), height: String(p.headerNumber), transaction: p.txBytes,
        root: p.merkleProof.root, siblings: p.merkleProof.siblings,
        lowerEndpointDigest: p.continuityProof.lowerEndpointDigest, continuityRoots: p.continuityProof.roots,
      } };
  } catch {
    // Do not leak credential-bearing URLs or remote response bodies into worker logs.
    return failure("NETWORK_ERROR", "OFFICIAL_SERVICE_UNAVAILABLE");
  }
}
