import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PINNED_FILES, pinnedFilePath, sha256Hex } from "../src/artifacts";

const FIXTURE_DIR = path.resolve(__dirname, "..", "..", "..", "test", "fixtures", "gpu", "attestcoin", "official");
const PROBE_DIR = path.resolve(__dirname, "..", "..", "..", "test", "fixtures", "gpu", "attestcoin", "probe");

interface Provenance {
  kind: string;
  files: Record<string, { package: string; version: string; path: string; sha256: string }>;
}

describe("official ABI fixture copies", () => {
  const prov = JSON.parse(readFileSync(path.join(FIXTURE_DIR, "PROVENANCE.json"), "utf8")) as Provenance;

  it("are labeled as official artifact copies, never as proofs", () => {
    expect(prov.kind).toBe("OFFICIAL_ARTIFACT_COPY");
  });

  it("hash to their provenance sha256 and to the installed package files (no drift either way)", () => {
    for (const [name, meta] of Object.entries(prov.files)) {
      const fixture = readFileSync(path.join(FIXTURE_DIR, name));
      expect(sha256Hex(fixture), `${name} vs PROVENANCE`).toBe(meta.sha256);
      const pinned = PINNED_FILES.find((p) => p.pkg === meta.package && p.file === meta.path);
      expect(pinned, `${name} must be in PINNED_FILES`).toBeDefined();
      expect(sha256Hex(readFileSync(pinnedFilePath(pinned!.id))), `${name} vs node_modules`).toBe(meta.sha256);
    }
  });
});

describe("recorded probe report", () => {
  it("cc3-testnet probe fixture is PROBED with zero FAIL and contains hostnames only", () => {
    const r = JSON.parse(readFileSync(path.join(PROBE_DIR, "cc3-testnet.sepolia.probe.json"), "utf8")) as {
      environmentStatus: string;
      summary: { fail: number; pass: number };
      checks: Array<{ id: string; status: string; target: string }>;
      manifestId: string;
    };
    expect(r.environmentStatus).toBe("PROBED");
    expect(r.summary.fail).toBe(0);
    expect(r.summary.pass).toBeGreaterThan(0);
    expect(r.manifestId).toBe("cc3-testnet.sepolia.v1");
    for (const c of r.checks) expect(c.target, c.id).not.toMatch(/[?#]|:\/\/[^/\s]+\/./);
    expect(r.checks.find((c) => c.id === "precompile.rejectsInvalidProof")?.status).toBe("PASS");
  });
});
