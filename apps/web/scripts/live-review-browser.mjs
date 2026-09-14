import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import {
  Contract,
  FetchRequest,
  Interface,
  JsonRpcProvider,
  Wallet,
  formatUnits,
  parseUnits,
} from "ethers";

// This script signs REAL TESTNET transactions, never mocked RPC or receipts.
// Use only a disposable funded test wallet. Keys/tokens are never logged or persisted.
assert.equal(
  process.env.GPU_ALLOW_TESTNET_TRANSACTIONS,
  "1",
  "Set GPU_ALLOW_TESTNET_TRANSACTIONS=1 explicitly",
);
assert.ok(
  process.env.GPU_SMOKE_PRIVATE_KEY,
  "GPU_SMOKE_PRIVATE_KEY is required",
);
const webUrl = process.env.GPU_REVIEW_WEB_URL;
const apiUrl = process.env.GPU_REVIEW_API_URL;
const flow = process.env.GPU_REVIEW_FLOW || "lp";
const readOnly = process.env.GPU_REVIEW_READ_ONLY === "1";
const expectedRepaymentHash = process.env.GPU_REVIEW_EXPECT_REPAYMENT_TX;
if (expectedRepaymentHash)
  assert.ok(
    readOnly &&
      flow === "borrower" &&
      /^0x[0-9a-fA-F]{64}$/.test(expectedRepaymentHash),
    "Repayment activity verification requires read-only borrower mode",
  );
assert.ok(["lp", "borrower"].includes(flow), "Unsupported smoke flow");
const facilityId = process.env.GPU_REVIEW_FACILITY_ID;
const resumeCancelledId = process.env.GPU_REVIEW_RESUME_CANCELLED_REQUEST;
const resumePendingId = process.env.GPU_REVIEW_RESUME_PENDING_REQUEST;
const resumeBorrowerRepay =
  process.env.GPU_REVIEW_RESUME_BORROWER_REPAY === "1";
if (resumeBorrowerRepay) assert.equal(flow, "borrower");
assert.ok(
  !(resumeCancelledId && resumePendingId),
  "Choose one explicit resume stage",
);
if (resumePendingId) assert.ok(flow === "lp" && /^\d+$/.test(resumePendingId));
if (resumeCancelledId)
  assert.ok(flow === "lp" && /^\d+$/.test(resumeCancelledId));
if (flow === "borrower")
  assert.ok(facilityId, "An explicit borrower facility ID is required");
assert.ok(webUrl && apiUrl, "Set GPU_REVIEW_WEB_URL and GPU_REVIEW_API_URL");
const configResponse = await fetch(`${apiUrl}/v1/config`);
assert.equal(configResponse.status, 200);
const config = await configResponse.json();
assert.equal(config.configured, true);
assert.equal(config.executionProfile, "NATIVE_TESTNET");
assert.equal(config.chainId, 102031);
assert.equal(config.asset.testOnly, true);
assert.equal(config.asset.decimals, 6);
const retryableReadMethods = new Set([
  "eth_chainId",
  "eth_blockNumber",
  "eth_getBlockByNumber",
  "eth_getTransactionByHash",
  "eth_getTransactionReceipt",
  "eth_getCode",
  "eth_call",
  "eth_estimateGas",
  "eth_gasPrice",
  "eth_getBalance",
  "eth_getTransactionCount",
  "eth_maxPriorityFeePerGas",
]);
class LiveReadProvider extends JsonRpcProvider {
  async _send(payload) {
    const methods = (Array.isArray(payload) ? payload : [payload]).map(
      (item) => item.method,
    );
    const attempts = methods.every((method) => retryableReadMethods.has(method))
      ? 3
      : 1;
    for (let attempt = 1; ; attempt++) {
      try {
        return await super._send(payload);
      } catch (error) {
        if (attempt >= attempts) throw error;
        console.log(
          `RETRY_READ_ONLY_RPC ${methods.join(",")} ${attempt}/${attempts}`,
        );
        await new Promise((resolve) => setTimeout(resolve, 250 * attempt));
      }
    }
  }
}
const rpcRequest = new FetchRequest(config.rpcUrl);
rpcRequest.timeout = 12000;
// Reads may retry transport failures. Raw transaction broadcasts NEVER retry.
// Single requests also avoid depending on the public endpoint's batch behavior.
const provider = new LiveReadProvider(rpcRequest, undefined, {
  batchMaxCount: 1,
});
assert.equal((await provider.getNetwork()).chainId, 102031n);
const wallet = new Wallet(process.env.GPU_SMOKE_PRIVATE_KEY, provider);
const abi = (name) =>
  JSON.parse(
    readFileSync(
      fileURLToPath(
        new URL(`../../../test/fixtures/gpu/abi/${name}.json`, import.meta.url),
      ),
      "utf8",
    ),
  );
const tokenAbi = abi("GpuTestToken");
const vaultAbi = abi("LendingVaultV2");
const token = new Contract(config.asset.address, tokenAbi, provider);
const vault = new Contract(config.contracts.vault, vaultAbi, provider);
assert.equal(await token.testOnly(), true);
assert.equal(
  (await vault.asset()).toLowerCase(),
  config.asset.address.toLowerCase(),
);
assert.ok(
  (await provider.getBalance(wallet.address)) > 0n,
  "Disposable wallet needs test CTC gas",
);
let initialShares = await vault.balanceOf(wallet.address);
if (resumeCancelledId || resumePendingId) {
  const prior = await vault.withdrawalRequest(
    BigInt(resumeCancelledId || resumePendingId),
  );
  assert.equal(prior[0].toLowerCase(), wallet.address.toLowerCase());
  assert.equal(prior[8], Boolean(resumeCancelledId));
  if (resumeCancelledId) assert.equal(prior[4], 0n);
  else assert.ok(prior[4] > 0n, "Pending resume requires an unfilled request");
  assert.equal(prior[6], 0n);
  assert.ok(
    initialShares > 0n && initialShares <= 1000000000n,
    "Resume is limited to the prior 1 tUSD smoke position",
  );
  initialShares = 0n;
} else if (flow === "lp")
  assert.equal(
    initialShares,
    0n,
    "Use a clean disposable LP wallet, not an existing position",
  );
const supplyAmount = parseUnits("1", 6);
const repaymentCap = parseUnits("1.001", 6);
let canonicalFacilityId;
const allowedVault = new Set([
  "deposit",
  "withdraw",
  "requestWithdrawal",
  "cancelWithdrawal",
  "processWithdrawals",
  "claimWithdrawal",
]);
const vaultInterface = new Interface(vaultAbi);
const tokenInterface = new Interface(tokenAbi);
const managerInterface = new Interface(abi("CreditFacilityManager"));
const routerInterface = new Interface(abi("RepaymentRouter"));
const submitted = [];
function reportWalletFailure(method, error) {
  console.log(
    `WALLET_RPC_FAILURE ${JSON.stringify({
      method,
      code: error?.code,
      summary: error?.shortMessage,
      reason: String(
        error?.info?.error?.message || error?.error?.message || "",
      ).slice(0, 600),
    })}`,
  );
}
const allowedReads = new Set([
  "eth_blockNumber",
  "eth_getBlockByNumber",
  "eth_getTransactionByHash",
  "eth_getTransactionReceipt",
  "eth_getCode",
  "eth_call",
  "eth_estimateGas",
  "eth_gasPrice",
  "eth_getBalance",
  "eth_getTransactionCount",
  "eth_maxPriorityFeePerGas",
]);
const localChrome =
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await chromium.launch({
  executablePath:
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ||
    (existsSync(localChrome) ? localChrome : undefined),
});
let debugPage;
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  debugPage = page;
  page.setDefaultTimeout(120000);
  const errors = [];
  let sessionToken;
  let sessionExpiresAt = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame())
      console.log(`BROWSER_NAVIGATION ${new URL(frame.url()).pathname}`);
  });
  page.on("response", async (response) => {
    if (
      new URL(response.url()).pathname === "/gpu/auth/verify" &&
      response.status() === 200
    ) {
      const value = await response.json();
      sessionToken = value.token;
      sessionExpiresAt = value.expiresAt;
      console.log(
        `AUTHENTICATED session lifetime ${sessionExpiresAt - Math.floor(Date.now() / 1000)} seconds`,
      );
    }
  });
  await page.exposeFunction(
    "liveWalletRequest",
    async ({ method, params = [] }) => {
      if (method === "eth_accounts" || method === "eth_requestAccounts")
        return [wallet.address];
      if (method === "eth_chainId") return "0x18e8f";
      if (method === "eth_signTypedData_v4") {
        const typed = JSON.parse(params[1]);
        assert.equal(typed.domain.name, "Rackline API Login");
        assert.equal(Number(typed.domain.chainId), config.chainId);
        delete typed.types.EIP712Domain;
        return wallet.signTypedData(typed.domain, typed.types, typed.message);
      }
      if (method === "eth_sendTransaction") {
        assert.equal(
          readOnly,
          false,
          "Read-only verification cannot send a transaction",
        );
        const tx = params[0];
        assert.equal(tx.from.toLowerCase(), wallet.address.toLowerCase());
        assert.equal(BigInt(tx.value || 0), 0n, "No native transfers allowed");
        const destination = tx.to.toLowerCase();
        let call;
        if (destination === config.asset.address.toLowerCase()) {
          call = tokenInterface.parseTransaction(tx);
          assert.ok(
            (flow === "lp" ? ["faucet", "approve"] : ["approve"]).includes(
              call.name,
            ),
          );
          if (call.name === "approve") {
            assert.equal(
              call.args[0].toLowerCase(),
              (flow === "lp"
                ? config.contracts.vault
                : config.contracts.repaymentRouter
              ).toLowerCase(),
            );
            assert.ok(
              call.args[1] <= (flow === "lp" ? supplyAmount : repaymentCap),
            );
          }
        } else if (flow === "lp") {
          assert.equal(destination, config.contracts.vault.toLowerCase());
          call = vaultInterface.parseTransaction(tx);
          assert.ok(allowedVault.has(call.name));
          if (call.name === "deposit") assert.ok(call.args[0] <= supplyAmount);
        } else if (destination === config.contracts.manager.toLowerCase()) {
          assert.equal(
            resumeBorrowerRepay,
            false,
            "Repayment resume cannot submit another borrow",
          );
          call = managerInterface.parseTransaction(tx);
          assert.equal(call.name, "borrow");
          assert.equal(call.args[0].toLowerCase(), canonicalFacilityId);
          assert.equal(call.args[1], supplyAmount);
          assert.equal(call.args[2], supplyAmount);
        } else {
          assert.equal(
            destination,
            config.contracts.repaymentRouter.toLowerCase(),
          );
          call = routerInterface.parseTransaction(tx);
          assert.equal(call.name, "repayExact");
          assert.equal(call.args[0].toLowerCase(), canonicalFacilityId);
          assert.equal(call.args[1], repaymentCap);
        }
        let sent;
        try {
          sent = await wallet.sendTransaction({
            to: tx.to,
            data: tx.data,
            value: 0n,
          });
        } catch (error) {
          reportWalletFailure(`${method}:${call.name}`, error);
          throw error;
        }
        submitted.push({ action: call.name, hash: sent.hash });
        console.log(`SUBMITTED real testnet ${call.name}: ${sent.hash}`);
        return sent.hash;
      }
      assert.ok(
        allowedReads.has(method),
        `Unsupported live-wallet request: ${method}`,
      );
      try {
        return await provider.send(method, params);
      } catch (error) {
        reportWalletFailure(method, error);
        throw error;
      }
    },
  );
  await page.addInitScript(() =>
    Reflect.set(window, "ethereum", {
      request: (args) => window.liveWalletRequest(args),
      on() {},
      removeListener() {},
    }),
  );
  await page.goto(`${webUrl.replace(/\/$/, "")}/app`);
  await page
    .getByRole("button", { name: "Connect wallet", exact: true })
    .first()
    .click();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  async function ensureSession() {
    const connect = page
      .getByRole("button", { name: "Connect wallet", exact: true })
      .first();
    const disconnected = await connect.isVisible();
    if (!disconnected && sessionExpiresAt * 1000 > Date.now() + 180000) return;
    if (disconnected)
      console.log(
        `SESSION_SCREEN ${String(await page.locator("body").innerText()).slice(0, 1500)}`,
      );
    if (!(await connect.isVisible()))
      await page.locator(".rl-wallet-button").click();
    await connect.click();
    await page.getByRole("button", { name: "Refresh", exact: true }).waitFor();
    console.log("PASS refreshed real wallet session before expiry");
  }
  const refresh = async () => {
    await ensureSession();
    if (
      !(await page
        .getByRole("button", { name: "Refresh", exact: true })
        .isVisible())
    ) {
      console.log(
        `MISSING_REFRESH ${JSON.stringify({
          url: page.url(),
          dialogs: await page.getByRole("dialog").count(),
          body: (await page.locator("body").innerText()).slice(0, 3500),
          refreshDom: await page
            .locator("button")
            .filter({ hasText: /^Refresh$/ })
            .evaluateAll((elements) =>
              elements.map((element) => ({
                text: element.textContent,
                hidden:
                  element.closest('[aria-hidden="true"]')?.tagName || null,
              })),
            ),
        })}`,
      );
    }
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
  };
  // A polling read tolerates one transient transport failure (ECONNRESET, timeout); the deadline still bounds it.
  async function pollRead(url) {
    try {
      return await fetch(url, { headers: { Authorization: `Bearer ${sessionToken}` } });
    } catch (error) {
      console.log(`RETRY_READ_ONLY_RPC transient API read failure: ${error?.cause?.code ?? error?.code ?? error?.message}`);
      return null;
    }
  }
  async function waitLp(predicate) {
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      await ensureSession();
      const response = await pollRead(`${apiUrl}/v1/lp`);
      if (response?.ok) {
        const result = await response.json();
        assert.equal(result.meta.deploymentId, config.deploymentId);
        assert.equal(result.meta.executionProfile, "NATIVE_TESTNET");
        if (predicate(result.data)) {
          await refresh();
          return result.data;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error(
      "Canonical LP projection did not reflect confirmed transaction in two minutes",
    );
  }
  async function transact(button, amount, scope = page) {
    await ensureSession();
    await scope
      .getByRole("button", { name: button, exact: true })
      .and(page.locator(":enabled"))
      .click();
    const dialog = page.getByRole("dialog");
    if (amount !== undefined) {
      await dialog.getByRole("textbox").fill(amount);
      await dialog.getByRole("button", { name: "Review transaction" }).click();
    }
    await dialog.getByRole("button", { name: "Confirm in wallet" }).click();
    await Promise.race([
      dialog
        .getByText("Transaction confirmed with two block confirmations.")
        .waitFor(),
      dialog
        .locator(".rl-transaction-error")
        .waitFor()
        .then(async () => {
          throw new Error(
            `Wallet action failed: ${await dialog.locator(".rl-transaction-error").innerText()}`,
          );
        }),
    ]);
    await dialog.getByRole("button", { name: "Done" }).click();
    console.log(`PASS real browser ${button}`);
  }
  if (readOnly && flow === "lp") {
    await waitLp((data) => BigInt(data.shares) === 0n);
  } else if (flow === "borrower") {
    assert.ok(
      (await token.balanceOf(wallet.address)) >= 1000n,
      "Borrower needs at least 0.001 test tUSD for accrued interest",
    );
    async function waitFacility(predicate) {
      const deadline = Date.now() + 120000;
      while (Date.now() < deadline) {
        await ensureSession();
        const response = await pollRead(
          `${apiUrl}/v1/facilities/${encodeURIComponent(facilityId)}/transaction-context`,
        );
        if (response?.ok) {
          const result = await response.json();
          assert.equal(result.meta.deploymentId, config.deploymentId);
          assert.equal(result.meta.executionProfile, "NATIVE_TESTNET");
          assert.equal(
            result.data.wallet.toLowerCase(),
            wallet.address.toLowerCase(),
          );
          assert.equal(result.data.facilityId, facilityId);
          assert.equal(
            result.data.manager.toLowerCase(),
            config.contracts.manager.toLowerCase(),
          );
          assert.equal(
            result.data.repaymentRouter.toLowerCase(),
            config.contracts.repaymentRouter.toLowerCase(),
          );
          if (predicate(result.data, result.meta)) {
            await refresh();
            return result.data;
          }
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      throw new Error(
        "Canonical facility context did not become ready in two minutes",
      );
    }
    const initial = await waitFacility((data, meta) =>
      readOnly
        ? BigInt(data.debt) === 0n
        : resumeBorrowerRepay
        ? BigInt(data.debt) >= supplyAmount &&
          BigInt(data.debt) <= repaymentCap
        : meta.freshness === "FRESH" &&
          !data.drawBlockedReason &&
          BigInt(data.availableDraw || 0) >= supplyAmount,
    );
    if (!readOnly && !resumeBorrowerRepay)
      assert.equal(
        BigInt(initial.debt),
        0n,
        "Use the explicitly prepared zero-debt test facility",
      );
    canonicalFacilityId = initial.canonicalFacilityId.toLowerCase();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Borrow", exact: true })
      .click();
    const facility = page
      .getByRole("heading", { name: `Facility ${facilityId}`, exact: true })
      .locator("..");
    if (!readOnly && !resumeBorrowerRepay) {
      await transact("Borrow", "1", facility);
      await waitFacility((data) => BigInt(data.debt) >= supplyAmount);
    } else if (!readOnly) {
      console.log(
        "Resuming only repayment of the prior 1 tUSD borrower smoke; no new borrow will be submitted",
      );
    }
    if (!readOnly) {
      await transact("Repay directly", "1.001", facility);
      await waitFacility((data) => BigInt(data.debt) === 0n);
    }
    console.log(
      "PASS real borrower zero debt after repayExact cap; only execution debt transferred",
    );
  } else {
    await waitLp(() => true);
    let fundedId;
    if (resumePendingId) {
      await waitLp((item) =>
        item.withdrawals.some(
          (row) =>
            row.requestId === resumePendingId &&
            !row.cancelled &&
            BigInt(row.sharesRemaining) > 0n,
        ),
      );
      fundedId = resumePendingId;
      console.log(
        `Resuming pending request ${fundedId}; no new deposit or withdrawal request will be submitted`,
      );
    } else {
      let queued;
      let data;
      if (resumeCancelledId) {
        const position = await waitLp(
          (item) =>
            BigInt(item.shares) > 0n &&
            item.withdrawals.some(
              (row) => row.requestId === resumeCancelledId && row.cancelled,
            ),
        );
        queued = BigInt(position.shares) / 4n;
        console.log(
          `Resuming confirmed cancelled request ${resumeCancelledId}; no deposit or earlier request will be repeated`,
        );
      } else {
        if ((await token.balanceOf(wallet.address)) < supplyAmount) {
          await transact("Get test tokens");
          await waitLp((data) => BigInt(data.walletBalance) >= supplyAmount);
        }
        await transact("Supply", "1");
        const supplied = await waitLp(
          (data) => BigInt(data.shares) > initialShares,
        );
        const added = BigInt(supplied.shares) - initialShares;
        queued = added / 4n;
        assert.ok(queued > 0n);
        await transact("Join withdrawal queue", formatUnits(queued, 18));
        data = await waitLp((item) =>
          item.withdrawals.some(
            (row) => BigInt(row.sharesRemaining) === queued && !row.cancelled,
          ),
        );
        const cancelledId = data.withdrawals.find(
          (row) => BigInt(row.sharesRemaining) === queued && !row.cancelled,
        ).requestId;
        await transact("Cancel");
        await waitLp((item) =>
          item.withdrawals.some(
            (row) => row.requestId === cancelledId && row.cancelled,
          ),
        );
      }
      await transact("Join withdrawal queue", formatUnits(queued, 18));
      data = await waitLp((item) =>
        item.withdrawals.some(
          (row) => BigInt(row.sharesRemaining) === queued && !row.cancelled,
        ),
      );
      fundedId = data.withdrawals.find(
        (row) => BigInt(row.sharesRemaining) === queued && !row.cancelled,
      ).requestId;
    }
    await transact("Allocate available liquidity to queued requests");
    await waitLp((item) =>
      item.withdrawals.some(
        (row) =>
          row.requestId === fundedId &&
          BigInt(row.assetsReserved) > BigInt(row.assetsClaimed),
      ),
    );
    // Rows include the earlier cancelled request; only the funded claim is enabled.
    await page
      .getByRole("button", { name: "Claim", exact: true })
      .and(page.locator(":enabled"))
      .click();
    const claimDialog = page.getByRole("dialog");
    await claimDialog
      .getByRole("button", { name: "Confirm in wallet" })
      .click();
    await claimDialog
      .getByText("Transaction confirmed with two block confirmations.")
      .waitFor();
    await claimDialog.getByRole("button", { name: "Done" }).click();
    await waitLp((item) =>
      item.withdrawals.some(
        (row) => row.requestId === fundedId && BigInt(row.assetsClaimed) > 0n,
      ),
    );
    console.log("PASS real browser Claim");
    const remaining = (await vault.balanceOf(wallet.address)) - initialShares;
    if (remaining > 0n) {
      await transact("Withdraw", formatUnits(remaining, 18));
      await waitLp((item) => BigInt(item.shares) === initialShares);
    }
  }
  if (flow === "lp") {
    await page
      .getByRole("heading", { name: "Supply & withdrawal", exact: true })
      .waitFor();
    await expect(
      page
        .getByText("Your vault position", { exact: true })
        .locator("..")
        .locator("strong"),
    ).toHaveText("0 tUSD", { timeout: 120000 });
  } else {
    // A borrower may hold several facilities; scope the readback to the audited facility panel.
    await expect(
      page
        .getByRole("heading", { name: `Facility ${facilityId}`, exact: true })
        .locator("..")
        .getByText("Current chain debt", { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText("0 tUSD", { timeout: 120000 });
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
      true,
    );
    const directory = fileURLToPath(
      new URL("../node_modules/.cache/playwright/", import.meta.url),
    );
    mkdirSync(directory, { recursive: true });
    await page.screenshot({
      path: `${directory}native-${flow}-${width}.png`,
      fullPage: true,
    });
  }
  if (expectedRepaymentHash) {
    const response = await fetch(`${apiUrl}/v1/repayments`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    assert.equal(response.status, 200);
    const result = await response.json();
    assert.equal(result.meta.deploymentId, config.deploymentId);
    const allocation = result.data.find(
      (item) =>
        item.facilityId === facilityId &&
        item.onchainTxHash?.toLowerCase() ===
          expectedRepaymentHash.toLowerCase(),
    );
    assert.ok(allocation, "Expected repayment must exist in actual API data");
    assert.equal(allocation.repaymentApplied, true);
    assert.equal(allocation.applicationEvidence, "FINALIZED_ROUTER_EVENT");
    assert.equal(allocation.received.amount, "1000002");
    assert.equal(allocation.principalPaid.amount, "1000000");
    assert.equal(allocation.interestPaid.amount, "2");
    assert.equal(allocation.excess.amount, "0");
    assert.equal(allocation.recordedNewDebt.amount, "0");
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    if (!(await nav.isVisible()))
      await page.getByRole("button", { name: "Open navigation" }).click();
    await nav.getByRole("button", { name: "Activity", exact: true }).click();
    const panel = page
      .getByRole("heading", { name: "Facility repayment allocations" })
      .locator("..");
    await expect(panel.getByText("Applied · finalized event")).toBeVisible();
    await expect(
      panel.locator(`a[href$="/tx/${expectedRepaymentHash}"]`),
    ).toBeVisible();
    await expect(panel.getByText("1.000002", { exact: true })).toBeVisible();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth + 1,
        ),
        true,
      );
      const directory = fileURLToPath(
        new URL("../node_modules/.cache/playwright/", import.meta.url),
      );
      mkdirSync(directory, { recursive: true });
      await page.screenshot({
        path: `${directory}native-repayment-activity-${width}.png`,
        fullPage: true,
      });
    }
    console.log(
      "PASS read-only actual Router.Repaid API allocation and activity UI",
    );
  }
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify({
      result: "PASS",
      evidence: readOnly
        ? "NATIVE_TESTNET_READ_ONLY"
        : "NATIVE_TESTNET_REAL_TRANSACTIONS",
      flow,
      resumedCancelledRequest: resumeCancelledId || null,
      resumedPendingRequest: resumePendingId || null,
      resumedBorrowerRepay: resumeBorrowerRepay,
      expectedRepaymentHash: expectedRepaymentHash || null,
      chainId: 102031,
      deploymentId: config.deploymentId,
      wallet: wallet.address,
      transactions: submitted,
      nativeProofAcceptance: "NOT_ASSERTED",
      partnerRevenue: "NOT_ASSERTED",
    }),
  );
} catch (error) {
  if (debugPage) {
    console.log(
      `BROWSER_FAILURE_STATE ${(await debugPage.locator("body").innerText()).slice(0, 5000)}`,
    );
    const directory = fileURLToPath(
      new URL("../node_modules/.cache/playwright/", import.meta.url),
    );
    mkdirSync(directory, { recursive: true });
    await debugPage.screenshot({
      path: `${directory}native-${flow}-failure.png`,
      fullPage: true,
    });
  }
  throw error;
} finally {
  await browser.close();
  provider.destroy();
}
