export function getEnvString(key: string): string {
  const value = (import.meta.env as Record<string, unknown>)[key];
  return typeof value === 'string' ? value : '';
}

export function getEnvNumber(key: string, fallback: number): number {
  const raw = getEnvString(key);
  if (!raw) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

export const env = {
  rpcUrl: getEnvString('VITE_RPC_URL'),
  chainId: getEnvNumber('VITE_CHAIN_ID', 102031),
  hashCreditManager: getEnvString('VITE_HASH_CREDIT_MANAGER'),
  btcSpvVerifier: getEnvString('VITE_BTC_SPV_VERIFIER'),
  checkpointManager: getEnvString('VITE_CHECKPOINT_MANAGER'),
} as const;

