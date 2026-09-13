/** Stateful app ABI encoding in the pinned ethers/official SDK process. Never targets the verifier probe. */
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { Interface } from "ethers";
import { Manifest, validateManifest } from "./manifest";
import { checkArtifacts } from "./artifacts";

export function encodeSubmission(m: Manifest, input: Record<string, any>): Record<string, unknown> {
  const { artifact, plan } = input;
  if (!validateManifest(m).ok || !checkArtifacts().ok || m.mock || artifact.manifestHash !== m.manifestHash ||
      artifact.status !== "PROOF_READY" || artifact.nativeAccepted !== false) throw new Error("invalid native artifact binding");
  const contract = plan.purpose === "evidence.consume" ? "EvidenceBook" : plan.purpose === "receivables.ingest" ? "ReceivableBook" : null;
  if (!contract || !m.source.emitters.some(e => e.address.toLowerCase() === plan.expectedEmitter.toLowerCase())) {
    throw new Error("unregistered source emitter or application purpose");
  }
  const sourcePath = path.resolve(__dirname, "..", "abi", `${contract}.json`);
  const abiPath = existsSync(sourcePath) ? sourcePath : path.resolve(__dirname, "..", "..", "abi", `${contract}.json`);
  const iface = new Interface(JSON.parse(readFileSync(abiPath, "utf8")));
  const p = artifact.proof;
  const envelope = [p.chainKey, p.height, p.transaction, p.root, p.siblings, p.lowerEndpointDigest, p.continuityRoots];
  const calldata = iface.encodeFunctionData(plan.purpose === "evidence.consume" ? "consume" : "ingest",
    [plan.providerId, envelope, plan.expectedEmitter, plan.topic0s, plan.instructions]);
  return { version: 1, purpose: plan.purpose, manifestHash: m.manifestHash, calldata };
}
