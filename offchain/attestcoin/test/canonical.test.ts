/**
 * GPU-076 cross-language vectors: the TypeScript side must derive the same canonical IDs and parse the
 * same amounts as the Python generator (test/fixtures/gpu/attestcoin/canonical-id-vectors-v1.json).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { AbiCoder, keccak256, toUtf8Bytes } from "ethers";
import { describe, expect, it } from "vitest";

const FIXTURE = path.resolve(__dirname, "..", "..", "..", "test", "fixtures", "gpu", "attestcoin", "canonical-id-vectors-v1.json");

interface Vectors {
  sourceEventIds: Array<{ envId: string; chainKey: string; height: string; txIndex: string; logOrdinal: string; id: string }>;
  economicEventIds: Array<{ economicEventId: string; hash: string }>;
  amounts: Array<{ amount: string; decimals: number; display: string }>;
}

export function sourceEventId(envId: string, chainKey: bigint, height: bigint, txIndex: bigint, logOrdinal: bigint): string {
  const envHash = keccak256(toUtf8Bytes(envId));
  return keccak256(AbiCoder.defaultAbiCoder().encode(["bytes32", "uint64", "uint64", "uint64", "uint32"], [envHash, chainKey, height, txIndex, logOrdinal]));
}

function display(amount: string, decimals: number): string {
  const v = BigInt(amount);
  const base = 10n ** BigInt(decimals);
  const whole = v / base;
  const frac = v % base;
  return decimals === 0 ? whole.toString() : `${whole}.${frac.toString().padStart(decimals, "0")}`;
}

describe("canonical ids and amounts match the Python vectors", () => {
  const vec = JSON.parse(readFileSync(FIXTURE, "utf8")) as Vectors;

  it("sourceEventId = keccak256(abi.encode(keccak(envId), chainKey, height, txIndex, logOrdinal))", () => {
    for (const v of vec.sourceEventIds) {
      // locator fields are strings: 2^64-1 as a JSON number parses to 2^64 in JavaScript (lossy).
      expect(sourceEventId(v.envId, BigInt(v.chainKey), BigInt(v.height), BigInt(v.txIndex), BigInt(v.logOrdinal))).toBe(v.id);
    }
    // same locator on a different environment or chainKey is a different event
    const ids = new Set(vec.sourceEventIds.map((v) => v.id));
    expect(ids.size).toBe(vec.sourceEventIds.length);
  });

  it("economicEventId hash = keccak256(utf8)", () => {
    for (const v of vec.economicEventIds) expect(keccak256(toUtf8Bytes(v.economicEventId))).toBe(v.hash);
  });

  it("amounts round-trip as strings/BigInt with exact display", () => {
    for (const a of vec.amounts) {
      expect(BigInt(a.amount).toString()).toBe(a.amount);
      expect(display(a.amount, a.decimals)).toBe(a.display);
    }
    // 2^53+1 as a JSON number would be lossy: prove why strings are mandatory
    expect(Number("9007199254740993")).not.toBe(9007199254740993n as unknown as number);
    expect(BigInt("9007199254740993")).toBe(9007199254740993n);
  });
});
