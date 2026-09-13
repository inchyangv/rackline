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
  rpcUrl: 'https://rpc.cc3-testnet.creditcoin.network',
  chainId: 102031,
  hashCreditManager: '0x593e140982cDC040d69B7E7623A045C6d6Ca2055',
  btcSpvVerifier: '0x16DEd6a617a911471cd4549C24Ed8C281f096fd2',
  vaultAddress: '0x4d74126369BacB67085a1E70d535cA15515d1AFa',
  stablecoinAddress: '0xb9D6E174C8e0267Fb0cC3F2AC34130D680151B6A',
  apiUrl: 'https://api-hashcredit.studioliq.com',
  explorerBase: 'https://creditcoin-testnet.blockscout.com',
  explorerApiBase: 'https://creditcoin-testnet.blockscout.com/api',
} as const;

export const env = {
  rpcUrl: getEnvString('VITE_RPC_URL', defaults.rpcUrl),
  chainId: getEnvNumber('VITE_CHAIN_ID', defaults.chainId),
  hashCreditManager: getEnvString('VITE_HASH_CREDIT_MANAGER', defaults.hashCreditManager),
  btcSpvVerifier: getEnvString('VITE_BTC_SPV_VERIFIER', defaults.btcSpvVerifier),
  vaultAddress: getEnvString('VITE_VAULT_ADDRESS', defaults.vaultAddress),
  stablecoinAddress: getEnvString('VITE_STABLECOIN_ADDRESS', defaults.stablecoinAddress),
  apiUrl: getEnvString('VITE_API_URL', defaults.apiUrl),
  explorerBase: getEnvString('VITE_EXPLORER_BASE', defaults.explorerBase),
  explorerApiBase: getEnvString('VITE_EXPLORER_API_BASE', defaults.explorerApiBase),
} as const;
