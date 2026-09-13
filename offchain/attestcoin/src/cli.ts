/**
 * CLI (no network unless `probe`):
 *   check                              — artifact pins + ABI signature sets + every manifest under config/attestcoin
 *   probe --manifest <path> [--out <path>] [--allow-mock]
 *                                      — read-only RPC/API probe of one manifest; writes a JSON report
 *   hash --manifest <path>             — print the canonical manifestHash for a manifest
 * Exit codes: 0 ok, 1 check/validation failure, 2 usage error, 3 probe found FAIL/UNSUPPORTED.
 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { loadPinnedAbi, signatureSetHash } from "./abi";
import { BLOCK_PROVER_MUTABILITY, EXPECTED_BLOCK_PROVER_SIGNATURES, EXPECTED_CHAIN_INFO_SIGNATURES, checkArtifacts } from "./artifacts";
import { type Manifest, computeManifestHash, validateManifest } from "./manifest";
import { probeManifest } from "./probe";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const MANIFEST_DIR = path.join(REPO_ROOT, "config", "attestcoin");
/** `npm --prefix <pkg> run …` sets cwd to the package; resolve user paths against where npm was invoked. */
const USER_CWD = process.env.INIT_CWD ?? process.cwd();
const userPath = (p: string): string => path.resolve(USER_CWD, p);

function readManifest(p: string): Manifest {
  return JSON.parse(readFileSync(p, "utf8")) as Manifest;
}

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
}

function cmdCheck(): number {
  let failed = false;
  const art = checkArtifacts();
  console.log(`artifacts: ${art.ok ? "OK" : "DRIFT"} installed=${JSON.stringify(art.installedVersions)}`);
  for (const f of art.files) console.log(`  ${f.ok ? "ok " : "BAD"} ${f.id} ${f.file}`);
  for (const e of art.errors) console.log(`  error: ${e}`);
  failed ||= !art.ok;

  const bp = loadPinnedAbi("blockProverAbi");
  const missingBp = EXPECTED_BLOCK_PROVER_SIGNATURES.filter((s) => !bp.signatures.includes(s));
  const ci = loadPinnedAbi("chainInfoAbi");
  const missingCi = EXPECTED_CHAIN_INFO_SIGNATURES.filter((s) => !ci.signatures.includes(s));
  console.log(`blockProver ABI: ${bp.signatures.length} entries, signatureSetHash=${signatureSetHash(bp.signatures)}${missingBp.length ? ` MISSING ${missingBp.join(", ")}` : ""}`);
  console.log(`chainInfo ABI: ${ci.signatures.length} entries, signatureSetHash=${signatureSetHash(ci.signatures)}${missingCi.length ? ` MISSING ${missingCi.join(", ")}` : ""}`);
  failed ||= missingBp.length > 0 || missingCi.length > 0;
  for (const [name, expected] of Object.entries(BLOCK_PROVER_MUTABILITY)) {
    const muts = new Set<string>();
    bp.iface.forEachFunction((f) => {
      if (f.name === name) muts.add(f.stateMutability);
    });
    const ok = muts.size === 1 && muts.has(expected);
    console.log(`  mutability ${name}: ${[...muts].join(",")} (expected ${expected}) ${ok ? "ok" : "BAD"}`);
    failed ||= !ok;
  }

  let manifests: string[] = [];
  try {
    manifests = readdirSync(MANIFEST_DIR).filter((f) => f.endsWith(".json") && !f.endsWith(".schema.json"));
  } catch {
    console.log(`manifests: directory missing ${MANIFEST_DIR}`);
    failed = true;
  }
  for (const f of manifests) {
    const p = path.join(MANIFEST_DIR, f);
    try {
      const m = readManifest(p);
      const v = validateManifest(m);
      console.log(`manifest ${f}: ${v.ok ? "VALID" : "INVALID"} profile=${m.executionProfile} status=${m.environmentStatus} hash=${m.manifestHash ?? "null"}`);
      for (const e of v.errors) console.log(`  error: ${e}`);
      for (const w of v.warnings) console.log(`  warn: ${w}`);
      failed ||= !v.ok;
    } catch (e) {
      console.log(`manifest ${f}: unreadable: ${(e as Error).message}`);
      failed = true;
    }
  }
  return failed ? 1 : 0;
}

async function cmdProbe(args: string[]): Promise<number> {
  const mp = argValue(args, "--manifest");
  if (!mp) {
    console.error("usage: probe --manifest <path> [--out <path>] [--allow-mock]");
    return 2;
  }
  const m = readManifest(userPath(mp));
  const v = validateManifest(m);
  if (!v.ok) {
    console.error(`manifest invalid:\n  ${v.errors.join("\n  ")}`);
    return 1;
  }
  if (m.mock && !args.includes("--allow-mock")) {
    console.error("refusing to probe a mock manifest (pass --allow-mock to probe a local double explicitly)");
    return 1;
  }
  const report = await probeManifest(m);
  const out = argValue(args, "--out");
  const json = JSON.stringify(report, null, 2);
  if (out) writeFileSync(userPath(out), json + "\n");
  console.log(json);
  console.error(`environmentStatus=${report.environmentStatus} pass=${report.summary.pass} fail=${report.summary.fail} skip=${report.summary.skip} info=${report.summary.info}`);
  return report.summary.fail === 0 && report.environmentStatus === "PROBED" ? 0 : 3;
}

function cmdHash(args: string[]): number {
  const mp = argValue(args, "--manifest");
  if (!mp) {
    console.error("usage: hash --manifest <path>");
    return 2;
  }
  console.log(computeManifestHash(readManifest(userPath(mp))));
  return 0;
}

async function main(): Promise<number> {
  const [cmd, ...rest] = process.argv.slice(2);
  switch (cmd) {
    case "check":
      return cmdCheck();
    case "probe":
      return cmdProbe(rest);
    case "hash":
      return cmdHash(rest);
    default:
      console.error("usage: cli <check|probe|hash> ...");
      return 2;
  }
}

main().then(
  (code) => process.exit(code),
  (e) => {
    console.error((e as Error).stack ?? String(e));
    process.exit(1);
  },
);
