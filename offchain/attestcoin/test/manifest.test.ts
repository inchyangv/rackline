import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { type Manifest, OFFICIAL, computeManifestHash, redactUrl, validateManifest } from "../src/manifest";

const CONFIG_DIR = path.resolve(__dirname, "..", "..", "..", "config", "attestcoin");

function load(name: string): Manifest {
  return JSON.parse(readFileSync(path.join(CONFIG_DIR, name), "utf8")) as Manifest;
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

/** Recompute the hash after mutating a fixture so tests fail for the intended reason only. */
function rehash(m: Manifest): Manifest {
  m.manifestHash = computeManifestHash(m);
  return m;
}

describe("committed manifests", () => {
  it("cc3-testnet.sepolia.json is a valid NATIVE_TESTNET manifest with a current hash", () => {
    const m = load("cc3-testnet.sepolia.json");
    const v = validateManifest(m);
    expect(v.errors).toEqual([]);
    expect(m.executionProfile).toBe("NATIVE_TESTNET");
    expect(m.mock).toBe(false);
    expect(m.manifestHash).toBe(computeManifestHash(m));
    expect(m.destination.chainId).toBe(OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_TESTNET);
    expect(m.source.chainKey).toBe(1);
    expect(m.source.chainId).toBe(11155111);
  });

  it("local-mock.json is a valid LOCAL_MOCK manifest that cannot claim PROBED", () => {
    const m = load("local-mock.json");
    expect(validateManifest(m).errors).toEqual([]);
    expect(m.mock).toBe(true);
    expect(m.verificationMethod).toBe("LOCAL_MOCK");
    const bad = rehash(clone(m));
    bad.environmentStatus = "PROBED";
    bad.source.supportConfirmedBy = "PROBE";
    rehash(bad);
    expect(validateManifest(bad).errors.join("\n")).toMatch(/LOCAL_MOCK manifest cannot claim environmentStatus=PROBED/);
  });
});

describe("fail-closed validation (native profiles)", () => {
  const base = () => load("cc3-testnet.sepolia.json");

  it("rejects mock=true or verificationMethod=LOCAL_MOCK in NATIVE_TESTNET", () => {
    const m = rehash(Object.assign(clone(base()), { mock: true }));
    expect(validateManifest(m).errors.join("\n")).toMatch(/cannot set mock=true/);
    const m2 = rehash(Object.assign(clone(base()), { verificationMethod: "LOCAL_MOCK" as const }));
    expect(validateManifest(m2).errors.join("\n")).toMatch(/requires verificationMethod=ATTESTCOIN_NATIVE/);
  });

  it("rejects a non-official BlockProver / ChainInfo address (no alternative verifier)", () => {
    const m = clone(base());
    m.destination.blockProver.address = "0x000000000000000000000000000000000000dEaD";
    rehash(m);
    expect(validateManifest(m).errors.join("\n")).toMatch(/blockProver must be the official precompile/);
    const m2 = clone(base());
    m2.destination.chainInfo.address = "0x000000000000000000000000000000000000dEaD";
    rehash(m2);
    expect(validateManifest(m2).errors.join("\n")).toMatch(/chainInfo must be the official precompile/);
  });

  it("rejects a wrong destination chain id for the profile (testnet≠mainnet)", () => {
    const m = clone(base());
    m.destination.chainId = OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_MAINNET;
    rehash(m);
    expect(validateManifest(m).errors.join("\n")).toMatch(/NATIVE_TESTNET destination.chainId must be 102031/);
    const p = clone(base());
    p.executionProfile = "PRODUCTION";
    rehash(p);
    expect(validateManifest(p).errors.join("\n")).toMatch(/PRODUCTION destination.chainId must be 102030/);
    // PRODUCTION additionally requires PROBE-confirmed source support and a pinned decoder code hash.
    const p2 = clone(base());
    p2.executionProfile = "PRODUCTION";
    p2.destination.chainId = OFFICIAL.CREDITCOIN_CHAIN_IDS.CC3_MAINNET;
    p2.source.supportConfirmedBy = "DOCS";
    p2.environmentStatus = "UNCONFIRMED";
    p2.destination.decoder.codeKeccak256 = null;
    rehash(p2);
    const errs = validateManifest(p2).errors.join("\n");
    expect(errs).toMatch(/PRODUCTION requires source support confirmed by PROBE/);
    expect(errs).toMatch(/PRODUCTION requires a probed decoder codeKeccak256/);
  });

  it("rejects an unsupported encoding version and a zero chainKey", () => {
    const m = clone(base());
    m.source.encoding = 2;
    rehash(m);
    expect(validateManifest(m).errors.join("\n")).toMatch(/source.encoding must be 1/);
    const m2 = clone(base());
    m2.source.chainKey = 0;
    rehash(m2);
    expect(validateManifest(m2).errors.join("\n")).toMatch(/chainKey must be a positive integer/);
  });

  it("rejects local, non-https, credentialed, or query-string RPC/proof URLs", () => {
    for (const bad of ["http://localhost:8545", "https://user:pw@rpc.example.org", "https://rpc.example.org/?apikey=abc", "http://rpc.example.org"]) {
      const m = clone(base());
      m.destination.rpcUrls = [bad];
      rehash(m);
      expect(validateManifest(m).ok, bad).toBe(false);
    }
    const m = clone(base());
    m.proofService.baseUrl = "http://127.0.0.1:3000";
    rehash(m);
    expect(validateManifest(m).errors.join("\n")).toMatch(/proofService.baseUrl/);
  });

  it("rejects proof path drift from the pinned SDK contract", () => {
    const m = clone(base());
    m.proofService.paths.proofByTx = "/api/v2/proof-by-tx";
    rehash(m);
    expect(validateManifest(m).errors.join("\n")).toMatch(/proofService.paths.proofByTx must be \/api\/v1\/proof-by-tx/);
  });

  it("rejects a stale manifestHash and a PROBED status without PROBE confirmation", () => {
    const m = clone(base());
    m.notes.push("edited without rehash");
    expect(validateManifest(m).errors.join("\n")).toMatch(/manifestHash stale/);
    const m2 = clone(base());
    m2.environmentStatus = "PROBED";
    m2.source.supportConfirmedBy = "DOCS";
    rehash(m2);
    expect(validateManifest(m2).errors.join("\n")).toMatch(/environmentStatus=PROBED requires source.supportConfirmedBy=PROBE/);
  });

  it("rejects secret values and 32-byte hex outside the allowed fields", () => {
    const m = clone(base());
    m.secretRefs = { sourceRpc: "https://rpc.example.org/abc" };
    rehash(m);
    expect(validateManifest(m).errors.join("\n")).toMatch(/must be an ENV VAR NAME/);
    const m2 = clone(base());
    m2.notes.push("0x" + "ab".repeat(32));
    rehash(m2);
    expect(validateManifest(m2).errors.join("\n")).toMatch(/possible private key/);
  });

  it("rejects requiredVerification other than ATTESTCOIN_NATIVE (R2-D02)", () => {
    const m = clone(base()) as unknown as Record<string, unknown>;
    m.requiredVerification = "OFFCHAIN_ASSERTION";
    const typed = rehash(m as unknown as Manifest);
    expect(validateManifest(typed).errors.join("\n")).toMatch(/requiredVerification must be ATTESTCOIN_NATIVE/);
  });
});

describe("helpers", () => {
  it("manifestHash is canonical (key order independent) and excludes itself", () => {
    const m = load("cc3-testnet.sepolia.json");
    const reordered = JSON.parse(JSON.stringify(Object.fromEntries(Object.entries(m).reverse()))) as Manifest;
    expect(computeManifestHash(reordered)).toBe(computeManifestHash(m));
    const withNull = clone(m);
    withNull.manifestHash = null;
    expect(computeManifestHash(withNull)).toBe(computeManifestHash(m));
  });

  it("redactUrl strips credentials and query strings", () => {
    expect(redactUrl("https://user:pw@rpc.example.org/v3/secretkey?x=1")).toBe("https://rpc.example.org");
    expect(redactUrl("not a url")).toBe("<invalid-url>");
  });
});
