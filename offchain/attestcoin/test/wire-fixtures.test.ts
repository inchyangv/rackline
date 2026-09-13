import { readFileSync } from "node:fs";
import path from "node:path";
import { AbiCoder } from "ethers";
import { describe, expect, it } from "vitest";
import {
  ACCOUNT_KEY,
  OBLIGATION_RECOGNIZED_TOPIC0,
  SYNTHETIC,
  buildWireFixtures,
  renderWireFixtures,
  type WireFixtureFile,
} from "../src/wire-fixtures";

const WIRE = path.resolve(__dirname, "..", "..", "..", "test", "fixtures", "gpu", "attestcoin", "wire", "synthetic-obligation-v1.json");
const coder = AbiCoder.defaultAbiCoder();

describe("GPU-078 synthetic wire fixture", () => {
  const onDisk = readFileSync(WIRE, "utf8");
  const parsed = JSON.parse(onDisk) as WireFixtureFile;

  it("is byte-reproducible from the pinned official SDK encoder", () => {
    expect(renderWireFixtures()).toBe(onDisk);
  });

  it("is labeled SYNTHETIC and pinned to the installed SDK version, never as a capture or proof", () => {
    expect(parsed.kind).toBe("SYNTHETIC_WIRE_FIXTURES");
    expect(parsed.sdkVersion).toBe("@gluwa/usc-sdk@0.18.0");
    expect(parsed.note).toMatch(/not chain captures/);
    expect(parsed.topic0).toBe(OBLIGATION_RECOGNIZED_TOPIC0);
    expect(parsed.accountKey).toBe(ACCOUNT_KEY);
  });

  it("decodes with the official (uint8, bytes[]) envelope and the expected receipt shape per case", () => {
    const built = buildWireFixtures();
    for (const [name, c] of Object.entries(built.cases)) {
      const [txType, chunks] = coder.decode(["uint8", "bytes[]"], c.txBytes) as unknown as [bigint, string[]];
      expect(txType, name).toBe(2n);
      expect(chunks.length, name).toBe(3);
      const rx = coder.decode(["uint8", "uint64", "tuple(address, bytes32[], bytes)[]", "bytes"], chunks[2]!) as unknown as [
        bigint,
        bigint,
        Array<[string, string[], string]>,
        string,
      ];
      const status = rx[0];
      const logs = rx[2];
      const fromEscrow = logs.filter((l) => l[0].toLowerCase() === SYNTHETIC.emitter.toLowerCase());
      if (name === "receiptFailed") {
        expect(status).toBe(0n);
      } else {
        expect(status).toBe(1n);
        expect(fromEscrow.length, name).toBe(c.expectedLogs);
      }
      if (c.expectedOrdinal !== undefined) {
        expect(logs[c.expectedOrdinal]![0].toLowerCase()).toBe(SYNTHETIC.emitter.toLowerCase());
      }
      if (c.amounts) {
        const amounts = fromEscrow.map((l) => (coder.decode(["address", "address", "uint256", "uint64", "uint32"], l[2])[2] as bigint).toString());
        expect(amounts).toEqual(c.amounts);
        expect(fromEscrow.map((l) => l[1][2])).toEqual(c.refs);
      }
    }
  });
});
