export function getEnvString(key: string, fallback = ''): string {
  const value = (import.meta.env as Record<string, unknown>)[key];
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

export function getEnvNumber(key: string, fallback: number): number {
  const raw = getEnvString(key);
  if (!raw) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

const defaults = {
  rpcUrl: 'https://testnet.hsk.xyz',
  chainId: 133,
  hashCreditManager: '',
  btcSpvVerifier: '',
  checkpointManager: '',
  vaultAddress: '',
  stablecoinAddress: '',
  apiUrl: 'https://api-hashcredit.studioliq.com',
  btcExplorerTxBase: 'https://mempool.space/testnet/tx',
} as const;

export const env = {
  rpcUrl: getEnvString('VITE_RPC_URL', defaults.rpcUrl),
  chainId: getEnvNumber('VITE_CHAIN_ID', defaults.chainId),
  hashCreditManager: getEnvString('VITE_HASH_CREDIT_MANAGER', defaults.hashCreditManager),
  btcSpvVerifier: getEnvString('VITE_BTC_SPV_VERIFIER', defaults.btcSpvVerifier),
  checkpointManager: getEnvString('VITE_CHECKPOINT_MANAGER', defaults.checkpointManager),
  vaultAddress: getEnvString('VITE_VAULT_ADDRESS', defaults.vaultAddress),
  stablecoinAddress: getEnvString('VITE_STABLECOIN_ADDRESS', defaults.stablecoinAddress),
  apiUrl: getEnvString('VITE_API_URL', defaults.apiUrl),
  btcExplorerTxBase: getEnvString('VITE_BTC_EXPLORER_TX_BASE', defaults.btcExplorerTxBase),
} as const;
