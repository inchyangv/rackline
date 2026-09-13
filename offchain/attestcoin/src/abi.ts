/**
 * Loads the pinned official ABIs and exposes canonical signature sets so tests and the probe
 * can assert the interface we build against is exactly the one the SDK ships.
 */
import { readFileSync } from "node:fs";
import { Interface, type InterfaceAbi } from "ethers";
import { pinnedFilePath, sha256Hex } from "./artifacts";

export interface LoadedAbi {
  id: string;
  sha256: string;
  abi: InterfaceAbi;
  iface: Interface;
  signatures: string[];
}

function unwrap(json: unknown): InterfaceAbi {
  if (Array.isArray(json)) return json as InterfaceAbi;
  if (json && typeof json === "object" && Array.isArray((json as { abi?: unknown }).abi)) {
    return (json as { abi: InterfaceAbi }).abi;
  }
  throw new Error("unrecognised ABI JSON shape");
}

export function loadPinnedAbi(id: "blockProverAbi" | "chainInfoAbi" | "evmV1DecoderAbi"): LoadedAbi {
  const raw = readFileSync(pinnedFilePath(id));
  const abi = unwrap(JSON.parse(raw.toString("utf8")));
  const iface = new Interface(abi);
  const signatures: string[] = [];
  iface.forEachFunction((f) => signatures.push(f.format("sighash")));
  iface.forEachEvent((e) => signatures.push(`event ${e.format("sighash")}`));
  signatures.sort();
  return { id, sha256: sha256Hex(raw), abi, iface, signatures };
}

/** Stable hash of the signature set (independent of JSON whitespace/field order). */
export function signatureSetHash(signatures: readonly string[]): string {
  return sha256Hex([...signatures].sort().join("\n"));
}

export function functionMutability(loaded: LoadedAbi, name: string): string[] {
  const out: string[] = [];
  loaded.iface.forEachFunction((f) => {
    if (f.name === name) out.push(f.stateMutability);
  });
  return out;
}
