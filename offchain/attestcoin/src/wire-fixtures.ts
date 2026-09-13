/**
 * SYNTHETIC wire fixtures for the LOCAL verifier tests (GPU-078).
 *
 * `txBytes` are produced by the pinned official encoder (`@gluwa/usc-sdk` `encoding.abiEncode`, EncodingVersion.V1)
 * from synthetic transaction/receipt objects. They are NOT chain captures and carry NO proof: merkle/continuity
 * fields are placeholders for the LOCAL `MockBlockProver` only. A genuine capture belongs to GPU-080.
 *
 * The generator is deterministic; `test/wire-fixtures.test.ts` regenerates and compares against
 * `test/fixtures/gpu/attestcoin/wire/synthetic-obligation-v1.json` so the committed bytes are always reproducible
 * from the pinned SDK version.
 */
import { AbiCoder, keccak256, toUtf8Bytes, zeroPadValue, type TransactionReceipt } from "ethers";
import { encoding } from "@gluwa/usc-sdk";
import { installedVersion } from "./artifacts";

export const OBLIGATION_RECOGNIZED_SIGNATURE =
  "ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)";
export const OBLIGATION_RECOGNIZED_TOPIC0 = keccak256(toUtf8Bytes(OBLIGATION_RECOGNIZED_SIGNATURE));

/** TEST_ONLY addresses (docs/gpu/attestcoin/evidence-contract.md examples). */
export const SYNTHETIC = {
  providerSlug: "mockdepin-testonly",
  externalAccountId: "acct-A",
  emitter: "0x00000000000000000000000000000000000000e1", // TEST_ONLY escrow / source contract
  foreignEmitter: "0x00000000000000000000000000000000000000E2", // same topics, unregistered emitter
  issuer: "0x0000000000000000000000000000000000000155",
  payer: "0x00000000000000000000000000000000000000fa",
  dueAt: 1_761_868_800n, // 2025-10-31T00:00:00Z (issuer-CLAIMED, never proven)
  chainId: 11_155_111n, // Sepolia
} as const;

export const ACCOUNT_KEY = keccak256(toUtf8Bytes(`${SYNTHETIC.providerSlug}:${SYNTHETIC.externalAccountId}`));

const coder = AbiCoder.defaultAbiCoder();

export interface SyntheticLog {
  emitter: string;
  obligationRef: string; // bytes32
  amount: bigint;
  revision: number;
}

export function obligationLog(l: SyntheticLog): { address: string; topics: string[]; data: string } {
  return {
    address: l.emitter,
    topics: [OBLIGATION_RECOGNIZED_TOPIC0, ACCOUNT_KEY, l.obligationRef, zeroPadValue(SYNTHETIC.issuer, 32)],
    data: coder.encode(
      ["address", "address", "uint256", "uint64", "uint32"],
      [SYNTHETIC.payer, SYNTHETIC.emitter, l.amount, SYNTHETIC.dueAt, l.revision],
    ),
  };
}

/** A fixed synthetic EIP-1559 (type 2) transaction to the escrow; only the receipt varies per case. */
function syntheticTx(): encoding.TransactionWithRaw {
  const formatted = {
    type: 2,
    nonce: 7,
    gasLimit: 210_000n,
    from: SYNTHETIC.issuer,
    to: SYNTHETIC.emitter,
    value: 0n,
    data: "0x1234abcd",
    chainId: SYNTHETIC.chainId,
    maxPriorityFeePerGas: 1_500_000_000n,
    maxFeePerGas: 30_000_000_000n,
    accessList: [],
    signature: {
      yParity: 1,
      r: "0x1111111111111111111111111111111111111111111111111111111111111111",
      s: "0x2222222222222222222222222222222222222222222222222222222222222222",
    },
  };
  // The encoder only reads the fields above; the ethers class shape is not required for a synthetic object.
  return new encoding.TransactionWithRaw(formatted as never, new encoding.RawTransactionResponse(null));
}

function syntheticReceipt(status: number, logs: ReturnType<typeof obligationLog>[]): TransactionReceipt {
  return {
    status,
    gasUsed: 123_456n,
    logs,
    logsBloom: "0x" + "00".repeat(256),
  } as unknown as TransactionReceipt;
}

export function encodeSynthetic(status: number, logs: ReturnType<typeof obligationLog>[]): string {
  return encoding.abiEncode(syntheticTx(), syntheticReceipt(status, logs), encoding.EncodingVersion.V1).abi;
}

export interface WireCase {
  description: string;
  txBytes: string;
  expectedLogs: number;
  expectedOrdinal?: number;
  refs?: string[];
  amounts?: string[];
}

export interface WireFixtureFile {
  kind: "SYNTHETIC_WIRE_FIXTURES";
  note: string;
  sdkVersion: string;
  topic0: string;
  accountKey: string;
  emitter: string;
  issuer: string;
  cases: Record<string, WireCase>;
}

const REF_A = keccak256(toUtf8Bytes("inv-2026-08-A"));
const REF_B = keccak256(toUtf8Bytes("inv-2026-08-B"));
const USDC = (n: number) => BigInt(n) * 1_000_000n;

export function buildWireFixtures(): WireFixtureFile {
  const a = { emitter: SYNTHETIC.emitter, obligationRef: REF_A, amount: USDC(12_000), revision: 1 };
  const b = { emitter: SYNTHETIC.emitter, obligationRef: REF_B, amount: USDC(9_000), revision: 1 };
  const foreignA = { emitter: SYNTHETIC.foreignEmitter, obligationRef: REF_A, amount: USDC(99_000), revision: 1 };
  return {
    kind: "SYNTHETIC_WIRE_FIXTURES",
    note:
      "GPU-078 LOCAL fixtures. txBytes were produced with the pinned official encoder (@gluwa/usc-sdk 0.18.0 encoding.abiEncode, EncodingVersion.V1) from SYNTHETIC transactions. They are not chain captures and carry no proof; merkle/continuity fields are placeholders for the LOCAL MockBlockProver only. A genuine capture belongs to GPU-080.",
    sdkVersion: `@gluwa/usc-sdk@${installedVersion("@gluwa/usc-sdk")}`,
    topic0: OBLIGATION_RECOGNIZED_TOPIC0,
    accountKey: ACCOUNT_KEY,
    emitter: SYNTHETIC.emitter,
    issuer: SYNTHETIC.issuer,
    cases: {
      obligation2Logs: {
        description:
          "type-2 tx, status 1, two ObligationRecognized logs from the escrow (inv-A 12,000 USDC, inv-B 9,000 USDC)",
        txBytes: encodeSynthetic(1, [obligationLog(a), obligationLog(b)]),
        expectedLogs: 2,
        refs: [REF_A, REF_B],
        amounts: [a.amount.toString(), b.amount.toString()],
      },
      receiptFailed: {
        description: "same logs but receipt status 0",
        txBytes: encodeSynthetic(0, [obligationLog(a)]),
        expectedLogs: 0,
      },
      foreignEmitterOnly: {
        description: "one log from an unregistered emitter with identical topics",
        txBytes: encodeSynthetic(1, [obligationLog(foreignA)]),
        expectedLogs: 0,
      },
      mixedEmitters: {
        description: "escrow log at ordinal 1, foreign emitter at ordinal 0 and 2",
        txBytes: encodeSynthetic(1, [
          obligationLog({ ...foreignA, amount: 1n }),
          obligationLog(b),
          obligationLog({ emitter: SYNTHETIC.foreignEmitter, obligationRef: REF_B, amount: 2n, revision: 1 }),
        ]),
        expectedLogs: 1,
        expectedOrdinal: 1,
      },
      noLogs: {
        description: "status 1, no logs",
        txBytes: encodeSynthetic(1, []),
        expectedLogs: 0,
      },
    },
  };
}

export function renderWireFixtures(): string {
  return JSON.stringify(buildWireFixtures(), null, 2) + "\n";
}
