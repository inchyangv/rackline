import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { chromium } from "@playwright/test";
import { Wallet } from "ethers";

// Actual HTTP/API/database exercise. Only the browser wallet is a public disposable signing fixture.
const base = process.env.GPU_REVIEW_WEB_URL || "http://127.0.0.1:4273";
const localChrome =
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await chromium.launch({
  executablePath:
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ||
    (existsSync(localChrome) ? localChrome : undefined),
});
try {
  for (const [width, key] of [
    [1440, "17"],
    [390, "18"],
  ]) {
    const wallet = new Wallet(`0x${key.repeat(32)}`);
    const context = await browser.newContext({
      viewport: { width, height: 1000 },
    });
    const page = await context.newPage();
    const errors = [];
    const proofReads = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("response", (response) => {
      if (
        new URL(response.url()).pathname === "/v1/proofs" &&
        response.request().method() === "GET"
      )
        proofReads.push(response.status());
    });
    await page.exposeFunction(
      "reviewWalletRequest",
      async ({ method, params }) => {
        if (method === "eth_getCode") {
          assert.equal(params[0].toLowerCase(), wallet.address.toLowerCase());
          return "0x"; // Public disposable signer fixture is an EOA; no contract/RPC state is simulated.
        }
        if (method === "eth_chainId") return "0x18e8f";
        if (method === "eth_accounts" || method === "eth_requestAccounts")
          return [wallet.address];
        if (method === "eth_signTypedData_v4") {
          const td = JSON.parse(params[1]);
          delete td.types.EIP712Domain;
          return wallet.signTypedData(td.domain, td.types, td.message);
        }
        throw new Error(`Read-only API review does not permit ${method}`);
      },
    );
    await page.addInitScript(() => {
      Reflect.set(window, "ethereum", {
        request: (args) => window.reviewWalletRequest(args),
        on() {},
        removeListener() {},
      });
    });
    const navigate = async (name) => {
      const nav = page.getByRole("navigation", { name: "Main navigation" });
      if (!(await nav.isVisible()))
        await page.getByRole("button", { name: "Open navigation" }).click();
      await nav.getByRole("button", { name, exact: true }).click();
    };
    await page.goto(`${base}/app`);
    await page
      .getByRole("button", { name: "Connect wallet", exact: true })
      .first()
      .click();
    await page
      .getByRole("heading", { name: "Overview", exact: true })
      .waitFor();
    await navigate("Providers");
    if (
      await page
        .getByRole("heading", { name: "Register your borrower profile" })
        .count()
    ) {
      await page.getByLabel("Jurisdiction").fill("KR");
      await page
        .getByLabel("Company registration reference")
        .fill(`doc://company/${width}`);
      const onboardingResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/v1/onboarding") &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Register profile" }).click();
      const onboarding = await onboardingResponse;
      assert.equal(onboarding.status(), 201, await onboarding.text());
      await page
        .getByText(/Borrower profile saved with review pending/)
        .waitFor();
      await page
        .getByRole("button", { name: "Reconnect wallet to continue" })
        .click();
    }
    await page
      .getByRole("heading", { name: "Request a provider connection" })
      .waitFor();
    await page
      .getByRole("combobox", { name: "Provider", exact: true })
      .selectOption("test-provider");
    await page
      .getByLabel("Provider account reference")
      .fill(`review-account-${width}`);
    await page
      .getByLabel("Ownership / authority evidence reference")
      .fill(`doc://ownership/${width}`);
    await page
      .getByLabel("Reason for request")
      .fill("Test-only browser/API interoperability review.");
    const response = page.waitForResponse(
      (response) =>
        response.url().endsWith("/v1/connections") &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Submit for review" }).click();
    assert.equal((await response).status(), 202);
    await page.getByText(/Connection request saved for review/).waitFor();
    await page.reload();
    await page
      .getByRole("button", { name: "Connect wallet", exact: true })
      .first()
      .click();
    await page
      .getByRole("heading", { name: "Request a provider connection" })
      .waitFor();
    await page.getByText("Connection request retained for review").waitFor();
    await page
      .getByText("No proof requests recorded for this wallet.")
      .waitFor();
    assert.ok(
      proofReads.length > 0,
      "Actual proof history endpoint must be called",
    );
    assert.ok(
      proofReads.every((status) => status === 200),
      "Actual proof history responses must be valid",
    );
    assert.equal(
      await page.evaluate(() =>
        Object.keys(localStorage).some((key) => /gpu|session|token/.test(key)),
      ),
      false,
    );
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
      true,
    );
    assert.deepEqual(errors, []);
    console.log(
      `PASS actual API/PostgreSQL: ${width}px login → onboarding → session refresh → connection request → reload persisted review`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
