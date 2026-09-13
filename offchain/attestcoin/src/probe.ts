/**
 * Read-only environment probe. Given a validated manifest it confirms, without signing or
 * broadcasting anything:
 *   - destination/source EVM chain ids on the allowlisted RPCs,
 *   - the official ChainInfo precompile's supported-chain table (chainKey ↔ chainId ↔ encoding),
 *   - latest attestation height/hash and attestation genesis for the chainKey,
 *   - the official decoder contract has code (and its keccak256),
 *   - the BlockProver precompile answers its documented calls (calculateTxIndex vectors) and
 *     rejects an invalid proof (revert, never `true`),
 *   - the proof-builder service's attested-height endpoint on the primary and every alternate
 *     hostname (reported separately; hostnames are never assumed to be aliases).
 *
 * Bytecode presence at the precompile addresses is reported as information only: native
 * precompiles have `extcodesize == 0` on Creditcoin (NativeQueryVerifierLib.hasPrecompile).
 *
 * The transport is injectable so the logic is unit-tested offline; the default transport uses
 * ethers JsonRpcProvider + global fetch. Output contains hostnames only, never full URLs.
 */
import { AbiCoder, JsonRpcProvider, Network, keccak256 } from "ethers";
import { loadPinnedAbi } from "./abi";
import { type EnvironmentStatus, type Manifest, OFFICIAL, redactUrl } from "./manifest";

export type CallResult = { ok: true; data: string } | { ok: false; error: string; revertReason: string | null };

export interface ProbeTransport {
  ethChainId(rpcUrl: string): Promise<number>;
  ethBlockNumber(rpcUrl: string, blockTag: "finalized" | "latest"): Promise<number>;
  ethCall(rpcUrl: string, to: string, data: string, blockTag: "finalized" | "latest"): Promise<CallResult>;
  ethGetCode(rpcUrl: string, address: string): Promise<string>;
  httpGetJson(url: string, timeoutMs: number): Promise<{ status: number; body: unknown }>;
}

export type CheckStatus = "PASS" | "FAIL" | "SKIP" | "INFO";
export interface ProbeCheck {
  id: string;
  status: CheckStatus;
  target: string;
  detail: string;
  data?: Record<string, unknown>;
}

export interface ProbeReport {
  probeVersion: 1;
  probedAt: string;
  manifestId: string;
  manifestHash: string | null;
  executionProfile: string;
  environmentStatus: EnvironmentStatus;
  checks: ProbeCheck[];
  summary: { pass: number; fail: number; skip: number; info: number };
}

const ZERO32 = "0x" + "00".repeat(32);

function parseRevertReason(errText: string): string | null {
  // Error(string) selector 0x08c379a0 followed by ABI-encoded string.
  const m = /0x08c379a0[0-9a-fA-F]+/.exec(errText);
  if (!m) return null;
  try {
    const [reason] = AbiCoder.defaultAbiCoder().decode(["string"], "0x" + m[0].slice(10));
    return String(reason);
  } catch {
    return null;
  }
}

export function defaultTransport(): ProbeTransport {
  const providers = new Map<string, JsonRpcProvider>();
  const provider = (url: string): JsonRpcProvider => {
    let p = providers.get(url);
    if (!p) {
      // staticNetwork avoids an implicit eth_chainId/network-detect race; we call eth_chainId explicitly.
      p = new JsonRpcProvider(url, undefined, { staticNetwork: Network.from(1), batchMaxCount: 1 });
      providers.set(url, p);
    }
    return p;
  };
  return {
    async ethChainId(rpcUrl) {
      const hex = (await provider(rpcUrl).send("eth_chainId", [])) as string;
      return Number(BigInt(hex));
    },
    async ethBlockNumber(rpcUrl, blockTag) {
      const block = (await provider(rpcUrl).send("eth_getBlockByNumber", [blockTag, false])) as { number: string } | null;
      if (!block) throw new Error(`no ${blockTag} block`);
      return Number(BigInt(block.number));
    },
    async ethCall(rpcUrl, to, data, blockTag) {
      try {
        const out = (await provider(rpcUrl).send("eth_call", [{ to, data }, blockTag])) as string;
        return { ok: true, data: out };
      } catch (e) {
        const text = JSON.stringify(e, Object.getOwnPropertyNames(e as object));
        return { ok: false, error: (e as Error).message.slice(0, 300), revertReason: parseRevertReason(text) };
      }
    },
    async ethGetCode(rpcUrl, address) {
      return (await provider(rpcUrl).send("eth_getCode", [address, "latest"])) as string;
    },
    async httpGetJson(url, timeoutMs) {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const res = await fetch(url, { signal: ctrl.signal, headers: { accept: "application/json" } });
        let body: unknown = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }
        return { status: res.status, body };
      } finally {
        clearTimeout(t);
      }
    },
  };
}

export interface ProbeOptions {
  transport?: ProbeTransport;
  httpTimeoutMs?: number;
  now?: () => Date;
}

export async function probeManifest(m: Manifest, opts: ProbeOptions = {}): Promise<ProbeReport> {
  const t = opts.transport ?? defaultTransport();
  const timeout = opts.httpTimeoutMs ?? 15_000;
  const checks: ProbeCheck[] = [];
  const chainInfoAbi = loadPinnedAbi("chainInfoAbi");
  const blockProverAbi = loadPinnedAbi("blockProverAbi");
  const dest = m.destination;
  const primaryRpc = dest.rpcUrls[0];
  let unsupported = false;

  const push = (c: ProbeCheck) => checks.push(c);

  // 1. destination chain id on every allowlisted RPC.
  for (const url of dest.rpcUrls) {
    try {
      const id = await t.ethChainId(url);
      push({
        id: "destination.chainId",
        status: id === dest.chainId ? "PASS" : "FAIL",
        target: redactUrl(url),
        detail: `eth_chainId=${id}, manifest=${dest.chainId}`,
        data: { observed: id, expected: dest.chainId },
      });
    } catch (e) {
      push({ id: "destination.chainId", status: "FAIL", target: redactUrl(url), detail: `rpc error: ${(e as Error).message.slice(0, 200)}` });
    }
  }
  if (!primaryRpc) {
    push({ id: "destination.rpc", status: "FAIL", target: "-", detail: "no destination rpc" });
    return finish();
  }

  // 2. finalized block number for record.
  try {
    const bn = await t.ethBlockNumber(primaryRpc, "finalized");
    push({ id: "destination.finalizedBlock", status: "INFO", target: redactUrl(primaryRpc), detail: `finalized=${bn}`, data: { finalized: bn } });
  } catch (e) {
    push({ id: "destination.finalizedBlock", status: "FAIL", target: redactUrl(primaryRpc), detail: (e as Error).message.slice(0, 200) });
  }

  // 3. ChainInfo supported chains.
  const ci = chainInfoAbi.iface;
  const supportedCall = await t.ethCall(primaryRpc, dest.chainInfo.address, ci.encodeFunctionData("get_supported_chains", []), "finalized");
  let supported: Array<{ chainKey: number; chainId: number; chainName: string; chainEncoding: number }> = [];
  if (!supportedCall.ok) {
    push({ id: "chainInfo.supportedChains", status: "FAIL", target: dest.chainInfo.address, detail: `call failed: ${supportedCall.error}` });
  } else {
    try {
      const [rows] = ci.decodeFunctionResult("get_supported_chains", supportedCall.data) as unknown as [Array<[bigint, bigint, string, bigint]>];
      supported = rows.map((r) => ({
        chainKey: Number(r[0]),
        chainId: Number(r[1]),
        chainName: Buffer.from(r[2].slice(2), "hex").toString("utf8"),
        chainEncoding: Number(r[3]),
      }));
      const match = supported.find((c) => c.chainKey === m.source.chainKey);
      if (!match) {
        unsupported = true;
        push({ id: "chainInfo.sourceSupported", status: "FAIL", target: `chainKey=${m.source.chainKey}`, detail: `chainKey not in supported table → UNSUPPORTED_SOURCE`, data: { supported } });
      } else {
        const idOk = match.chainId === m.source.chainId;
        const encOk = match.chainEncoding === m.source.encoding && match.chainEncoding === OFFICIAL.ENCODING_V1;
        if (!idOk || !encOk) unsupported = true;
        push({
          id: "chainInfo.sourceSupported",
          status: idOk && encOk ? "PASS" : "FAIL",
          target: `chainKey=${m.source.chainKey}`,
          detail: `onchain chainId=${match.chainId} (manifest ${m.source.chainId}), encoding=${match.chainEncoding} (manifest ${m.source.encoding}), name="${match.chainName}"`,
          data: { match, supported },
        });
      }
    } catch (e) {
      push({ id: "chainInfo.supportedChains", status: "FAIL", target: dest.chainInfo.address, detail: `decode failed: ${(e as Error).message.slice(0, 200)}` });
    }
  }

  // 4. latest attestation + genesis for the chainKey.
  let onchainAttested: number | null = null;
  const latestCall = await t.ethCall(primaryRpc, dest.chainInfo.address, ci.encodeFunctionData("get_latest_attestation_height_and_hash", [m.source.chainKey]), "finalized");
  if (latestCall.ok) {
    try {
      const [res] = ci.decodeFunctionResult("get_latest_attestation_height_and_hash", latestCall.data) as unknown as [[bigint, string, boolean, boolean]];
      const height = Number(res[0]);
      const exists = Boolean(res[3]);
      if (exists) onchainAttested = height;
      push({
        id: "chainInfo.latestAttestation",
        status: exists ? "PASS" : "FAIL",
        target: `chainKey=${m.source.chainKey}`,
        detail: exists ? `height=${height} isAttestation=${String(res[2])}` : "no attestation exists for chainKey",
        data: { height, hash: res[1], isAttestation: res[2], exists },
      });
    } catch (e) {
      push({ id: "chainInfo.latestAttestation", status: "FAIL", target: `chainKey=${m.source.chainKey}`, detail: `decode failed: ${(e as Error).message.slice(0, 200)}` });
    }
  } else {
    push({ id: "chainInfo.latestAttestation", status: "FAIL", target: `chainKey=${m.source.chainKey}`, detail: `call failed: ${latestCall.error}` });
  }
  const genesisCall = await t.ethCall(primaryRpc, dest.chainInfo.address, ci.encodeFunctionData("get_attestation_genesis_height", [m.source.chainKey]), "finalized");
  if (genesisCall.ok) {
    const [g] = ci.decodeFunctionResult("get_attestation_genesis_height", genesisCall.data) as unknown as [bigint];
    push({
      id: "chainInfo.genesisHeight",
      status: Number(g) === m.source.genesisBlock ? "PASS" : "FAIL",
      target: `chainKey=${m.source.chainKey}`,
      detail: `onchain=${Number(g)} manifest=${m.source.genesisBlock}`,
      data: { onchain: Number(g), manifest: m.source.genesisBlock },
    });
  } else {
    push({ id: "chainInfo.genesisHeight", status: "FAIL", target: `chainKey=${m.source.chainKey}`, detail: `call failed: ${genesisCall.error}` });
  }

  // 5. decoder code presence + keccak (an ordinary contract: code presence is meaningful here).
  if (dest.decoder.address) {
    try {
      const code = await t.ethGetCode(primaryRpc, dest.decoder.address);
      const len = (code.length - 2) / 2;
      const hash = len > 0 ? keccak256(code) : null;
      const pinned = dest.decoder.codeKeccak256;
      const status: CheckStatus = len === 0 ? "FAIL" : pinned === null ? "PASS" : pinned === hash ? "PASS" : "FAIL";
      push({
        id: "decoder.code",
        status,
        target: dest.decoder.address,
        detail: len === 0 ? "no code at decoder address" : `codeBytes=${len} keccak256=${hash}${pinned ? (pinned === hash ? " (matches manifest)" : ` (MISMATCH manifest ${pinned})`) : " (manifest has no pin yet)"}`,
        data: { codeBytes: len, codeKeccak256: hash, pinned },
      });
    } catch (e) {
      push({ id: "decoder.code", status: "FAIL", target: dest.decoder.address, detail: (e as Error).message.slice(0, 200) });
    }
  } else {
    push({ id: "decoder.code", status: "SKIP", target: "-", detail: "no decoder address in manifest" });
  }

  // 6. precompile bytecode — INFO only (documented: native precompiles have no bytecode).
  for (const [label, addr] of [["blockProver", dest.blockProver.address], ["chainInfo", dest.chainInfo.address]] as const) {
    try {
      const code = await t.ethGetCode(primaryRpc, addr);
      push({ id: `precompile.bytecode.${label}`, status: "INFO", target: addr, detail: `codeBytes=${(code.length - 2) / 2} (0 is expected for native precompiles; not a deployment judgement)` });
    } catch (e) {
      push({ id: `precompile.bytecode.${label}`, status: "INFO", target: addr, detail: `eth_getCode failed: ${(e as Error).message.slice(0, 120)}` });
    }
  }

  // 7. documented call: calculateTxIndex vectors (isLeft => current node is the right child).
  const bp = blockProverAbi.iface;
  const vectors: Array<{ siblings: Array<[string, boolean]>; expected: number }> = [
    { siblings: [], expected: 0 },
    { siblings: [[ZERO32, true], [ZERO32, false]], expected: 1 },
    { siblings: [[ZERO32, false], [ZERO32, true]], expected: 2 },
    { siblings: [[ZERO32, true], [ZERO32, true], [ZERO32, true]], expected: 7 },
  ];
  for (const v of vectors) {
    const data = bp.encodeFunctionData("calculateTxIndex", [{ root: ZERO32, siblings: v.siblings.map(([hash, isLeft]) => ({ hash, isLeft })) }]);
    const r = await t.ethCall(primaryRpc, dest.blockProver.address, data, "latest");
    if (!r.ok) {
      push({ id: "precompile.calculateTxIndex", status: "FAIL", target: dest.blockProver.address, detail: `call failed for ${JSON.stringify(v.siblings.map((s) => s[1]))}: ${r.error}` });
      continue;
    }
    const [idx] = bp.decodeFunctionResult("calculateTxIndex", r.data) as unknown as [bigint];
    push({
      id: "precompile.calculateTxIndex",
      status: Number(idx) === v.expected ? "PASS" : "FAIL",
      target: dest.blockProver.address,
      detail: `siblings.isLeft=${JSON.stringify(v.siblings.map((s) => s[1]))} → ${Number(idx)} (expected ${v.expected})`,
    });
  }

  // 8. documented failure: verify() with a bogus proof must not return true.
  {
    const height = onchainAttested ?? 1;
    const data = bp.encodeFunctionData("verify(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))", [
      m.source.chainKey,
      height,
      "0x00",
      { root: ZERO32, siblings: [] },
      { lowerEndpointDigest: ZERO32, roots: [] },
    ]);
    const r = await t.ethCall(primaryRpc, dest.blockProver.address, data, "latest");
    if (r.ok) {
      let returned: boolean | null = null;
      try {
        returned = Boolean((bp.decodeFunctionResult("verify(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))", r.data) as unknown as [boolean])[0]);
      } catch {
        returned = null;
      }
      push({
        id: "precompile.rejectsInvalidProof",
        status: returned === true ? "FAIL" : returned === false ? "PASS" : "FAIL",
        target: dest.blockProver.address,
        detail: returned === true ? "verify() returned TRUE for a bogus proof — this is not the official precompile" : `verify() returned ${String(returned)} without revert`,
      });
    } else {
      push({
        id: "precompile.rejectsInvalidProof",
        status: "PASS",
        target: dest.blockProver.address,
        detail: `verify() reverted${r.revertReason ? ` with "${r.revertReason}"` : ""}`,
        data: { revertReason: r.revertReason },
      });
    }
  }

  // 9. proof service attested height — primary and each alternate, separately.
  const serviceHosts = [m.proofService.baseUrl, ...m.proofService.alternateBaseUrls];
  for (let i = 0; i < serviceHosts.length; i++) {
    const base = serviceHosts[i] as string;
    const url = `${base.replace(/\/$/, "")}${m.proofService.paths.attestedHeight}/${m.source.chainKey}`;
    const role = i === 0 ? "primary" : `alternate[${i - 1}]`;
    try {
      const res = await t.httpGetJson(url, timeout);
      const h = (res.body as { attestedHeight?: unknown } | null)?.attestedHeight;
      const ok = res.status === 200 && typeof h === "number" && Number.isInteger(h) && h >= 0;
      const lag = ok && onchainAttested !== null ? onchainAttested - (h as number) : null;
      push({
        id: "proofService.attestedHeight",
        status: ok ? "PASS" : "FAIL",
        target: `${role} ${redactUrl(base)}`,
        detail: ok ? `attestedHeight=${h}${lag !== null ? ` (onchain − service = ${lag})` : ""}` : `http ${res.status}, body=${JSON.stringify(res.body).slice(0, 120)}`,
        data: { role, attestedHeight: ok ? h : null, onchainAttested, lag },
      });
    } catch (e) {
      push({ id: "proofService.attestedHeight", status: "FAIL", target: `${role} ${redactUrl(base)}`, detail: (e as Error).message.slice(0, 200) });
    }
  }

  // 10. source chain id on allowlisted source RPCs (if any).
  if (m.source.rpcUrls.length === 0) {
    push({ id: "source.chainId", status: "SKIP", target: "-", detail: "no source rpc allowlisted" });
  }
  for (const url of m.source.rpcUrls) {
    try {
      const id = await t.ethChainId(url);
      push({ id: "source.chainId", status: id === m.source.chainId ? "PASS" : "FAIL", target: redactUrl(url), detail: `eth_chainId=${id}, manifest=${m.source.chainId}`, data: { observed: id, expected: m.source.chainId } });
    } catch (e) {
      push({ id: "source.chainId", status: "FAIL", target: redactUrl(url), detail: `rpc error: ${(e as Error).message.slice(0, 200)}` });
    }
  }

  return finish();

  function finish(): ProbeReport {
    const summary = { pass: 0, fail: 0, skip: 0, info: 0 };
    for (const c of checks) summary[c.status.toLowerCase() as keyof typeof summary]++;
    const critical = checks.filter((c) => c.status === "FAIL" && !c.id.startsWith("precompile.bytecode"));
    const environmentStatus: EnvironmentStatus = unsupported ? "UNSUPPORTED" : critical.length === 0 && summary.pass > 0 ? "PROBED" : "UNCONFIRMED";
    return {
      probeVersion: 1,
      probedAt: (opts.now ?? (() => new Date()))().toISOString(),
      manifestId: m.manifestId,
      manifestHash: m.manifestHash,
      executionProfile: m.executionProfile,
      environmentStatus,
      checks,
      summary,
    };
  }
}
