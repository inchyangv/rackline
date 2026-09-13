import { env } from './env'

export function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

/** Creditcoin (EVM) explorer — address page. */
export function getAddressExplorerUrl(address: string): string {
  if (!/^0x[0-9a-fA-F]{40}$/.test(address)) return ''
  const base = normalizeBaseUrl(env.explorerBase)
  return base ? `${base}/address/${address}` : ''
}

/** Creditcoin (EVM) explorer — transaction page. */
export function getTxExplorerUrl(hash: string): string {
  if (!/^0x[0-9a-fA-F]{64}$/.test(hash)) return ''
  const base = normalizeBaseUrl(env.explorerBase)
  return base ? `${base}/tx/${hash}` : ''
}

export function getRpcHost(): string {
  try {
    return new URL(env.rpcUrl).host
  } catch {
    return env.rpcUrl
  }
}
