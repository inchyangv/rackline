import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Contract, FetchRequest, Interface, JsonRpcProvider, Wallet, ZeroHash, id, keccak256, parseUnits } from "ethers";

// Payer-persona and credit-operations scenarios against the DEPLOYED TEST_ONLY environment.
// Personas (SIM-AETHIR, SIM-GPUNET) are simulated payers on the Sepolia source escrow; see
// config/gpu/scenarios/payer-personas.json and docs/gpu/scenarios/live-payer-scenarios.md.
// Keys and session tokens stay in memory; output carries public identifiers only.
const webUrl = (process.env.GPU_REVIEW_WEB_URL || "").replace(/\/$/, "");
const apiUrl = (process.env.GPU_REVIEW_API_URL || "").replace(/\/$/, "");
assert.ok(webUrl && apiUrl, "Set GPU_REVIEW_WEB_URL and GPU_REVIEW_API_URL");
const keyFile = process.env.GPU_SCENARIO_KEYS;
assert.ok(keyFile && existsSync(keyFile), "GPU_SCENARIO_KEYS must name the role key file");
const allowTransactions = process.env.GPU_ALLOW_TESTNET_TRANSACTIONS === "1";
const allowNativeRefresh = process.env.GPU_SCENARIO_NATIVE_REFRESH === "1";
const approval = "--approval=user-20260914";
if (allowNativeRefresh) {
  assert.ok(allowTransactions, "Native refresh requires GPU_ALLOW_TESTNET_TRANSACTIONS=1");
  assert.equal(process.env.GPU_SCENARIO_APPROVAL, "user-20260914", "Explicit approval reference required");
}
const only = process.env.GPU_SCENARIO_ONLY
  ? new Set(process.env.GPU_SCENARIO_ONLY.split(",").map((item) => item.trim()))
  : null;
const outFile = process.env.GPU_SCENARIO_OUT ? path.resolve(process.env.GPU_SCENARIO_OUT) : "";
const here = fileURLToPath(new URL(".", import.meta.url));
const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
const reviewScript = `${here}live-review-browser.mjs`;
const roles = JSON.parse(readFileSync(keyFile, "utf8"));
const manifest = JSON.parse(readFileSync(`${repoRoot}config/gpu/deployments/cc3-testnet.json`, "utf8"));
const environment = JSON.parse(readFileSync(`${repoRoot}config/attestcoin/cc3-testnet.sepolia.release.json`, "utf8"));
const personas = JSON.parse(readFileSync(`${repoRoot}config/gpu/scenarios/payer-personas.json`, "utf8"));
const abi = (name) => JSON.parse(readFileSync(`${repoRoot}test/fixtures/gpu/abi/${name}.json`, "utf8"));
const artifactDir = `${repoRoot}.artifacts/native-testnet/`;
const artifact = (name) => JSON.parse(readFileSync(`${artifactDir}${name}.json`, "utf8"));
const hasArtifact = (name) => existsSync(`${artifactDir}${name}.json`);

const config = await (await fetch(`${apiUrl}/v1/config`)).json();
assert.equal(config.executionProfile, "NATIVE_TESTNET");
assert.equal(config.chainId, 102031);
assert.equal(config.asset.testOnly, true);
const rpcRequest = new FetchRequest(config.rpcUrl);
rpcRequest.timeout = 12000;
const provider = new JsonRpcProvider(rpcRequest, undefined, { batchMaxCount: 1 });
assert.equal((await provider.getNetwork()).chainId, 102031n);
const sepolia = new JsonRpcProvider("https://ethereum-sepolia-rpc.publicnode.com");
const token = new Contract(config.asset.address, abi("GpuTestToken"), provider);
const vault = new Contract(config.contracts.vault, abi("LendingVaultV2"), provider);
const manager = new Contract(config.contracts.manager, abi("CreditFacilityManager"), provider);
const router = new Contract(config.contracts.repaymentRouter, abi("RepaymentRouter"), provider);
const ledger = new Contract(config.contracts.ledger, abi("DebtLedger"), provider);
const book = new Contract(manifest.contracts.ReceivableBook, abi("ReceivableBook"), provider);
const evidence = new Contract(manifest.contracts.EvidenceBook, abi("EvidenceBook"), provider);
const control = new Contract(manifest.contracts.ControlRegistry, abi("ControlRegistry"), provider);
const recovery = new Contract(manifest.contracts.RecoveryManager, abi("RecoveryManager"), provider);
const exposure = new Contract(manifest.contracts.ExposureController, abi("ExposureController"), provider);
const rolesContract = new Contract(manifest.contracts.ProtocolRoles, abi("ProtocolRoles"), provider);
const escrow = new Contract(environment.source.emitters[0].address, abi("SourceEscrow"), sepolia);
const sourceToken = new Contract(environment.source.tokens[0].address, abi("GpuTestToken"), sepolia);
const routerInterface = new Interface(abi("RepaymentRouter"));
const managerInterface = new Interface(abi("CreditFacilityManager"));
const rootKeys = [...new Set(readFileSync(`${repoRoot}keys/PRIVATE_KEYS.txt`, "utf8").match(/(?:0x)?[a-fA-F0-9]{64}/g) || [])];
assert.equal(rootKeys.length, 1, "Expected one unambiguous deployment key");
const deployerWallet = new Wallet(rootKeys[0].startsWith("0x") ? rootKeys[0] : `0x${rootKeys[0]}`, provider);
const borrowerWallet = new Wallet(roles.borrower.privateKey, provider);
const underwriterWallet = new Wallet(roles.underwriter.privateKey, provider);
const lpWallet = new Wallet(roles.lp.privateKey, provider);
const keeperWallet = new Wallet(roles.keeper.privateKey, provider);
const providerId = id(personas.providerId);
const accountKey = id(`${personas.providerId}:${personas.accountName}`);
const unit = (value) => parseUnits(String(value), 6);
const STATES = ["DRAFT", "UNDER_REVIEW", "CONTROL_PENDING", "ACTIVE", "DRAW_FROZEN", "DELINQUENT", "DEFAULTED", "RECOVERY", "REPAID", "RELEASED", "CLOSED_WITH_LOSS"];
const RECEIVABLE_STATES = ["NONE", "OPEN", "ASSIGNED", "PAID", "CANCELLED", "DISPUTED", "WRITTEN_OFF"];

// Facilities used by this suite (opened out of band with `native_tools.mjs open-facility`, imported with bootstrap_native).
const facilities = {
  aethir: { name: process.env.GPU_QA_AETHIR_FACILITY || "gpu080-facility-v5", agreement: process.env.GPU_QA_AETHIR_AGREEMENT || "gpu080-SIMULATED-control-v5" },
  gpunet: { name: process.env.GPU_QA_GPUNET_FACILITY || "gpu080-facility-v6", agreement: process.env.GPU_QA_GPUNET_AGREEMENT || "gpu080-SIMULATED-control-v6" },
  browser: { name: process.env.GPU_QA_BROWSER_FACILITY || "gpu080-facility-v7", agreement: process.env.GPU_QA_BROWSER_AGREEMENT || "gpu080-SIMULATED-control-v7" },
  // R-series: sacrificed on purpose (default → recovery → write-off); never reused.
  recovery: { name: process.env.GPU_QA_RECOVERY_FACILITY || "gpu080-facility-v8", agreement: process.env.GPU_QA_RECOVERY_AGREEMENT || "gpu080-SIMULATED-control-v8" },
};
for (const f of Object.values(facilities)) {
  f.id = id(f.name);
  f.sourceKey = keccak256(f.id);
  f.apiId = null;
}

// ---------------------------------------------------------------- helpers
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function http(pathname, { method = "GET", token: bearer, body } = {}) {
  const response = await fetch(`${apiUrl}${pathname}`, {
    method,
    headers: { ...(body ? { "content-type": "application/json" } : {}), ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let json = null;
  try { json = JSON.parse(text); } catch { json = null; }
  return { status: response.status, json, text };
}
async function login(wallet) {
  const issued = await http("/gpu/auth/challenge", { method: "POST", body: { wallet: wallet.address, chainId: config.chainId } });
  assert.equal(issued.status, 200, `challenge ${issued.text.slice(0, 200)}`);
  const types = { ...issued.json.typedData.types };
  delete types.EIP712Domain;
  const signature = await wallet.signTypedData(issued.json.typedData.domain, types, issued.json.typedData.message);
  const verified = await http("/gpu/auth/verify", { method: "POST", body: { wallet: wallet.address, chainId: config.chainId, nonce: issued.json.nonce, signature } });
  assert.equal(verified.status, 200, `verify ${verified.text.slice(0, 200)}`);
  return verified.json;
}
async function pollApi(pathname, bearer, predicate, timeoutMs = 180000, label = pathname) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await http(pathname, { token: bearer });
    if (last.status === 200 && predicate(last.json.data, last.json.meta)) return last.json;
    await sleep(3000);
  }
  throw new Error(`${label} did not reach the expected state: ${last?.text.slice(0, 300)}`);
}
function run(command, commandArgs, { cwd = repoRoot, env = {}, timeoutMs = 900000, onLine } = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, commandArgs, { cwd, env: { ...process.env, ...env } });
    let stdout = "";
    let stderr = "";
    let buffer = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      buffer += chunk;
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        if (onLine) onLine(line);
      }
    });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);
    child.on("close", (code) => { clearTimeout(timer); resolve({ code, stdout, stderr }); });
  });
}
/** payer_sim.mjs mutation: returns the record it wrote (public identifiers only). */
async function sim(commandArgs, { timeoutMs = 300000 } = {}) {
  const result = await run("node", ["script/gpu/payer_sim.mjs", ...commandArgs, "--broadcast", approval], { timeoutMs });
  const line = result.stdout.split("\n").find((row) => row.startsWith('{"record":'));
  if (result.code !== 0 || !line) throw new Error(`payer_sim ${commandArgs[0]} failed: ${result.stderr.slice(-400)}`);
  return JSON.parse(line);
}
async function officialProof(name, deadlineSeconds) {
  while (Date.now() / 1000 < deadlineSeconds) {
    const proof = await run("node", ["script/gpu/native_proofs.mjs", "--refresh", name], { timeoutMs: 120000 });
    if (proof.code === 0) return JSON.parse(readFileSync(`${artifactDir}${name}.proof.json`, "utf8"));
    await sleep(15000);
  }
  return null;
}
async function consumeStep(step, name, facilityName) {
  const outName = `${name}-consumption`;
  const result = await run("node", [
    "script/gpu/consume-native.mjs", "--step", step, "--proof", `.artifacts/native-testnet/${name}.proof.json`,
    "--facility", facilityName, "--out", `.artifacts/native-testnet/${outName}.json`, "--broadcast", approval,
  ], { timeoutMs: 420000 });
  const report = hasArtifact(outName) ? artifact(outName) : null;
  const row = report?.transactions?.[0] ?? null;
  return {
    ok: result.code === 0 && ["NATIVE_CONSUMED", "ALREADY_CONSUMED"].includes(row?.status) && row?.financialAuditStatus === "PASSED",
    code: result.code,
    stderr: result.stderr.slice(-300),
    row: row ? { step, name, sourceTxHash: row.sourceTxHash, sourceEventId: row.sourceEventId, destinationTxHash: row.destinationTxHash, destinationBlock: row.destinationBlock, status: row.status, financialAudit: row.financialAudit } : null,
  };
}
async function sendTx(wallet, contract, method, params, label, { waitBlocks = 2 } = {}) {
  const bound = contract.connect(wallet);
  const estimated = await bound[method].estimateGas(...params);
  const tx = await bound[method](...params, { gasLimit: (estimated * 3n) / 2n });
  const receipt = await tx.wait(waitBlocks);
  if (receipt.status !== 1) throw new Error(`${label} failed: ${tx.hash}`);
  return receipt;
}
function revertName(error, ifaces) {
  const data = error?.data ?? error?.info?.error?.data ?? error?.error?.data;
  if (typeof data === "string" && data.length >= 10) {
    for (const iface of ifaces) {
      try {
        const parsed = iface.parseError(data);
        if (parsed) return parsed.name;
      } catch { /* try next */ }
    }
    return `selector:${data.slice(0, 10)}`;
  }
  return error?.shortMessage ?? error?.code ?? "UNKNOWN";
}
async function expectRevert(fn, ifaces = [managerInterface, routerInterface, new Interface(abi("ExposureController")), new Interface(abi("RecoveryManager")), new Interface(abi("EvidenceBook")), new Interface(abi("ReceivableBook"))]) {
  try {
    await fn();
    return "NO_REVERT";
  } catch (error) {
    return revertName(error, ifaces);
  }
}
function logs(receipt, iface, name) {
  return receipt.logs.map((log) => { try { return iface.parseLog(log); } catch { return null; } }).filter((event) => event?.name === name);
}
const stringify = (value) => JSON.parse(JSON.stringify(value, (_, v) => (typeof v === "bigint" ? String(v) : v)));
async function chainNow() {
  return Number((await provider.getBlock("latest")).timestamp);
}
async function facilitySnapshot(f) {
  const now = await chainNow();
  const info = await manager.facilityInfo(f.id);
  const ids = await book.facilityReceivables(f.id);
  const receivables = [];
  for (const rid of ids) {
    const r = await book.receivable(rid);
    receivables.push({ id: rid, net: String(r.net), paid: String(r.paid), state: RECEIVABLE_STATES[Number(r.state)], revision: String(r.revision), dueAt: String(r.dueAt), evidenceValidUntil: String(r.evidenceValidUntil), payer: r.payer.toLowerCase() });
  }
  const [eligible, validUntil, age] = await book.eligibleUnpaid(f.id, 900, 0, 1000, now);
  let evaluation = null;
  try {
    const e = await exposure.evaluateDraw(f.id);
    evaluation = { eligibleReceivables: String(e.eligibleReceivables), receivableLimit: String(e.receivableLimit), facilityLimit: String(e.facilityLimit), availableDraw: String(e.availableDraw), evidenceValidUntil: String(e.evidenceValidUntil), checkpointAge: String(e.checkpointAge) };
  } catch (error) {
    evaluation = { error: revertName(error, [new Interface(abi("ExposureController"))]) };
  }
  const agreement = await control.agreement(info.controlAgreementId);
  return {
    at: now, state: STATES[Number(info.state)], wallet: info.wallet, debt: String(await ledger.legalDebtAt(f.id, now)),
    receivables, eligibleUnpaid: String(eligible), evidenceValidUntil: String(validUntil), checkpointAge: String(age), evaluation,
    controlObservationAge: now - Number(agreement.lastObservedAt),
  };
}
async function discoverApiIds(bearer) {
  const listed = await http("/v1/facilities?limit=100", { token: bearer });
  if (listed.status !== 200) return;
  for (const f of Object.values(facilities)) {
    const row = listed.json.data.find((item) => item.canonicalFacilityId?.toLowerCase() === f.id.toLowerCase());
    if (row) f.apiId = row.facilityId;
  }
}
async function delegate(env, label) {
  const submitted = [];
  let summary = null;
  const result = await run("node", [reviewScript], {
    cwd: here,
    env: { GPU_REVIEW_WEB_URL: webUrl, GPU_REVIEW_API_URL: apiUrl, ...env },
    onLine: (line) => {
      if (/^(PASS|SUBMITTED|WALLET_RPC_FAILURE|RETRY_READ_ONLY_RPC|AUTHENTICATED|BROWSER_FAILURE_STATE|MISSING_REFRESH)/.test(line))
        console.log(`  [${label}] ${line.slice(0, 200)}`);
      const match = line.match(/^SUBMITTED real testnet (\w+): (0x[0-9a-f]{64})/i);
      if (match) submitted.push({ action: match[1], hash: match[2] });
      if (line.startsWith('{"result":')) summary = JSON.parse(line);
    },
  });
  if (result.code !== 0) console.log(`  [${label}] stderr ${result.stderr.slice(-1200)}`);
  return { ...result, submitted, summary };
}

// ---------------------------------------------------------------- scenario registry
class Skip extends Error {}
const results = [];
const startedAt = new Date().toISOString();
const prior = process.env.GPU_SCENARIO_MERGE === "1" && outFile && existsSync(outFile) ? JSON.parse(readFileSync(outFile, "utf8")) : null;
const merged = () => results.map((record) => (record.status === "SKIPPED" && record.reason?.startsWith("filtered") && prior ? prior.scenarios.find((item) => item.id === record.id) ?? record : record));
function persist() {
  if (!outFile) return;
  const all = merged();
  const summary = {
    schemaVersion: "1.0", executionProfile: "NATIVE_TESTNET", scope: "LIVE_PAYER_PERSONA_AND_CREDIT_OPERATIONS",
    webUrl, apiUrl, chainId: 102031, sourceChainId: 11155111, deploymentId: config.deploymentId, manifestHash: config.manifestHash,
    startedAt: prior?.startedAt ?? startedAt, updatedAt: new Date().toISOString(),
    runs: [...(prior?.runs ?? []), startedAt].filter((value, index, array) => array.indexOf(value) === index),
    personas: Object.fromEntries(Object.entries(personas.personas).map(([name, p]) => [name, { label: p.label, imitates: p.imitates, payer: personas.deployed[name]?.payer ?? null }])),
    facilities: Object.fromEntries(Object.entries(facilities).map(([key, f]) => [key, { name: f.name, id: f.id, apiId: f.apiId }])),
    wallets: { lp: lpWallet.address, borrower: borrowerWallet.address, keeper: keeperWallet.address, underwriter: underwriterWallet.address, operator: deployerWallet.address },
    partnerRevenue: "SIMULATED", partnerSourceBinding: "UNCONFIGURED",
    totals: { pass: all.filter((r) => r.status === "PASS").length, fail: all.filter((r) => r.status === "FAIL").length, skipped: all.filter((r) => r.status === "SKIPPED").length },
    scenarios: all,
  };
  mkdirSync(path.dirname(outFile), { recursive: true });
  writeFileSync(outFile, JSON.stringify(summary, null, 2) + "\n");
}
async function scenario(idTag, persona, title, fn) {
  const record = { id: idTag, persona, title, status: "PASS", checks: [], evidence: {}, startedAt: new Date().toISOString() };
  console.log(`\n### ${idTag} [${persona}] ${title}`);
  if (only && !only.has(idTag)) {
    record.status = "SKIPPED";
    record.reason = "filtered by GPU_SCENARIO_ONLY";
    results.push(record);
    return record;
  }
  const ctx = {
    evidence: record.evidence,
    check(name, ok, detail) {
      record.checks.push({ name, ok: Boolean(ok), ...(detail === undefined ? {} : { detail: stringify(detail) }) });
      console.log(`  ${ok ? "ok  " : "FAIL"} ${name}${detail === undefined ? "" : " " + JSON.stringify(stringify(detail)).slice(0, 300)}`);
      return Boolean(ok);
    },
    skip(reason) { throw new Skip(reason); },
  };
  try {
    await fn(ctx);
    record.status = record.checks.every((c) => c.ok) ? "PASS" : "FAIL";
  } catch (error) {
    if (error instanceof Skip) {
      record.status = "SKIPPED";
      record.reason = error.message;
      console.log(`  SKIPPED ${error.message}`);
    } else {
      record.status = "FAIL";
      record.error = String(error?.message || error).slice(0, 800);
      console.log(`  ERROR ${record.error}`);
    }
  }
  record.evidence = stringify(record.evidence);
  record.finishedAt = new Date().toISOString();
  console.log(`  => ${record.status}`);
  results.push(record);
  persist();
  return record;
}
const requireTransactions = (t) => { if (!allowNativeRefresh) t.skip("GPU_SCENARIO_NATIVE_REFRESH is not 1"); };

// The ordered list of persona source events is persisted so N-series scenarios can run in a later invocation.
const eventsFile = `${artifactDir}qa-source-events.json`;
const sourceEvents = existsSync(eventsFile) ? JSON.parse(readFileSync(eventsFile, "utf8")) : [];
function recordEvent(record, facilityName) {
  const entry = { name: record.record, step: record.step, persona: record.persona ?? null, txHash: record.txHash, blockNumber: record.blockNumber, facilityName, consumed: false };
  const index = sourceEvents.findIndex((item) => item.name === entry.name);
  if (index >= 0) sourceEvents[index] = { ...sourceEvents[index], ...entry };
  else sourceEvents.push(entry);
  writeFileSync(eventsFile, JSON.stringify(sourceEvents, null, 2) + "\n");
  return entry;
}
const sourceOf = (f) => `${f.name}`;

const session = await login(borrowerWallet);
await discoverApiIds(session.token);
console.log(`facilities: ${JSON.stringify(Object.fromEntries(Object.entries(facilities).map(([k, f]) => [k, { name: f.name, apiId: f.apiId }])))}`);

// ================================================================ P. Persona setup and source-side behaviour (Sepolia)
await scenario("P0", "operator", "persona payers are deployed, registered as PAYER on the escrow and funded with faucet tokens", async (t) => {
  for (const [name, p] of Object.entries(personas.personas)) {
    const deployed = personas.deployed[name];
    t.check(`${name}: payer contract recorded`, Boolean(deployed?.payer), deployed && { payer: deployed.payer, deployTxHash: deployed.deployTxHash });
    if (!deployed) continue;
    const code = await sepolia.getCode(deployed.payer);
    const payer = new Contract(deployed.payer, ["function capabilities() view returns (tuple(bool provableObligation,bool provableAssignment,bool provablePayout,bool provableCheckpoint,bool measuredPayouts,bool simulatedRevenue))", "function sourceContract() view returns (address)", "function operator() view returns (address)"], sepolia);
    const capabilities = await payer.capabilities();
    const balance = await sourceToken.balanceOf(deployed.payer);
    t.evidence[name] = { label: p.label, payer: deployed.payer, codeSize: (code.length - 2) / 2, registered: await escrow.isRegisteredPayer(deployed.payer), simulatedRevenue: capabilities.simulatedRevenue, measuredPayouts: capabilities.measuredPayouts, sourceContract: (await payer.sourceContract()).toLowerCase(), balance: String(balance) };
    t.check(`${name}: registered payer bound to the escrow, declares simulatedRevenue=true`, t.evidence[name].registered && capabilities.simulatedRevenue && capabilities.measuredPayouts && t.evidence[name].sourceContract === environment.source.emitters[0].address.toLowerCase(), t.evidence[name]);
    t.check(`${name}: payer holds faucet tokens for settlements and is not the borrower wallet`, balance > 0n && deployed.payer.toLowerCase() !== borrowerWallet.address.toLowerCase());
  }
  t.check("persona registry is explicit about simulation (no partner claim)", personas.partnerRevenue === "SIMULATED" && personas.partnerSourceBinding === "UNCONFIGURED" && Object.values(personas.personas).every((p) => /SIM-/.test(p.label)));
});

const aethirEpochs = [
  { ref: "epoch-1", amount: "12000000", facility: facilities.aethir },
  { ref: "epoch-2", amount: "12000000", facility: facilities.aethir },
  { ref: "epoch-3", amount: "12000000", facility: facilities.aethir },
  { ref: "epoch-4", amount: "10000000", facility: facilities.browser },
];
await scenario("P1", "sim-aethir", "epoch reward obligations are recognised by the issuer and assigned to the operator's facilities", async (t) => {
  requireTransactions(t);
  const before = { revision: await escrow.accountLatestRevision(accountKey), open: await escrow.accountOpenAmount(accountKey) };
  t.evidence.source = { before: stringify(before), events: [] };
  for (const epoch of aethirEpochs) {
    const recognized = await sim(["recognize", "--persona", "sim-aethir", "--ref", epoch.ref, "--amount", epoch.amount, "--due-seconds", "86400", "--name", `qa-aethir-${epoch.ref}-recognize`]);
    t.evidence.source.events.push(recordEvent(recognized, epoch.facility.name));
    const assigned = await sim(["assign", "--persona", "sim-aethir", "--ref", epoch.ref, "--facility", epoch.facility.name, "--name", `qa-aethir-${epoch.ref}-assign`]);
    t.evidence.source.events.push(recordEvent(assigned, epoch.facility.name));
    const obligation = await escrow.obligation(accountKey, recognized.obligationRef);
    t.check(`${epoch.ref}: recognised for the SIM-AETHIR payer and assigned to ${epoch.facility.name}`, obligation.payer.toLowerCase() === personas.deployed["sim-aethir"].payer && String(obligation.net) === epoch.amount && obligation.assignedTo === epoch.facility.sourceKey && Number(obligation.status) === 1, { txHashes: [recognized.txHash, assigned.txHash], revision: String(obligation.revision) });
  }
  const after = { revision: await escrow.accountLatestRevision(accountKey), open: await escrow.accountOpenAmount(accountKey) };
  t.evidence.source.after = stringify(after);
  t.check("account revision advanced by two per epoch and open amount by the recognised total", after.revision - before.revision === BigInt(aethirEpochs.length * 2) && after.open - before.open === aethirEpochs.reduce((sum, e) => sum + BigInt(e.amount), 0n));
});

await scenario("P2", "sim-aethir", "the network pays epoch-1 in full after the epoch closes (measured payout through the token path)", async (t) => {
  requireTransactions(t);
  const payerBefore = await sourceToken.balanceOf(personas.deployed["sim-aethir"].payer);
  const paid = await sim(["payout", "--persona", "sim-aethir", "--ref", "epoch-1", "--amount", "12000000", "--settlement", "epoch-1-close", "--name", "qa-aethir-epoch-1-payout"]);
  t.evidence.event = recordEvent(paid, facilities.aethir.name);
  const obligation = await escrow.obligation(accountKey, paid.obligationRef);
  t.evidence.obligation = { net: String(obligation.net), paid: String(obligation.paid), status: Number(obligation.status), settlementSeq: paid.settlementSeq };
  t.check("payout was measured at exactly the declared amount and closed the obligation (PAID)", paid.measured === "12000000" && String(obligation.paid) === "12000000" && Number(obligation.status) === 2, t.evidence.obligation);
  t.check("tokens actually left the persona payer", payerBefore - (await sourceToken.balanceOf(personas.deployed["sim-aethir"].payer)) === 12000000n);
});

await scenario("P3", "sim-aethir", "a QoS/uptime adjustment reduces epoch-2 by a signed correction (SLA)", async (t) => {
  requireTransactions(t);
  const corrected = await sim(["correct", "--persona", "sim-aethir", "--ref", "epoch-2", "--delta", "-2000000", "--reason", "SLA", "--name", "qa-aethir-epoch-2-correct"]);
  t.evidence.event = recordEvent(corrected, facilities.aethir.name);
  const obligation = await escrow.obligation(accountKey, corrected.obligationRef);
  t.evidence.obligation = { net: String(obligation.net), paid: String(obligation.paid), revision: String(obligation.revision), status: Number(obligation.status) };
  t.check("epoch-2 net is 10 tUSD after the −2 tUSD SLA correction and stays OPEN/assigned", String(obligation.net) === "10000000" && Number(obligation.status) === 1 && obligation.assignedTo === facilities.aethir.sourceKey, t.evidence.obligation);
});

const gpunetJobs = [
  { ref: "job-1", amount: "8000000", due: "86400" },
  { ref: "job-2", amount: "6000000", due: "45" }, // falls due almost immediately → overdue haircut in the borrowing base
  { ref: "job-3", amount: "5000000", due: "86400" },
];
await scenario("P4", "sim-gpunet", "marketplace job invoices are recognised and assigned; one falls due before financing", async (t) => {
  requireTransactions(t);
  t.evidence.events = [];
  for (const job of gpunetJobs) {
    const recognized = await sim(["recognize", "--persona", "sim-gpunet", "--ref", job.ref, "--amount", job.amount, "--due-seconds", job.due, "--name", `qa-gpunet-${job.ref}-recognize`]);
    t.evidence.events.push(recordEvent(recognized, facilities.gpunet.name));
    const assigned = await sim(["assign", "--persona", "sim-gpunet", "--ref", job.ref, "--facility", facilities.gpunet.name, "--name", `qa-gpunet-${job.ref}-assign`]);
    t.evidence.events.push(recordEvent(assigned, facilities.gpunet.name));
    const obligation = await escrow.obligation(accountKey, recognized.obligationRef);
    t.check(`${job.ref}: recognised for the SIM-GPUNET payer and assigned to ${facilities.gpunet.name}`, obligation.payer.toLowerCase() === personas.deployed["sim-gpunet"].payer && String(obligation.net) === job.amount && obligation.assignedTo === facilities.gpunet.sourceKey, { dueAt: String(obligation.dueAt), txHashes: [recognized.txHash, assigned.txHash] });
  }
});

await scenario("P5", "sim-gpunet", "streaming partial settlements on job-1 (3 tUSD, then 2 tUSD) by the persona payer", async (t) => {
  requireTransactions(t);
  const first = await sim(["payout", "--persona", "sim-gpunet", "--ref", "job-1", "--amount", "3000000", "--settlement", "job-1-stream-1", "--name", "qa-gpunet-job-1-payout-1"]);
  t.evidence.first = recordEvent(first, facilities.gpunet.name);
  const second = await sim(["payout", "--persona", "sim-gpunet", "--ref", "job-1", "--amount", "2000000", "--settlement", "job-1-stream-2", "--name", "qa-gpunet-job-1-payout-2"]);
  t.evidence.second = recordEvent(second, facilities.gpunet.name);
  const obligation = await escrow.obligation(accountKey, first.obligationRef);
  t.evidence.obligation = { net: String(obligation.net), paid: String(obligation.paid), status: Number(obligation.status), seqs: [first.settlementSeq, second.settlementSeq] };
  t.check("job-1 shows 5 of 8 tUSD paid and remains OPEN", String(obligation.paid) === "5000000" && Number(obligation.status) === 1, t.evidence.obligation);
  t.check("settlement sequence numbers are distinct and increasing", BigInt(second.settlementSeq) === BigInt(first.settlementSeq) + 1n);
});

await scenario("P6", "sim-gpunet", "chargeback: the issuer reverses the second stream settlement and tokens return to the payer", async (t) => {
  requireTransactions(t);
  const second = artifact("qa-gpunet-job-1-payout-2");
  const payerBefore = await sourceToken.balanceOf(personas.deployed["sim-gpunet"].payer);
  const cancelled = await sim(["cancel-payout", "--seq", second.settlementSeq, "--name", "qa-gpunet-job-1-chargeback"]);
  t.evidence.event = recordEvent({ ...cancelled, persona: "sim-gpunet" }, facilities.gpunet.name);
  const obligation = await escrow.obligation(accountKey, second.obligationRef);
  t.evidence.obligation = { net: String(obligation.net), paid: String(obligation.paid), status: Number(obligation.status) };
  t.check("job-1 paid amount fell back to 3 tUSD", String(obligation.paid) === "3000000", t.evidence.obligation);
  t.check("the reversed 2 tUSD actually returned to the persona payer", (await sourceToken.balanceOf(personas.deployed["sim-gpunet"].payer)) - payerBefore === 2000000n);
  t.check("the same settlement cannot be reversed twice (static)", (await expectRevert(() => escrow.connect(deployerWallet.connect(sepolia)).cancelPayout.staticCall(second.settlementSeq), [new Interface(abi("SourceEscrow"))])) === "PayoutAlreadyCancelled");
});

await scenario("P7", "sim-gpunet", "dispute: job-3 is cancelled by a full negative correction (CANCEL must zero the open amount)", async (t) => {
  requireTransactions(t);
  const cancelled = await sim(["correct", "--persona", "sim-gpunet", "--ref", "job-3", "--delta", "-5000000", "--reason", "CANCEL", "--name", "qa-gpunet-job-3-cancel"]);
  t.evidence.event = recordEvent(cancelled, facilities.gpunet.name);
  const obligation = await escrow.obligation(accountKey, cancelled.obligationRef);
  t.evidence.obligation = { net: String(obligation.net), paid: String(obligation.paid), status: Number(obligation.status), revision: String(obligation.revision) };
  t.check("job-3 is CANCELLED with net 0", Number(obligation.status) === 3 && String(obligation.net) === "0", t.evidence.obligation);
  t.check("a cancelled obligation can no longer be paid (static)", (await expectRevert(() => new Contract(personas.deployed["sim-gpunet"].payer, ["function payout(bytes32,bytes32,address,uint256,bytes32) returns (uint64,uint256)"], deployerWallet.connect(sepolia)).payout.staticCall(accountKey, cancelled.obligationRef, environment.source.tokens[0].address, 1000000n, id("after-cancel")), [new Interface(abi("SourceEscrow"))])) === "ObligationNotOpen");
});

await scenario("P8", "misuse", "source-side misuse is rejected by the escrow (unregistered payer, stranger issuer, overpayment, bad cancel, unknown account/token)", async (t) => {
  const result = await run("node", ["script/gpu/payer_sim.mjs", "negative", "--persona", "sim-gpunet", "--open-ref", "job-1", "--name", "qa-source-negative"], { timeoutMs: 180000 });
  const summary = hasArtifact("qa-source-negative") ? artifact("qa-source-negative") : null;
  t.evidence.checks = summary?.checks ?? null;
  for (const [label, check] of Object.entries(summary?.checks ?? {})) t.check(label, check.ok, check);
  t.check("negative suite exited cleanly", result.code === 0 && summary?.allOk === true, { code: result.code, stderr: result.stderr.slice(-200) });
});

await scenario("P9", "stranger", "a direct deposit by a non-payer is bucketed as unattributed and never becomes a payout", async (t) => {
  requireTransactions(t);
  const paidBefore = await escrow.accountPaidCumulative(accountKey);
  const revisionBefore = await escrow.accountLatestRevision(accountKey);
  const deposit = await sim(["unattributed", "--amount", "1000000", "--name", "qa-unattributed-deposit"]);
  t.evidence.deposit = deposit;
  t.check("deposit recorded with a deposit sequence and THIRD_PARTY_UNKNOWN origin (deployer is not a borrower wallet)", Boolean(deposit.depositSeq) && deposit.origin === 1, deposit);
  t.check("unattributed balance holds the deposit", BigInt(deposit.unattributedBalance) >= 1000000n);
  t.check("account paid total and revision are untouched (not a payout, not evidence)", (await escrow.accountPaidCumulative(accountKey)) === paidBefore && (await escrow.accountLatestRevision(accountKey)) === revisionBefore);
  const receipt = await sepolia.getTransactionReceipt(deposit.txHash);
  const topic = new Interface(abi("SourceEscrow")).getEvent("UnattributedDeposit").topicHash;
  const registry = new Contract(manifest.contracts.ProviderRegistry, abi("ProviderRegistry"), provider);
  t.check("the UnattributedDeposit topic is not a registered evidence meaning on Creditcoin", receipt.logs.some((log) => log.topics[0] === topic) && !(await registry.isEmitterRegistered(providerId, environment.source.emitters[0].address, topic)));
});

// ================================================================ N. Native proofs and consumption (official Attestcoin → Creditcoin)
await scenario("N1", "keeper", "every persona source transition is proven by the official Attestcoin service", async (t) => {
  requireTransactions(t);
  const pending = sourceEvents.filter((e) => !e.consumed);
  if (pending.length === 0) t.skip("no pending persona source events");
  const deadline = Date.now() / 1000 + 1800;
  const proofs = await Promise.all(pending.map((e) => officialProof(e.name, deadline)));
  t.evidence.proofs = pending.map((e, index) => ({ name: e.name, txHash: e.txHash, height: proofs[index]?.height ?? null, status: proofs[index]?.status ?? "PENDING" }));
  t.check(`official proofs became PROOF_READY for all ${pending.length} pending source transitions`, proofs.every(Boolean), t.evidence.proofs.filter((p) => p.status !== "PROOF_READY"));
  t.check("proof artifacts are bound to the release manifest and NATIVE_TESTNET profile", proofs.every((p) => p && p.manifestHash === config.manifestHash && p.executionProfile === "NATIVE_TESTNET" && p.verificationMethod === "ATTESTCOIN_NATIVE" && p.nativeAccepted === false));
});

await scenario("N2", "keeper", "persona transitions are consumed in source order and the destination ledger mirrors the source", async (t) => {
  requireTransactions(t);
  const pending = sourceEvents.filter((e) => !e.consumed && hasArtifact(`${e.name}.proof`));
  if (pending.length === 0) t.skip("nothing proven and pending");
  const statsBefore = await book.accountStats(providerId, accountKey);
  t.evidence.before = { eventsConsumed: String(statsBefore.eventsConsumed), openAmount: String(statsBefore.openAmount), paidCumulative: String(statsBefore.paidCumulative) };
  t.evidence.consumptions = [];
  for (const e of pending) {
    const outcome = await consumeStep(e.step, e.name, e.facilityName);
    t.evidence.consumptions.push(outcome.row ?? { name: e.name, code: outcome.code, stderr: outcome.stderr });
    t.check(`${e.name} (${e.step}) consumed on Creditcoin, audited proof-only`, outcome.ok, { code: outcome.code, status: outcome.row?.status, stderr: outcome.stderr });
    if (!outcome.ok) return;
    e.consumed = true;
    e.destinationTxHash = outcome.row.destinationTxHash;
    e.sourceEventId = outcome.row.sourceEventId;
    writeFileSync(eventsFile, JSON.stringify(sourceEvents, null, 2) + "\n");
  }
  const stats = await book.accountStats(providerId, accountKey);
  const source = { revision: await escrow.accountLatestRevision(accountKey), open: await escrow.accountOpenAmount(accountKey), paid: await escrow.accountPaidCumulative(accountKey) };
  t.evidence.after = { eventsConsumed: String(stats.eventsConsumed), openAmount: String(stats.openAmount), paidCumulative: String(stats.paidCumulative), source: stringify(source) };
  t.check("destination eventsConsumed equals the source account revision (no gap, no lag)", stats.eventsConsumed === source.revision, t.evidence.after);
  t.check("destination open and paid totals reconcile with the source escrow", stats.openAmount === source.open && stats.paidCumulative === source.paid, t.evidence.after);
  const aethir = await facilitySnapshot(facilities.aethir);
  const gpunet = await facilitySnapshot(facilities.gpunet);
  t.evidence.facilities = { aethir: aethir.receivables, gpunet: gpunet.receivables };
  const byNet = (rows, net) => rows.filter((r) => r.net === net);
  t.check("SIM-AETHIR: epoch-1 PAID in full, epoch-2 corrected to 10 tUSD, epoch-3 untouched, all with the persona payer", byNet(aethir.receivables, "12000000").some((r) => r.state === "PAID" && r.paid === "12000000") && byNet(aethir.receivables, "10000000").some((r) => r.state === "ASSIGNED" && r.paid === "0") && byNet(aethir.receivables, "12000000").some((r) => r.state === "ASSIGNED" && r.paid === "0") && aethir.receivables.every((r) => r.payer === personas.deployed["sim-aethir"].payer), aethir.receivables);
  t.check("SIM-GPUNET: job-1 paid 3 tUSD after the chargeback, job-2 open, job-3 CANCELLED with net 0", byNet(gpunet.receivables, "8000000").some((r) => r.state === "ASSIGNED" && r.paid === "3000000") && byNet(gpunet.receivables, "6000000").some((r) => r.state === "ASSIGNED" && r.paid === "0") && byNet(gpunet.receivables, "0").some((r) => r.state === "CANCELLED"), gpunet.receivables);
  const now = await chainNow();
  t.check("proof consumption created no destination debt on either facility", (await ledger.legalDebtAt(facilities.aethir.id, now)) === 0n && (await ledger.legalDebtAt(facilities.gpunet.id, now)) === 0n);
});

await scenario("N3", "misuse", "a consumed source log cannot be consumed twice (replay of the same proof)", async (t) => {
  const done = sourceEvents.find((e) => e.consumed && e.sourceEventId);
  if (!done) t.skip("no consumed persona event to replay");
  t.evidence.replayed = { name: done.name, sourceEventId: done.sourceEventId };
  t.check("EvidenceBook marks the source event as consumed", await evidence.isConsumed(done.sourceEventId));
  const outcome = await consumeStep(done.step, done.name, done.facilityName);
  t.evidence.tool = outcome.row;
  t.check("the consumption tool refuses to resubmit and re-audits the canonical receipt (ALREADY_CONSUMED)", outcome.ok && outcome.row?.status === "ALREADY_CONSUMED", outcome.row);
  const receipt = await provider.getTransactionReceipt(done.destinationTxHash);
  const original = { to: receipt.to, data: (await provider.getTransaction(done.destinationTxHash)).data, from: keeperWallet.address };
  t.check("replaying the identical ingest calldata reverts on chain (static)", (await expectRevert(() => provider.call(original))) !== "NO_REVERT");
});

let checkpointA = null;
await scenario("N4", "keeper", "checkpoint A: reserve → official proof → control observations → consumption makes persona receivables eligible", async (t) => {
  requireTransactions(t);
  const stats = await book.accountStats(providerId, accountKey);
  const checkpoint = await sim(["checkpoint", "--name", "qa-checkpoint-a"]);
  checkpointA = checkpoint;
  t.evidence.source = checkpoint;
  console.log(`  checkpoint window closes ${new Date(checkpoint.protectedUntil * 1000).toISOString()}`);
  const reserved = await run("node", ["script/gpu/payer_sim.mjs", "negative", "--persona", "sim-aethir", "--name", "qa-source-negative-reserved"], { timeoutMs: 180000 });
  const reservedChecks = hasArtifact("qa-source-negative-reserved") ? artifact("qa-source-negative-reserved").checks : {};
  t.check("while reserved, the account rejects source mutations (AccountReserved)", reservedChecks["reserved account rejects source mutations until the window closes"]?.ok === true, reservedChecks["reserved account rejects source mutations until the window closes"] ?? { code: reserved.code });
  const proof = await officialProof("qa-checkpoint-a", checkpoint.protectedUntil - 150);
  t.check("official proof became PROOF_READY inside the reservation window", Boolean(proof));
  if (!proof) return;
  for (const f of [facilities.aethir, facilities.gpunet]) {
    const observe = await run("node", ["script/gpu/native_tools.mjs", "observe", "--agreement", f.agreement, "--broadcast", approval], { timeoutMs: 180000 });
    const line = observe.stdout.split("\n").find((row) => row.startsWith("{"));
    t.check(`control observation refreshed for ${f.name}`, observe.code === 0 && Boolean(line), { code: observe.code, stderr: observe.stderr.slice(-200) });
    if (line) t.evidence[`observe_${f.name}`] = JSON.parse(line);
  }
  const outcome = await consumeStep("reserveCheckpoint", "qa-checkpoint-a", facilities.aethir.name);
  t.evidence.consumption = outcome.row;
  t.check("checkpoint consumed on Creditcoin and audited proof-only", outcome.ok, { code: outcome.code, status: outcome.row?.status, stderr: outcome.stderr });
  if (!outcome.ok) return;
  const consumed = await book.checkpoint(providerId, accountKey);
  t.check("consumed checkpoint revision equals consumed events", consumed.latestRevision === stats.eventsConsumed, { latestRevision: String(consumed.latestRevision), eventsConsumed: String(stats.eventsConsumed) });
  const aethir = await facilitySnapshot(facilities.aethir);
  const gpunet = await facilitySnapshot(facilities.gpunet);
  t.evidence.aethir = aethir;
  t.evidence.gpunet = gpunet;
  // SIM-AETHIR: epoch-2 (10) + epoch-3 (12) unpaid; epoch-1 is PAID. Advance rate 50 %.
  t.check("SIM-AETHIR facility: eligibleUnpaid = 22 tUSD (paid epoch excluded, SLA correction applied) and availableDraw = 11 tUSD", aethir.eligibleUnpaid === "22000000" && aethir.evaluation.availableDraw === "11000000", { eligible: aethir.eligibleUnpaid, evaluation: aethir.evaluation });
  // SIM-GPUNET: job-1 unpaid 5 + job-2 6 × 90 % (overdue haircut 10 %) = 10.4; job-3 cancelled. Advance rate 50 % → 5.2.
  t.check("SIM-GPUNET facility: eligibleUnpaid = 10.4 tUSD (partial payment, chargeback, overdue haircut, cancelled job) and availableDraw = 5.2 tUSD", gpunet.eligibleUnpaid === "10400000" && gpunet.evaluation.availableDraw === "5200000", { eligible: gpunet.eligibleUnpaid, evaluation: gpunet.evaluation });
  const fresh = await login(borrowerWallet);
  await discoverApiIds(fresh.token);
  for (const [key, f] of Object.entries({ aethir: facilities.aethir, gpunet: facilities.gpunet })) {
    if (!f.apiId) { t.check(`API lists ${f.name}`, false); continue; }
    const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.freshness === "FRESH" && meta.canonicalBlock.number >= outcome.row.destinationBlock, 180000, `API canonical block past consumption (${key})`);
    t.evidence[`api_${key}`] = { canonicalBlock: context.meta.canonicalBlock.number, availableDraw: context.data.availableDraw, drawBlockedReason: context.data.drawBlockedReason, debt: context.data.debt };
    t.check(`API availableDraw for ${f.name} matches the chain evaluation`, context.data.availableDraw === (key === "aethir" ? aethir : gpunet).evaluation.availableDraw && !context.data.drawBlockedReason, t.evidence[`api_${key}`]);
  }
});

// ================================================================ K. Credit operations on chain
await scenario("K1", "borrower", "SIM-AETHIR facility: 5 tUSD draw inside the window; a draw above availableDraw is refused", async (t) => {
  requireTransactions(t);
  const f = facilities.aethir;
  const before = await facilitySnapshot(f);
  if (before.evaluation.availableDraw === "0" || before.state !== "ACTIVE") t.skip(`facility not drawable (${before.state}, availableDraw ${before.evaluation.availableDraw})`);
  const over = await expectRevert(() => manager.connect(borrowerWallet).borrow.staticCall(f.id, unit(12), 0));
  t.check("a 12 tUSD draw (> availableDraw 11) reverts with ExceedsAvailableDraw", over === "ExceedsAvailableDraw", { observed: over });
  const stranger = await expectRevert(() => manager.connect(lpWallet).borrow.staticCall(f.id, unit(1), 0));
  t.check("a non-borrower wallet cannot draw (NotBorrower)", stranger === "NotBorrower", { observed: stranger });
  const balanceBefore = await token.balanceOf(borrowerWallet.address);
  const receipt = await sendTx(borrowerWallet, manager, "borrow", [f.id, unit(5), unit(5)], "borrow 5");
  const borrowed = logs(receipt, managerInterface, "Borrowed")[0];
  t.evidence.borrow = { txHash: receipt.hash, block: receipt.blockNumber, amount: String(borrowed?.args.amount), newDebt: String(borrowed?.args.newDebt) };
  t.check("Borrowed event: 5 tUSD, debt 5 tUSD", borrowed && borrowed.args.amount === unit(5) && borrowed.args.newDebt === unit(5), t.evidence.borrow);
  t.check("borrower received exactly 5 tUSD", (await token.balanceOf(borrowerWallet.address)) - balanceBefore === unit(5));
  const after = await facilitySnapshot(f);
  t.evidence.after = { debt: after.debt, availableDraw: after.evaluation.availableDraw };
  const room = BigInt(after.evaluation.availableDraw);
  t.check("availableDraw fell to ≈ 6 tUSD (11 − 5 − seconds of accrued interest)", room <= unit(6) && room > unit(6) - 1000n, t.evidence.after);
  const fresh = await login(borrowerWallet);
  const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.canonicalBlock.number >= receipt.blockNumber && BigInt(data.debt) >= unit(5), 180000, "API debt after draw");
  t.evidence.api = { debt: context.data.debt, principal: context.data.principal, availableDraw: context.data.availableDraw };
  t.check("API mirrors principal 5 tUSD and the reduced availableDraw", context.data.principal === "5000000" && BigInt(context.data.availableDraw) <= unit(6) && BigInt(context.data.availableDraw) > unit(6) - 1000n, t.evidence.api);
});

await scenario("K2", "borrower", "SIM-GPUNET facility: 3 tUSD draw against partially paid, haircut and cancelled invoices", async (t) => {
  requireTransactions(t);
  const f = facilities.gpunet;
  const before = await facilitySnapshot(f);
  if (before.evaluation.availableDraw === "0" || before.state !== "ACTIVE") t.skip(`facility not drawable (${before.state}, availableDraw ${before.evaluation.availableDraw})`);
  const receipt = await sendTx(borrowerWallet, manager, "borrow", [f.id, unit(3), unit(3)], "borrow 3");
  const borrowed = logs(receipt, managerInterface, "Borrowed")[0];
  t.evidence.borrow = { txHash: receipt.hash, block: receipt.blockNumber, amount: String(borrowed?.args.amount), newDebt: String(borrowed?.args.newDebt), availableBefore: before.evaluation.availableDraw };
  t.check("Borrowed event: 3 tUSD, debt 3 tUSD", borrowed && borrowed.args.amount === unit(3) && borrowed.args.newDebt === unit(3), t.evidence.borrow);
  const after = await facilitySnapshot(f);
  const room = BigInt(after.evaluation.availableDraw);
  // The checkpoint window may close between the draw and this read-back; then the correct answer is 0.
  const windowClosed = after.eligibleUnpaid === "0" && Number((await book.checkpoint(providerId, accountKey)).protectedUntil) <= after.at;
  t.check(windowClosed ? "availableDraw is 0 because the checkpoint window closed after the draw" : "availableDraw fell to ≈ 2.2 tUSD (5.2 − 3 − seconds of accrued interest)", windowClosed ? room === 0n : room <= unit("2.2") && room > unit("2.2") - 1000n, { availableDraw: after.evaluation.availableDraw, windowClosed });
});

await scenario("K3", "guardian", "SIM-GPUNET facility: guardian freeze blocks draws; the underwriter reactivates", async (t) => {
  requireTransactions(t);
  const f = facilities.gpunet;
  const state = STATES[Number(await manager.state(f.id))];
  if (state !== "ACTIVE") t.skip(`facility is ${state}`);
  const isGuardian = await rolesContract.hasRole(id("GUARDIAN"), deployerWallet.address);
  if (!isGuardian) t.skip("operator key does not hold GUARDIAN");
  const frozen = await sendTx(deployerWallet, manager, "freezeDraws", [f.id, id("QA_incident_drill")], "freezeDraws");
  t.evidence.freeze = { txHash: frozen.hash, block: frozen.blockNumber };
  t.check("facility is DRAW_FROZEN", STATES[Number(await manager.state(f.id))] === "DRAW_FROZEN");
  const blocked = await expectRevert(() => manager.connect(borrowerWallet).borrow.staticCall(f.id, unit(1), 0));
  t.check("a draw while frozen reverts", blocked !== "NO_REVERT", { observed: blocked });
  const repayable = await expectRevert(() => router.connect(borrowerWallet).repayExact.staticCall(f.id, unit(1)));
  const frozenDebt = await ledger.legalDebtAt(f.id, await chainNow());
  // With debt the router must accept the repayment; without debt the only acceptable refusal is NothingToRepay (never a state gate).
  // Without a router allowance the static call still reaches the token pull (TransferFailed): the state gate did not block it.
  t.check("repayment stays available while frozen (static repayExact is not blocked by the freeze)", frozenDebt > 0n ? ["NO_REVERT", "TransferFailed"].includes(repayable) : repayable === "NothingToRepay", { observed: repayable, debt: String(frozenDebt) });
  const fresh = await login(borrowerWallet);
  const listed = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "DRAW_FROZEN"), 240000, "API DRAW_FROZEN");
  t.check("API projects DRAW_FROZEN", listed.data.some((item) => item.facilityId === f.apiId && item.state === "DRAW_FROZEN"));
  const wrongRole = await expectRevert(() => manager.connect(deployerWallet).transition.staticCall(f.id, 3, id("QA_resume")));
  t.check("a non-underwriter cannot reactivate (NotRole)", wrongRole === "NotRole", { observed: wrongRole });
  const resumed = await sendTx(underwriterWallet, manager, "transition", [f.id, 3, id("QA_incident_cleared")], "transition ACTIVE");
  t.evidence.resume = { txHash: resumed.hash, block: resumed.blockNumber };
  t.check("facility is ACTIVE again", STATES[Number(await manager.state(f.id))] === "ACTIVE");
  const back = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "ACTIVE"), 240000, "API ACTIVE");
  t.check("API projects ACTIVE again", back.data.some((item) => item.facilityId === f.apiId && item.state === "ACTIVE"));
});

await scenario("K4", "third-party", "SIM-GPUNET facility: a settlement-rail stand-in repays 1 tUSD with repayFor (payer ≠ borrower)", async (t) => {
  requireTransactions(t);
  const f = facilities.gpunet;
  const now = await chainNow();
  const debtBefore = await ledger.legalDebtAt(f.id, now);
  if (debtBefore === 0n) t.skip("no debt on the SIM-GPUNET facility");
  const settlementRef = id("qa-sim-gpunet-rail-settlement-1");
  await sendTx(lpWallet, token, "approve", [config.contracts.repaymentRouter, unit(1)], "approve", { waitBlocks: 1 });
  const receipt = await sendTx(lpWallet, router, "repayFor", [f.id, unit(1), settlementRef], "repayFor 1");
  const repaid = logs(receipt, routerInterface, "Repaid")[0];
  t.evidence.repayFor = { txHash: receipt.hash, block: receipt.blockNumber, ...(repaid ? Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) : {}) };
  t.check("Repaid event: 1 tUSD applied (interest first, then principal) by a third-party payer", repaid && repaid.args.principalPaid + repaid.args.interestPaid + repaid.args.feePaid === unit(1) && repaid.args.newDebt < debtBefore, t.evidence.repayFor);
  t.check("the Repaid payer is the third-party wallet, not the borrower", repaid && repaid.args.payer.toLowerCase() === lpWallet.address.toLowerCase() && repaid.args.settlementRef === settlementRef);
  const fresh = await login(borrowerWallet);
  const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.canonicalBlock.number >= receipt.blockNumber, 180000, "API after repayFor");
  t.evidence.api = { debt: context.data.debt, principal: context.data.principal };
  t.check("API principal reflects the third-party repayment (< 3 tUSD)", BigInt(context.data.principal) === unit(3) - repaid.args.principalPaid, t.evidence.api);
});

await scenario("K5", "borrower", "SIM-AETHIR facility: partial repayment of 2 tUSD; interest accrues on the remainder", async (t) => {
  requireTransactions(t);
  const f = facilities.aethir;
  const now = await chainNow();
  const debtBefore = await ledger.legalDebtAt(f.id, now);
  if (debtBefore === 0n) t.skip("no debt on the SIM-AETHIR facility");
  await sendTx(borrowerWallet, token, "approve", [config.contracts.repaymentRouter, unit(2)], "approve", { waitBlocks: 1 });
  const receipt = await sendTx(borrowerWallet, router, "repayExact", [f.id, unit(2)], "repayExact 2");
  const repaid = logs(receipt, routerInterface, "Repaid")[0];
  t.evidence.repay = { txHash: receipt.hash, block: receipt.blockNumber, ...(repaid ? Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) : {}) };
  t.check("Repaid event: 2 tUSD applied, debt reduced, no excess", repaid && repaid.args.principalPaid + repaid.args.interestPaid + repaid.args.feePaid === unit(2) && repaid.args.excess === 0n && repaid.args.newDebt < debtBefore, t.evidence.repay);
  const later = await chainNow();
  const debtAfter = await ledger.legalDebtAt(f.id, later);
  const view = await ledger.view_(f.id);
  t.evidence.ledger = { debtAfter: String(debtAfter), principal: String(view.principal ?? view[2]), at: later };
  t.check("remaining legal debt ≈ 3 tUSD plus accrued interest (10 % APR, ACT/365)", debtAfter >= unit(3) && debtAfter < unit(3) + 10000n, t.evidence.ledger);
  const projected = await ledger.legalDebtAt(f.id, later + 86400);
  t.check("one day ahead the ledger projects ~0.000822 tUSD more interest on 3 tUSD (rate 1000 bps)", projected - debtAfter >= 800n && projected - debtAfter <= 850n, { projectedDelta: String(projected - debtAfter) });
});

await scenario("K6", "underwriter", "SIM-AETHIR facility: installment schedule → overdue → DELINQUENT → paid → cured back to ACTIVE", async (t) => {
  requireTransactions(t);
  const f = facilities.aethir;
  if (STATES[Number(await manager.state(f.id))] !== "ACTIVE") t.skip("facility is not ACTIVE");
  const now = await chainNow();
  if ((await ledger.legalDebtAt(f.id, now)) === 0n) t.skip("no debt");
  const dueAt = now + 90;
  const schedule = await sendTx(underwriterWallet, recovery, "setSchedule", [f.id, dueAt, 3600, 0, unit(1)], "setSchedule");
  t.evidence.schedule = { txHash: schedule.hash, dueAt, grace: 3600, dueAmount: "1000000" };
  const early = await expectRevert(() => recovery.connect(keeperWallet).markDelinquent.staticCall(f.id));
  t.check("before the due time markDelinquent reverts (NotDue)", early === "NotDue", { observed: early });
  while ((await chainNow()) <= dueAt) await sleep(10000);
  const marked = await sendTx(keeperWallet, recovery, "markDelinquent", [f.id], "markDelinquent");
  t.evidence.delinquent = { txHash: marked.hash, block: marked.blockNumber };
  t.check("facility is DELINQUENT after the installment is overdue", STATES[Number(await manager.state(f.id))] === "DELINQUENT");
  const blocked = await expectRevert(() => manager.connect(borrowerWallet).borrow.staticCall(f.id, unit(1), 0));
  t.check("draws are refused while DELINQUENT", blocked !== "NO_REVERT", { observed: blocked });
  const fresh = await login(borrowerWallet);
  const listed = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "DELINQUENT"), 240000, "API DELINQUENT");
  t.check("API projects DELINQUENT", listed.data.some((item) => item.facilityId === f.apiId && item.state === "DELINQUENT"));
  const notYet = await expectRevert(() => recovery.connect(keeperWallet).cure.staticCall(f.id));
  t.check("cure is refused until the installment is paid (NotDue)", notYet === "NotDue", { observed: notYet });
  await sendTx(borrowerWallet, token, "approve", [config.contracts.repaymentRouter, unit(1)], "approve", { waitBlocks: 1 });
  const paid = await sendTx(borrowerWallet, router, "repayExact", [f.id, unit(1)], "repayExact 1 (installment)");
  t.evidence.installment = { txHash: paid.hash, block: paid.blockNumber };
  const cured = await sendTx(keeperWallet, recovery, "cure", [f.id], "cure");
  t.evidence.cure = { txHash: cured.hash, block: cured.blockNumber };
  t.check("facility is ACTIVE again after the installment was paid and cured", STATES[Number(await manager.state(f.id))] === "ACTIVE");
  const back = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "ACTIVE"), 240000, "API ACTIVE after cure");
  t.check("API projects ACTIVE after the cure", back.data.some((item) => item.facilityId === f.apiId && item.state === "ACTIVE"));
});

await scenario("K7", "borrower", "both persona facilities are repaid in full; REPAID is reached and LP NAV grew by the interest", async (t) => {
  requireTransactions(t);
  const navBefore = await vault.nav();
  t.evidence.navBefore = String(navBefore);
  let interest = 0n;
  for (const [key, f] of Object.entries({ aethir: facilities.aethir, gpunet: facilities.gpunet })) {
    const now = await chainNow();
    const debt = await ledger.legalDebtAt(f.id, now);
    if (debt === 0n) { t.check(`${key}: already debt-free`, true); continue; }
    const cap = debt + unit("0.01");
    await sendTx(borrowerWallet, token, "approve", [config.contracts.repaymentRouter, cap], "approve", { waitBlocks: 1 });
    const receipt = await sendTx(borrowerWallet, router, "repayExact", [f.id, cap], `repayExact ${key}`);
    const repaid = logs(receipt, routerInterface, "Repaid")[0];
    interest += repaid.args.interestPaid;
    t.evidence[key] = { txHash: receipt.hash, block: receipt.blockNumber, ...Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) };
    t.check(`${key}: Repaid event ends with debt 0 and no excess transferred`, repaid.args.newDebt === 0n && repaid.args.excess === 0n, t.evidence[key]);
    t.check(`${key}: facility is REPAID (terminal)`, STATES[Number(await manager.state(f.id))] === "REPAID");
    const redraw = await expectRevert(() => manager.connect(borrowerWallet).borrow.staticCall(f.id, unit(1), 0));
    t.check(`${key}: a further draw on the REPAID facility reverts`, redraw !== "NO_REVERT", { observed: redraw });
  }
  const navAfter = await vault.nav();
  t.evidence.navAfter = String(navAfter);
  t.evidence.interestPaidNow = String(interest);
  t.check("vault NAV did not fall through the cycle (interest accrues to LPs)", navAfter >= navBefore, { navBefore: String(navBefore), navAfter: String(navAfter) });
  const fresh = await login(borrowerWallet);
  for (const f of [facilities.aethir, facilities.gpunet]) {
    const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data) => BigInt(data.debt) === 0n, 180000, `API debt 0 (${f.name})`);
    t.check(`API debt is zero on ${f.name}`, context.data.debt === "0");
  }
  // The API history must mirror every finalized Repaid of both facilities, whether sent in this run or earlier.
  const repayments = await http("/v1/repayments?limit=100", { token: fresh.token });
  t.evidence.apiRepayments = repayments.json?.data?.length ?? null;
  const listed = new Map((repayments.json?.data ?? []).map((row) => [`${row.onchainTxHash?.toLowerCase()}`, row]));
  const missing = [];
  let onchainCount = 0;
  for (const f of [facilities.aethir, facilities.gpunet]) {
    const events = await router.queryFilter(router.filters.Repaid(f.id), manifest.deploymentBlock, "latest");
    for (const event of events) {
      onchainCount += 1;
      const row = listed.get(event.transactionHash.toLowerCase());
      const matches = row && row.facilityId === f.apiId && row.repaymentApplied === true
        && BigInt(row.principalPaid.amount) === event.args.principalPaid && BigInt(row.interestPaid.amount) === event.args.interestPaid
        && BigInt(row.recordedNewDebt.amount) === event.args.newDebt && (row.payerAddress ?? "").toLowerCase() === event.args.payer.toLowerCase();
      if (!matches) missing.push({ facility: f.name, txHash: event.transactionHash, listed: Boolean(row) });
    }
  }
  t.evidence.repaidOnChain = onchainCount;
  t.evidence.repaidMissingFromApi = missing;
  t.check(`API repayment history lists all ${onchainCount} finalized Repaid legs of both facilities with matching amounts and payer`, repayments.status === 200 && onchainCount > 0 && missing.length === 0, { count: t.evidence.apiRepayments, missing });
});

await scenario("K8", "borrower", "browser regression on a fresh facility: checkpoint B → observation → consumption → borrow 1 / repay through the UI", async (t) => {
  requireTransactions(t);
  const f = facilities.browser;
  if (!f.apiId) t.skip("browser facility not registered in the API");
  const snapshot = await facilitySnapshot(f);
  if (snapshot.state !== "ACTIVE") t.skip(`facility is ${snapshot.state}`);
  if (checkpointA) {
    while ((await sepolia.getBlock("latest")).timestamp < checkpointA.protectedUntil + 5) await sleep(15000);
  }
  const stats = await book.accountStats(providerId, accountKey);
  const checkpoint = await sim(["checkpoint", "--name", "qa-checkpoint-b"]);
  t.evidence.source = checkpoint;
  console.log(`  checkpoint window closes ${new Date(checkpoint.protectedUntil * 1000).toISOString()}`);
  const proof = await officialProof("qa-checkpoint-b", checkpoint.protectedUntil - 150);
  t.check("official proof became PROOF_READY inside the window", Boolean(proof));
  if (!proof) return;
  const observe = await run("node", ["script/gpu/native_tools.mjs", "observe", "--agreement", f.agreement, "--broadcast", approval], { timeoutMs: 180000 });
  const observeLine = observe.stdout.split("\n").find((row) => row.startsWith("{"));
  t.check("control observation refreshed on chain", observe.code === 0 && Boolean(observeLine));
  const outcome = await consumeStep("reserveCheckpoint", "qa-checkpoint-b", f.name);
  t.evidence.consumption = outcome.row;
  t.check("checkpoint B consumed and audited proof-only", outcome.ok, { status: outcome.row?.status, stderr: outcome.stderr });
  if (!outcome.ok) return;
  t.check("consumed checkpoint revision equals consumed events", (await book.checkpoint(providerId, accountKey)).latestRevision === stats.eventsConsumed);
  const eligible = await facilitySnapshot(f);
  t.evidence.eligible = { eligibleUnpaid: eligible.eligibleUnpaid, availableDraw: eligible.evaluation.availableDraw };
  t.check("browser facility: eligibleUnpaid = 10 tUSD (epoch-4) and availableDraw = 5 tUSD", eligible.eligibleUnpaid === "10000000" && eligible.evaluation.availableDraw === "5000000", t.evidence.eligible);
  const fresh = await login(borrowerWallet);
  await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.freshness === "FRESH" && !data.drawBlockedReason && BigInt(data.availableDraw || 0) >= unit(1), Math.max(30000, (checkpoint.protectedUntil - 90) * 1000 - Date.now()), "API eligible draw");
  const before = await token.balanceOf(borrowerWallet.address);
  const flow = await delegate({ GPU_ALLOW_TESTNET_TRANSACTIONS: "1", GPU_SMOKE_PRIVATE_KEY: roles.borrower.privateKey, GPU_REVIEW_FLOW: "borrower", GPU_REVIEW_FACILITY_ID: f.apiId }, "K8");
  t.check("live borrower browser flow passed (borrow 1 tUSD, repay with 1.001 cap, debt 0)", flow.code === 0 && flow.summary?.result === "PASS", { code: flow.code, tail: flow.stdout.slice(-400) });
  t.evidence.transactions = [];
  for (const item of flow.submitted) {
    const receipt = await provider.getTransactionReceipt(item.hash);
    t.evidence.transactions.push({ ...item, block: receipt?.blockNumber ?? null, status: receipt?.status ?? null });
    t.check(`${item.action} receipt ${item.hash.slice(0, 10)}… succeeded`, receipt?.status === 1);
  }
  const repay = flow.submitted.find((item) => item.action === "repayExact");
  if (repay) {
    const receipt = await provider.getTransactionReceipt(repay.hash);
    const repaid = logs(receipt, routerInterface, "Repaid")[0];
    t.evidence.repaid = repaid ? Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) : null;
    t.check("Repaid log: principal 1 tUSD, no excess, debt 0", Boolean(repaid) && repaid.args.principalPaid === 1000000n && repaid.args.excess === 0n && repaid.args.newDebt === 0n, t.evidence.repaid);
    const after = await token.balanceOf(borrowerWallet.address);
    t.check("net token cost equals interest + fees only", Boolean(repaid) && before - after === repaid.args.interestPaid + repaid.args.feePaid, { delta: String(before - after) });
  }
  t.check("browser facility is REPAID", STATES[Number(await manager.state(f.id))] === "REPAID");
});

await scenario("K9", "lp", "LP read parity after the persona cycles: API position equals chain and the vault holds no borrower-owned residue", async (t) => {
  const fresh = await login(lpWallet);
  const position = await http("/v1/lp", { token: fresh.token });
  t.check("/v1/lp responds", position.status === 200);
  if (position.status !== 200) return;
  const shares = await vault.balanceOf(lpWallet.address);
  const nav = await vault.nav();
  Object.assign(t.evidence, { apiShares: position.json.data.shares, chainShares: String(shares), apiNav: position.json.data.nav, chainNav: String(nav), borrowerOwned: position.json.data.borrowerOwned, availableCash: position.json.data.availableCash });
  t.check("API shares equal chain shares", position.json.data.shares === String(shares), t.evidence);
  t.check("API NAV is within one block of the chain NAV", BigInt(position.json.data.nav) <= nav && nav - BigInt(position.json.data.nav) < unit("0.01"), t.evidence);
  t.check("no borrower-owned residue (unclaimed excess) after the cycles", position.json.data.borrowerOwned === "0", t.evidence);
});

// ================================================================ R. Non-payment: default, recovery and write-off (chain + API)
// The operator was paid by the network directly after financing and did not repay. This is the failure mode the
// product exists to control (E2); on the TEST_ONLY deployment control is SIMULATED, so the drill shows what the
// credit machinery does when collections do not arrive: delinquency, approved default, accrual freeze, recovery
// reserve, impairment and a treasury write-off that leaves the legal debt on the ledger.
const recoveryInterface = new Interface(abi("RecoveryManager"));
const vaultInterface = new Interface(abi("LendingVaultV2"));
const treasuryWallet = new Wallet(roles.treasury.privateKey, provider);
const recoveryRefs = { epoch: "epoch-5", amount: "12000000", draw: unit(4) };

await scenario("R0", "operator", "recovery-drill facility is open on chain, registered in the API and bound to the recovery manager", async (t) => {
  const f = facilities.recovery;
  const info = await manager.facilityInfo(f.id);
  t.check(`${f.name} exists and is ACTIVE with the borrower wallet`, info.exists && STATES[Number(info.state)] === "ACTIVE" && info.wallet.toLowerCase() === borrowerWallet.address.toLowerCase(), { state: STATES[Number(info.state)], wallet: info.wallet });
  const bound = (await manager.recoveryManager()).toLowerCase();
  t.check("CreditFacilityManager and LendingVaultV2 are bound to the deployed RecoveryManager", bound === manifest.contracts.RecoveryManager.toLowerCase() && (await vault.recoveryManager()).toLowerCase() === bound, { bound });
  const holders = { underwriter: await rolesContract.hasRole(id("UNDERWRITER"), underwriterWallet.address), guardian: await rolesContract.hasRole(id("GUARDIAN"), deployerWallet.address), servicer: await rolesContract.hasRole(id("SERVICER"), deployerWallet.address), treasury: await rolesContract.hasRole(id("TREASURY"), treasuryWallet.address) };
  t.check("the drill wallets hold UNDERWRITER / GUARDIAN / SERVICER / TREASURY", Object.values(holders).every(Boolean), holders);
  const fresh = await login(borrowerWallet);
  await discoverApiIds(fresh.token);
  t.check("API lists the facility", Boolean(f.apiId), { apiId: f.apiId });
  t.check("no debt, no receivables yet", (await ledger.legalDebtAt(f.id, await chainNow())) === 0n && (await book.facilityReceivables(f.id)).length === 0);
});

await scenario("R1", "sim-aethir", "epoch-5 reward is recognised for the drill facility, proven and consumed (financing basis exists)", async (t) => {
  requireTransactions(t);
  const f = facilities.recovery;
  if ((await book.facilityReceivables(f.id)).length > 0) t.skip("drill receivable already on chain");
  const recognized = await sim(["recognize", "--persona", "sim-aethir", "--ref", recoveryRefs.epoch, "--amount", recoveryRefs.amount, "--due-seconds", "86400", "--name", `qa-aethir-${recoveryRefs.epoch}-recognize`]);
  const assigned = await sim(["assign", "--persona", "sim-aethir", "--ref", recoveryRefs.epoch, "--facility", f.name, "--name", `qa-aethir-${recoveryRefs.epoch}-assign`]);
  const events = [recordEvent(recognized, f.name), recordEvent(assigned, f.name)];
  t.evidence.source = events;
  const deadline = Date.now() / 1000 + 1500;
  const proofs = await Promise.all(events.map((e) => officialProof(e.name, deadline)));
  t.check("official proofs became PROOF_READY for the recognition and the assignment", proofs.every(Boolean));
  if (!proofs.every(Boolean)) return;
  t.evidence.consumptions = [];
  for (const e of events) {
    const outcome = await consumeStep(e.step, e.name, f.name);
    t.evidence.consumptions.push(outcome.row ?? { name: e.name, code: outcome.code, stderr: outcome.stderr });
    t.check(`${e.name} consumed on Creditcoin, audited proof-only`, outcome.ok, { code: outcome.code, status: outcome.row?.status, stderr: outcome.stderr });
    if (!outcome.ok) return;
    e.consumed = true; e.destinationTxHash = outcome.row.destinationTxHash; e.sourceEventId = outcome.row.sourceEventId;
    writeFileSync(eventsFile, JSON.stringify(sourceEvents, null, 2) + "\n");
  }
  const snapshot = await facilitySnapshot(f);
  t.evidence.receivables = snapshot.receivables;
  t.check("the drill facility holds one ASSIGNED 12 tUSD receivable payable by SIM-AETHIR", snapshot.receivables.length === 1 && snapshot.receivables[0].state === "ASSIGNED" && snapshot.receivables[0].net === recoveryRefs.amount && snapshot.receivables[0].payer === personas.deployed["sim-aethir"].payer, snapshot.receivables);
});

let checkpointC = null;
await scenario("R2", "borrower", "checkpoint C makes epoch-5 eligible; the operator draws 4 tUSD against it", async (t) => {
  requireTransactions(t);
  const f = facilities.recovery;
  if ((await ledger.legalDebtAt(f.id, await chainNow())) > 0n) t.skip("drill facility already has debt");
  while ((await sepolia.getBlock("latest")).timestamp < Number(await escrow.protectedUntil(accountKey)) + 5) await sleep(15000);
  const stats = await book.accountStats(providerId, accountKey);
  const checkpoint = await sim(["checkpoint", "--name", "qa-checkpoint-c"]);
  checkpointC = checkpoint;
  t.evidence.source = checkpoint;
  console.log(`  checkpoint window closes ${new Date(checkpoint.protectedUntil * 1000).toISOString()}`);
  const proof = await officialProof("qa-checkpoint-c", checkpoint.protectedUntil - 150);
  t.check("official proof became PROOF_READY inside the reservation window", Boolean(proof));
  if (!proof) return;
  const observe = await run("node", ["script/gpu/native_tools.mjs", "observe", "--agreement", f.agreement, "--broadcast", approval], { timeoutMs: 180000 });
  t.check("control observation refreshed on chain", observe.code === 0 && observe.stdout.split("\n").some((row) => row.startsWith("{")), { code: observe.code, stderr: observe.stderr.slice(-200) });
  const outcome = await consumeStep("reserveCheckpoint", "qa-checkpoint-c", f.name);
  t.evidence.consumption = outcome.row;
  t.check("checkpoint C consumed and audited proof-only", outcome.ok, { status: outcome.row?.status, stderr: outcome.stderr });
  if (!outcome.ok) return;
  t.check("consumed checkpoint revision equals consumed events", (await book.checkpoint(providerId, accountKey)).latestRevision === stats.eventsConsumed);
  const eligible = await facilitySnapshot(f);
  t.evidence.eligible = { eligibleUnpaid: eligible.eligibleUnpaid, availableDraw: eligible.evaluation.availableDraw };
  t.check("eligibleUnpaid = 12 tUSD and availableDraw = 6 tUSD (50 % advance rate)", eligible.eligibleUnpaid === recoveryRefs.amount && eligible.evaluation.availableDraw === "6000000", t.evidence.eligible);
  const receipt = await sendTx(borrowerWallet, manager, "borrow", [f.id, recoveryRefs.draw, recoveryRefs.draw], "borrow 4");
  const borrowed = logs(receipt, managerInterface, "Borrowed")[0];
  t.evidence.borrow = { txHash: receipt.hash, block: receipt.blockNumber, amount: String(borrowed?.args.amount), newDebt: String(borrowed?.args.newDebt) };
  t.check("Borrowed event: 4 tUSD, debt 4 tUSD", borrowed && borrowed.args.amount === recoveryRefs.draw && borrowed.args.newDebt === recoveryRefs.draw, t.evidence.borrow);
  const fresh = await login(borrowerWallet);
  const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.canonicalBlock.number >= receipt.blockNumber && BigInt(data.debt) >= recoveryRefs.draw, 180000, "API debt after draw");
  t.evidence.api = { debt: context.data.debt, principal: context.data.principal, availableDraw: context.data.availableDraw };
  t.check("API mirrors principal 4 tUSD", context.data.principal === "4000000", t.evidence.api);
});

await scenario("R3", "sim-aethir", "the network pays epoch-5 to the operator after financing: the receivable is PAID, the borrowing base collapses, the debt does not move", async (t) => {
  requireTransactions(t);
  const f = facilities.recovery;
  const before = await facilitySnapshot(f);
  if (before.debt === "0") t.skip("drill facility has no debt");
  if (before.receivables.some((r) => r.state === "PAID")) t.skip("epoch-5 already paid");
  if (checkpointC) while ((await sepolia.getBlock("latest")).timestamp < checkpointC.protectedUntil + 5) await sleep(15000);
  const paid = await sim(["payout", "--persona", "sim-aethir", "--ref", recoveryRefs.epoch, "--amount", recoveryRefs.amount, "--settlement", `${recoveryRefs.epoch}-close`, "--name", `qa-aethir-${recoveryRefs.epoch}-payout`]);
  const event = recordEvent(paid, f.name);
  t.evidence.source = event;
  const obligation = await escrow.obligation(accountKey, paid.obligationRef);
  t.check("source: payout measured at 12 tUSD and the obligation is PAID", paid.measured === recoveryRefs.amount && Number(obligation.status) === 2, { measured: paid.measured, status: Number(obligation.status) });
  const proof = await officialProof(event.name, Date.now() / 1000 + 1500);
  t.check("official proof became PROOF_READY", Boolean(proof));
  if (!proof) return;
  const outcome = await consumeStep("settle", event.name, f.name);
  t.evidence.consumption = outcome.row;
  t.check("payout consumed on Creditcoin, audited proof-only (no debt or cash mutation)", outcome.ok && outcome.row?.financialAudit?.debtMutationEvents === 0, { status: outcome.row?.status, stderr: outcome.stderr });
  if (!outcome.ok) return;
  event.consumed = true; event.destinationTxHash = outcome.row.destinationTxHash; event.sourceEventId = outcome.row.sourceEventId;
  writeFileSync(eventsFile, JSON.stringify(sourceEvents, null, 2) + "\n");
  const after = await facilitySnapshot(f);
  t.evidence.after = { debt: after.debt, receivables: after.receivables, eligibleUnpaid: after.eligibleUnpaid, evaluation: after.evaluation };
  t.check("destination: epoch-5 is PAID in full", after.receivables.some((r) => r.state === "PAID" && r.paid === recoveryRefs.amount), after.receivables);
  t.check("borrowing base is now 0 (a paid receivable is not collateral) and no further draw is available", after.eligibleUnpaid === "0" && after.evaluation.availableDraw === "0", { eligibleUnpaid: after.eligibleUnpaid, availableDraw: after.evaluation.availableDraw });
  t.check("legal debt is unchanged by the source payout (debt falls only on a destination receipt)", BigInt(after.debt) >= recoveryRefs.draw && BigInt(after.debt) < recoveryRefs.draw + 10000n, { debt: after.debt });
  const fresh = await login(borrowerWallet);
  const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.canonicalBlock.number >= outcome.row.destinationBlock, 180000, "API after payout consumption");
  t.evidence.api = { availableDraw: context.data.availableDraw, drawBlockedReason: context.data.drawBlockedReason, debt: context.data.debt };
  t.check("API shows availableDraw 0 with a blocked reason while the debt stays at 4 tUSD", context.data.availableDraw === "0" && Boolean(context.data.drawBlockedReason) && BigInt(context.data.debt) >= recoveryRefs.draw, t.evidence.api);
});

await scenario("R4", "underwriter", "no repayment: schedule → DELINQUENT → dispute blocks default → approved default → DEFAULTED with accrual frozen", async (t) => {
  requireTransactions(t);
  const f = facilities.recovery;
  const state = STATES[Number(await manager.state(f.id))];
  if (state !== "ACTIVE") t.skip(`facility is ${state}`);
  const now = await chainNow();
  if ((await ledger.legalDebtAt(f.id, now)) === 0n) t.skip("no debt");
  const dueAt = now + 90;
  const grace = 60;
  const schedule = await sendTx(underwriterWallet, recovery, "setSchedule", [f.id, dueAt, grace, 0, unit(1)], "setSchedule");
  t.evidence.schedule = { txHash: schedule.hash, dueAt, grace, disputeWindow: 0, dueAmount: "1000000" };
  while ((await chainNow()) <= dueAt) await sleep(10000);
  const marked = await sendTx(keeperWallet, recovery, "markDelinquent", [f.id], "markDelinquent");
  t.evidence.delinquent = { txHash: marked.hash, block: marked.blockNumber };
  t.check("facility is DELINQUENT once the installment is overdue", STATES[Number(await manager.state(f.id))] === "DELINQUENT");
  const inGrace = await expectRevert(() => recovery.connect(underwriterWallet).approveDefault.staticCall(f.id, id("QA_non_payment")), [recoveryInterface]);
  t.check("inside the grace period a default cannot be approved (NotDue)", inGrace === "NotDue", { observed: inGrace });
  while ((await chainNow()) <= dueAt + grace) await sleep(10000);
  const unapproved = await expectRevert(() => recovery.connect(deployerWallet).declareDefault.staticCall(f.id), [recoveryInterface]);
  t.check("the guardian cannot declare a default the underwriter has not approved (NotApproved)", unapproved === "NotApproved", { observed: unapproved });
  const disputed = await sendTx(deployerWallet, recovery, "setDispute", [f.id, true], "setDispute true");
  t.evidence.dispute = { opened: disputed.hash };
  const whileDisputed = await expectRevert(() => recovery.connect(underwriterWallet).approveDefault.staticCall(f.id, id("QA_non_payment")), [recoveryInterface]);
  t.check("an open servicer dispute blocks default approval (DisputeOpen)", whileDisputed === "DisputeOpen", { observed: whileDisputed });
  const cleared = await sendTx(deployerWallet, recovery, "setDispute", [f.id, false], "setDispute false");
  t.evidence.dispute.cleared = cleared.hash;
  const wrongRole = await expectRevert(() => recovery.connect(deployerWallet).approveDefault.staticCall(f.id, id("QA_non_payment")), [recoveryInterface]);
  t.check("only the underwriter approves a default (NotRole for the servicer key)", wrongRole === "NotRole", { observed: wrongRole });
  const approved = await sendTx(underwriterWallet, recovery, "approveDefault", [f.id, id("QA_non_payment")], "approveDefault");
  t.evidence.approved = { txHash: approved.hash, reason: id("QA_non_payment") };
  t.check("DefaultApproved event carries the reason", logs(approved, recoveryInterface, "DefaultApproved").some((e) => e.args.reason === id("QA_non_payment")));
  const declared = await sendTx(deployerWallet, recovery, "declareDefault", [f.id], "declareDefault");
  t.evidence.defaulted = { txHash: declared.hash, block: declared.blockNumber };
  t.check("facility is DEFAULTED", STATES[Number(await manager.state(f.id))] === "DEFAULTED");
  t.check("StateChanged(DELINQUENT → DEFAULTED) was emitted by the manager", logs(declared, managerInterface, "StateChanged").some((e) => STATES[Number(e.args.to ?? e.args[2])] === "DEFAULTED"));
  const at = await chainNow();
  const frozenNow = await ledger.legalDebtAt(f.id, at);
  const frozenLater = await ledger.legalDebtAt(f.id, at + 30 * 86400);
  t.evidence.accrual = { frozen: await ledger.isFrozen(f.id), debtNow: String(frozenNow), debtIn30Days: String(frozenLater) };
  t.check("interest accrual is frozen at default (30 days ahead projects the same legal debt)", (await ledger.isFrozen(f.id)) && frozenLater === frozenNow, t.evidence.accrual);
  const draw = await expectRevert(() => manager.connect(borrowerWallet).borrow.staticCall(f.id, unit(1), 0));
  t.check("draws are refused while DEFAULTED", draw !== "NO_REVERT", { observed: draw });
  const repayable = await expectRevert(() => router.connect(borrowerWallet).repayExact.staticCall(f.id, unit(1)));
  // Without a router allowance the static call still reaches the token pull (TransferFailed): the state gate did not block it.
  t.check("the borrower may still repay while DEFAULTED (static repayExact is not blocked by the state gate)", ["NO_REVERT", "TransferFailed"].includes(repayable), { observed: repayable });
  const fresh = await login(borrowerWallet);
  const listed = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "DEFAULTED"), 240000, "API DEFAULTED");
  t.check("API projects DEFAULTED", listed.data.some((item) => item.facilityId === f.apiId && item.state === "DEFAULTED"));
});

await scenario("R5", "servicer", "recovery: a pledged reserve is applied to the debt through the router; the reserve cannot be pulled back while debt remains", async (t) => {
  requireTransactions(t);
  const f = facilities.recovery;
  const state = STATES[Number(await manager.state(f.id))];
  if (state !== "DEFAULTED" && state !== "RECOVERY") t.skip(`facility is ${state}`);
  if (state === "DEFAULTED") {
    const opened = await sendTx(deployerWallet, recovery, "beginRecovery", [f.id], "beginRecovery");
    t.evidence.recovery = { txHash: opened.hash, block: opened.blockNumber };
  }
  t.check("facility is RECOVERY", STATES[Number(await manager.state(f.id))] === "RECOVERY");
  const debtBefore = await ledger.legalDebtAt(f.id, await chainNow());
  const pledge = unit(1);
  // The reserve owner is a third party (the LP wallet stands in for a guarantor); the borrower cannot hijack it.
  await sendTx(lpWallet, token, "approve", [manifest.contracts.RecoveryManager, pledge], "approve reserve", { waitBlocks: 1 });
  const funded = await sendTx(lpWallet, recovery, "fundReserve", [f.id, pledge], "fundReserve 1");
  t.evidence.reserve = { txHash: funded.hash, owner: lpWallet.address, amount: String(pledge) };
  t.check("ReserveFunded event: 1 tUSD pledged by the reserve owner", logs(funded, recoveryInterface, "ReserveFunded").some((e) => e.args.amount === pledge && e.args.owner.toLowerCase() === lpWallet.address.toLowerCase()));
  const stranger = await expectRevert(() => recovery.connect(borrowerWallet).fundReserve.staticCall(f.id, pledge), [recoveryInterface]);
  t.check("a second wallet cannot take over the reserve (NotReserveOwner)", stranger === "NotReserveOwner", { observed: stranger });
  const locked = await expectRevert(() => recovery.connect(lpWallet).returnReserve.staticCall(f.id), [recoveryInterface]);
  t.check("the reserve cannot be returned while debt is outstanding (OutstandingDebt)", locked === "OutstandingDebt", { observed: locked });
  const applied = await sendTx(deployerWallet, recovery, "applyReserve", [f.id], "applyReserve");
  const repaid = logs(applied, routerInterface, "Repaid")[0];
  t.evidence.applied = { txHash: applied.hash, block: applied.blockNumber, ...(repaid ? Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) : {}) };
  t.check("ReserveApplied 1 tUSD → Repaid event with the RecoveryManager as payer", logs(applied, recoveryInterface, "ReserveApplied").some((e) => e.args.amount === pledge) && repaid && repaid.args.payer.toLowerCase() === manifest.contracts.RecoveryManager.toLowerCase() && repaid.args.principalPaid + repaid.args.interestPaid + repaid.args.feePaid === pledge, t.evidence.applied);
  const debtAfter = await ledger.legalDebtAt(f.id, await chainNow());
  t.check("legal debt fell by exactly the applied reserve (accrual stays frozen)", debtBefore - debtAfter === pledge, { debtBefore: String(debtBefore), debtAfter: String(debtAfter) });
  const fresh = await login(borrowerWallet);
  const listed = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "RECOVERY"), 240000, "API RECOVERY");
  t.check("API projects RECOVERY", listed.data.some((item) => item.facilityId === f.apiId && item.state === "RECOVERY"));
  const context = await pollApi(`/v1/facilities/${f.apiId}/transaction-context`, fresh.token, (data, meta) => meta.canonicalBlock.number >= applied.blockNumber, 180000, "API after applyReserve");
  t.evidence.api = { debt: context.data.debt, principal: context.data.principal };
  t.check("API debt equals the chain debt after the reserve was applied", BigInt(context.data.debt) === debtAfter, t.evidence.api);
});

await scenario("R6", "treasury", "loss: the underwriter impairs the remainder (LP NAV falls), the treasury writes off → CLOSED_WITH_LOSS; the legal debt survives", async (t) => {
  requireTransactions(t);
  const f = facilities.recovery;
  if (STATES[Number(await manager.state(f.id))] !== "RECOVERY") t.skip("facility is not in RECOVERY");
  const debt = await ledger.legalDebtAt(f.id, await chainNow());
  const navBefore = await vault.nav();
  const impairId = id("qa-loss-epoch-5-impairment");
  const writeOffId = id("qa-loss-epoch-5-writeoff");
  const tooMuch = await expectRevert(() => recovery.connect(underwriterWallet).impair.staticCall(f.id, impairId, debt + 1n), [recoveryInterface, vaultInterface]);
  t.check("impairment above the exposure is refused (ImpairmentExceedsExposure)", tooMuch === "ImpairmentExceedsExposure", { observed: tooMuch });
  const impaired = await sendTx(underwriterWallet, recovery, "impair", [f.id, impairId, debt], "impair");
  const navImpaired = await vault.nav();
  t.evidence.impairment = { txHash: impaired.hash, amount: String(debt), navBefore: String(navBefore), navAfter: String(navImpaired) };
  t.check("LP NAV fell by exactly the impaired amount (book loss recognised before write-off)", navBefore - navImpaired === debt, t.evidence.impairment);
  t.check("vault records the impairment against the facility", (await vault.impairmentOf(f.id)) === debt);
  const lp = await login(lpWallet);
  const position = await pollApi("/v1/lp", lp.token, (data) => BigInt(data.nav) <= navImpaired, 180000, "API NAV after impairment");
  t.check("API LP NAV reflects the impairment", BigInt(position.data.nav) <= navImpaired && navImpaired - BigInt(position.data.nav) < unit("0.01"), { apiNav: position.data.nav, chainNav: String(navImpaired) });
  const duplicate = await expectRevert(() => recovery.connect(underwriterWallet).approveWriteOff.staticCall(f.id, impairId), [recoveryInterface]);
  t.check("a loss id cannot be reused for the write-off approval (NotApproved)", duplicate === "NotApproved", { observed: duplicate });
  const unapproved = await expectRevert(() => recovery.connect(treasuryWallet).writeOff.staticCall(f.id, writeOffId), [recoveryInterface]);
  t.check("the treasury cannot write off without the underwriter's approval (NotApproved)", unapproved === "NotApproved", { observed: unapproved });
  const approved = await sendTx(underwriterWallet, recovery, "approveWriteOff", [f.id, writeOffId], "approveWriteOff");
  t.evidence.approval = { txHash: approved.hash, lossId: writeOffId };
  const wrongRole = await expectRevert(() => recovery.connect(underwriterWallet).writeOff.staticCall(f.id, writeOffId), [recoveryInterface]);
  t.check("only TREASURY executes the write-off (NotRole)", wrongRole === "NotRole", { observed: wrongRole });
  const written = await sendTx(treasuryWallet, recovery, "writeOff", [f.id, writeOffId], "writeOff");
  const loss = logs(written, recoveryInterface, "LossApplied").find((e) => e.args.writeOff === true);
  const navAfter = await vault.nav();
  t.evidence.writeOff = { txHash: written.hash, block: written.blockNumber, loss: loss ? String(loss.args.amount) : null, navAfter: String(navAfter) };
  t.check("LossApplied(writeOff=true) for the remaining debt", Boolean(loss) && loss.args.amount === debt, t.evidence.writeOff);
  t.check("facility is CLOSED_WITH_LOSS (terminal)", STATES[Number(await manager.state(f.id))] === "CLOSED_WITH_LOSS" && (await manager.isTransitionAllowed(10, 3)) === false);
  t.check("the vault marks the facility written off and released its impairment; NAV is unchanged by the write-off itself", (await vault.isWrittenOff(f.id)) && (await vault.impairmentOf(f.id)) === 0n && navAfter === navImpaired, { navImpaired: String(navImpaired), navAfter: String(navAfter) });
  const legal = await ledger.legalDebtAt(f.id, await chainNow());
  t.check("write-off is not forgiveness: the ledger still carries the legal debt", legal === debt, { legalDebt: String(legal) });
  const draw = await expectRevert(() => manager.connect(borrowerWallet).borrow.staticCall(f.id, unit(1), 0));
  t.check("no draw is possible on a written-off facility", draw !== "NO_REVERT", { observed: draw });
  const fresh = await login(borrowerWallet);
  const listed = await pollApi("/v1/facilities?limit=100", fresh.token, (data) => data.some((item) => item.facilityId === f.apiId && item.state === "CLOSED_WITH_LOSS"), 240000, "API CLOSED_WITH_LOSS");
  t.check("API projects CLOSED_WITH_LOSS", listed.data.some((item) => item.facilityId === f.apiId && item.state === "CLOSED_WITH_LOSS"));
  const after = await http("/v1/lp", { token: lp.token });
  t.check("API LP NAV still equals the chain NAV after the write-off", after.status === 200 && BigInt(after.json.data.nav) <= navAfter && navAfter - BigInt(after.json.data.nav) < unit("0.01"), { apiNav: after.json?.data?.nav, chainNav: String(navAfter) });
});

persist();
const failed = results.filter((r) => r.status === "FAIL");
console.log(`\n${results.filter((r) => r.status === "PASS").length} PASS / ${failed.length} FAIL / ${results.filter((r) => r.status === "SKIPPED").length} SKIPPED`);
if (failed.length) console.log(`FAILED: ${failed.map((r) => r.id).join(", ")}`);
process.exit(failed.length ? 1 : 0);
