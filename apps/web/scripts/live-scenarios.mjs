import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import {
  Contract,
  FetchRequest,
  Interface,
  JsonRpcProvider,
  Wallet,
  formatUnits,
  id,
  keccak256,
  parseUnits,
} from "ethers";

// Persona scenarios against the DEPLOYED TEST_ONLY environment.
// See docs/gpu/scenarios/live-user-scenarios.md for the catalog.
// Keys and session tokens stay in memory; output carries public identifiers only.
const webUrl = (process.env.GPU_REVIEW_WEB_URL || "").replace(/\/$/, "");
const apiUrl = (process.env.GPU_REVIEW_API_URL || "").replace(/\/$/, "");
assert.ok(webUrl && apiUrl, "Set GPU_REVIEW_WEB_URL and GPU_REVIEW_API_URL");
const keyFile = process.env.GPU_SCENARIO_KEYS;
assert.ok(keyFile && existsSync(keyFile), "GPU_SCENARIO_KEYS must name the role key file");
const allowTransactions = process.env.GPU_ALLOW_TESTNET_TRANSACTIONS === "1";
const allowNativeRefresh = process.env.GPU_SCENARIO_NATIVE_REFRESH === "1";
if (allowNativeRefresh) {
  assert.ok(allowTransactions, "Native refresh requires GPU_ALLOW_TESTNET_TRANSACTIONS=1");
  assert.equal(process.env.GPU_SCENARIO_APPROVAL, "user-20260914", "Explicit approval reference required");
}
const only = process.env.GPU_SCENARIO_ONLY
  ? new Set(process.env.GPU_SCENARIO_ONLY.split(",").map((item) => item.trim()))
  : null;
const outFile = process.env.GPU_SCENARIO_OUT ? path.resolve(process.env.GPU_SCENARIO_OUT) : "";
const facilityId = process.env.GPU_REVIEW_FACILITY_ID || "5DCNY1D03WP51EAK4V024YB60F";
const priorRepaymentHash =
  process.env.GPU_REVIEW_EXPECT_REPAYMENT_TX ||
  "0xa369810d67bb59695e7acc87d4163d1a1257876d6fba28635ee154dd1bc2fe78";
const here = fileURLToPath(new URL(".", import.meta.url));
const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
const roles = JSON.parse(readFileSync(keyFile, "utf8"));
const manifest = JSON.parse(
  readFileSync(`${repoRoot}config/gpu/deployments/cc3-testnet.json`, "utf8"),
);
const abi = (name) =>
  JSON.parse(readFileSync(`${repoRoot}test/fixtures/gpu/abi/${name}.json`, "utf8"));

const config = await (await fetch(`${apiUrl}/v1/config`)).json();
assert.equal(config.executionProfile, "NATIVE_TESTNET");
assert.equal(config.chainId, 102031);
assert.equal(config.asset.testOnly, true);
const rpcRequest = new FetchRequest(config.rpcUrl);
rpcRequest.timeout = 12000;
const provider = new JsonRpcProvider(rpcRequest, undefined, { batchMaxCount: 1 });
assert.equal((await provider.getNetwork()).chainId, 102031n);
const token = new Contract(config.asset.address, abi("GpuTestToken"), provider);
const vault = new Contract(config.contracts.vault, abi("LendingVaultV2"), provider);
const manager = new Contract(config.contracts.manager, abi("CreditFacilityManager"), provider);
const book = new Contract(manifest.contracts.ReceivableBook, abi("ReceivableBook"), provider);
const routerInterface = new Interface(abi("RepaymentRouter"));
const lpWallet = new Wallet(roles.lp.privateKey, provider);
const borrowerWallet = new Wallet(roles.borrower.privateKey, provider);
const oneToken = parseUnits("1", 6);
const apiOrigin = new URL(apiUrl).origin;
const rpcOrigin = new URL(config.rpcUrl).origin;
const shotDir = `${here}../node_modules/.cache/playwright/scenarios/`;
mkdirSync(shotDir, { recursive: true });

// ---------------------------------------------------------------- helpers
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function http(path, { method = "GET", token: bearer, body, headers = {} } = {}) {
  const response = await fetch(`${apiUrl}${path}`, {
    method,
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return { status: response.status, json, text, headers: response.headers };
}
async function challenge(wallet, chainId = config.chainId) {
  const result = await http("/gpu/auth/challenge", { method: "POST", body: { wallet: wallet.address, chainId } });
  assert.equal(result.status, 200, `challenge ${result.text.slice(0, 200)}`);
  return result.json;
}
async function sign(wallet, typedData) {
  const types = { ...typedData.types };
  delete types.EIP712Domain;
  return wallet.signTypedData(typedData.domain, types, typedData.message);
}
async function login(wallet) {
  const issued = await challenge(wallet);
  const signature = await sign(wallet, issued.typedData);
  const verified = await http("/gpu/auth/verify", {
    method: "POST",
    body: { wallet: wallet.address, chainId: config.chainId, nonce: issued.nonce, signature },
  });
  assert.equal(verified.status, 200, `verify ${verified.text.slice(0, 200)}`);
  return verified.json;
}
async function pollApi(path, bearer, predicate, timeoutMs = 180000, label = path) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await http(path, { token: bearer });
    if (last.status === 200 && predicate(last.json.data, last.json.meta)) return last.json;
    await sleep(3000);
  }
  throw new Error(`${label} did not reach the expected state: ${last?.text.slice(0, 300)}`);
}
function run(command, args, { cwd = repoRoot, env = {}, timeoutMs = 900000, onLine } = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, env: { ...process.env, ...env } });
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
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
  });
}

const browser = await chromium.launch({
  executablePath:
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ||
    (existsSync("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
      ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      : undefined),
});
const allowedReads = new Set([
  "eth_blockNumber", "eth_getBlockByNumber", "eth_getTransactionByHash", "eth_getTransactionReceipt",
  "eth_getCode", "eth_call", "eth_estimateGas", "eth_gasPrice", "eth_getBalance",
  "eth_getTransactionCount", "eth_maxPriorityFeePerGas",
]);
/** Synthetic EIP-1193 wallet bound to a real key. Transactions are refused unless explicitly allowed. */
async function openWallet({ wallet, chainId = 102031, switchBehavior = "accept", viewport = { width: 1440, height: 1000 } }) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const state = { errors: [], walletCalls: [], apiRequests: [], externalRequests: [], chainId, token: null, expiresAt: 0 };
  page.on("pageerror", (error) => state.errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === apiOrigin) state.apiRequests.push(`${request.method()} ${url.pathname}`);
    else if (url.origin !== new URL(webUrl).origin && !url.protocol.startsWith("data"))
      state.externalRequests.push(`${request.method()} ${url.origin}${url.pathname}`);
  });
  page.on("response", async (response) => {
    if (new URL(response.url()).pathname === "/gpu/auth/verify" && response.status() === 200) {
      const value = await response.json();
      state.token = value.token;
      state.expiresAt = value.expiresAt;
    }
  });
  await page.exposeFunction("liveWalletRequest", async ({ method, params = [] }) => {
    state.walletCalls.push(method);
    if (method === "eth_accounts" || method === "eth_requestAccounts") return [wallet.address];
    if (method === "eth_chainId") return `0x${state.chainId.toString(16)}`;
    if (method === "wallet_switchEthereumChain") {
      if (switchBehavior === "reject") throw new Error("User rejected the network switch.");
      state.chainId = Number(params[0].chainId);
      return null;
    }
    if (method === "eth_signTypedData_v4") {
      const typed = JSON.parse(params[1]);
      assert.equal(typed.domain.name, "Rackline API Login");
      assert.equal(Number(typed.domain.chainId), config.chainId);
      return sign(wallet, typed);
    }
    if (method === "eth_sendTransaction") throw new Error("SCENARIO_POLICY: this scenario never submits a transaction");
    assert.ok(allowedReads.has(method), `Unsupported wallet request ${method}`);
    return provider.send(method, params);
  });
  await page.addInitScript(() =>
    Reflect.set(window, "ethereum", {
      request: (args) => window.liveWalletRequest(args),
      on() {},
      removeListener() {},
    }),
  );
  const connect = async () => {
    await page.getByRole("button", { name: "Connect wallet", exact: true }).first().click();
  };
  const signIn = async () => {
    await page.goto(`${webUrl}/app`);
    await connect();
    await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  };
  const navigate = async (name) => {
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    if (!(await nav.isVisible())) await page.getByRole("button", { name: "Open navigation" }).click();
    await nav.getByRole("button", { name, exact: true }).click();
  };
  const fits = async () =>
    page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  const shot = async (name) => {
    await page.screenshot({ path: `${shotDir}${name}.png`, fullPage: true });
  };
  return { page, context, state, connect, signIn, navigate, fits, shot, close: () => context.close() };
}

// ---------------------------------------------------------------- scenario registry
class Skip extends Error {}
const results = [];
const startedAt = new Date().toISOString();
// GPU_SCENARIO_MERGE=1 keeps prior records of filtered-out scenarios from an existing output file.
const prior = process.env.GPU_SCENARIO_MERGE === "1" && outFile && existsSync(outFile)
  ? JSON.parse(readFileSync(outFile, "utf8"))
  : null;
const merged = () =>
  results.map((record) =>
    record.status === "SKIPPED" && record.reason?.startsWith("filtered") && prior
      ? prior.scenarios.find((item) => item.id === record.id) ?? record
      : record,
  );
function persist() {
  if (!outFile) return;
  const summary = {
    schemaVersion: "1.0",
    executionProfile: "NATIVE_TESTNET",
    scope: "LIVE_USER_SCENARIOS",
    webUrl,
    apiUrl,
    chainId: 102031,
    deploymentId: config.deploymentId,
    manifestHash: config.manifestHash,
    startedAt: prior?.startedAt ?? startedAt,
    updatedAt: new Date().toISOString(),
    runs: [...(prior?.runs ?? (prior ? [prior.startedAt] : [])), startedAt].filter((value, index, all) => all.indexOf(value) === index),
    wallets: { lp: lpWallet.address, borrower: borrowerWallet.address, keeper: roles.keeper.address },
    partnerRevenue: "SIMULATED",
    nativeProofAcceptance: merged().some((r) => r.id === "D3b" && r.status === "PASS")
      ? "REFRESHED_CHECKPOINT_CONSUMED"
      : "NOT_ASSERTED",
    totals: {
      pass: merged().filter((r) => r.status === "PASS").length,
      fail: merged().filter((r) => r.status === "FAIL").length,
      skipped: merged().filter((r) => r.status === "SKIPPED").length,
    },
    scenarios: merged(),
    ...(prior?.history ? { history: prior.history } : {}),
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
      record.checks.push({ name, ok: Boolean(ok), ...(detail === undefined ? {} : { detail }) });
      console.log(`  ${ok ? "ok  " : "FAIL"} ${name}${detail === undefined ? "" : " " + JSON.stringify(detail).slice(0, 300)}`);
      return Boolean(ok);
    },
    skip(reason) {
      throw new Skip(reason);
    },
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
  record.finishedAt = new Date().toISOString();
  console.log(`  => ${record.status}`);
  results.push(record);
  persist();
  return record;
}

// ================================================================ A. Visitor
await scenario("A1", "visitor", "public pages render at desktop and mobile widths", async (t) => {
  for (const path of ["/", "/app", "/demo"]) {
    const response = await fetch(`${webUrl}${path}`);
    t.check(`GET ${path} is 200 HTML`, response.status === 200 && /text\/html/.test(response.headers.get("content-type") || ""), {
      status: response.status,
    });
  }
  for (const [width, height] of [[1440, 1000], [390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const path of ["/", "/app"]) {
      await page.goto(`${webUrl}${path}`);
      await page.waitForLoadState("networkidle");
      const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
      t.check(`${path} fits ${width}px without horizontal overflow`, fits);
      await page.screenshot({ path: `${shotDir}A1-${path.replace("/", "") || "home"}-${width}.png`, fullPage: true });
    }
    t.check(`/app shows Connect wallet at ${width}px`, await page.getByRole("button", { name: "Connect wallet", exact: true }).first().isVisible());
    t.check(`no uncaught page errors at ${width}px`, errors.length === 0, errors);
    await context.close();
  }
});

await scenario("A2", "visitor", "fixture demo makes no API or RPC calls", async (t) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const external = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if ([apiOrigin, rpcOrigin].includes(url.origin)) external.push(`${request.method()} ${url.origin}${url.pathname}`);
  });
  await page.goto(`${webUrl}/demo`);
  await page.waitForLoadState("networkidle");
  const buttons = await page.getByRole("button").count();
  t.check("demo renders interactive controls", buttons > 3, { buttons });
  for (const button of await page.getByRole("button").all()) {
    const label = (await button.textContent())?.trim() || "";
    if (/^(Borrow|Lend|Provider|Operations|Activity|Overview)$/i.test(label)) {
      await button.click().catch(() => {});
    }
  }
  await page.waitForLoadState("networkidle");
  t.check("no API or RPC origin request from /demo", external.length === 0, external);
  t.check("no uncaught page errors", errors.length === 0, errors);
  t.evidence.requestsObserved = external;
  await context.close();
});

await scenario("A3", "visitor", "public API binding equals the committed deployment manifest", async (t) => {
  const health = await http("/health");
  t.check("/health alive", health.status === 200 && health.json?.status === "alive", health.json);
  const ready = await http("/ready");
  t.check("/ready ready and FRESH", ready.status === 200 && ready.json?.status === "ready" && ready.json.meta?.freshness === "FRESH", {
    status: ready.json?.status, freshness: ready.json?.meta?.freshness, block: ready.json?.meta?.canonicalBlock?.number,
  });
  t.check("/ready deployment matches manifest", ready.json?.meta?.deploymentId === manifest.deploymentId && ready.json?.meta?.manifestHash === manifest.manifestHash);
  t.check("/v1/config deployment matches manifest", config.deploymentId === manifest.deploymentId && config.manifestHash === manifest.manifestHash && config.chainId === manifest.chainId);
  const expected = {
    vault: manifest.contracts.LendingVaultV2, manager: manifest.contracts.CreditFacilityManager,
    repaymentRouter: manifest.contracts.RepaymentRouter, ledger: manifest.contracts.DebtLedger, roles: manifest.contracts.ProtocolRoles,
    asset: manifest.asset.address,
  };
  for (const [key, address] of Object.entries(expected)) {
    t.check(`config.contracts.${key} matches manifest`, (config.contracts[key] || "").toLowerCase() === address.toLowerCase(), { api: config.contracts[key], manifest: address });
  }
  t.check("config asset matches manifest", config.asset.address.toLowerCase() === manifest.asset.address.toLowerCase() && config.asset.decimals === 6 && config.asset.testOnly === true);
  const head = await provider.getBlockNumber();
  t.evidence.rpcHead = head;
  for (const name of ["LendingVaultV2", "CreditFacilityManager", "RepaymentRouter", "DebtLedger", "ReceivableBook", "EvidenceBook", "AttestcoinRevenueVerifier", "GpuTestToken"]) {
    const code = await provider.getCode(manifest.contracts[name]);
    t.check(`${name} on-chain code hash matches manifest`, keccak256(code) === manifest.contractCodeHashes[name]);
  }
  t.check("vault asset is the configured test token", (await vault.asset()).toLowerCase() === config.asset.address.toLowerCase());
  t.check("token is TEST_ONLY", (await token.testOnly()) === true);
  t.check("ready block is at or behind RPC head", ready.json.meta.canonicalBlock.number <= head + 1, { ready: ready.json.meta.canonicalBlock.number, head });
});

await scenario("A4", "visitor", "unauthenticated and garbage-token requests are denied", async (t) => {
  for (const path of ["/v1/me", "/v1/lp", "/v1/facilities", "/v1/operations", "/v1/connection-requests", "/v1/proofs"]) {
    const anonymous = await http(path);
    t.check(`${path} without token → 401`, anonymous.status === 401, { status: anonymous.status, code: anonymous.json?.error?.code });
    const garbage = await http(path, { token: "not-a-real-token" });
    t.check(`${path} garbage token → 401`, garbage.status === 401, { status: garbage.status });
  }
  const post = await http("/v1/onboarding", { method: "POST", body: { idempotencyKey: "anonymous-1", jurisdiction: "KR", registrationReference: "doc://x/y" } });
  t.check("POST /v1/onboarding without token → 401", post.status === 401, { status: post.status });
  const forged = await http("/v1/me", { token: "eyJhbGciOiJub25lIn0.eyJ3YWxsZXQiOiIweDAwIn0." });
  t.check("unsigned JWT-shaped token → 401", forged.status === 401, { status: forged.status });
});

// ================================================================ B. Wallet login edge cases
await scenario("B1", "misuse", "wallet on Ethereum mainnet must switch before sign-in", async (t) => {
  const stranger = Wallet.createRandom();
  const rejecting = await openWallet({ wallet: stranger, chainId: 1, switchBehavior: "reject" });
  await rejecting.page.goto(`${webUrl}/app`);
  await rejecting.connect();
  await rejecting.page.getByRole("alert").first().waitFor();
  const alertText = (await rejecting.page.getByRole("alert").first().innerText()).trim();
  t.check("rejected switch shows an error", /reject|switch|network/i.test(alertText), { alertText });
  t.check("rejected switch issued no challenge", !rejecting.state.apiRequests.some((r) => r.includes("/gpu/auth/challenge")), rejecting.state.apiRequests);
  t.check("no Overview without the correct chain", (await rejecting.page.getByRole("heading", { name: "Overview", exact: true }).count()) === 0);
  t.check("switch was requested", rejecting.state.walletCalls.includes("wallet_switchEthereumChain"));
  await rejecting.close();
  const accepting = await openWallet({ wallet: stranger, chainId: 1, switchBehavior: "accept" });
  await accepting.page.goto(`${webUrl}/app`);
  await accepting.connect();
  await accepting.page.getByText("Network switched. Connect again to sign in.").waitFor();
  t.check("accepted switch asks to connect again", true);
  t.check("no challenge before the second connect", !accepting.state.apiRequests.some((r) => r.includes("/gpu/auth/challenge")));
  await accepting.connect();
  await accepting.page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  t.check("sign-in succeeds after the switch", Boolean(accepting.state.token));
  t.check("no uncaught page errors", accepting.state.errors.length === 0, accepting.state.errors);
  await accepting.close();
});

await scenario("B2", "misuse", "challenge signed by a different key is rejected", async (t) => {
  const victim = Wallet.createRandom();
  const attacker = Wallet.createRandom();
  const issued = await challenge(victim);
  const signature = await sign(attacker, issued.typedData);
  const verified = await http("/gpu/auth/verify", {
    method: "POST",
    body: { wallet: victim.address, chainId: config.chainId, nonce: issued.nonce, signature },
  });
  t.check("verify rejected", verified.status >= 400 && verified.status < 500 && !verified.json?.token, { status: verified.status, code: verified.json?.error?.code });
});

await scenario("B3", "misuse", "nonce replay is rejected", async (t) => {
  const wallet = Wallet.createRandom();
  const issued = await challenge(wallet);
  const signature = await sign(wallet, issued.typedData);
  const body = { wallet: wallet.address, chainId: config.chainId, nonce: issued.nonce, signature };
  const first = await http("/gpu/auth/verify", { method: "POST", body });
  t.check("first verify succeeds", first.status === 200 && Boolean(first.json?.token), { status: first.status });
  const second = await http("/gpu/auth/verify", { method: "POST", body });
  t.check("replayed verify rejected", second.status >= 400 && !second.json?.token, { status: second.status, code: second.json?.error?.code });
});

await scenario("B4", "misuse", "unknown nonce and mismatched chain are rejected", async (t) => {
  const wallet = Wallet.createRandom();
  const issued = await challenge(wallet);
  const signature = await sign(wallet, issued.typedData);
  const unknown = await http("/gpu/auth/verify", {
    method: "POST",
    body: { wallet: wallet.address, chainId: config.chainId, nonce: `${issued.nonce.slice(0, -4)}0000`, signature },
  });
  t.check("unknown nonce rejected", unknown.status >= 400 && !unknown.json?.token, { status: unknown.status, code: unknown.json?.error?.code });
  const wrongChain = await http("/gpu/auth/verify", {
    method: "POST",
    body: { wallet: wallet.address, chainId: 1, nonce: issued.nonce, signature },
  });
  t.check("mainnet chainId rejected", wrongChain.status >= 400 && !wrongChain.json?.token, { status: wrongChain.status, code: wrongChain.json?.error?.code });
});

const newcomer = Wallet.createRandom();
await scenario("B5", "unknown-wallet", "first sign-in shows an empty, honest state", async (t) => {
  const session = await openWallet({ wallet: newcomer });
  await session.signIn();
  const me = await http("/v1/me", { token: session.state.token });
  t.check("/v1/me roles empty and no borrower", me.status === 200 && me.json.data.roles.length === 0 && me.json.data.borrowerId === null, me.json?.data);
  await session.navigate("Borrow");
  t.check("borrow view asks to register a profile", await session.page.getByText(/Register your borrower profile in Providers/).first().isVisible());
  await session.navigate("Earn");
  await session.page.getByRole("heading", { name: "Supply & withdrawal", exact: true }).waitFor();
  const position = await session.page.getByText("Your vault position", { exact: true }).locator("..").locator("strong").innerText();
  t.check("vault position is 0 tUSD", position.trim() === "0 tUSD", { position });
  t.check("withdraw disabled with zero shares", await session.page.getByRole("button", { name: "Withdraw", exact: true }).isDisabled());
  const operations = await http("/v1/operations", { token: session.state.token });
  t.check("operations scope denied for unknown wallet", operations.status === 403, { status: operations.status });
  for (const width of [1440, 390]) {
    await session.page.setViewportSize({ width, height: 1000 });
    t.check(`fits ${width}px`, await session.fits());
    await session.shot(`B5-${width}`);
  }
  t.check("no wallet transaction was requested", !session.state.walletCalls.includes("eth_sendTransaction"));
  t.check("no uncaught page errors", session.state.errors.length === 0, session.state.errors);
  await session.close();
});

// ================================================================ C. LP
await scenario("C1", "lp", "read-only LP position parity between chain, API and UI", async (t) => {
  const session = await openWallet({ wallet: lpWallet });
  await session.signIn();
  await session.navigate("Earn");
  await session.page.getByRole("heading", { name: "Supply & withdrawal", exact: true }).waitFor();
  const lp = await http("/v1/lp", { token: session.state.token });
  t.check("/v1/lp 200 for this deployment", lp.status === 200 && lp.json.meta.deploymentId === config.deploymentId);
  const [shares, balance, nav, totalShares] = await Promise.all([
    vault.balanceOf(lpWallet.address), token.balanceOf(lpWallet.address), vault.nav(), vault.totalShares(),
  ]);
  t.evidence.chain = { shares: String(shares), walletBalance: String(balance), nav: String(nav), totalShares: String(totalShares) };
  t.evidence.api = { shares: lp.json.data.shares, walletBalance: lp.json.data.walletBalance, nav: lp.json.data.nav, totalShares: lp.json.data.totalShares };
  t.check("API shares equal chain shares", BigInt(lp.json.data.shares) === shares, t.evidence);
  t.check("API wallet balance equals chain balance", BigInt(lp.json.data.walletBalance) === balance);
  t.check("API NAV equals chain NAV", BigInt(lp.json.data.nav) === nav);
  t.check("API total shares equal chain supply", BigInt(lp.json.data.totalShares) === totalShares);
  const position = (await session.page.getByText("Your vault position", { exact: true }).locator("..").locator("strong").innerText()).trim();
  t.check("UI position equals API share assets", position === `${formatUnits(BigInt(lp.json.data.shareAssets), 6).replace(/\.0$/, "")} tUSD`, { position, shareAssets: lp.json.data.shareAssets });
  t.check("prior withdrawal history is visible in the API", lp.json.data.withdrawals.length >= 2, { rows: lp.json.data.withdrawals.length });
  t.check("no uncaught page errors", session.state.errors.length === 0, session.state.errors);
  await session.close();
});

await scenario("C3", "lp", "over-withdraw is blocked in the UI and by the contract", async (t) => {
  const shares = await vault.balanceOf(lpWallet.address);
  if (shares !== 0n) t.skip(`LP wallet holds ${shares} shares; guard scenario requires an empty position`);
  const session = await openWallet({ wallet: lpWallet });
  await session.signIn();
  await session.navigate("Earn");
  await session.page.getByRole("heading", { name: "Supply & withdrawal", exact: true }).waitFor();
  t.check("Withdraw button disabled", await session.page.getByRole("button", { name: "Withdraw", exact: true }).isDisabled());
  t.check("Join withdrawal queue disabled", await session.page.getByRole("button", { name: "Join withdrawal queue", exact: true }).isDisabled());
  let reverted = false;
  try {
    await vault.withdraw.staticCall(parseUnits("1", 18), 0n, { from: lpWallet.address });
  } catch (error) {
    reverted = true;
    t.evidence.revert = String(error.shortMessage || error.message).slice(0, 200);
  }
  t.check("static withdraw of 1 share reverts with zero balance", reverted, t.evidence.revert);
  t.check("no wallet transaction was requested", !session.state.walletCalls.includes("eth_sendTransaction"));
  await session.close();
});

const reviewScript = `${here}live-review-browser.mjs`;
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
async function confirmReceipts(t, submitted) {
  const receipts = [];
  for (const item of submitted) {
    const receipt = await provider.getTransactionReceipt(item.hash);
    receipts.push({ ...item, block: receipt?.blockNumber ?? null, status: receipt?.status ?? null });
    t.check(`${item.action} receipt ${item.hash.slice(0, 10)}… succeeded`, receipt?.status === 1, { block: receipt?.blockNumber });
  }
  return receipts;
}

await scenario("C2", "lp", "full liquidity cycle with real testnet transactions", async (t) => {
  if (!allowTransactions) t.skip("GPU_ALLOW_TESTNET_TRANSACTIONS is not 1");
  if ((await vault.balanceOf(lpWallet.address)) !== 0n) t.skip("LP wallet already holds shares");
  const before = { balance: await token.balanceOf(lpWallet.address), gas: await provider.getBalance(lpWallet.address) };
  const outcome = await delegate({ GPU_ALLOW_TESTNET_TRANSACTIONS: "1", GPU_SMOKE_PRIVATE_KEY: roles.lp.privateKey, GPU_REVIEW_FLOW: "lp" }, "C2");
  t.check("live LP browser flow passed", outcome.code === 0 && outcome.summary?.result === "PASS", { code: outcome.code, tail: outcome.stdout.slice(-400) });
  t.evidence.transactions = await confirmReceipts(t, outcome.submitted);
  const actions = outcome.submitted.map((item) => item.action);
  for (const expected of ["approve", "deposit", "requestWithdrawal", "cancelWithdrawal", "requestWithdrawal", "processWithdrawals", "claimWithdrawal"])
    t.check(`cycle includes ${expected}`, actions.includes(expected));
  const after = { shares: await vault.balanceOf(lpWallet.address), balance: await token.balanceOf(lpWallet.address), gas: await provider.getBalance(lpWallet.address) };
  t.evidence.walletBalanceBefore = String(before.balance);
  t.evidence.walletBalanceAfter = String(after.balance);
  t.evidence.gasSpentWei = String(before.gas - after.gas);
  t.check("final LP shares are zero", after.shares === 0n, { shares: String(after.shares) });
  t.check("token balance returned within 1 tUSD of the start (queue fill may round)", after.balance <= before.balance + oneToken && after.balance >= before.balance - oneToken, t.evidence);
});

// ================================================================ D. Borrower
const facilityContext = async (bearer) => http(`/v1/facilities/${facilityId}/transaction-context`, { token: bearer });
let canonicalFacilityId = null;
await scenario("D1", "borrower", "read-only facility history and finalized repayment evidence", async (t) => {
  const outcome = await delegate(
    { GPU_ALLOW_TESTNET_TRANSACTIONS: "1", GPU_SMOKE_PRIVATE_KEY: roles.borrower.privateKey, GPU_REVIEW_FLOW: "borrower", GPU_REVIEW_READ_ONLY: "1", GPU_REVIEW_FACILITY_ID: facilityId, GPU_REVIEW_EXPECT_REPAYMENT_TX: priorRepaymentHash },
    "D1",
  );
  t.check("read-only borrower audit passed (debt 0, Repaid allocation, activity link)", outcome.code === 0 && outcome.summary?.evidence === "NATIVE_TESTNET_READ_ONLY", { code: outcome.code, tail: outcome.stdout.slice(-400) });
  t.check("read-only run submitted nothing", outcome.submitted.length === 0);
  const session = await login(borrowerWallet);
  const facility = await http(`/v1/facilities/${facilityId}`, { token: session.token });
  t.check("facility is REPAID with zero recorded principal", facility.status === 200 && facility.json.data.state === "REPAID" && facility.json.data.recordedPrincipal.amount === "0", { state: facility.json?.data?.state });
  const receipt = await provider.getTransactionReceipt(priorRepaymentHash);
  const repaid = receipt.logs.map((log) => { try { return routerInterface.parseLog(log); } catch { return null; } }).find((event) => event?.name === "Repaid");
  t.check("prior Repaid log: principal 1 tUSD, interest 2 units, no excess, debt 0", Boolean(repaid) && repaid.args.principalPaid === 1000000n && repaid.args.interestPaid === 2n && repaid.args.excess === 0n && repaid.args.newDebt === 0n, repaid ? Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) : null);
  t.evidence.priorRepaymentHash = priorRepaymentHash;
});

await scenario("D2", "borrower", "draw is blocked while source protection is expired; repayment path stays honest", async (t) => {
  const session = await login(borrowerWallet);
  const context = await facilityContext(session.token);
  t.check("transaction-context 200", context.status === 200, { status: context.status });
  canonicalFacilityId = context.json.data.canonicalFacilityId;
  const now = Number((await provider.getBlock("latest")).timestamp);
  const [eligible, validUntil, age] = await book.eligibleUnpaid(canonicalFacilityId, 900, 0, 1000, now);
  t.evidence.chainEligibility = { eligible: String(eligible), evidenceValidUntil: String(validUntil), checkpointAge: String(age), at: now };
  t.evidence.api = { availableDraw: context.json.data.availableDraw, drawBlockedReason: context.json.data.drawBlockedReason, debt: context.json.data.debt };
  if (eligible > 0n) t.skip(`checkpoint currently fresh (eligible ${eligible}); blocked-draw scenario not observable now`);
  t.check("API reports NO_ELIGIBLE_DRAW with zero availableDraw", context.json.data.drawBlockedReason === "NO_ELIGIBLE_DRAW" && context.json.data.availableDraw === "0", t.evidence.api);
  t.check("chain eligibleUnpaid is zero", eligible === 0n);
  t.check("debt is zero", context.json.data.debt === "0");
  let reverted = false;
  try {
    await manager.borrow.staticCall(canonicalFacilityId, oneToken, oneToken, { from: borrowerWallet.address });
  } catch (error) {
    reverted = true;
    t.evidence.borrowRevert = String(error.shortMessage || error.message).slice(0, 200);
  }
  t.check("static borrow reverts on chain", reverted, t.evidence.borrowRevert);
  const ui = await openWallet({ wallet: borrowerWallet });
  await ui.signIn();
  await ui.navigate("Borrow");
  const facility = ui.page.getByRole("heading", { name: `Facility ${facilityId}`, exact: true }).locator("..");
  await facility.waitFor();
  await ui.page.getByRole("button", { name: "Refresh", exact: true }).click({ timeout: 5000 }).catch(() => {});
  await facility.getByText(/NO_ELIGIBLE_DRAW/).waitFor();
  t.check("UI shows the blocked reason", true);
  t.check("Borrow button disabled", await facility.getByRole("button", { name: "Borrow", exact: true }).isDisabled());
  t.check("Repay directly disabled with zero debt", await facility.getByRole("button", { name: "Repay directly", exact: true }).isDisabled());
  t.check("no wallet transaction was requested", !ui.state.walletCalls.includes("eth_sendTransaction"));
  await ui.shot("D2-blocked");
  await ui.close();
});

let refreshedCheckpoint = null;
const approval = "--approval=user-20260914";
const sepoliaProvider = new JsonRpcProvider("https://ethereum-sepolia-rpc.publicnode.com");
const sourceAccountKey = id("mockdepin-testonly:native-integration");
const sourceProviderId = id("mockdepin-testonly");
/** Poll the official Attestcoin proof service for one recorded source transition. */
async function officialProof(name, deadlineSeconds) {
  while (Date.now() / 1000 < deadlineSeconds) {
    const proof = await run("node", ["script/gpu/native_proofs.mjs", "--refresh", name], { timeoutMs: 120000 });
    if (proof.code === 0) return JSON.parse(readFileSync(`${repoRoot}.artifacts/native-testnet/${name}.proof.json`, "utf8"));
    console.log(`  official proof for ${name} pending (${Math.round(deadlineSeconds - Date.now() / 1000)} s left)`);
    await sleep(15000);
  }
  return null;
}
async function consumeStep(step, proofFile, outName) {
  const result = await run("node", [
    "script/gpu/consume-native.mjs", "--step", step, "--proof", proofFile,
    "--out", `.artifacts/native-testnet/${outName}.json`, "--broadcast", approval,
  ], { timeoutMs: 420000 });
  const reportPath = `${repoRoot}.artifacts/native-testnet/${outName}.json`;
  const report = existsSync(reportPath) ? JSON.parse(readFileSync(reportPath, "utf8")) : null;
  const row = report?.transactions?.[0] ?? null;
  return {
    // ALREADY_CONSUMED re-audits the canonical consumption receipt of an earlier run.
    ok: result.code === 0 && ["NATIVE_CONSUMED", "ALREADY_CONSUMED"].includes(row?.status) && row?.financialAuditStatus === "PASSED",
    code: result.code,
    stderr: result.stderr.slice(-300),
    row: row ? { step, sourceTxHash: row.sourceTxHash, destinationTxHash: row.destinationTxHash, destinationBlock: row.destinationBlock, status: row.status, financialAudit: row.financialAudit } : null,
  };
}
await scenario("D3", "operator", "new source transitions (payout, new obligation) are proven and consumed without touching debt or cash", async (t) => {
  if (!allowNativeRefresh) t.skip("GPU_SCENARIO_NATIVE_REFRESH is not 1");
  if (!canonicalFacilityId) canonicalFacilityId = (await facilityContext((await login(borrowerWallet)).token)).json.data.canonicalFacilityId;
  const ledger = new Contract(config.contracts.ledger, abi("DebtLedger"), provider);
  const receivablesBefore = await book.facilityReceivables(canonicalFacilityId);
  const first = await book.receivable(receivablesBefore[0]);
  t.evidence.before = { receivables: receivablesBefore.length, paid: String(first.paid), evidenceValidUntil: String(first.evidenceValidUntil), revision: String(first.revision) };
  // Sepolia: registered payer settles 1 source tUSD, then the issuer recognises and assigns a new 10 tUSD obligation.
  const settle = await run("node", ["script/gpu/native_tools.mjs", "settle", "--broadcast", approval], { timeoutMs: 300000 });
  const settleLine = settle.stdout.split("\n").find((row) => row.startsWith("{"));
  t.check("Sepolia payout (1 source tUSD) mined by the registered payer", settle.code === 0 && Boolean(settleLine), { code: settle.code, stderr: settle.stderr.slice(-300) });
  const obligation = await run("node", ["script/gpu/native_tools.mjs", "obligation", "--broadcast", approval], { timeoutMs: 300000 });
  const obligationLine = obligation.stdout.split("\n").find((row) => row.startsWith("{"));
  t.check("Sepolia recognition + assignment of a new obligation mined by the issuer", obligation.code === 0 && Boolean(obligationLine), { code: obligation.code, stderr: obligation.stderr.slice(-300) });
  if (settle.code !== 0 || obligation.code !== 0) return;
  t.evidence.source = { payout: JSON.parse(settleLine), obligation: JSON.parse(obligationLine) };
  const deadline = Date.now() / 1000 + 1800;
  const [settleProof, recognizeProof, assignProof] = await Promise.all([
    officialProof("settle-refresh", deadline), officialProof("recognize-refresh", deadline), officialProof("assign-refresh", deadline),
  ]);
  t.check("official Attestcoin proofs became PROOF_READY for all three source transitions", Boolean(settleProof && recognizeProof && assignProof));
  if (!(settleProof && recognizeProof && assignProof)) return;
  t.evidence.proofs = Object.fromEntries([["settle", settleProof], ["recognizeObligation", recognizeProof], ["assignObligation", assignProof]].map(([k, v]) => [k, { height: v.height, txHash: v.txHash }]));
  const consumptions = [];
  for (const [step, name] of [["settle", "settle-refresh"], ["recognizeObligation", "recognize-refresh"], ["assignObligation", "assign-refresh"]]) {
    const outcome = await consumeStep(step, `.artifacts/native-testnet/${name}.proof.json`, `${name}-consumption`);
    consumptions.push(outcome.row);
    t.check(`${step} consumed on Creditcoin and audited as proof-only (0 debt/vault mutations)`, outcome.ok, { code: outcome.code, status: outcome.row?.status, stderr: outcome.stderr });
    if (!outcome.ok) return;
  }
  t.evidence.consumptions = consumptions;
  const now = Number((await provider.getBlock("latest")).timestamp);
  const after = await book.receivable(receivablesBefore[0]);
  const receivablesAfter = await book.facilityReceivables(canonicalFacilityId);
  const fresh = await book.receivable(receivablesAfter[receivablesAfter.length - 1]);
  t.evidence.after = {
    receivables: receivablesAfter.length,
    original: { paid: String(after.paid), evidenceValidUntil: String(after.evidenceValidUntil), revision: String(after.revision) },
    newReceivable: { net: String(fresh.net), paid: String(fresh.paid), state: String(fresh.state), evidenceValidUntil: String(fresh.evidenceValidUntil), facilityId: fresh.facilityId },
  };
  t.check("original receivable paid increased by the measured payout", after.paid - first.paid === BigInt(t.evidence.source.payout.amount), t.evidence.after.original);
  t.check("a payout does not renew evidence validity (contract semantics)", after.evidenceValidUntil === first.evidenceValidUntil);
  t.check("new receivable is ASSIGNED to the facility with fresh evidence validity", receivablesAfter.length === receivablesBefore.length + 1 && fresh.facilityId.toLowerCase() === canonicalFacilityId.toLowerCase() && String(fresh.state) === "2" && Number(fresh.evidenceValidUntil) > now, t.evidence.after.newReceivable);
  const stats = await book.accountStats(sourceProviderId, sourceAccountKey);
  t.evidence.destinationStats = { eventsConsumed: String(stats.eventsConsumed), openAmount: String(stats.openAmount), paidCumulative: String(stats.paidCumulative) };
  t.check("source transitions created no destination debt", (await ledger.legalDebtAt(canonicalFacilityId, now)) === 0n);
});

await scenario("D3b", "operator", "native checkpoint refresh makes receivables eligible on chain", async (t) => {
  if (!allowNativeRefresh) t.skip("GPU_SCENARIO_NATIVE_REFRESH is not 1");
  if (!canonicalFacilityId) canonicalFacilityId = (await facilityContext((await login(borrowerWallet)).token)).json.data.canonicalFacilityId;
  const stats = await book.accountStats(sourceProviderId, sourceAccountKey);
  t.evidence.destinationStats = { eventsConsumed: String(stats.eventsConsumed), openAmount: String(stats.openAmount), paidCumulative: String(stats.paidCumulative) };
  const checkpoint = await run("node", ["script/gpu/native_tools.mjs", "checkpoint", "--broadcast", approval], { timeoutMs: 300000 });
  const line = checkpoint.stdout.split("\n").find((row) => row.startsWith("{"));
  t.check("Sepolia reserveCheckpoint mined", checkpoint.code === 0 && Boolean(line), { code: checkpoint.code, stderr: checkpoint.stderr.slice(-300) });
  if (checkpoint.code !== 0) return;
  const source = JSON.parse(line);
  const sourceBlock = await sepoliaProvider.getBlock(source.block);
  refreshedCheckpoint = { ...source, observedAt: sourceBlock.timestamp };
  t.evidence.source = refreshedCheckpoint;
  console.log(`  checkpoint window closes ${new Date(source.protectedUntil * 1000).toISOString()}`);
  const artifact = await officialProof("checkpoint-refresh", source.protectedUntil - 200);
  t.check("official Attestcoin proof became PROOF_READY inside the window", Boolean(artifact));
  if (!artifact) return;
  t.evidence.proof = { status: artifact.status, height: artifact.height, txHash: artifact.txHash, manifestHash: artifact.manifestHash };
  const outcome = await consumeStep("reserveCheckpoint", ".artifacts/native-testnet/checkpoint-refresh.proof.json", "checkpoint-consumption");
  t.evidence.consumption = outcome.row;
  t.check("checkpoint consumed on Creditcoin and audited as proof-only (0 debt/vault mutations)", outcome.ok, { code: outcome.code, status: outcome.row?.status, stderr: outcome.stderr });
  if (!outcome.ok) return;
  const block = await provider.getBlock("latest");
  const [eligible, validUntil, age] = await book.eligibleUnpaid(canonicalFacilityId, 900, 0, 1000, block.timestamp);
  const consumed = await book.checkpoint(sourceProviderId, sourceAccountKey);
  t.evidence.chain = { block: block.number, at: block.timestamp, eligibleUnpaid: String(eligible), evidenceValidUntil: String(validUntil), checkpointAge: String(age),
    checkpoint: { seq: String(consumed.checkpointSeq), latestRevision: String(consumed.latestRevision), observedAt: String(consumed.observedAt), protectedUntil: String(consumed.protectedUntil) } };
  t.check("consumed checkpoint reconciles with consumed events (revision == eventsConsumed)", consumed.latestRevision === stats.eventsConsumed, t.evidence.chain.checkpoint);
  t.check("on-chain eligibleUnpaid > 0 while the checkpoint is fresh", eligible > 0n && age <= 900n && Number(consumed.protectedUntil) > block.timestamp, t.evidence.chain);
  const session = await login(borrowerWallet);
  const context = await pollApi(`/v1/facilities/${facilityId}/transaction-context`, session.token, (data, meta) => meta.freshness === "FRESH" && meta.canonicalBlock.number >= outcome.row.destinationBlock, 180000, "API canonical block past consumption");
  t.evidence.api = { canonicalBlock: context.meta.canonicalBlock.number, availableDraw: context.data.availableDraw, drawBlockedReason: context.data.drawBlockedReason, debt: context.data.debt };
  t.check("API canonical block includes the consumption", context.meta.canonicalBlock.number >= outcome.row.destinationBlock, t.evidence.api);
});

await scenario("D4", "borrower", "a REPAID facility cannot draw again even with fresh evidence and a fresh checkpoint", async (t) => {
  if (!canonicalFacilityId) canonicalFacilityId = (await facilityContext((await login(borrowerWallet)).token)).json.data.canonicalFacilityId;
  const block = await provider.getBlock("latest");
  const info = await manager.facilityInfo(canonicalFacilityId);
  const evaluation = await manager.evaluateDraw(canonicalFacilityId, 0);
  const exposure = new Contract(manifest.contracts.ExposureController, abi("ExposureController"), provider);
  const raw = await exposure.evaluateDraw(canonicalFacilityId);
  const control = new Contract(manifest.contracts.ControlRegistry, abi("ControlRegistry"), provider);
  const agreement = await control.agreement(info.controlAgreementId);
  const states = ["DRAFT", "UNDER_REVIEW", "CONTROL_PENDING", "ACTIVE", "DRAW_FROZEN", "DELINQUENT", "DEFAULTED", "RECOVERY", "REPAID", "RELEASED", "CLOSED_WITH_LOSS"];
  t.evidence.chain = {
    block: block.number, at: block.timestamp, facilityState: states[Number(info.state)],
    managerEvaluation: { eligibleReceivables: String(evaluation.eligibleReceivables), receivableLimit: String(evaluation.receivableLimit), availableDraw: String(evaluation.availableDraw), evidenceValidUntil: String(evaluation.evidenceValidUntil), checkpointAge: String(evaluation.checkpointAge) },
    exposureEvaluation: { eligibleReceivables: String(raw.eligibleReceivables), availableDraw: String(raw.availableDraw) },
    controlObservation: { lastObservedAt: String(agreement.lastObservedAt), ageSeconds: block.timestamp - Number(agreement.lastObservedAt), maxAge: 900 },
  };
  t.check("facility is REPAID (terminal: only RELEASED follows)", states[Number(info.state)] === "REPAID" && (await manager.isTransitionAllowed(info.state, 3)) === false, t.evidence.chain.facilityState);
  t.check("eligible receivables exist on chain", evaluation.eligibleReceivables > 0n, t.evidence.chain.managerEvaluation);
  t.check("availableDraw is 0 despite eligible receivables", evaluation.availableDraw === 0n && raw.availableDraw === 0n);
  let revert = null;
  try {
    await manager.borrow.staticCall(canonicalFacilityId, oneToken, oneToken, { from: borrowerWallet.address });
  } catch (error) {
    revert = error;
  }
  let reason = null;
  try {
    reason = revert ? manager.interface.parseError(revert.data ?? revert.info?.error?.data ?? "0x")?.name ?? null : null;
  } catch {
    reason = null;
  }
  t.evidence.borrowRevert = reason ?? String(revert?.shortMessage || revert?.message || "").slice(0, 160);
  t.check("static borrow reverts", Boolean(revert), t.evidence.borrowRevert);
  const session = await login(borrowerWallet);
  const context = await facilityContext(session.token);
  const facility = await http(`/v1/facilities/${facilityId}`, { token: session.token });
  t.evidence.api = { state: facility.json?.data?.state, availableDraw: context.json?.data?.availableDraw, drawBlockedReason: context.json?.data?.drawBlockedReason, debt: context.json?.data?.debt };
  t.check("API reports REPAID and blocks the draw", facility.json?.data?.state === "REPAID" && context.json?.data?.availableDraw === "0" && Boolean(context.json?.data?.drawBlockedReason), t.evidence.api);
  const ui = await openWallet({ wallet: borrowerWallet });
  await ui.signIn();
  await ui.navigate("Borrow");
  const panel = ui.page.getByRole("heading", { name: `Facility ${facilityId}`, exact: true }).locator("..");
  await panel.waitFor();
  t.check("UI Borrow disabled", await panel.getByRole("button", { name: "Borrow", exact: true }).isDisabled());
  t.check("UI Repay disabled with zero debt", await panel.getByRole("button", { name: "Repay directly", exact: true }).isDisabled());
  t.check("no wallet transaction was requested", !ui.state.walletCalls.includes("eth_sendTransaction"));
  await ui.shot("D4-repaid-facility");
  await ui.close();
});

// The additional facility used by D5/D6 (GPU_SCENARIO_FACILITY_* select a later one, e.g. v4).
const facilityV3 = {
  name: process.env.GPU_SCENARIO_FACILITY_NAME || "gpu080-facility-v3",
  agreement: process.env.GPU_SCENARIO_AGREEMENT_NAME || "gpu080-SIMULATED-control-v3",
  apiId: process.env.GPU_SCENARIO_FACILITY_API_ID || "6131NSGXQYJRXR73DP59TKEYTV",
  receipt: process.env.GPU_SCENARIO_FACILITY_RECEIPT
    ? path.resolve(process.env.GPU_SCENARIO_FACILITY_RECEIPT)
    : `${repoRoot}config/gpu/evidence/native-20260914/open-facility-v3-receipt.json`,
};
const facilityV3Key = id(facilityV3.name);
await scenario("D5", "operator", "an additional facility is opened on chain, registered in the API and receives its own consumed obligation", async (t) => {
  if (!allowNativeRefresh) t.skip("GPU_SCENARIO_NATIVE_REFRESH is not 1");
  const receipt = JSON.parse(readFileSync(facilityV3.receipt, "utf8"));
  t.check("opening receipt names this facility and agreement", receipt.facilityId === facilityV3Key && receipt.agreementId === id(facilityV3.agreement) && receipt.receipts.length === 11, { facilityId: receipt.facilityId, transactions: receipt.receipts.length });
  for (const row of receipt.receipts) {
    const onchain = await provider.getTransactionReceipt(row.transactionHash);
    if (onchain?.status !== 1) {
      t.evidence.openingFailures = [...(t.evidence.openingFailures ?? []), row.transactionHash];
      t.check(`opening transaction ${row.transactionHash.slice(0, 10)}… succeeded`, false, { status: onchain?.status });
    }
  }
  t.check("all eleven opening transactions are canonical and successful", t.evidence.openingFailures === undefined);
  t.evidence.openingTransactions = receipt.receipts.map((row) => ({ hash: row.transactionHash, block: parseInt(row.blockNumber, 16) }));
  const info = await manager.facilityInfo(facilityV3Key);
  const anchor = await manager.anchor(facilityV3Key);
  // Before D6 the facility is ACTIVE; once D6 has completed its draw → repay cycle it is REPAID (terminal).
  const cycled = [...(prior?.scenarios ?? []), ...results].some((r) => r.id === "D6" && r.status === "PASS" && r.evidence?.api?.facilityId === facilityV3.apiId);
  const expectedStates = cycled ? ["ACTIVE", "REPAID"] : ["ACTIVE"];
  const states = ["DRAFT", "UNDER_REVIEW", "CONTROL_PENDING", "ACTIVE", "DRAW_FROZEN", "DELINQUENT", "DEFAULTED", "RECOVERY", "REPAID", "RELEASED", "CLOSED_WITH_LOSS"];
  t.evidence.chain = { state: states[Number(info.state)], expectedStates, wallet: info.wallet, controlAgreementId: info.controlAgreementId, anchorLimit: String(anchor.auth.limit), anchorValidUntil: String(anchor.auth.validUntil) };
  t.check(`facility is ${expectedStates.join("/")} for the borrower wallet with an anchored underwriter authorization`, expectedStates.includes(states[Number(info.state)]) && info.wallet.toLowerCase() === borrowerWallet.address.toLowerCase() && info.controlAgreementId === id(facilityV3.agreement) && anchor.exists && anchor.auth.limit > 0n, t.evidence.chain);
  const session = await login(borrowerWallet);
  // The indexer projects state transitions a few blocks after the import; wait for it.
  const listed = await pollApi("/v1/facilities", session.token, (data) => data.some((item) => item.facilityId === facilityV3.apiId && expectedStates.includes(item.state)), 240000, `facility ${expectedStates.join("/")} in API`);
  const row = listed.data.find((item) => item.facilityId === facilityV3.apiId);
  t.check(`API lists the additional facility as ${expectedStates.join("/")} for the same borrower`, Boolean(row) && expectedStates.includes(row.state) && row.borrowerId === session.borrowerId, row && { state: row.state, borrowerId: row.borrowerId });
  const context = await pollApi(`/v1/facilities/${facilityV3.apiId}/transaction-context`, session.token, (data) => data.canonicalFacilityId?.toLowerCase() === facilityV3Key.toLowerCase(), 240000, "facility v3 context");
  t.check("API binds the additional facility to its canonical on-chain id", context.data.canonicalFacilityId.toLowerCase() === facilityV3Key.toLowerCase() && context.data.debt === "0", { debt: context.data.debt, blocked: context.data.drawBlockedReason });
  const assignRecord = JSON.parse(readFileSync(`${repoRoot}.artifacts/native-testnet/assign-refresh.json`, "utf8"));
  const recognizeRecord = JSON.parse(readFileSync(`${repoRoot}.artifacts/native-testnet/recognize-refresh.json`, "utf8"));
  t.check("recorded Sepolia obligation is assigned to the additional facility", assignRecord.facilityName === facilityV3.name && assignRecord.facilityKey === keccak256(facilityV3Key), assignRecord);
  const deadline = Date.now() / 1000 + 1500;
  const [recognizeProof, assignProof] = await Promise.all([officialProof("recognize-refresh", deadline), officialProof("assign-refresh", deadline)]);
  t.check("official Attestcoin proofs became PROOF_READY for recognition and assignment", Boolean(recognizeProof && assignProof));
  if (!(recognizeProof && assignProof)) return;
  t.evidence.source = { recognition: recognizeProof.txHash, assignment: assignProof.txHash, obligationRef: assignRecord.obligationRef };
  const before = (await book.facilityReceivables(facilityV3Key)).length;
  const consumptions = [];
  for (const [step, name] of [["recognizeObligation", "recognize-refresh"], ["assignObligation", "assign-refresh"]]) {
    const outcome = await consumeStep(step, `.artifacts/native-testnet/${name}.proof.json`, `${name}-v3-consumption`);
    consumptions.push(outcome.row);
    t.check(`${step} consumed on Creditcoin and audited as proof-only (0 debt/vault mutations)`, outcome.ok, { code: outcome.code, status: outcome.row?.status, stderr: outcome.stderr });
    if (!outcome.ok) return;
  }
  t.evidence.consumptions = consumptions;
  const ids = await book.facilityReceivables(facilityV3Key);
  const fresh = await book.receivable(ids[ids.length - 1]);
  const now = Number((await provider.getBlock("latest")).timestamp);
  t.evidence.receivable = { count: ids.length, net: String(fresh.net), paid: String(fresh.paid), state: String(fresh.state), evidenceValidUntil: String(fresh.evidenceValidUntil) };
  t.check("the additional facility holds the recorded obligation as an ASSIGNED receivable with fresh evidence validity", ids.length >= 1 && ids.length <= before + 1 && fresh.net === BigInt(assignRecord.amount ?? recognizeRecord.amount) && String(fresh.state) === "2" && Number(fresh.evidenceValidUntil) > now, t.evidence.receivable);
});

await scenario("D6", "borrower", "real draw and repayment on the new facility through the browser", async (t) => {
  if (!allowNativeRefresh) t.skip("GPU_SCENARIO_NATIVE_REFRESH is not 1");
  const stats = await book.accountStats(sourceProviderId, sourceAccountKey);
  const checkpoint = await run("node", ["script/gpu/native_tools.mjs", "checkpoint", "--broadcast", approval], { timeoutMs: 300000 });
  const line = checkpoint.stdout.split("\n").find((row) => row.startsWith("{"));
  t.check("Sepolia reserveCheckpoint mined", checkpoint.code === 0 && Boolean(line), { code: checkpoint.code, stderr: checkpoint.stderr.slice(-300) });
  if (checkpoint.code !== 0) return;
  const source = JSON.parse(line);
  t.evidence.source = source;
  console.log(`  checkpoint window closes ${new Date(source.protectedUntil * 1000).toISOString()}`);
  const artifact = await officialProof("checkpoint-refresh", source.protectedUntil - 150);
  t.check("official Attestcoin proof became PROOF_READY inside the window", Boolean(artifact));
  if (!artifact) return;
  // Operator refreshes the SIMULATED control observation (15-minute gate) right before consumption.
  const observe = await run("node", ["script/gpu/native_tools.mjs", "observe", "--agreement", facilityV3.agreement, "--broadcast", approval], { timeoutMs: 180000 });
  const observeLine = observe.stdout.split("\n").find((row) => row.startsWith("{"));
  t.check("control observation refreshed on chain", observe.code === 0 && Boolean(observeLine), { code: observe.code, stderr: observe.stderr.slice(-200) });
  if (observeLine) t.evidence.controlObservation = JSON.parse(observeLine);
  const consumption = run("node", [
    "script/gpu/consume-native.mjs", "--step", "reserveCheckpoint", "--proof", ".artifacts/native-testnet/checkpoint-refresh.proof.json",
    "--out", ".artifacts/native-testnet/checkpoint-v3-consumption.json", "--broadcast", approval,
  ], { timeoutMs: 420000 });
  const session = await login(borrowerWallet);
  let eligible = null;
  try {
    eligible = await pollApi(`/v1/facilities/${facilityV3.apiId}/transaction-context`, session.token,
      (data, meta) => meta.freshness === "FRESH" && !data.drawBlockedReason && BigInt(data.availableDraw || 0) >= oneToken,
      Math.max(30000, (source.protectedUntil - 90) * 1000 - Date.now()), "eligible draw on facility v3");
  } catch (error) {
    t.evidence.apiError = error.message.slice(0, 400);
  }
  t.evidence.api = eligible?.data ?? null;
  t.check("API reports availableDraw ≥ 1 tUSD on facility v3", Boolean(eligible), eligible?.data);
  if (!eligible) {
    await consumption;
    return;
  }
  const before = await token.balanceOf(borrowerWallet.address);
  const outcome = await delegate({ GPU_ALLOW_TESTNET_TRANSACTIONS: "1", GPU_SMOKE_PRIVATE_KEY: roles.borrower.privateKey, GPU_REVIEW_FLOW: "borrower", GPU_REVIEW_FACILITY_ID: facilityV3.apiId }, "D6");
  t.check("live borrower browser flow passed (borrow 1 tUSD, repay with 1.001 cap, debt 0)", outcome.code === 0 && outcome.summary?.result === "PASS", { code: outcome.code, tail: outcome.stdout.slice(-400) });
  t.evidence.transactions = await confirmReceipts(t, outcome.submitted);
  const repay = outcome.submitted.find((item) => item.action === "repayExact");
  if (repay) {
    const receipt = await provider.getTransactionReceipt(repay.hash);
    const repaid = receipt.logs.map((log) => { try { return routerInterface.parseLog(log); } catch { return null; } }).find((event) => event?.name === "Repaid");
    t.evidence.repaid = repaid ? Object.fromEntries(Object.entries(repaid.args.toObject()).map(([k, v]) => [k, String(v)])) : null;
    t.check("Repaid log: principal 1 tUSD, no excess, debt 0", Boolean(repaid) && repaid.args.principalPaid === 1000000n && repaid.args.excess === 0n && repaid.args.newDebt === 0n, t.evidence.repaid);
    const after = await token.balanceOf(borrowerWallet.address);
    t.evidence.netTokenDelta = String(after - before);
    t.check("net token cost equals interest + fees only (cap not transferred)", Boolean(repaid) && before - after === repaid.args.interestPaid + repaid.args.feePaid, t.evidence.netTokenDelta);
  }
  const now = Number((await provider.getBlock("latest")).timestamp);
  const ledger = new Contract(config.contracts.ledger, abi("DebtLedger"), provider);
  t.check("canonical legal debt is zero on facility v3", (await ledger.legalDebtAt(facilityV3Key, now)) === 0n);
  const done = await consumption;
  const report = existsSync(`${repoRoot}.artifacts/native-testnet/checkpoint-v3-consumption.json`) ? JSON.parse(readFileSync(`${repoRoot}.artifacts/native-testnet/checkpoint-v3-consumption.json`, "utf8")) : null;
  const row = report?.transactions?.[0];
  t.evidence.checkpointConsumption = row ? { destinationTxHash: row.destinationTxHash, destinationBlock: row.destinationBlock, status: row.status, financialAudit: row.financialAudit, protection: row.protection } : null;
  t.check("checkpoint consumption audited as proof-only", done.code === 0 && row?.status === "NATIVE_CONSUMED" && row?.financialAuditStatus === "PASSED", { code: done.code, status: row?.status });
  t.evidence.destinationStatsBefore = { eventsConsumed: String(stats.eventsConsumed) };
  const refreshed = await login(borrowerWallet);
  const final = await pollApi(`/v1/facilities/${facilityV3.apiId}/transaction-context`, refreshed.token, (data) => BigInt(data.debt) === 0n, 180000, "API debt 0 on facility v3");
  t.check("API debt is zero on facility v3", final.data.debt === "0");
});

// ================================================================ E. Onboarding
let onboarded = null;
await scenario("E1", "unknown-wallet", "borrower onboarding through the app is persisted and idempotent", async (t) => {
  const session = await openWallet({ wallet: newcomer });
  await session.signIn();
  await session.navigate("Providers");
  await session.page.getByLabel("Jurisdiction").fill("KR");
  await session.page.getByLabel("Company registration reference").fill("doc://scenario/e1/registration");
  await session.page.getByRole("button", { name: "Register profile" }).click();
  await session.page.getByText(/Borrower profile saved with review pending/).waitFor();
  t.check("UI confirms pending review", true);
  const onboardingCalls = session.state.apiRequests.filter((r) => r === "POST /v1/onboarding");
  t.check("exactly one onboarding POST", onboardingCalls.length === 1, session.state.apiRequests);
  const bearer = session.state.token;
  const relogin = await login(newcomer);
  const me = await http("/v1/me", { token: relogin.token });
  t.check("/v1/me shows borrower role after reconnect", me.json?.data?.roles?.includes("borrower") && Boolean(me.json.data.borrowerId), me.json?.data);
  onboarded = { borrowerId: me.json?.data?.borrowerId, token: relogin.token };
  t.evidence.borrowerId = onboarded.borrowerId;
  const key = `scenario-e1-${Date.now()}`;
  const body = { idempotencyKey: key, jurisdiction: "KR", registrationReference: "doc://scenario/e1/registration" };
  const first = await http("/v1/onboarding", { method: "POST", token: relogin.token, body });
  const replay = await http("/v1/onboarding", { method: "POST", token: relogin.token, body });
  t.check("already-linked wallet returns the same borrower (201)", first.status === 201 && first.json.data.borrowerId === onboarded.borrowerId, { status: first.status });
  let identical = false;
  try {
    assert.deepEqual(replay.json, first.json);
    identical = true;
  } catch {
    identical = false;
  }
  t.check("identical replay returns the identical response", replay.status === 201 && identical, replay.json);
  const conflict = await http("/v1/onboarding", { method: "POST", token: relogin.token, body: { ...body, jurisdiction: "US" } });
  t.check("same key with a different payload → 409 IDEMPOTENCY_CONFLICT", conflict.status === 409 && conflict.json?.error?.code === "IDEMPOTENCY_CONFLICT", { status: conflict.status, code: conflict.json?.error?.code });
  t.check("stale pre-onboarding token remains usable for reads only until expiry", (await http("/v1/me", { token: bearer })).status === 200);
  t.check("no localStorage token persistence", !(await session.page.evaluate(() => Object.keys(localStorage).some((key) => /token|session|registration|connection/.test(key)))));
  t.check("no uncaught page errors", session.state.errors.length === 0, session.state.errors);
  await session.close();
});

await scenario("E2", "new-borrower", "provider connection request is persisted across reload", async (t) => {
  if (!onboarded) t.skip("E1 did not onboard a wallet");
  const session = await openWallet({ wallet: newcomer });
  await session.signIn();
  await session.navigate("Providers");
  await session.page.getByRole("heading", { name: "Request a provider connection" }).waitFor();
  await session.page.getByRole("combobox", { name: "Provider", exact: true }).selectOption("mockdepin-testonly");
  const account = `scenario-e2-${Date.now()}`;
  await session.page.getByLabel("Provider account reference").fill(account);
  await session.page.getByLabel("Ownership / authority evidence reference").fill("doc://scenario/e2/ownership");
  await session.page.getByLabel("Reason for request").fill("Live scenario E2 connection request for review.");
  await session.page.getByRole("button", { name: "Submit for review" }).click();
  await session.page.getByText(/Connection request saved for review/).waitFor();
  t.check("UI confirms the request", true);
  const listed = await http("/v1/connection-requests", { token: session.state.token });
  const row = listed.json?.data?.find((item) => item.externalAccountId === account);
  t.check("request listed as PENDING_REVIEW", Boolean(row) && row.state === "PENDING_REVIEW", row);
  t.evidence.applicationId = row?.applicationId;
  await session.page.reload();
  await session.connect();
  // The URL hash keeps the Providers page selected after reload.
  await session.page.getByRole("heading", { name: "Request a provider connection" }).waitFor();
  const review = session.page.getByRole("heading", { name: "Account & rights review" }).locator("..");
  await review.getByText("Connection request retained for review").waitFor();
  t.check("request visible after reload as pending review", await review.getByText("Pending review", { exact: true }).first().isVisible());
  const duplicate = await http("/v1/connections", {
    method: "POST", token: session.state.token,
    body: { idempotencyKey: `scenario-e2-dup-${Date.now()}`, providerId: "mockdepin-testonly", externalAccountId: account, evidenceReference: "doc://scenario/e2/ownership", reason: "Duplicate request for the same account." },
  });
  t.check("duplicate account request returns the same application", duplicate.status === 202 && duplicate.json?.data?.applicationId === row?.applicationId, { status: duplicate.status, id: duplicate.json?.data?.applicationId });
  t.check("credentialConfigured stays false", duplicate.json?.data?.credentialConfigured === false);
  t.check("no wallet transaction was requested", !session.state.walletCalls.includes("eth_sendTransaction"));
  for (const width of [1440, 390]) {
    await session.page.setViewportSize({ width, height: 1000 });
    t.check(`fits ${width}px`, await session.fits());
    await session.shot(`E2-${width}`);
  }
  await session.close();
});

await scenario("E3", "new-borrower", "proof request for a foreign provider account is refused", async (t) => {
  if (!onboarded) t.skip("E1 did not onboard a wallet");
  const session = await login(newcomer);
  const foreign = await http("/v1/proofs", {
    method: "POST", token: session.token,
    body: { idempotencyKey: `scenario-e3-${Date.now()}`, providerAccountId: "mockdepin-testonly:native-integration", txHash: priorRepaymentHash },
  });
  t.check("foreign provider account → 404", foreign.status === 404, { status: foreign.status, code: foreign.json?.error?.code });
  const mine = await http("/v1/proofs", { token: session.token });
  t.check("no proof request recorded for this wallet", mine.status === 200 && mine.json.data.length === 0, { count: mine.json?.data?.length });
  const facility = await http(`/v1/facilities/${facilityId}`, { token: session.token });
  t.check("another borrower's facility is not readable", facility.status === 403 || facility.status === 404, { status: facility.status });
});

// ================================================================ F. Staff scopes
await scenario("F1", "lp-and-borrower", "staff scopes are denied to customer wallets", async (t) => {
  for (const [name, wallet] of [["lp", lpWallet], ["borrower", borrowerWallet]]) {
    const session = await login(wallet);
    for (const path of ["/v1/operations", "/v1/recoveries"]) {
      const read = await http(path, { token: session.token });
      t.check(`${name} ${path} → 403`, read.status === 403 && read.json?.error?.code === "FORBIDDEN_SCOPE", { status: read.status });
    }
    const action = await http("/v1/operations/NOPE/actions", {
      method: "POST", token: session.token,
      body: { idempotencyKey: `scenario-f1-${Date.now()}`, action: "acknowledge", reason: "scenario probe", expectedVersion: 0 },
    });
    t.check(`${name} operations action → 403`, action.status === 403, { status: action.status });
  }
  const lp = await login(lpWallet);
  const foreignFacility = await http(`/v1/facilities/${facilityId}`, { token: lp.token });
  t.check("LP cannot read the borrower's facility", foreignFacility.status === 403 || foreignFacility.status === 404, { status: foreignFacility.status });
  const foreignContext = await http(`/v1/facilities/${facilityId}/transaction-context`, { token: lp.token });
  t.check("LP cannot read the borrower's transaction context", foreignContext.status === 403 || foreignContext.status === 404, { status: foreignContext.status });
});

await scenario("F2", "keeper-underwriter-treasury", "staff roles are not inferred from deployment keys", async (t) => {
  for (const name of ["keeper", "underwriter", "treasury"]) {
    const session = await login(new Wallet(roles[name].privateKey));
    t.check(`${name} wallet has no API roles`, session.roles.length === 0 && session.borrowerId === null, { roles: session.roles });
    const operations = await http("/v1/operations", { token: session.token });
    t.check(`${name} /v1/operations → 403`, operations.status === 403, { status: operations.status });
  }
});

// ================================================================ G. Cross-cutting
await scenario("G1", "any", "CORS echoes only the allowed origin", async (t) => {
  const allowed = await http("/v1/config", { headers: { Origin: webUrl } });
  t.check("allowed origin echoed", allowed.headers.get("access-control-allow-origin") === webUrl, { header: allowed.headers.get("access-control-allow-origin") });
  const foreign = await http("/v1/config", { headers: { Origin: "https://evil.example" } });
  t.check("foreign origin not echoed", !foreign.headers.get("access-control-allow-origin"), { header: foreign.headers.get("access-control-allow-origin") });
  const preflight = await fetch(`${apiUrl}/v1/onboarding`, { method: "OPTIONS", headers: { Origin: "https://evil.example", "Access-Control-Request-Method": "POST" } });
  t.check("foreign preflight not allowed", !preflight.headers.get("access-control-allow-origin"), { status: preflight.status });
});

await scenario("G2", "any", "session lifetime is bounded", async (t) => {
  const session = await login(Wallet.createRandom());
  const lifetime = session.expiresAt - Math.floor(Date.now() / 1000);
  t.evidence.lifetimeSeconds = lifetime;
  t.check("session lifetime ≤ 1 hour", lifetime > 0 && lifetime <= 3600, { lifetime });
});

await scenario("G3", "any", "authenticated reads carry consistent deployment metadata", async (t) => {
  const session = await login(borrowerWallet);
  const head = await provider.getBlockNumber();
  for (const path of ["/v1/facilities", "/v1/receivables", "/v1/settlements", "/v1/repayments", "/v1/connections", "/v1/control-agreements", "/v1/lp", "/v1/providers"]) {
    const read = await http(path, { token: session.token });
    const meta = read.json?.meta;
    t.check(`${path} bound to this deployment and fresh`, read.status === 200 && meta?.deploymentId === config.deploymentId && meta?.manifestHash === config.manifestHash && meta?.freshness === "FRESH" && Math.abs(head - meta.canonicalBlock.number) <= 60, {
      status: read.status, block: meta?.canonicalBlock?.number, head, freshness: meta?.freshness,
    });
    t.check(`${path} never claims financial authorization`, meta?.financialAuthorization === false);
  }
});

await browser.close();
provider.destroy();
persist();
const totals = { pass: results.filter((r) => r.status === "PASS").length, fail: results.filter((r) => r.status === "FAIL").length, skipped: results.filter((r) => r.status === "SKIPPED").length };
console.log("\n" + results.map((r) => `${r.status.padEnd(7)} ${r.id} ${r.title}${r.reason ? ` (${r.reason})` : ""}${r.error ? ` — ${r.error}` : ""}`).join("\n"));
console.log(JSON.stringify({ result: totals.fail === 0 ? "PASS" : "FAIL", ...totals, evidence: outFile || null }));
process.exitCode = totals.fail === 0 ? 0 : 1;
