import { readFileSync } from "node:fs";
import path from "node:path";
import { AbiCoder, Interface, keccak256 } from "ethers";
import { describe, expect, it } from "vitest";
import { loadPinnedAbi } from "../src/abi";
import { type Manifest, computeManifestHash } from "../src/manifest";
import { type CallResult, type ProbeTransport, probeManifest } from "../src/probe";

const CONFIG_DIR = path.resolve(__dirname, "..", "..", "..", "config", "attestcoin");
const ZERO32 = "0x" + "00".repeat(32);
const SAMPLE_HASH = "0x" + "9e".repeat(32);

function manifest(): Manifest {
  return JSON.parse(readFileSync(path.join(CONFIG_DIR, "cc3-testnet.sepolia.json"), "utf8")) as Manifest;
}

interface FakeChainState {
  destChainId: number;
  sourceChainId: number;
  supported: Array<[number, number, string, number]>; // chainKey, chainId, name, encoding
  latest: { height: number; exists: boolean };
  genesis: number;
  decoderCode: string;
  /** what verify() does with a bogus proof */
  verifyBehaviour: "revert" | "true" | "false";
  serviceHeights: Record<string, number | "http500" | "badbody">;
}

function encodeError(reason: string): string {
  return "0x08c379a0" + AbiCoder.defaultAbiCoder().encode(["string"], [reason]).slice(2);
}

/** Simulates the official precompiles + decoder + proof service from a small state object. */
function fakeTransport(state: FakeChainState, m: Manifest): ProbeTransport {
  const ci: Interface = loadPinnedAbi("chainInfoAbi").iface;
  const bp: Interface = loadPinnedAbi("blockProverAbi").iface;
  const isDest = (url: string) => m.destination.rpcUrls.includes(url);
  return {
    async ethChainId(url) {
      if (isDest(url)) return state.destChainId;
      if (m.source.rpcUrls.includes(url)) return state.sourceChainId;
      throw new Error("unknown rpc");
    },
    async ethBlockNumber() {
      return 5_483_040;
    },
    async ethCall(_url, to, data): Promise<CallResult> {
      if (to.toLowerCase() === m.destination.chainInfo.address.toLowerCase()) {
        const fn = ci.getFunction(data.slice(0, 10));
        if (!fn) return { ok: false, error: "unknown selector", revertReason: null };
        if (fn.name === "get_supported_chains") {
          const rows = state.supported.map(([k, id, name, enc]) => [k, id, "0x" + Buffer.from(name).toString("hex"), enc]);
          return { ok: true, data: ci.encodeFunctionResult(fn, [rows]) };
        }
        if (fn.name === "get_latest_attestation_height_and_hash") {
          return { ok: true, data: ci.encodeFunctionResult(fn, [[state.latest.height, SAMPLE_HASH, true, state.latest.exists]]) };
        }
        if (fn.name === "get_attestation_genesis_height") {
          return { ok: true, data: ci.encodeFunctionResult(fn, [state.genesis]) };
        }
        return { ok: false, error: "unsupported in fake", revertReason: null };
      }
      if (to.toLowerCase() === m.destination.blockProver.address.toLowerCase()) {
        const fn = bp.getFunction(data.slice(0, 10));
        if (!fn) return { ok: false, error: "unknown selector", revertReason: null };
        if (fn.name === "calculateTxIndex") {
          const [proof] = bp.decodeFunctionData(fn, data) as unknown as [{ siblings: Array<{ isLeft: boolean }> }];
          // Official semantics (BlockProverTypes): isLeft ⇒ current node is the right child ⇒ bit set.
          let idx = 0;
          proof.siblings.forEach((s, i) => {
            if (s.isLeft) idx |= 1 << i;
          });
          return { ok: true, data: bp.encodeFunctionResult(fn, [idx]) };
        }
        if (fn.name === "verify") {
          if (state.verifyBehaviour === "revert") {
            return { ok: false, error: "execution reverted", revertReason: "Merkle proof validation failed" };
          }
          return { ok: true, data: bp.encodeFunctionResult(fn, [state.verifyBehaviour === "true"]) };
        }
        return { ok: false, error: "unsupported in fake", revertReason: null };
      }
      return { ok: false, error: "unknown target", revertReason: null };
    },
    async ethGetCode(_url, address) {
      if (m.destination.decoder.address && address.toLowerCase() === m.destination.decoder.address.toLowerCase()) return state.decoderCode;
      return "0x";
    },
    async httpGetJson(url) {
      const host = new URL(url).host;
      const v = state.serviceHeights[host];
      if (v === undefined) throw new Error(`fake: no route for ${host}`);
      if (v === "http500") return { status: 500, body: { error: "boom" } };
      if (v === "badbody") return { status: 200, body: { attestedHeight: "11698660" } };
      return { status: 200, body: { attestedHeight: v } };
    },
  };
}

function healthy(m: Manifest): FakeChainState {
  return {
    destChainId: m.destination.chainId,
    sourceChainId: m.source.chainId,
    supported: [
      [3, 1, "Ethereum", 1],
      [1, 11155111, "Sepolia ethereum", 1],
    ],
    latest: { height: 11_698_660, exists: true },
    genesis: 0,
    decoderCode: "0x6080604052",
    verifyBehaviour: "revert",
    serviceHeights: Object.fromEntries([m.proofService.baseUrl, ...m.proofService.alternateBaseUrls].map((u) => [new URL(u).host, 11_698_660])),
  };
}

const NOW = () => new Date("2026-09-14T00:00:00Z");

describe("probeManifest (offline fake transport)", () => {
  it("healthy environment → PROBED with no FAIL; hostnames only in output", async () => {
    const m = manifest();
    m.destination.decoder.codeKeccak256 = keccak256("0x6080604052");
    m.manifestHash = computeManifestHash(m);
    const r = await probeManifest(m, { transport: fakeTransport(healthy(m), m), now: NOW });
    expect(r.environmentStatus).toBe("PROBED");
    expect(r.summary.fail).toBe(0);
    expect(r.checks.find((c) => c.id === "chainInfo.sourceSupported")?.status).toBe("PASS");
    expect(r.checks.filter((c) => c.id === "precompile.calculateTxIndex").every((c) => c.status === "PASS")).toBe(true);
    expect(r.checks.find((c) => c.id === "precompile.rejectsInvalidProof")?.detail).toMatch(/Merkle proof validation failed/);
    expect(r.checks.filter((c) => c.id === "proofService.attestedHeight").length).toBe(1 + m.proofService.alternateBaseUrls.length);
    expect(r.checks.find((c) => c.id === "decoder.code")?.detail).toMatch(/matches manifest/);
    const text = JSON.stringify(r);
    for (const u of [...m.destination.rpcUrls, ...m.source.rpcUrls, m.proofService.baseUrl]) {
      const p = new URL(u);
      if (p.pathname !== "/") expect(text).not.toContain(p.pathname);
    }
    expect(r.probedAt).toBe("2026-09-14T00:00:00.000Z");
  });

  it("destination chain id mismatch → FAIL / UNCONFIRMED", async () => {
    const m = manifest();
    const s = healthy(m);
    s.destChainId = 102030;
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    expect(r.checks.find((c) => c.id === "destination.chainId")?.status).toBe("FAIL");
    expect(r.environmentStatus).toBe("UNCONFIRMED");
  });

  it("chainKey missing from the official supported table → UNSUPPORTED", async () => {
    const m = manifest();
    const s = healthy(m);
    s.supported = [[3, 1, "Ethereum", 1]];
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    expect(r.environmentStatus).toBe("UNSUPPORTED");
    expect(r.checks.find((c) => c.id === "chainInfo.sourceSupported")?.detail).toMatch(/UNSUPPORTED_SOURCE/);
  });

  it("chainKey present but chainId or encoding differs from manifest → UNSUPPORTED", async () => {
    const m = manifest();
    const s = healthy(m);
    s.supported = [
      [3, 1, "Ethereum", 1],
      [1, 17000, "Holesky", 1],
    ];
    expect((await probeManifest(m, { transport: fakeTransport(s, m) })).environmentStatus).toBe("UNSUPPORTED");
    const s2 = healthy(m);
    s2.supported = [
      [3, 1, "Ethereum", 1],
      [1, 11155111, "Sepolia ethereum", 2],
    ];
    expect((await probeManifest(m, { transport: fakeTransport(s2, m) })).environmentStatus).toBe("UNSUPPORTED");
  });

  it("a verifier that returns TRUE for a bogus proof is flagged as not the official precompile", async () => {
    const m = manifest();
    const s = healthy(m);
    s.verifyBehaviour = "true";
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    const c = r.checks.find((c) => c.id === "precompile.rejectsInvalidProof");
    expect(c?.status).toBe("FAIL");
    expect(c?.detail).toMatch(/not the official precompile/);
    expect(r.environmentStatus).toBe("UNCONFIRMED");
  });

  it("verify returning false (no revert) still counts as rejecting", async () => {
    const m = manifest();
    const s = healthy(m);
    s.verifyBehaviour = "false";
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    expect(r.checks.find((c) => c.id === "precompile.rejectsInvalidProof")?.status).toBe("PASS");
  });

  it("decoder without code, or with code that differs from the pinned keccak → FAIL", async () => {
    const m = manifest();
    const s = healthy(m);
    s.decoderCode = "0x";
    expect((await probeManifest(m, { transport: fakeTransport(s, m) })).checks.find((c) => c.id === "decoder.code")?.status).toBe("FAIL");
    const m2 = manifest();
    m2.destination.decoder.codeKeccak256 = keccak256("0x1234");
    m2.manifestHash = computeManifestHash(m2);
    const r2 = await probeManifest(m2, { transport: fakeTransport(healthy(m2), m2) });
    expect(r2.checks.find((c) => c.id === "decoder.code")?.status).toBe("FAIL");
    expect(r2.checks.find((c) => c.id === "decoder.code")?.detail).toMatch(/MISMATCH/);
  });

  it("proof service: http 500, non-integer body, and lag vs on-chain are reported per hostname", async () => {
    const m = manifest();
    const s = healthy(m);
    const primary = new URL(m.proofService.baseUrl).host;
    s.serviceHeights[primary] = "http500";
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    const checks = r.checks.filter((c) => c.id === "proofService.attestedHeight");
    expect(checks[0]?.status).toBe("FAIL");
    expect(checks[0]?.target).toMatch(/^primary /);
    s.serviceHeights[primary] = "badbody";
    expect((await probeManifest(m, { transport: fakeTransport(s, m) })).checks.filter((c) => c.id === "proofService.attestedHeight")[0]?.status).toBe("FAIL");
    s.serviceHeights[primary] = 11_698_600;
    const lagged = (await probeManifest(m, { transport: fakeTransport(s, m) })).checks.filter((c) => c.id === "proofService.attestedHeight")[0];
    expect(lagged?.status).toBe("PASS");
    expect(lagged?.data?.lag).toBe(60);
  });

  it("no attestation for the chainKey → FAIL", async () => {
    const m = manifest();
    const s = healthy(m);
    s.latest = { height: 0, exists: false };
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    expect(r.checks.find((c) => c.id === "chainInfo.latestAttestation")?.status).toBe("FAIL");
  });

  it("genesis height drift → FAIL", async () => {
    const m = manifest();
    const s = healthy(m);
    s.genesis = 42;
    const r = await probeManifest(m, { transport: fakeTransport(s, m) });
    expect(r.checks.find((c) => c.id === "chainInfo.genesisHeight")?.status).toBe("FAIL");
  });

  it("calculateTxIndex semantics: isLeft sibling ⇒ bit set (vector [L,R] → 1, [R,L] → 2, [L,L,L] → 7)", async () => {
    const m = manifest();
    const r = await probeManifest(m, { transport: fakeTransport(healthy(m), m) });
    const details = r.checks.filter((c) => c.id === "precompile.calculateTxIndex").map((c) => c.detail);
    expect(details.some((d) => d.includes("[true,false] → 1"))).toBe(true);
    expect(details.some((d) => d.includes("[false,true] → 2"))).toBe(true);
    expect(details.some((d) => d.includes("[true,true,true] → 7"))).toBe(true);
    void ZERO32;
  });
});
