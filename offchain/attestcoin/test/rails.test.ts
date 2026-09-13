import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { type Manifest } from "../src/manifest";
import { type RailManifest, loadRail, validateRail } from "../src/rails";

const ROOT = path.resolve(__dirname, "..", "..", "..");
const RAIL = path.join(ROOT, "config", "gpu", "rails", "cc3-testnet.mockdepin.draft.json");
const SCHEMA = path.join(ROOT, "config", "gpu", "schema", "settlement-rails-v1.schema.json");
const testnet = JSON.parse(readFileSync(path.join(ROOT, "config", "attestcoin", "cc3-testnet.sepolia.json"), "utf8")) as Manifest;
const clone = (): RailManifest => JSON.parse(JSON.stringify(loadRail(RAIL))) as RailManifest;

describe("settlement rail manifest (GPU-008)", () => {
  it("schema lists every top-level key the draft uses and forbids extras", () => {
    const schema = JSON.parse(readFileSync(SCHEMA, "utf8")) as { required: string[]; additionalProperties: boolean; properties: Record<string, unknown> };
    const rail = loadRail(RAIL) as unknown as Record<string, unknown>;
    expect(schema.additionalProperties).toBe(false);
    for (const k of Object.keys(rail)) expect(schema.required, k).toContain(k);
    for (const k of schema.required) expect(rail, k).toHaveProperty(k);
  });

  it("TEST_ONLY draft rail is valid against the probed cc3-testnet manifest, with only honest nulls", () => {
    const v = validateRail(loadRail(RAIL), testnet);
    expect(v.errors).toEqual([]);
    expect(v.ok).toBe(true);
    const rail = loadRail(RAIL);
    expect(rail.railStatus).toBe("TEST_ONLY");
    expect(rail.partnerSourceBinding).toBe("UNCONFIGURED");
    expect(rail.escrow.address).toBeNull();
  });

  it("rejects a rail whose source chain is not the manifest's supported source (UNSUPPORTED_SOURCE)", () => {
    const rail = clone();
    rail.sourceChain.chainId = 42161; // Arbitrum: not in the official table
    rail.sourceChain.chainKey = 7;
    const v = validateRail(rail, testnet);
    expect(v.ok).toBe(false);
    expect(v.errors.join("\n")).toMatch(/UNSUPPORTED_SOURCE/);
  });

  it("rejects a manifest hash mismatch and a missing manifest", () => {
    const rail = clone();
    rail.evidence.attestcoinManifestHash = "sha256:" + "0".repeat(64);
    expect(validateRail(rail, testnet).errors.join("\n")).toMatch(/attestcoinManifestHash mismatch/);
    expect(validateRail(clone(), null).errors.join("\n")).toMatch(/not found/);
  });

  it("a PRODUCTION rail with UNCONFIRMED legs, null addresses or a testnet manifest is rejected", () => {
    const rail = clone();
    rail.executionProfile = "PRODUCTION";
    rail.railStatus = "PILOT_APPROVED";
    rail.partnerSourceBinding = "VERIFIED";
    const v = validateRail(rail, testnet);
    expect(v.ok).toBe(false);
    const text = v.errors.join("\n");
    expect(text).toMatch(/UNCONFIRMED is not allowed on a PRODUCTION rail/);
    expect(text).toMatch(/null is not allowed on a PRODUCTION rail/);
    expect(text).toMatch(/executionProfile PRODUCTION != attestcoin manifest NATIVE_TESTNET/);
  });

  it("a test-profile rail cannot claim partnerSourceBinding=VERIFIED or PILOT_APPROVED", () => {
    const rail = clone();
    rail.partnerSourceBinding = "VERIFIED";
    rail.railStatus = "PILOT_APPROVED";
    const text = validateRail(rail, testnet).errors.join("\n");
    expect(text).toMatch(/real partner evidence/);
    expect(text).toMatch(/only PRODUCTION rails can be PILOT_APPROVED/);
  });

  it("requiredVerification is pinned to ATTESTCOIN_NATIVE and finality semantics are fixed", () => {
    const rail = clone() as unknown as { evidence: Record<string, unknown>; sourceChain: Record<string, unknown> };
    rail.evidence.requiredVerification = "OFFCHAIN_ASSERTION";
    rail.sourceChain.finality = "confirmations";
    const text = validateRail(rail as unknown as RailManifest, testnet).errors.join("\n");
    expect(text).toMatch(/ATTESTCOIN_NATIVE/);
    expect(text).toMatch(/finality must be 'attestation'/);
  });
});
