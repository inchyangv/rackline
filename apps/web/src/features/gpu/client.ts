import {
  formatUnits,
  getAddress,
  isAddress,
  keccak256,
  toUtf8Bytes,
  ZeroAddress,
} from "ethers";
import type { ReadMeta } from "./generated/api";

export type Profile = "LOCAL_MOCK" | "NATIVE_TESTNET" | "PRODUCTION";
export interface Asset {
  chainId: number;
  address: string | null;
  decimals: number;
  symbol?: string;
  testOnly?: boolean;
}
export interface Config {
  schemaVersion: "1.0";
  executionProfile: Profile;
  chainId: number;
  appDomain: string;
  deploymentId: string;
  manifestHash: string;
  rpcUrl: string | null;
  explorerUrl: string | null;
  configured: boolean;
  contracts: {
    vault: string | null;
    asset: string | null;
    manager: string | null;
    repaymentRouter: string | null;
  };
  asset: Asset;
  capabilities: Record<string, boolean | string>;
  requiredVerification?: string;
  nativeStatus?: string;
  partnerRevenue?: string;
  configurationErrors?: string[];
}
export interface Session {
  token: string;
  expiresAt: number;
  wallet: string;
  borrowerId: string | null;
  roles: string[];
}
export interface Envelope<T> {
  schemaVersion: "1.0";
  data: T;
  meta: ReadMeta;
  pagination?: { nextCursor: string | null };
}
export interface TransactionContext {
  facilityId: string;
  canonicalFacilityId: string;
  wallet: string;
  chainId: number;
  manager: string;
  repaymentRouter: string;
  asset: Asset;
  debt: string;
  availableDraw: string | null;
  drawBlockedReason: string | null;
  expiresAt: number;
}
export interface Withdrawal {
  requestId: string;
  sharesRemaining: string;
  assetsReserved: string;
  assetsClaimed: string;
  cancelled: boolean;
  epoch: number;
  expiresAt: number;
}
export interface LpData {
  wallet: string;
  asset: Asset;
  nav: string;
  availableCash: string;
  walletBalance: string;
  shares: string;
  availableShares?: string;
  shareDecimals?: number;
  shareAssets: string;
  currentEpoch: number;
  withdrawals: Withdrawal[];
  impairment?: string;
  borrowerOwned?: string;
  realizedYield?: string | null;
  depositsPaused?: boolean;
  epochRolloverRequired?: boolean;
  recoveries?: { epoch: number; claimable: string }[];
}

export class ApiFailure extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export function apiBase(): string {
  return (import.meta.env.VITE_GPU_API_URL || "").replace(/\/$/, "");
}
export async function request<T>(
  path: string,
  options: { token?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: options.body === undefined ? "GET" : "POST",
    signal: options.signal
      ? AbortSignal.any([options.signal, AbortSignal.timeout(20_000)])
      : AbortSignal.timeout(20_000),
    cache: "no-store",
    headers: {
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      ...(options.body === undefined
        ? {}
        : { "Content-Type": "application/json" }),
    },
    ...(options.body === undefined
      ? {}
      : { body: JSON.stringify(options.body) }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiFailure(
      body?.error?.code || "UPSTREAM_UNAVAILABLE",
      body?.error?.message || "The service is unavailable. Please retry.",
    );
  if (!body || typeof body !== "object")
    throw new ApiFailure(
      "INVALID_RESPONSE",
      "The API returned an invalid response.",
    );
  return body as T;
}

export function validateConfig(value: Config): Config {
  if (
    value.schemaVersion !== "1.0" ||
    !["LOCAL_MOCK", "NATIVE_TESTNET", "PRODUCTION"].includes(
      value.executionProfile,
    )
  )
    throw new Error("Unsupported GPU deployment profile or API version.");
  if (!Number.isSafeInteger(value.chainId) || value.chainId <= 0)
    throw new Error("Deployment chain is not configured.");
  if (!value.appDomain || !value.deploymentId || !value.manifestHash)
    throw new Error("Deployment identity is incomplete.");
  if (!value.configured) return value;
  if (value.executionProfile === "PRODUCTION" && value.asset?.testOnly)
    throw new Error("Production cannot use a test-only loan asset.");
  if (
    !value.asset ||
    value.asset.chainId !== value.chainId ||
    !Number.isInteger(value.asset.decimals) ||
    value.asset.decimals < 0 ||
    value.asset.decimals > 18
  )
    throw new Error("Loan token chain or decimals are invalid.");
  for (const address of Object.values(value.contracts))
    if (!address || !isAddress(address) || getAddress(address) === ZeroAddress)
      throw new Error("A required GPU contract address is missing or invalid.");
  if (
    !value.asset.address ||
    value.asset.address.toLowerCase() !== value.contracts.asset?.toLowerCase()
  )
    throw new Error("Loan asset does not match the deployment.");
  for (const url of [value.rpcUrl, value.explorerUrl])
    if (url && !/^https?:\/\//.test(url))
      throw new Error("Deployment RPC or explorer URL is invalid.");
  if (
    value.executionProfile !== "LOCAL_MOCK" &&
    value.requiredVerification &&
    value.requiredVerification !== "ATTESTCOIN_NATIVE"
  )
    throw new Error("Native deployment cannot use a substitute verifier.");
  return value;
}

export function validateRead(meta: ReadMeta, config: Config): void {
  if (
    meta.executionProfile !== config.executionProfile ||
    meta.chainId !== config.chainId ||
    meta.manifestHash !== config.manifestHash ||
    meta.deploymentId !== config.deploymentId
  )
    throw new ApiFailure(
      "PROFILE_MISMATCH",
      "This response belongs to a different deployment. Reconnect after refreshing.",
    );
}

export function exactAmount(
  raw: string | null | undefined,
  decimals = 6,
): string {
  if (raw == null || !/^\d+$/.test(raw)) return "Unavailable";
  const [whole, fraction = ""] = formatUnits(BigInt(raw), decimals).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction.replace(/0+$/, "") ? `.${fraction.replace(/0+$/, "")}` : ""}`;
}

export function parseAmount(value: string, decimals: number): bigint {
  if (
    !Number.isInteger(decimals) ||
    decimals < 0 ||
    decimals > 18 ||
    !/^\d+(\.\d+)?$/.test(value) ||
    value.length > 78
  )
    throw new Error(
      "Enter a positive amount without commas or exponent notation.",
    );
  const [whole, fraction = ""] = value.split(".");
  if (fraction.length > decimals)
    throw new Error(`This token supports at most ${decimals} decimal places.`);
  const result =
    BigInt(whole) * 10n ** BigInt(decimals) +
    BigInt(fraction.padEnd(decimals, "0") || "0");
  if (result <= 0n || result >= 2n ** 256n)
    throw new Error(
      "Enter an amount greater than zero within the token limit.",
    );
  return result;
}

export function validateLogin(
  typedData: {
    domain: Record<string, unknown>;
    primaryType: string;
    message: Record<string, unknown>;
  },
  config: Config,
  wallet: string,
): void {
  const { domain, message } = typedData;
  if (
    domain.name !== "Rackline API Login" ||
    domain.version !== "1" ||
    Number(domain.chainId) !== config.chainId ||
    domain.salt !== keccak256(toUtf8Bytes(config.appDomain)) ||
    domain.verifyingContract !== undefined ||
    typedData.primaryType !== "Login" ||
    message.purpose !== "API_LOGIN" ||
    message.appDomain !== config.appDomain ||
    Number(message.chainId) !== config.chainId ||
    String(message.wallet).toLowerCase() !== wallet.toLowerCase() ||
    Number(message.expiresAt) <= Date.now() / 1000
  )
    throw new Error(
      "The login challenge does not match this wallet and application.",
    );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiFailure) return `${error.message} (${error.code})`;
  if (
    error &&
    typeof error === "object" &&
    "code" in error &&
    [4001, "ACTION_REJECTED"].includes(error.code as number | string)
  )
    return "Cancelled in wallet. No transaction was completed.";
  if (error && typeof error === "object" && "shortMessage" in error)
    return String(error.shortMessage).slice(0, 240);
  return error instanceof Error
    ? error.message
    : "The request failed. Please retry.";
}
