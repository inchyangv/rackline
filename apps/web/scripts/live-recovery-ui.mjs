import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { Contract, JsonRpcProvider, Wallet } from "ethers";

// Read-only browser check of facilities in non-performing states (DEFAULTED / RECOVERY / CLOSED_WITH_LOSS)
// against the DEPLOYED environment: the borrower sees the state badge, cannot borrow, sees the recovery
// repayment in the activity history; the LP sees the impaired vault NAV. The synthetic wallet signs the
// login only — any eth_sendTransaction is refused.
//   GPU_UI_FACILITIES="<apiId>:<STATE>[:<expectedDebtUnits>],..."  GPU_UI_REPAY_TXS="0x…,0x…"
//   GPU_SCENARIO_OUT=evidence/.../recovery-ui.json   GPU_UI_SHOTS=evidence/.../ui/
const webUrl = (process.env.GPU_REVIEW_WEB_URL || "").replace(/\/$/, "");
const apiUrl = (process.env.GPU_REVIEW_API_URL || "").replace(/\/$/, "");
assert.ok(webUrl && apiUrl, "Set GPU_REVIEW_WEB_URL and GPU_REVIEW_API_URL");
const keyFile = process.env.GPU_SCENARIO_KEYS;
assert.ok(keyFile && existsSync(keyFile), "GPU_SCENARIO_KEYS must name the role key file");
const roles = JSON.parse(readFileSync(keyFile, "utf8"));
const targets = (process.env.GPU_UI_FACILITIES || "").split(",").filter(Boolean).map((item) => {
  const [apiId, state, debt] = item.split(":");
  return { apiId, state, debt: debt ?? null };
});
assert.ok(targets.length, "GPU_UI_FACILITIES is empty");
const repayTxs = (process.env.GPU_UI_REPAY_TXS || "").split(",").filter(Boolean).map((h) => h.toLowerCase());
const outFile = process.env.GPU_SCENARIO_OUT ? path.resolve(process.env.GPU_SCENARIO_OUT) : "";
const here = fileURLToPath(new URL(".", import.meta.url));
const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
const shotDir = process.env.GPU_UI_SHOTS ? path.resolve(process.env.GPU_UI_SHOTS) + "/" : `${here}../node_modules/.cache/playwright/recovery-ui/`;
mkdirSync(shotDir, { recursive: true });
const abi = (name) => JSON.parse(readFileSync(`${repoRoot}test/fixtures/gpu/abi/${name}.json`, "utf8"));

const config = await (await fetch(`${apiUrl}/v1/config`)).json();
assert.equal(config.executionProfile, "NATIVE_TESTNET");
const provider = new JsonRpcProvider(config.rpcUrl, undefined, { batchMaxCount: 1 });
const vault = new Contract(config.contracts.vault, abi("LendingVaultV2"), provider);
const borrowerWallet = new Wallet(roles.borrower.privateKey, provider);
const lpWallet = new Wallet(roles.lp.privateKey, provider);
const pretty = (value) => value.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
const exact = (units, decimals = 6) => {
  const n = BigInt(units);
  const whole = n / 10n ** BigInt(decimals);
  const frac = (n % 10n ** BigInt(decimals)).toString().padStart(decimals, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : `${whole}`;
};
const allowedReads = new Set(["eth_blockNumber", "eth_getBlockByNumber", "eth_getTransactionByHash", "eth_getTransactionReceipt", "eth_getCode", "eth_call", "eth_estimateGas", "eth_gasPrice", "eth_getBalance", "eth_getTransactionCount", "eth_maxPriorityFeePerGas"]);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || (existsSync("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : undefined),
});
async function open(wallet, viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const state = { errors: [], walletCalls: [] };
  page.on("pageerror", (error) => state.errors.push(error.message));
  await page.exposeFunction("liveWalletRequest", async ({ method, params = [] }) => {
    state.walletCalls.push(method);
    if (method === "eth_accounts" || method === "eth_requestAccounts") return [wallet.address];
    if (method === "eth_chainId") return `0x${(102031).toString(16)}`;
    if (method === "wallet_switchEthereumChain") return null;
    if (method === "eth_signTypedData_v4") {
      const typed = JSON.parse(params[1]);
      assert.equal(typed.domain.name, "Rackline API Login");
      const types = { ...typed.types };
      delete types.EIP712Domain;
      return wallet.signTypedData(typed.domain, types, typed.message);
    }
    if (method === "eth_sendTransaction") throw new Error("UI_CHECK_POLICY: this check never submits a transaction");
    assert.ok(allowedReads.has(method), `Unsupported wallet request ${method}`);
    return provider.send(method, params);
  });
  await page.addInitScript(() => Reflect.set(window, "ethereum", { request: (args) => window.liveWalletRequest(args), on() {}, removeListener() {} }));
  await page.goto(`${webUrl}/app`);
  await page.getByRole("button", { name: "Connect wallet", exact: true }).first().click();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  const navigate = async (name) => {
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    if (!(await nav.isVisible())) await page.getByRole("button", { name: "Open navigation" }).click();
    await nav.getByRole("button", { name, exact: true }).click();
  };
  const shot = (name) => page.screenshot({ path: `${shotDir}${name}.png`, fullPage: true });
  return { page, state, navigate, shot, close: () => context.close() };
}

const checks = [];
const check = (name, ok, detail) => {
  checks.push({ name, ok: Boolean(ok), ...(detail === undefined ? {} : { detail }) });
  console.log(`  ${ok ? "ok  " : "FAIL"} ${name}${detail === undefined ? "" : " " + JSON.stringify(detail).slice(0, 300)}`);
};
const evidence = { facilities: [], activity: {}, lp: {} };
const now = Number((await provider.getBlock("latest")).timestamp);

console.log("### borrower: facility panels");
const ui = await open(borrowerWallet);
await ui.navigate("Borrow");
for (const target of targets) {
  const panel = ui.page.getByRole("heading", { name: `Facility ${target.apiId}`, exact: true }).locator("..");
  await panel.waitFor();
  await panel.getByText("Finalized debt view").waitFor();
  const badge = (await panel.locator(".rl-badge").first().textContent())?.trim();
  const borrowDisabled = await panel.getByRole("button", { name: "Borrow", exact: true }).isDisabled();
  const repayDisabled = await panel.getByRole("button", { name: "Repay directly", exact: true }).isDisabled();
  const debtText = (await panel.locator("dt", { hasText: "Current chain debt" }).locator("..").locator("dd").textContent())?.trim();
  const availableText = (await panel.locator("dt", { hasText: "Available to borrow" }).locator("..").locator("dd").textContent())?.trim();
  const noticeText = (await panel.locator(".gpu-notice").allTextContents()).join(" | ").trim();
  const row = { ...target, badge, borrowDisabled, repayDisabled, debtText, availableText, noticeText };
  evidence.facilities.push(row);
  check(`${target.apiId}: badge shows ${pretty(target.state)}`, badge === pretty(target.state), { badge });
  check(`${target.apiId}: Borrow is disabled`, borrowDisabled);
  check(`${target.apiId}: Available to borrow shows 0`, availableText?.startsWith("0 "), { availableText });
  if (target.debt != null) {
    check(`${target.apiId}: Current chain debt shows the ledger's legal debt (${exact(target.debt)})`, debtText?.startsWith(exact(target.debt)), { debtText });
    check(`${target.apiId}: Repay directly stays enabled while legal debt remains (recovery collections)`, !repayDisabled);
  }
  check(`${target.apiId}: draw-blocked notice names the state gate in words (FACILITY_NOT_ACTIVE)`, noticeText.includes("FACILITY_NOT_ACTIVE") && /not active|frozen|default|recovery|written off|repaid|released/i.test(noticeText), { noticeText: noticeText.slice(0, 200) });
  // Credit status: why the facility is in this state (finalized manager / recovery / vault events).
  const credit = panel.locator(".gpu-credit");
  const hasCredit = (await credit.count()) > 0;
  const creditText = hasCredit ? (await credit.textContent())?.replace(/\s+/g, " ").trim() ?? "" : "";
  const timeline = hasCredit ? await credit.locator(".gpu-timeline li").allTextContents() : [];
  row.creditText = creditText.slice(0, 600);
  row.timeline = timeline.map((t) => t.replace(/\s+/g, " ").trim());
  check(`${target.apiId}: credit status section explains the ${target.state} state`, hasCredit && creditText.startsWith(`Why this facility is ${pretty(target.state).toLowerCase()}`), { creditText: creditText.slice(0, 200) });
  const expectations = {
    DELINQUENT: [/installment of .* due .* was not paid/i, /Installment due/],
    DEFAULTED: [/Default approved by the underwriter on/i, /Interest accrual is frozen/i, /Installment due/],
    RECOVERY: [/Recovery opened on/i, /Recovery reserve/, /applied/],
    CLOSED_WITH_LOSS: [/Written off on/i, /loss of/i, /Write-off is not forgiveness/i, /Loss written off/],
  }[target.state] ?? [];
  for (const pattern of expectations) check(`${target.apiId}: credit status mentions ${pattern}`, pattern.test(creditText), { creditText: creditText.slice(0, 300) });
  check(`${target.apiId}: state timeline lists the transitions with triggers and transaction links`, timeline.length >= 1 && timeline.every((t) => /from/.test(t)) && (await credit.locator(".gpu-timeline a[href*='/tx/']").count()) >= 1, { timeline: row.timeline.slice(0, 5) });
  if (["DEFAULTED", "RECOVERY", "CLOSED_WITH_LOSS"].includes(target.state)) {
    check(`${target.apiId}: the timeline reaches back to the delinquency (installment overdue)`, timeline.some((t) => /installment overdue/i.test(t)), { timeline: row.timeline.slice(0, 6) });
  }
  await ui.shot(`facility-${target.apiId}-${target.state}`);
}
await ui.shot("borrow-page");

console.log("### borrower: activity history");
await ui.navigate("Activity");
await ui.page.getByRole("heading", { name: "Facility repayment allocations", exact: true }).waitFor();
const activity = ui.page.getByRole("heading", { name: "Facility repayment allocations", exact: true }).locator("..");
await activity.locator(".gpu-evidence").first().waitFor();
const links = await activity.locator("a[href]").evaluateAll((els) => els.map((a) => a.getAttribute("href")));
const badges = await activity.locator(".gpu-evidence").allTextContents();
evidence.activity = { allocations: badges.length, links: links.length };
for (const tx of repayTxs) {
  check(`activity lists repayment ${tx.slice(0, 10)}…`, links.some((h) => h && h.toLowerCase().includes(tx)), { found: links.filter((h) => h && h.toLowerCase().includes(tx)) });
}
check("every listed allocation is marked as a finalized event", badges.length > 0 && badges.every((t) => t.includes("Applied · finalized event")), { allocations: badges.length });
await ui.shot("activity-repayments");
check("borrower session requested no transaction", !ui.state.walletCalls.includes("eth_sendTransaction"));
check("no page errors (borrower)", ui.state.errors.length === 0, ui.state.errors);
await ui.close();

console.log("### LP: vault NAV after impairment and write-off");
const lp = await open(lpWallet);
await lp.navigate("Earn");
const navMetric = lp.page.locator(".rl-metric", { hasText: "Vault net assets" });
await navMetric.waitFor();
const navText = (await navMetric.locator("strong").textContent())?.trim();
const chainNav = await vault.nav();
evidence.lp = { navText, chainNav: String(chainNav), totalImpairment: String(await vault.totalImpairment()), writtenOffCount: String(await vault.writtenOffCount()) };
check("Earn page shows the impaired vault NAV equal to the chain (after write-off)", navText?.startsWith(exact(chainNav)), evidence.lp);
await lp.shot("earn-vault-nav");
check("no page errors (LP)", lp.state.errors.length === 0, lp.state.errors);
await lp.close();

console.log("### mobile width");
const mobile = await open(borrowerWallet, { width: 400, height: 860 });
await mobile.navigate("Borrow");
const first = mobile.page.getByRole("heading", { name: `Facility ${targets[0].apiId}`, exact: true }).locator("..");
await first.waitFor();
check("facility panel fits a 400 px viewport without horizontal scroll", await mobile.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
await mobile.shot(`facility-${targets[0].apiId}-mobile`);
await mobile.close();
await browser.close();

const summary = {
  schemaVersion: "1.0", executionProfile: "NATIVE_TESTNET", scope: "LIVE_RECOVERY_STATE_UI", webUrl, apiUrl, chainId: 102031,
  deploymentId: config.deploymentId, manifestHash: config.manifestHash, at: new Date().toISOString(), chainBlockTime: now,
  wallets: { borrower: borrowerWallet.address, lp: lpWallet.address }, partnerRevenue: "SIMULATED", transactionsSubmitted: 0,
  totals: { pass: checks.filter((c) => c.ok).length, fail: checks.filter((c) => !c.ok).length }, checks, evidence, screenshots: shotDir,
};
if (outFile) {
  mkdirSync(path.dirname(outFile), { recursive: true });
  writeFileSync(outFile, JSON.stringify(summary, null, 2) + "\n");
}
console.log(`\n${summary.totals.pass} PASS / ${summary.totals.fail} FAIL`);
process.exit(summary.totals.fail ? 1 : 0);
