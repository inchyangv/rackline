import { describe, expect, it } from "vitest";
import { functionMutability, loadPinnedAbi, signatureSetHash } from "../src/abi";
import {
  BLOCK_PROVER_MUTABILITY,
  EXPECTED_BLOCK_PROVER_SIGNATURES,
  EXPECTED_CHAIN_INFO_SIGNATURES,
  PINNED_FILES,
  PINNED_PACKAGES,
  checkArtifacts,
  installedVersion,
} from "../src/artifacts";

describe("pinned official artifacts", () => {
  it("installed package versions equal the pins", () => {
    for (const [pkg, pin] of Object.entries(PINNED_PACKAGES)) {
      expect(installedVersion(pkg), pkg).toBe(pin.version);
    }
  });

  it("every pinned file hashes to the recorded sha256 (no silent ABI/decoder drift)", () => {
    const r = checkArtifacts();
    expect(r.errors).toEqual([]);
    expect(r.ok).toBe(true);
    expect(r.files.length).toBe(PINNED_FILES.length);
    for (const f of r.files) expect(f.actual, f.id).toBe(f.expected);
  });

  it("BlockProver ABI exposes exactly the documented single/batch verify, verifyAndEmit, calculateTxIndex and event", () => {
    const bp = loadPinnedAbi("blockProverAbi");
    for (const s of EXPECTED_BLOCK_PROVER_SIGNATURES) expect(bp.signatures, s).toContain(s);
    expect(bp.signatures.length).toBe(EXPECTED_BLOCK_PROVER_SIGNATURES.length);
    expect(signatureSetHash(bp.signatures)).toMatch(/^[0-9a-f]{64}$/);
  });

  it("BlockProver mutability: verify is view, verifyAndEmit is nonpayable (SDK verifySingle = staticCall verify)", () => {
    const bp = loadPinnedAbi("blockProverAbi");
    for (const [name, expected] of Object.entries(BLOCK_PROVER_MUTABILITY)) {
      const muts = new Set(functionMutability(bp, name));
      expect([...muts], name).toEqual([expected]);
    }
    // The SDK method name must not leak into Solidity: there is no `verifySingle` in the native ABI.
    expect(functionMutability(bp, "verifySingle")).toEqual([]);
  });

  it("ChainInfo ABI exposes the supported-chain and attestation queries the probe relies on", () => {
    const ci = loadPinnedAbi("chainInfoAbi");
    for (const s of EXPECTED_CHAIN_INFO_SIGNATURES) expect(ci.signatures, s).toContain(s);
    const sc = ci.iface.getFunction("get_supported_chains");
    expect(sc?.outputs[0]?.baseType).toBe("array");
    expect(sc?.outputs[0]?.arrayChildren?.components?.map((c) => `${c.name}:${c.type}`)).toEqual([
      "chainKey:uint64",
      "chainId:uint64",
      "chainName:bytes",
      "chainEncoding:uint8",
    ]);
  });

  it("EvmV1Decoder ABI (SDK copy) carries the receipt/log helpers the verifier will use", () => {
    const d = loadPinnedAbi("evmV1DecoderAbi");
    for (const s of [
      "decodeReceiptFields(bytes)",
      "decodeCommonTxFields(bytes)",
      "getTransactionType(bytes)",
      "isValidTransactionType(uint8)",
    ]) {
      expect(d.signatures, s).toContain(s);
    }
    expect(d.signatures.filter((s) => s.startsWith("getLogsByEventSignature(")).length).toBe(2);
    d.iface.forEachFunction((f) => expect(f.stateMutability, f.name).toBe("pure"));
  });
});
