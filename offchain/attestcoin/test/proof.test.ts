import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { fetchProof, proofJson, ProofTransport } from "../src/proof";
import { Manifest } from "../src/manifest";

const manifest = (): Manifest => JSON.parse(readFileSync(path.resolve(__dirname, "../../../config/attestcoin/cc3-testnet.sepolia.json"), "utf8"));
const hash = "0x" + "ab".repeat(32);
const request = (m: Manifest) => ({ version: 1 as const, txHash: hash, manifestHash: m.manifestHash! });
const fake = (): ProofTransport => ({
  chainId: async () => 11155111,
  receipt: async () => ({ blockNumber: 100, status: 1 }),
  wait: async () => {},
  proof: async () => ({ success: true, data: { chainKey: 1, headerNumber: 100, txIndex: 0, txHash: hash,
    txBytes: "0x1234", merkleProof: { root: hash, siblings: [] }, continuityProof: { lowerEndpointDigest: hash, roots: [] },
    cached: true, generatedAt: new Date() } }),
});

describe("official SDK proof boundary", () => {
  it("keeps SDK cache-poll console output out of the JSON protocol and restores logging", async () => {
    const m = manifest();
    const debug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const before = console.log;
    const result = await proofJson(m, request(m), { ...fake(), wait: async () => {
      console.log("Height 11700014 not yet attested and in proof builder service cache. Retrying...");
      console.info("SDK status detail");
      console.debug("Height 11700014 not yet attested and in proof builder service cache ... Retrying...");
    } });
    expect(JSON.parse(result).status).toBe("PROOF_READY");
    expect(result).not.toContain("Retrying");
    expect(console.log).toBe(before);
    expect(debug).not.toHaveBeenCalled();
    debug.mockRestore();
  });
  it("only produces untrusted PROOF_READY; no native success flag", async () => {
    const m = manifest();
    const result = await fetchProof(m, request(m), fake());
    expect(result.status).toBe("PROOF_READY");
    expect(result.nativeAccepted).toBe(false);
    expect(result.height).toBe("100");
  });
  it("rejects manifest substitution before touching transport", async () => {
    const m = manifest();
    const f = fake();
    f.chainId = async () => { throw new Error("must not call"); };
    expect((await fetchProof(m, { ...request(m), manifestHash: "wrong" }, f)).status).toBe("INVALID");
  });
  it("rejects a source chain mismatch", async () => {
    const m = manifest();
    expect((await fetchProof(m, request(m), { ...fake(), chainId: async () => 1 })).code).toBe("SOURCE_CHAIN_MISMATCH");
  });
  it("waits for cache and preserves retryability", async () => {
    const m = manifest();
    const result = await fetchProof(m, request(m), { ...fake(), wait: async () => { throw new Error("cache lag"); } });
    expect(result.status).toBe("NOT_READY");
  });
  it("rejects reverted source transactions", async () => {
    const m = manifest();
    expect((await fetchProof(m, request(m), { ...fake(), receipt: async () => ({ blockNumber: 100, status: 0 }) })).status).toBe("INVALID");
  });
  it("rejects wrong proof height/hash and classifies network errors without leaking URLs", async () => {
    const m = manifest();
    const f = fake();
    const p = await f.proof(hash);
    p.data!.headerNumber = 99;
    expect((await fetchProof(m, request(m), { ...f, proof: async () => p })).code).toBe("PROOF_RESPONSE_BINDING");
    const result = await fetchProof(m, request(m), { ...f, proof: async () => { throw new Error("https://secret-token.example"); } });
    expect(result.status).toBe("NETWORK_ERROR");
    expect(JSON.stringify(result)).not.toContain("secret-token");
  });
});
