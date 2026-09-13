import { expect, test, type Page } from "@playwright/test";
import {
  Interface,
  Transaction,
  Wallet,
  keccak256,
  toBeHex,
  toUtf8Bytes,
} from "ethers";
import { ILendingVaultV2Abi } from "../src/features/gpu/generated/ILendingVaultV2";
import { IRepaymentRouterAbi } from "../src/features/gpu/generated/IRepaymentRouter";
import { ICreditFacilityManagerAbi } from "../src/features/gpu/generated/ICreditFacilityManager";
import { GpuTestTokenAbi } from "../src/features/gpu/generated/GpuTestToken";

// Public, test-only deterministic wallet. No real provider, API, chain or assets are contacted.
const wallet = new Wallet(`0x${"17".repeat(32)}`);
const asset = {
  chainId: 102031,
  address: `0x${"11".repeat(20)}`,
  decimals: 6,
  symbol: "tUSD",
  testOnly: true,
};
const addresses = {
  asset: asset.address,
  vault: `0x${"22".repeat(20)}`,
  manager: `0x${"33".repeat(20)}`,
  repaymentRouter: `0x${"44".repeat(20)}`,
};
const config = {
  schemaVersion: "1.0",
  executionProfile: "NATIVE_TESTNET",
  chainId: 102031,
  appDomain: "rackline.test",
  deploymentId: "fixture-v2",
  manifestHash: `sha256:${"ab".repeat(32)}`,
  configured: true,
  contracts: addresses,
  asset,
  rpcUrl: "https://rpc.fixture.invalid",
  explorerUrl: "https://explorer.fixture.invalid",
  requiredVerification: "ATTESTCOIN_NATIVE",
  nativeStatus: "NOT_ESTABLISHED",
  partnerRevenue: "SIMULATED",
  capabilities: {},
};
const meta = {
  executionProfile: config.executionProfile,
  chainId: config.chainId,
  deploymentId: config.deploymentId,
  manifestHash: config.manifestHash,
  observedAt: "2026-09-14T00:00:00Z",
  canonicalBlock: {
    number: 200,
    hash: `0x${"ab".repeat(32)}`,
    timestamp: 1789344000,
  },
  freshness: "FRESH",
  canonicalScope: "INDEXER_WATERMARK_ONLY",
  financialAuthorization: false,
};
const money = (amount: string) => ({ amount, asset });
const facility = {
  facilityId: "FAC-001",
  borrowerId: "BOR-001",
  vaultId: "VAULT-001",
  executionProfile: config.executionProfile,
  state: "DRAW_FROZEN",
  loanAsset: asset,
  recordedPrincipal: money("42000000000"),
  recordedUnpaidInterest: money("126000000"),
  recordedFees: money("0"),
  recordedReservedDraws: money("0"),
  recordedApprovedCap: money("98000000000"),
  rateBps: "1150",
  advanceRateBps: "7000",
  maturityAt: "2026-10-14T00:00:00Z",
  controlAgreementId: "CTL-001",
  updatedAt: "2026-09-14T00:00:00Z",
};
const vaultInterface = new Interface(ILendingVaultV2Abi);
const routerInterface = new Interface(IRepaymentRouterAbi);
const tokenInterface = new Interface(GpuTestTokenAbi);
const managerInterface = new Interface(ICreditFacilityManagerAbi);

async function fixture(
  page: Page,
  {
    roles = ["borrower"],
    borrower = true,
    wrongChain = false,
    profileMismatch = false,
    drawAllowed = false,
    rejectSigning = false,
    simulationRevert = false,
    loss = false,
    reviewedAccount = false,
    walletCode = "0x",
    rejectContractWallet = false,
    missingChain = false,
    staleRead = false,
    missingProofReadyTime = false,
  } = {},
) {
  const errors: string[] = [];
  const mutations: { path: string; body: Record<string, unknown> }[] = [];
  const transactions: { to: string; data: string }[] = [];
  const proofRequests: Record<string, unknown>[] = [];
  const authRequests: Record<string, unknown>[] = [];
  let debt = 42126000000n;
  let walletBalance = 85000000000n;
  let vaultAssets = 2480000000000n;
  let supplied = 12500000000n;
  let registered = borrower;
  let allowance = 0n;
  let chain = wrongChain ? 1 : config.chainId;
  let configUnavailable = false;
  let lastTransaction: Record<string, unknown> | null = null;
  const withdrawals: {
    requestId: string;
    epoch: number;
    expiresAt: number;
    sharesRemaining: string;
    assetsReserved: string;
    assetsClaimed: string;
    cancelled: boolean;
  }[] = [];
  let recovery = loss ? 99000000n : 0n;
  const ifaceFor = (to: string) =>
    to.toLowerCase() === addresses.asset
      ? tokenInterface
      : to.toLowerCase() === addresses.repaymentRouter
        ? routerInterface
        : to.toLowerCase() === addresses.manager
          ? managerInterface
          : vaultInterface;
  const blockHash = `0x${"ab".repeat(32)}`;
  const envelope = (data: unknown) => ({
    schemaVersion: "1.0",
    data,
    meta: profileMismatch
      ? { ...meta, executionProfile: "LOCAL_MOCK" }
      : { ...meta, freshness: staleRead ? "STALE" : "FRESH" },
    pagination: { limit: 100, nextCursor: null },
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.exposeFunction(
    "gpuFixtureRequest",
    async ({ method, params }: { method: string; params: unknown[] }) => {
      if (method === "eth_chainId") return toBeHex(chain);
      if (method === "eth_requestAccounts" || method === "eth_accounts")
        return [wallet.address];
      if (method === "wallet_switchEthereumChain") {
        if (missingChain) {
          return { fixtureErrorCode: 4902 };
        }
        chain = config.chainId;
        return null;
      }
      if (method === "wallet_addEthereumChain") {
        chain = config.chainId;
        return null;
      }
      if (method === "eth_signTypedData_v4") {
        const data = JSON.parse(params[1] as string);
        delete data.types.EIP712Domain;
        return wallet.signTypedData(data.domain, data.types, data.message);
      }
      if (method === "eth_getCode")
        return String(params[0]).toLowerCase() === wallet.address.toLowerCase()
          ? walletCode
          : "0x60006000";
      if (method === "eth_blockNumber") return "0xcb";
      if (method === "eth_estimateGas") return "0x30d40";
      if (method === "eth_call") {
        const tx = params[0] as { to: string; data: string };
        const iface = ifaceFor(tx.to);
        const call = iface.parseTransaction(tx)!;
        if (call.name === "decimals")
          return iface.encodeFunctionResult(call.name, [6]);
        if (call.name === "testOnly")
          return iface.encodeFunctionResult(call.name, [true]);
        if (call.name === "allowance")
          return iface.encodeFunctionResult(call.name, [allowance]);
        if (call.name === "asset")
          return iface.encodeFunctionResult(call.name, [addresses.asset]);
        if (
          simulationRevert &&
          ["deposit", "withdraw", "borrow", "repayExact"].includes(call.name)
        )
          throw new Error(
            "Execution reverted: fixture slippage or liquidity rejection",
          );
        if (
          call.name === "previewDeposit" ||
          call.name === "previewWithdraw" ||
          call.name === "deposit" ||
          call.name === "withdraw"
        )
          return iface.encodeFunctionResult(call.name, [call.args[0]]);
        if (call.name === "repayExact") {
          const received = call.args[1] < debt ? call.args[1] : debt;
          return iface.encodeFunctionResult(call.name, [
            [
              call.args[1],
              received,
              received,
              0,
              0,
              received,
              0,
              debt - received,
            ],
          ]);
        }
        if (["faucet", "borrow", "cancelWithdrawal"].includes(call.name))
          return iface.encodeFunctionResult(call.name, []);
        if (
          call.name === "requestWithdrawal" ||
          call.name === "claimWithdrawal" ||
          call.name === "claimEpochRecovery"
        )
          return iface.encodeFunctionResult(call.name, [1n]);
        if (call.name === "processWithdrawals")
          return iface.encodeFunctionResult(call.name, [1n, 1n]);
        throw new Error(`Unhandled fixture call ${call.name}`);
      }
      if (method === "eth_sendTransaction") {
        if (rejectSigning)
          throw { code: 4001, message: "User rejected the request" };
        const tx = params[0] as { to: string; data: string };
        const signed = Transaction.from(
          await wallet.signTransaction({
            to: tx.to,
            data: tx.data,
            gasLimit: 200000n,
            gasPrice: 1n,
            nonce: transactions.length,
            chainId: config.chainId,
            type: 0,
          }),
        );
        transactions.push({ to: tx.to, data: tx.data });
        const iface = ifaceFor(tx.to);
        const call = iface.parseTransaction(tx)!;
        if (call.name === "approve") allowance = call.args[1];
        if (call.name === "deposit") {
          supplied += call.args[0];
          walletBalance -= call.args[0];
          vaultAssets += call.args[0];
        }
        if (call.name === "repayExact") {
          const received = call.args[1] < debt ? call.args[1] : debt;
          debt -= received;
          walletBalance -= received;
        }
        if (call.name === "borrow") {
          debt += call.args[1];
          walletBalance += call.args[1];
        }
        if (call.name === "faucet") walletBalance += 10000000000n;
        if (call.name === "withdraw") {
          supplied -= call.args[0];
          walletBalance += call.args[0];
        }
        if (call.name === "requestWithdrawal")
          withdrawals.push({
            requestId: String(withdrawals.length + 1),
            epoch: 0,
            expiresAt: Math.floor(Date.now() / 1000) + 604800,
            sharesRemaining: String(call.args[0]),
            assetsReserved: "0",
            assetsClaimed: "0",
            cancelled: false,
          });
        if (call.name === "cancelWithdrawal") {
          const row = withdrawals.find(
            (item) => item.requestId === String(call.args[0]),
          )!;
          row.cancelled = true;
          row.sharesRemaining = "0";
        }
        if (call.name === "processWithdrawals") {
          const row = withdrawals.find(
            (item) => BigInt(item.sharesRemaining) > 0n,
          );
          if (row) {
            const fill = BigInt(row.sharesRemaining) / 2n || 1n;
            row.sharesRemaining = String(BigInt(row.sharesRemaining) - fill);
            row.assetsReserved = String(BigInt(row.assetsReserved) + fill);
            supplied -= fill;
          }
        }
        if (call.name === "claimWithdrawal") {
          const row = withdrawals.find(
            (item) => item.requestId === String(call.args[0]),
          )!;
          walletBalance +=
            BigInt(row.assetsReserved) - BigInt(row.assetsClaimed);
          row.assetsClaimed = row.assetsReserved;
        }
        if (call.name === "claimEpochRecovery") {
          walletBalance += recovery;
          recovery = 0n;
        }
        lastTransaction = {
          hash: signed.hash,
          from: wallet.address,
          to: tx.to,
          input: tx.data,
          nonce: toBeHex(signed.nonce),
          gas: "0x30d40",
          gasPrice: "0x1",
          value: "0x0",
          chainId: toBeHex(config.chainId),
          type: "0x0",
          v: toBeHex(signed.signature!.networkV!),
          r: signed.signature!.r,
          s: signed.signature!.s,
          blockNumber: "0xc8",
          blockHash,
          transactionIndex: "0x0",
        };
        return signed.hash;
      }
      if (method === "eth_getTransactionByHash") return lastTransaction;
      if (method === "eth_getTransactionReceipt")
        return {
          transactionHash: lastTransaction!.hash,
          transactionIndex: "0x0",
          blockHash,
          blockNumber: "0xc8",
          from: wallet.address,
          to: lastTransaction!.to,
          cumulativeGasUsed: "0x10000",
          gasUsed: "0x10000",
          effectiveGasPrice: "0x1",
          contractAddress: null,
          logs: [],
          logsBloom: `0x${"00".repeat(256)}`,
          status: "0x1",
          type: "0x0",
        };
      throw new Error(`Unhandled wallet fixture method: ${method}`);
    },
  );
  await page.addInitScript(() => {
    const listeners = new Map<string, Set<() => void>>();
    Reflect.set(window, "gpuEmit", (event: string) =>
      listeners.get(event)?.forEach((listener) => listener()),
    );
    Reflect.set(window, "ethereum", {
      request: async (args: unknown) => {
        const result = await (
          Reflect.get(window, "gpuFixtureRequest") as (
            args: unknown,
          ) => Promise<unknown>
        )(args);
        if (
          result &&
          typeof result === "object" &&
          "fixtureErrorCode" in result
        )
          throw Object.assign(new Error("Unrecognized chain"), {
            code: result.fixtureErrorCode,
          });
        return result;
      },
      on: (event: string, listener: () => void) => {
        if (!listeners.has(event)) listeners.set(event, new Set());
        listeners.get(event)!.add(listener);
      },
      removeListener: (event: string, listener: () => void) =>
        listeners.get(event)?.delete(listener),
    });
  });
  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      mutations.push({ path, body });
      if (path === "/v1/onboarding") registered = true;
      if (path === "/v1/proofs") {
        const proof = {
          proofRequestId: "PRF-001",
          ...body,
          status: "REQUESTED",
          nativeStatus: "NOT_SUBMITTED",
        };
        proofRequests.push(proof);
        return route.fulfill({ json: envelope(proof) });
      }
      return route.fulfill({ json: envelope({ state: "PENDING_REVIEW" }) });
    }
    if (path === "/v1/config")
      return configUnavailable
        ? route.fulfill({
            status: 503,
            json: {
              error: {
                code: "UPSTREAM_UNAVAILABLE",
                message: "Temporary configuration failure",
              },
            },
          })
        : route.fulfill({ json: config });
    if (path === "/v1/proofs")
      return route.fulfill({ json: envelope(proofRequests) });
    if (path === "/v1/connections" && reviewedAccount)
      return route.fulfill({
        json: envelope([
          {
            providerAccountId: "TEST_PROVIDER:account-1",
            providerId: "TEST_PROVIDER",
            borrowerId: "BOR-001",
            externalAccountId: "account-1",
            credentialConfigured: true,
            accountReviewState: "APPROVED",
            controlVersion: 0,
            lastVerifiedAt: null,
            createdAt: new Date().toISOString(),
          },
        ]),
      });
    if (path === "/v1/lp")
      return route.fulfill({
        json: envelope({
          wallet: wallet.address,
          asset,
          nav: loss ? "0" : vaultAssets.toString(),
          availableCash: loss ? "0" : "782000000000",
          walletBalance: walletBalance.toString(),
          shares: supplied.toString(),
          availableShares: String(
            supplied -
              withdrawals.reduce(
                (sum, row) => sum + BigInt(row.sharesRemaining),
                0n,
              ),
          ),
          shareAssets: loss ? "0" : supplied.toString(),
          currentEpoch: 0,
          shareDecimals: 0,
          withdrawals,
          borrowerOwned: "0",
          impairment: "0",
          epochRolloverRequired: loss,
          recoveries: loss
            ? [{ epoch: 0, claimable: recovery.toString() }]
            : [],
        }),
      });
    if (path === "/v1/facilities")
      return route.fulfill({
        json: envelope([
          {
            ...facility,
            state: drawAllowed ? "ACTIVE" : "DRAW_FROZEN",
            recordedPrincipal: money((debt - 126000000n).toString()),
          },
        ]),
      });
    if (path.endsWith("/transaction-context"))
      return route.fulfill({
        json: envelope({
          facilityId: facility.facilityId,
          canonicalFacilityId: `0x${"55".repeat(32)}`,
          wallet: wallet.address,
          chainId: config.chainId,
          manager: addresses.manager,
          repaymentRouter: addresses.repaymentRouter,
          asset,
          debt: debt.toString(),
          availableDraw: drawAllowed ? "1000000000" : "0",
          drawBlockedReason: drawAllowed ? null : "NATIVE_PROOF_PENDING",
          expiresAt: Math.floor(Date.now() / 1000) + 600,
        }),
      });
    if (path === "/v1/providers")
      return route.fulfill({
        json: envelope([
          {
            providerId: "TEST_PROVIDER",
            displayName: "Test GPU provider",
            executionProfile: config.executionProfile,
            environmentStatus: "UNCONFIRMED",
            requiredVerification: "ATTESTCOIN_NATIVE",
            sourceEnvId: "sepolia",
            sourceChainKey: 1,
            sourceChainId: 11155111,
            manifestHash: config.manifestHash,
            testOnly: true,
            capabilities: { receivables: "UNCONFIRMED" },
          },
        ]),
      });
    if (path === "/v1/operations")
      return route.fulfill({
        json: envelope([
          {
            exceptionId: "OPS-001",
            kind: "PROOF_PENDING",
            severity: "HIGH",
            state: "OPEN",
            entityType: "receivable",
            entityId: "RCV-001",
            version: 2,
            createdAt: new Date().toISOString(),
            resolvedAt: null,
          },
        ]),
      });
    if (path === "/v1/receivables")
      return route.fulfill({
        json: envelope([
          {
            receivableId: "RCV-001",
            economicEventId: "EVT-001",
            providerAccountId: "ACCT-001",
            facilityId: facility.facilityId,
            state: "CONFIRMED",
            revision: 1,
            gross: money("5000000000"),
            net: money("5000000000"),
            paidAmount: money("0"),
            unpaidAmount: money("5000000000"),
            evidence: {
              proofRequestStatus: "READY",
              proofReadyAt: missingProofReadyTime
                ? null
                : new Date().toISOString(),
              nativeStatus: "VERIFIED",
              verificationMethod: "ATTESTCOIN_NATIVE",
              nativeCanonical: true,
              earningsProvenance: "SIMULATED",
              businessEligibilityReason: "AUTHORITATIVE_ASSESSMENT_UNAVAILABLE",
            },
          },
        ]),
      });
    if (path === "/v1/settlements")
      return route.fulfill({
        json: envelope([
          {
            settlementId: "SET-001",
            providerAccountId: "ACCT-001",
            state: "SOURCE_PAID",
            sourceAmount: money("5000000000"),
            destinationCashRecorded: false,
            destinationReceipts: [],
          },
        ]),
      });
    return route.fulfill({ json: envelope([]) });
  });
  await page.route("**/gpu/auth/**", async (route) => {
    const body = route.request().postDataJSON();
    if (route.request().url().endsWith("/verify")) {
      authRequests.push(body);
      if (rejectContractWallet)
        return route.fulfill({
          status: 401,
          json: {
            error: {
              code: "UNAUTHENTICATED",
              message: "Contract wallet is not allowlisted",
            },
          },
        });
      return route.fulfill({
        json: {
          token: "fixture-memory-token",
          expiresAt: Math.floor(Date.now() / 1000) + 3600,
          wallet: wallet.address,
          borrowerId: registered ? "BOR-001" : null,
          roles,
        },
      });
    }
    const nonce = `0x${"01".repeat(32)}`;
    return route.fulfill({
      json: {
        nonce,
        typedData: {
          domain: {
            name: "Rackline API Login",
            version: "1",
            chainId: config.chainId,
            salt: keccak256(toUtf8Bytes(config.appDomain)),
          },
          types: {
            Login: [
              { name: "wallet", type: "address" },
              { name: "chainId", type: "uint256" },
              { name: "appDomain", type: "string" },
              { name: "purpose", type: "string" },
              { name: "nonce", type: "bytes32" },
              { name: "issuedAt", type: "uint64" },
              { name: "expiresAt", type: "uint64" },
              { name: "borrowerHint", type: "string" },
            ],
          },
          primaryType: "Login",
          message: {
            wallet: body.wallet,
            chainId: config.chainId,
            appDomain: config.appDomain,
            purpose: "API_LOGIN",
            nonce,
            issuedAt: Math.floor(Date.now() / 1000),
            expiresAt: Math.floor(Date.now() / 1000) + 300,
            borrowerHint: "",
          },
        },
      },
    });
  });
  await page.goto("/app");
  await expect(
    page.getByRole("button", { name: "Connect wallet", exact: true }).first(),
  ).toBeVisible();
  return {
    errors,
    mutations,
    transactions,
    authRequests,
    debt: () => debt,
    withdrawals,
    proofRequests,
    setConfigUnavailable: (value: boolean) => {
      configUnavailable = value;
    },
    walletBalance: () => walletBalance,
  };
}
async function login(page: Page) {
  await page
    .getByRole("button", { name: "Connect wallet", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
}
async function navigate(page: Page, name: string) {
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  if (!(await nav.isVisible()))
    await page.getByRole("button", { name: "Open navigation" }).click();
  await nav.getByRole("button", { name, exact: true }).click();
}
async function confirmDialog(page: Page, amount?: string) {
  const dialog = page.getByRole("dialog");
  if (amount !== undefined) {
    await dialog.getByRole("textbox").fill(amount);
    await dialog.getByRole("button", { name: "Review transaction" }).click();
  }
  await dialog.getByRole("button", { name: "Confirm in wallet" }).click();
  await expect(
    dialog.getByText("Transaction confirmed with two block confirmations."),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();
}

test("contract wallet login uses server ERC1271 validation and rejects an unapproved account", async ({
  page,
}) => {
  const state = await fixture(page, {
    walletCode: "0x60006000",
    rejectContractWallet: true,
  });
  await page
    .getByRole("button", { name: "Connect wallet", exact: true })
    .first()
    .click();
  await expect(
    page.getByText("Contract wallet is not allowlisted"),
  ).toBeVisible();
  expect(state.authRequests[0].walletKind).toBe("erc1271");
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toHaveCount(0);
  expect(state.transactions).toEqual([]);
});

test("delegated EOA retains EOA login while a regular contract uses ERC1271", async ({
  page,
}) => {
  const delegated = await fixture(page, {
    walletCode: `0xef0100${"23".repeat(20)}`,
  });
  await login(page);
  expect(delegated.authRequests[0].walletKind).toBe("eoa");
});

test("connected app keeps native evidence, source cash and debt separate; outage permits repayment", async ({
  page,
}) => {
  const state = await fixture(page, { missingProofReadyTime: true });
  await login(page);
  await navigate(page, "Borrow");
  await expect(
    page.getByRole("button", { name: "Borrow", exact: true }).last(),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Repay directly" }),
  ).toBeEnabled();
  const debt = state.debt();
  await navigate(page, "Activity");
  await expect(
    page.getByText("Verified · Canonical consumption"),
  ).toBeVisible();
  await expect(
    page.getByText("Artifact ready", { exact: true }).locator("..").locator("dd"),
  ).toHaveText("Not recorded");
  await expect(page.getByText("Destination cash not received")).toBeVisible();
  expect(state.debt()).toBe(debt);
  await navigate(page, "Borrow");
  await page.getByRole("button", { name: "Repay directly" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Amount in tUSD").fill("1.25");
  await dialog.getByRole("button", { name: "Review transaction" }).click();
  await dialog.getByRole("button", { name: "Confirm in wallet" }).click();
  await expect(
    dialog.getByText("Transaction confirmed with two block confirmations."),
  ).toBeVisible();
  expect(state.debt()).toBe(debt - 1250000n);
  expect(state.transactions).toHaveLength(2);
  expect(state.transactions[1].to.toLowerCase()).toBe(
    addresses.repaymentRouter,
  );
  expect(routerInterface.parseTransaction(state.transactions[1])!.args[0]).toBe(
    `0x${"55".repeat(32)}`,
  );
  expect(state.errors).toEqual([]);
});

test("stale finalized debt snapshot names its block, blocks draws and keeps repayment separate", async ({
  page,
}) => {
  const state = await fixture(page, { staleRead: true, drawAllowed: true });
  await login(page);
  await navigate(page, "Borrow");
  await expect(
    page.getByText(/Finalized debt view: block 200 · Stale/),
  ).toBeVisible();
  await expect(page.getByText(/Stale debt snapshot/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Borrow", exact: true }).last(),
  ).toBeDisabled();
  const before = state.debt();
  await page.getByRole("button", { name: "Repay directly" }).click();
  await confirmDialog(page, "1");
  expect(state.debt()).toBe(before - 1000000n);
  expect(state.errors).toEqual([]);
});

test("repayment cap can exceed displayed debt without transferring excess", async ({
  page,
}) => {
  const state = await fixture(page);
  await login(page);
  await navigate(page, "Borrow");
  const before = state.walletBalance();
  const debt = state.debt();
  await page.getByRole("button", { name: "Repay directly" }).click();
  await confirmDialog(page, "42127");
  expect(state.debt()).toBe(0n);
  expect(state.walletBalance()).toBe(before - debt);
  expect(routerInterface.parseTransaction(state.transactions[1])!.args[1]).toBe(
    42127000000n,
  );
});

test("temporary configuration polling failure preserves login and pauses new wallet submission", async ({
  page,
}) => {
  await page.clock.install();
  const state = await fixture(page, { borrower: false, roles: [] });
  await login(page);
  await page.getByRole("button", { name: "Supply", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill("1");
  await dialog.getByRole("button", { name: "Review transaction" }).click();
  state.setConfigUnavailable(true);
  await page.clock.runFor(61000);
  await expect(
    dialog.getByRole("button", { name: "Confirm in wallet" }),
  ).toBeDisabled();
  await expect(
    dialog.getByText(/New wallet submissions are paused/),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Close transaction" }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  state.setConfigUnavailable(false);
  await page.clock.runFor(60000);
  await expect(
    page.getByText(/Service configuration is temporarily unavailable/),
  ).toHaveCount(0);
  expect(state.transactions).toHaveLength(0);
});

test("LP supply uses exact approval and minShares, confirms and refreshes actual fixture balance", async ({
  page,
}) => {
  const state = await fixture(page, { borrower: false, roles: [] });
  await login(page);
  await page.getByRole("button", { name: "Supply", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Amount in tUSD").fill("250.000001");
  await dialog.getByRole("button", { name: "Review transaction" }).click();
  await dialog.getByRole("button", { name: "Confirm in wallet" }).click();
  await expect(
    dialog.getByText("Transaction confirmed with two block confirmations."),
  ).toBeVisible();
  const approval = tokenInterface.parseTransaction(state.transactions[0])!;
  expect(approval.args[1]).toBe(250000001n);
  const deposit = vaultInterface.parseTransaction(state.transactions[1])!;
  expect(deposit.args[1]).toBe(248750000n);
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(
    page.getByText("12,750.000001 tUSD", { exact: true }),
  ).toBeVisible();
  expect(state.errors).toEqual([]);
});

test("borrower onboarding persists review requests and never self-approves provider control", async ({
  page,
}) => {
  const state = await fixture(page, { borrower: false, roles: [] });
  await login(page);
  await navigate(page, "Providers");
  await page.getByLabel("Jurisdiction").fill("KR");
  await page
    .getByLabel("Company registration reference")
    .fill("doc://company/registration");
  await page.getByRole("button", { name: "Register profile" }).click();
  await expect(
    page.getByText(/Borrower profile saved with review pending/),
  ).toBeVisible();
  expect(state.mutations[0].path).toBe("/v1/onboarding");
  expect(state.mutations[0].body.idempotencyKey).toBeTruthy();
  await page
    .getByRole("button", { name: "Reconnect wallet to continue" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Request a provider connection" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Provider", exact: true })
    .selectOption("TEST_PROVIDER");
  await page
    .getByLabel("Provider account reference")
    .fill("provider/account/123");
  await page
    .getByLabel("Ownership / authority evidence reference")
    .fill("doc://ownership/123");
  await page
    .getByLabel("Reason for request")
    .fill("Connect this account for receivable review.");
  await page.getByRole("button", { name: "Submit for review" }).click();
  await expect(
    page.getByText(/Connection request saved for review/),
  ).toBeVisible();
  expect(state.mutations[1].body.providerId).toBe("TEST_PROVIDER");
  expect(
    await page.evaluate(() =>
      Object.keys(localStorage).some((key) =>
        /token|session|registration|connection/.test(key),
      ),
    ),
  ).toBe(false);
  expect(state.errors).toEqual([]);
});

test("wallet changes invalidate session and mounted records; roles restrict operations", async ({
  page,
}) => {
  const state = await fixture(page);
  await login(page);
  await page.evaluate(() => {
    window.location.hash = "operations";
  });
  await expect(
    page.getByText(
      "Operations access requires an assigned operator, servicer, or guardian role.",
    ),
  ).toBeVisible();
  await page.evaluate(() =>
    (Reflect.get(window, "gpuEmit") as (event: string) => void)(
      "accountsChanged",
    ),
  );
  await expect(
    page.getByRole("button", { name: "Connect wallet", exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Case detail & audited action" }),
  ).toHaveCount(0);
  expect(state.errors).toEqual([]);
});

test("operations actions include version, reason and idempotency without native override", async ({
  page,
}) => {
  const state = await fixture(page, { roles: ["operator"] });
  await login(page);
  await navigate(page, "Operations");
  await page.getByRole("button", { name: /Proof pending/ }).click();
  await page
    .getByLabel("Reason for audit trail")
    .fill("Review official proof service availability.");
  await page.getByRole("button", { name: "Submit action" }).click();
  await expect(
    page.getByText(/Action recorded with your reason/),
  ).toBeVisible();
  expect(state.mutations[0].body).toMatchObject({
    action: "acknowledge",
    expectedVersion: 2,
    reason: "Review official proof service availability.",
  });
  expect(state.mutations[0].body.idempotencyKey).toBeTruthy();
  await expect(
    page.getByRole("button", { name: /mark.*verified/i }),
  ).toHaveCount(0);
  expect(state.errors).toEqual([]);
});

test("source proof request is account-bound, remains pending after reload, and never reduces debt", async ({
  page,
}) => {
  await page.clock.install();
  const state = await fixture(page, { reviewedAccount: true });
  await login(page);
  await navigate(page, "Providers");
  const debt = state.debt();
  await page
    .getByRole("combobox", { name: "Reviewed provider account" })
    .selectOption("TEST_PROVIDER:account-1");
  await page.getByLabel("Source transaction hash").fill(`0x${"99".repeat(32)}`);
  await page.getByRole("button", { name: "Request official proof" }).click();
  await expect(page.getByText(/Proof request PRF-001 received/)).toBeVisible();
  expect(state.mutations[0].body).toMatchObject({
    providerAccountId: "TEST_PROVIDER:account-1",
    txHash: `0x${"99".repeat(32)}`,
  });
  expect(Object.keys(state.mutations[0].body).sort()).toEqual([
    "idempotencyKey",
    "providerAccountId",
    "txHash",
  ]);
  await page.reload();
  await page
    .getByRole("button", { name: "Connect wallet", exact: true })
    .first()
    .click();
  await expect(page.getByText("PRF-001", { exact: true })).toBeVisible();
  await expect(page.getByText("Not submitted", { exact: true })).toBeVisible();
  state.proofRequests[0].status = "PROOF_READY";
  state.proofRequests[0].artifactHash = `0x${"a9".repeat(32)}`;
  await page.clock.runFor(16000);
  await expect(page.getByText("Proof ready", { exact: true })).toBeVisible();
  await expect(
    page.getByText(`0x${"a9".repeat(32)}`, { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Not submitted", { exact: true })).toBeVisible();
  expect(state.debt()).toBe(debt);
  expect(state.transactions).toHaveLength(0);
});

test("mismatched deployment data is rejected before balances render", async ({
  page,
}) => {
  await fixture(page, { profileMismatch: true });
  await login(page);
  await expect(page.getByText(/PROFILE_MISMATCH/).first()).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Supply", exact: true }),
  ).toHaveCount(0);
});

test("an unregistered Creditcoin testnet can be added before login", async ({
  page,
}) => {
  await fixture(page, { wrongChain: true, missingChain: true });
  await page
    .getByRole("button", { name: "Connect wallet", exact: true })
    .first()
    .click();
  await expect(
    page.getByText("Network switched. Connect again to sign in."),
  ).toBeVisible();
  await login(page);
});

test("wrong chain must switch before authentication and no session survives a chain change", async ({
  page,
}) => {
  await fixture(page, { wrongChain: true });
  await page
    .getByRole("button", { name: "Connect wallet", exact: true })
    .first()
    .click();
  await expect(
    page.getByText("Network switched. Connect again to sign in."),
  ).toBeVisible();
  await login(page);
  await page.evaluate(() =>
    (Reflect.get(window, "gpuEmit") as (event: string) => void)("chainChanged"),
  );
  await expect(
    page.getByText(/Wallet account or network changed/),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toHaveCount(0);
});

test("LP faucet, direct withdrawal, partial queue fill, cancel and one-time cash claim work", async ({
  page,
}) => {
  const state = await fixture(page, { borrower: false, roles: [] });
  await login(page);
  await page.getByRole("button", { name: "Get test tokens" }).click();
  await confirmDialog(page);
  expect(tokenInterface.parseTransaction(state.transactions[0])!.name).toBe(
    "faucet",
  );
  await page.getByRole("button", { name: "Withdraw", exact: true }).click();
  await confirmDialog(page, "1000000");
  expect(vaultInterface.parseTransaction(state.transactions[1])!.name).toBe(
    "withdraw",
  );
  await page.getByRole("button", { name: "Join withdrawal queue" }).click();
  await confirmDialog(page, "2000000");
  expect(state.withdrawals[0].sharesRemaining).toBe("2000000");
  await expect(
    page.getByRole("button", { name: "Claim", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", {
      name: "Allocate available liquidity to queued requests",
    })
    .click();
  await confirmDialog(page);
  expect(state.withdrawals[0].sharesRemaining).toBe("1000000");
  expect(state.withdrawals[0].assetsReserved).toBe("1000000");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await confirmDialog(page);
  expect(state.withdrawals[0].cancelled).toBe(true);
  await page.getByRole("button", { name: "Claim", exact: true }).click();
  await confirmDialog(page);
  expect(state.withdrawals[0].assetsClaimed).toBe("1000000");
  await expect(
    page.getByRole("button", { name: "Claim", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeDisabled();
  expect(state.transactions).toHaveLength(6);
  expect(state.errors).toEqual([]);
});

test("total-loss warning blocks recapitalization deposits and preserves prior recovery claim", async ({
  page,
}) => {
  const state = await fixture(page, { borrower: false, roles: [], loss: true });
  await login(page);
  await expect(
    page.getByText(/current epoch has suffered a total loss/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Supply", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Join withdrawal queue" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Claim recovery", exact: true })
    .click();
  await confirmDialog(page);
  await expect(
    page.getByRole("button", { name: "Claim recovery", exact: true }),
  ).toBeDisabled();
  expect(vaultInterface.parseTransaction(state.transactions[0])!.name).toBe(
    "claimEpochRecovery",
  );
  expect(state.errors).toEqual([]);
});

test("valid facility context submits borrow to its bound manager and updates debt only after confirmation", async ({
  page,
}) => {
  const state = await fixture(page, { drawAllowed: true });
  await login(page);
  await navigate(page, "Borrow");
  const debt = state.debt();
  await page
    .getByRole("main")
    .getByRole("button", { name: "Borrow", exact: true })
    .click();
  await confirmDialog(page, "20");
  expect(state.debt()).toBe(debt + 20000000n);
  expect(state.transactions).toHaveLength(1);
  const tx = managerInterface.parseTransaction(state.transactions[0])!;
  expect(tx.name).toBe("borrow");
  expect(tx.args[0]).toBe(`0x${"55".repeat(32)}`);
  expect(tx.args[2]).toBe(20000000n);
  expect(state.errors).toEqual([]);
});

test("wallet rejection leaves balances unchanged and the dialog can be closed safely", async ({
  page,
}) => {
  const state = await fixture(page, {
    borrower: false,
    roles: [],
    rejectSigning: true,
  });
  await login(page);
  await page.getByRole("button", { name: "Supply", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill("1");
  await dialog.getByRole("button", { name: "Review transaction" }).click();
  await dialog.getByRole("button", { name: "Confirm in wallet" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Close transaction" }),
  ).toBeEnabled();
  expect(state.transactions).toHaveLength(0);
  await dialog.getByRole("button", { name: "Close transaction" }).click();
  await expect(page.getByText("12,500 tUSD", { exact: true })).toBeVisible();
});

test("simulation revert prevents a vault transaction after approval and never claims success", async ({
  page,
}) => {
  const state = await fixture(page, {
    borrower: false,
    roles: [],
    simulationRevert: true,
  });
  await login(page);
  await page.getByRole("button", { name: "Supply", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill("1");
  await dialog.getByRole("button", { name: "Review transaction" }).click();
  await dialog.getByRole("button", { name: "Confirm in wallet" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(state.transactions).toHaveLength(1);
  expect(tokenInterface.parseTransaction(state.transactions[0])!.name).toBe(
    "approve",
  );
  await expect(
    dialog.getByText("Transaction confirmed with two block confirmations."),
  ).toHaveCount(0);
});

test("all connected screens fit mobile and keyboard focus remains inside a transaction", async ({
  page,
}, testInfo) => {
  const state = await fixture(page, { roles: ["operator"] });
  await login(page);
  for (const screen of [
    "Overview",
    "Earn",
    "Borrow",
    "Providers",
    "Activity",
    "Operations",
  ]) {
    await navigate(page, screen);
    await expect(
      page.getByRole("heading", { name: screen, exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Loading your records…")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
  }
  await navigate(page, "Earn");
  await expect(
    page.getByRole("button", { name: "Supply", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("connected-earn.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Supply", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveAccessibleName(
    "Supply to the vault",
  );
  for (let index = 0; index < 8; index++) {
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() =>
        Boolean(document.activeElement?.closest('[role="dialog"]')),
      ),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(state.errors).toEqual([]);
});
